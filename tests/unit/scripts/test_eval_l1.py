"""L1 decision replay (E3): mandatory invariants, determinism, preference diff.

The eval plan (§3/§4) says L1 must replay recorded fixtures and compare the
variant's decisions with the expected ones: mandatory rules 100% identical,
preference differences reported.  The "expected" side is the baseline policy, so
these tests pin three properties that failure mode would hide:

* a baseline replay is clean and decision-identical (no drift on correct code);
* a variant that moves a budget degrades to a *reported* preference diff, not a
  red — the difference is the point of an A/B run;
* a policy that breaks a hard rule (blank routing, duplicate escalation, a
  nondeterministic answer) is red even when the diff itself looks harmless.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / "scripts" / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import decision_replay as replay  # noqa: E402  (sibling module after sys.path setup)
import fixtures as fx  # noqa: E402
import run_gate as gate  # noqa: E402

from backend.config.models import TaskType  # noqa: E402
from backend.harness.policy import DefaultHarnessPolicy  # noqa: E402


def _fixture(fixture_id: str = "f1", phase: str = "reviewing", state=None) -> fx.EvalFixture:
    resolved = dict(state) if state is not None else {"phase": phase}
    return fx.EvalFixture(
        fixture_id=fixture_id,
        source="sqlite",
        thread_pseudonym="thread_abc",
        phase=phase,
        state_sha256=fx.state_sha256(resolved),
        redactions=fx.RedactionReport(),
        state=resolved,
    )


def _write_corpus(root: Path, fixtures: list[fx.EvalFixture]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    entries: list[fx.FixtureEntry] = []
    for fixture in fixtures:
        name = f"{fixture.fixture_id}.json"
        payload = fixture.model_dump_json(indent=2).encode("utf-8")
        (root / name).write_bytes(payload)
        entries.append(
            fx.FixtureEntry(
                fixture_id=fixture.fixture_id,
                file=name,
                sha256=hashlib.sha256(payload).hexdigest(),
                phase=fixture.phase,
                thread_pseudonym=fixture.thread_pseudonym,
            )
        )
    manifest = fx.FixtureManifest(
        source_kind="sqlite",
        generated_at="2026-11-14T00:00:00+00:00",
        total=len(entries),
        fixtures=entries,
    )
    manifest_bytes = manifest.model_dump_json(indent=2).encode("utf-8")
    (root / "manifest.json").write_bytes(manifest_bytes)
    (root / "manifest.sha256").write_text(
        hashlib.sha256(manifest_bytes).hexdigest(), encoding="utf-8"
    )
    return root


class _PublishingBudget(DefaultHarnessPolicy):
    """A one-decision variant: publishing gets a 4000-token budget."""

    def context_budget(self, *, phase: str = "") -> int | None:
        if phase == "publishing":
            return 4000
        return super().context_budget(phase=phase)


class _BlankRouting(DefaultHarnessPolicy):
    def route_model(self, task_type: TaskType) -> str:
        if task_type is TaskType.PUBLISHING:
            return "   "
        return super().route_model(task_type)


class _DuplicateEscalation(DefaultHarnessPolicy):
    def escalation_targets(self, task_type: TaskType) -> tuple[str, ...]:
        return ("model-a", "model-a")


class _Nondeterministic(DefaultHarnessPolicy):
    def __init__(self) -> None:
        self._calls = 0

    def context_budget(self, *, phase: str = "") -> int | None:
        self._calls += 1
        return None if self._calls % 2 else 100


def test_a_baseline_replay_is_clean_and_decision_identical(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [_fixture()])

    outcome = replay.run_l1_replay(DefaultHarnessPolicy(), corpus)

    assert outcome.status == "pass"
    assert outcome.fixtures == 1
    assert outcome.diff == {}
    assert "identical to the baseline" in outcome.detail


def test_a_variant_budget_change_is_a_preference_diff_not_a_red(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [_fixture(phase="publishing")])

    outcome = replay.run_l1_replay(_PublishingBudget(), corpus, variant=True)

    assert outcome.status == "pass"
    assert outcome.diff["f1"]["context_budget"] == {"baseline": None, "current": 4000}
    assert "preference differences on 1 fixture" in outcome.detail


def test_a_non_baseline_policy_without_variant_is_red(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [_fixture(phase="publishing")])

    outcome = replay.run_l1_replay(_PublishingBudget(), corpus, variant=False)

    assert outcome.status == "red"
    assert "baseline replay must be decision-identical" in outcome.detail


def test_a_blank_model_id_is_a_mandatory_red(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [_fixture()])

    outcome = replay.run_l1_replay(_BlankRouting(), corpus, variant=True)

    assert outcome.status == "red"
    assert "mandatory rules broken" in outcome.detail
    assert "no model id for publishing" in outcome.detail


def test_nondeterministic_decisions_are_red(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [_fixture()])

    outcome = replay.run_l1_replay(_Nondeterministic(), corpus, variant=True)

    assert outcome.status == "red"
    assert "not deterministic" in outcome.detail


def test_duplicate_escalation_targets_are_a_mandatory_red(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [_fixture()])

    outcome = replay.run_l1_replay(_DuplicateEscalation(), corpus, variant=True)

    assert outcome.status == "red"
    assert "repeats a target" in outcome.detail


def test_missing_corpus_is_a_skip_not_a_pass(tmp_path: Path):
    outcome = replay.run_l1_replay(DefaultHarnessPolicy(), tmp_path / "absent")

    assert outcome.status == "skip"
    assert "missing corpus is a gap, not a pass" in outcome.detail


def test_unreadable_corpus_is_red(tmp_path: Path):
    bad = tmp_path / "corpus"
    bad.mkdir()
    (bad / "manifest.json").write_text("{not json", encoding="utf-8")

    outcome = replay.run_l1_replay(DefaultHarnessPolicy(), bad)

    assert outcome.status == "red"
    assert "could not be replayed" in outcome.detail


def test_empty_corpus_is_a_skip_with_a_reason(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [])
    # `total == 0` with no entries; the corpus check owns the red for this.
    outcome = replay.run_l1_replay(DefaultHarnessPolicy(), corpus)

    assert outcome.status == "skip"
    assert "0 fixtures" in outcome.detail


def test_the_gate_runs_l1_and_reports_it(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [_fixture(), _fixture("f2", "planning")])

    report = gate.run_gate(corpus_dir=corpus, skip_benchmarks=True)

    by_name = {check.name: check for check in report.checks}
    assert by_name["l1"].status == "pass"
    assert report.l1 == {
        "status": "pass",
        "fixtures": 2,
        "fixtures_with_preference_diff": 0,
        "diff": {},
    }
    payload = report.to_dict()
    assert payload["l1"]["fixtures"] == 2
    assert payload["l1"] is not None and "l1_diff" not in payload
    json.dumps(payload)


def test_the_gate_reports_a_skipped_l1_as_a_skip(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [_fixture()])

    report = gate.run_gate(corpus_dir=corpus, skip_benchmarks=True, skip_l1=True)

    by_name = {check.name: check for check in report.checks}
    assert by_name["l1"].status == "skip"
    assert "--skip-l1" in by_name["l1"].detail


def test_the_gate_attaches_the_preference_diff_for_a_variant(tmp_path: Path):
    corpus = _write_corpus(tmp_path / "corpus", [_fixture(phase="publishing")])

    report = gate.run_gate(corpus_dir=corpus, variant=_PublishingBudget(), skip_benchmarks=True)

    by_name = {check.name: check for check in report.checks}
    assert by_name["l1"].status == "pass"
    assert by_name["variant"].status == "pass"
    assert report.l1_diff["f1"]["context_budget"]["current"] == 4000
    assert report.to_dict()["red"] is False


@pytest.mark.parametrize("value", [None, 0, 10], ids=["none", "zero", "ten"])
def test_budgets_at_the_boundary_are_valid(tmp_path: Path, value: int | None):
    """None and non-negative ints are legal; only <0 / bool / non-int are red."""
    record = replay.DecisionRecord(
        fixture_id="f1",
        phase="reviewing",
        models={task.value: "model-x" for task in TaskType},
        context_budget=value,
        escalation={task.value: () for task in TaskType},
        tool_limits={},
    )
    assert replay.mandatory_problems([record]) == []


def test_a_boolean_budget_is_rejected():
    record = replay.DecisionRecord(
        fixture_id="f1",
        phase="reviewing",
        models={task.value: "model-x" for task in TaskType},
        context_budget=True,  # type: ignore[arg-type]
        escalation={task.value: () for task in TaskType},
        tool_limits={},
    )
    problems = replay.mandatory_problems([record])
    assert any("context budget" in problem for problem in problems)
