"""P3/E3: the offline A/B gate — corpus integrity, policy snapshot, benchmarks.

Two postures are pinned here because the plan left them as decisions: the gate is
report-only by default (``--fail-on-red`` opts into blocking), and a variant is
only ever supplied explicitly.  Everything else is the integrity contract the
independent review asked for: an empty corpus is red, a corpus built by an older
redaction is red, unlisted fixture files are red, required benchmark checks must
actually say PASS, and a "variant" that changes nothing is treated as a mis-wired
injection rather than a pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / "scripts" / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import extract_fixtures as ex  # noqa: E402  (sibling module after sys.path setup)
import fixtures as fx  # noqa: E402
import run_gate as gate  # noqa: E402

STATE: dict[str, object] = {
    "account_id": "acc-1",
    "copy_content": {"selected_title": "标题", "body_text": "正文"},
    "visual_plan": {"image_paths": ["C:/a/b.png"]},
}


def _corpus(tmp_path: Path) -> Path:
    fixture = fx.build_fixture(
        source="sqlite", thread_id="thread-plain", checkpoint_id="cp-1", state=STATE
    )
    out = tmp_path / "corpus"
    ex.write_corpus(
        [fixture],
        out_dir=out,
        source_kind="sqlite",
        skipped={},
        generated_at="2026-01-01T00:00:00+00:00",
    )
    return out


def _passing_benchmarks() -> list[dict[str, object]]:
    return [
        {"id": "F1", "status": "PASS"},
        {"id": "F2", "status": "PASS"},
        {"id": "F4", "status": "PASS"},
        {"id": "F5", "status": "SKIP"},
        {"id": "F7", "status": "SKIP"},
        {"id": "F8", "status": "SKIP"},
    ]


def test_a_missing_corpus_is_a_skip_with_a_reason(tmp_path: Path):
    result = gate.check_corpus(tmp_path / "absent")
    assert result.status == "skip"
    assert "extract_fixtures" in result.detail


def test_a_valid_corpus_passes(tmp_path: Path):
    result = gate.check_corpus(_corpus(tmp_path))
    assert result.status == "pass", result.detail


def test_an_empty_corpus_is_red_not_a_pass(tmp_path: Path):
    """A green gate over zero evidence is the failure this check exists for."""
    out = tmp_path / "corpus"
    ex.write_corpus(
        [],
        out_dir=out,
        source_kind="sqlite",
        skipped={},
        generated_at="2026-01-01T00:00:00+00:00",
    )
    result = gate.check_corpus(out)
    assert result.status == "red"
    assert "empty" in result.detail


def test_a_tampered_fixture_is_red(tmp_path: Path):
    corpus = _corpus(tmp_path)
    fixture_file = next(corpus.glob("fixture-*.json"))
    fixture_file.write_text(fixture_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = gate.check_corpus(corpus)
    assert result.status == "red"
    assert "sha256" in result.detail


def test_a_manifest_from_another_schema_is_red(tmp_path: Path):
    corpus = _corpus(tmp_path)
    manifest_path = corpus / "manifest.json"
    manifest = manifest_path.read_text(encoding="utf-8").replace(
        '"schema_version": "2"', '"schema_version": "1"'
    )
    manifest_path.write_text(manifest, encoding="utf-8")
    result = gate.check_corpus(corpus)
    assert result.status == "red"
    assert "schema" in result.detail


def test_a_corpus_built_by_an_older_redaction_is_red(tmp_path: Path):
    corpus = _corpus(tmp_path)
    manifest_path = corpus / "manifest.json"
    manifest = manifest_path.read_text(encoding="utf-8").replace(
        '"redaction_version": "2"', '"redaction_version": "1"'
    )
    manifest_path.write_text(manifest, encoding="utf-8")
    result = gate.check_corpus(corpus)
    assert result.status == "red"
    assert "redaction" in result.detail


def test_an_unlisted_fixture_file_is_red(tmp_path: Path):
    corpus = _corpus(tmp_path)
    (corpus / "fixture-rogue.json").write_text("{}", encoding="utf-8")
    result = gate.check_corpus(corpus)
    assert result.status == "red"
    assert "unlisted" in result.detail


def test_the_default_policy_snapshot_covers_all_four_decisions():
    from backend.harness.policy import default_policy

    result, snapshot = gate.check_policy(default_policy())
    assert result.status == "pass", result.detail
    assert set(snapshot) == {"models", "context_budget", "escalation", "tool_limits"}


def test_a_variant_that_answers_nothing_is_red_not_informative():
    from backend.harness.policy import DefaultHarnessPolicy

    class _Broken(DefaultHarnessPolicy):
        def route_model(self, task_type):  # noqa: ANN001 - thrown-away variant
            return ""

    result, _ = gate.check_policy(_Broken(), label="variant")
    assert result.status == "red"
    assert "no usable model id" in result.detail


def test_a_whitespace_model_id_is_not_an_answer():
    from backend.harness.policy import DefaultHarnessPolicy

    class _Blank(DefaultHarnessPolicy):
        def route_model(self, task_type):  # noqa: ANN001
            return " "

    result, _ = gate.check_policy(_Blank(), label="variant")
    assert result.status == "red"


def test_a_negative_context_budget_is_not_an_answer():
    from backend.harness.policy import DefaultHarnessPolicy

    class _Negative(DefaultHarnessPolicy):
        def context_budget(self, *, phase: str = "") -> int | None:
            return -1

    result, _ = gate.check_policy(_Negative(), label="variant")
    assert result.status == "red"
    assert "context_budget" in result.detail


def test_diff_names_only_the_decisions_that_moved():
    from backend.harness.policy import DefaultHarnessPolicy

    class _Variant(DefaultHarnessPolicy):
        def route_model(self, task_type):  # noqa: ANN001
            return "variant-model"

    baseline = gate.check_policy(DefaultHarnessPolicy())[1]
    variant = gate.check_policy(_Variant())[1]
    diff = gate.diff_snapshots(baseline, variant)
    assert set(diff) == {"models"}
    assert gate.diff_snapshots(baseline, baseline) == {}


def test_benchmarks_require_pass_status_not_merely_presence():
    assert gate.check_benchmarks(_passing_benchmarks()).status == "pass"

    failing = _passing_benchmarks()
    failing[0]["status"] = "FAIL"
    assert gate.check_benchmarks(failing).status == "red"

    skipped_required = _passing_benchmarks()
    skipped_required[0]["status"] = "SKIP"
    assert gate.check_benchmarks(skipped_required).status == "red"

    missing = [item for item in _passing_benchmarks() if item["id"] != "F2"]
    assert gate.check_benchmarks(missing).status == "red"

    unknown = _passing_benchmarks() + [{"id": "F9", "status": "ERROR"}]
    assert gate.check_benchmarks(unknown).status == "red"


def test_a_gap_that_got_implemented_is_not_a_failure():
    implemented = _passing_benchmarks()
    for item in implemented:
        if item["id"] in {"F5", "F7", "F8"}:
            item["status"] = "PASS"
    assert gate.check_benchmarks(implemented).status == "pass"


def test_a_failing_runner_turns_into_a_red_check(tmp_path: Path):
    def _explode() -> list[dict[str, object]]:
        raise RuntimeError("suite broke")

    report = gate.run_gate(corpus_dir=_corpus(tmp_path), benchmark_runner=_explode)
    benchmarks = next(check for check in report.checks if check.name == "benchmarks")
    assert benchmarks.status == "red"


def test_variant_diff_is_informational_not_a_red(tmp_path: Path):
    from backend.harness.policy import DefaultHarnessPolicy

    class _Variant(DefaultHarnessPolicy):
        def route_model(self, task_type):  # noqa: ANN001
            return "variant-model"

    report = gate.run_gate(
        corpus_dir=_corpus(tmp_path),
        variant=_Variant(),
        benchmark_runner=_passing_benchmarks,
    )
    assert report.red is False
    assert "models" in report.diff
    assert report.mode == "report"


def test_a_decision_identical_variant_is_red(tmp_path: Path):
    from backend.harness.policy import DefaultHarnessPolicy

    report = gate.run_gate(
        corpus_dir=_corpus(tmp_path),
        variant=DefaultHarnessPolicy(),
        benchmark_runner=_passing_benchmarks,
    )
    variant = next(check for check in report.checks if check.name == "variant")
    assert variant.status == "red"
    assert "decision-identical" in variant.detail


def test_mode_follows_the_blocking_decision_not_the_variant(tmp_path: Path):
    report = gate.run_gate(
        corpus_dir=_corpus(tmp_path),
        benchmark_runner=_passing_benchmarks,
        fail_on_red=True,
    )
    assert report.mode == "block"


def test_the_cli_is_report_only_by_default_and_can_be_told_to_block(tmp_path: Path):
    corpus = _corpus(tmp_path)
    assert gate.main(["--corpus", str(corpus), "--skip-benchmarks"]) == 0

    fixture_file = next(corpus.glob("fixture-*.json"))
    fixture_file.write_text(fixture_file.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert gate.main(["--corpus", str(corpus), "--skip-benchmarks"]) == 0
    assert gate.main(["--corpus", str(corpus), "--skip-benchmarks", "--fail-on-red"]) == 1


def test_a_real_variant_moves_only_model_routing():
    """The shipped example changes one decision; the diff must say exactly that."""
    from backend.config.models import TaskType
    from backend.harness.policy import DefaultHarnessPolicy

    policy = gate.load_variant("scripts.eval.variants.route_lighter:make_policy")
    baseline = gate.check_policy(DefaultHarnessPolicy())[1]
    variant = gate.check_policy(policy)[1]

    diff = gate.diff_snapshots(baseline, variant)
    assert set(diff) == {"models"}
    key = TaskType.CONTENT_ANALYSIS.value
    assert diff["models"]["variant"][key] == "deepseek-v4-flash"
    assert diff["models"]["baseline"][key] != "deepseek-v4-flash"


def test_the_cli_injects_a_variant_module_by_name(tmp_path: Path, capsys):
    corpus = _corpus(tmp_path)
    code = gate.main(
        [
            "--corpus",
            str(corpus),
            "--skip-benchmarks",
            "--variant",
            "scripts.eval.variants.route_lighter:make_policy",
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "decisions changed: models" in output
    assert "mode=report red=False" in output


def test_the_report_is_json_able(tmp_path: Path):
    report = gate.run_gate(corpus_dir=_corpus(tmp_path), benchmark_runner=_passing_benchmarks)
    json.dumps(report.to_dict())


def test_load_variant_rejects_a_spec_that_is_not_a_policy():
    with pytest.raises(ValueError):
        gate.load_variant("")
    with pytest.raises(TypeError):
        gate.load_variant("json:loads")
