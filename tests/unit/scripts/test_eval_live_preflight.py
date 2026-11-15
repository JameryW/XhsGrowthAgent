"""E4 live-run preflight: refuse to start a live run in a half-prepared state.

The live run itself is external, so this module is the last thing that can fail
*locally*: missing baseline corpora, missing pseudonymisation key, missing model
egress credentials, or an output directory git could commit.  A preflight that
says "ready" wrongly would be the thing an operator points at when a live run
leaks content or over-spends, so the blocks are pinned here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / "scripts" / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import live_preflight as live_preflight  # noqa: E402

ENV = {
    "XHS_EVAL_LIVE": "1",
    "XHS_EVAL_REDACTION_KEY": "hmac-test-key",
    "MAGPIE_API_KEY": "sk-test",
    "MAGPIE_BASE_URL": "http://10.0.0.10:3425/v1",
}
IGNORED = lambda _path, _root: True  # noqa: E731  (tiny injectable checker)
NOT_IGNORED = lambda _path, _root: False  # noqa: E731


def _plan(**overrides):
    base = {
        "samples": 3,
        "account": "test-account",
        "judge": "llm",
        "max_calls": 199,
        "calls_per_sample": 5,
    }
    base.update(overrides)
    return live_preflight.L3Plan(**base)


def _write_corpus(root: Path, *, fixtures: int = 1, name: str = "corpus") -> Path:
    corpus = root / name
    corpus.mkdir(parents=True, exist_ok=True)
    payload = {"fixtures": [{"fixture_id": f"fixture-{index}"} for index in range(fixtures)]}
    (corpus / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return corpus


def _write_tools(root: Path, *, cases: int = 2) -> Path:
    tools = root / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    payload = {"cases": [{"case_id": f"case-{index}"} for index in range(cases)]}
    (tools / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return tools


def _report(tmp_path: Path, *, plan=None, env=None, **overrides):
    options = {
        "env": ENV if env is None else env,
        "repo_root": tmp_path / "repo",
        "out_dir": Path(".eval-live"),
        "corpus_dir": _write_corpus(tmp_path),
        "tool_corpus_dir": _write_tools(tmp_path),
        "ignore_checker": IGNORED,
    }
    options.update(overrides)
    return live_preflight.run_preflight(plan or _plan(), **options)


def _check(report, name: str):
    for check in report.checks:
        if check.name == name:
            return check
    raise AssertionError(f"no check named {name!r}: {[c.name for c in report.checks]}")


def test_fully_prepared_run_is_ready(tmp_path):
    report = _report(tmp_path)
    assert report.ready is True, report.summary()
    assert report.blocked == []
    assert _check(report, "corpus").status == live_preflight.PASS
    assert _check(report, "tool_corpus").status == live_preflight.PASS


def test_missing_account_blocks_the_plan(tmp_path):
    report = _report(tmp_path, plan=_plan(account=""))
    assert report.ready is False
    assert _check(report, "plan").status == live_preflight.BLOCK
    assert "account is required" in _check(report, "plan").detail


def test_unarmed_live_run_is_blocked(tmp_path):
    env = {key: value for key, value in ENV.items() if key != "XHS_EVAL_LIVE"}
    report = _report(tmp_path, env=env)
    assert report.ready is False
    assert "XHS_EVAL_LIVE=1" in _check(report, "plan").detail


def test_judge_none_is_blocked(tmp_path):
    report = _report(tmp_path, plan=_plan(judge="none"))
    assert report.ready is False
    assert "judge is 'none'" in _check(report, "plan").detail


def test_human_judge_passes_but_records_the_human_note(tmp_path):
    report = _report(tmp_path, plan=_plan(judge="human"))
    plan_check = _check(report, "plan")
    assert plan_check.status == live_preflight.PASS
    assert "human reviewer" in plan_check.detail


def test_missing_redaction_key_blocks(tmp_path):
    env = {key: value for key, value in ENV.items() if key != "XHS_EVAL_REDACTION_KEY"}
    report = _report(tmp_path, env=env)
    assert report.ready is False
    check = _check(report, "redaction_key")
    assert check.status == live_preflight.BLOCK
    assert "XHS_EVAL_REDACTION_KEY" in check.detail


def test_missing_magpie_credentials_block(tmp_path):
    env = {key: value for key, value in ENV.items() if key != "MAGPIE_API_KEY"}
    report = _report(tmp_path, env=env)
    assert report.ready is False
    assert "MAGPIE_API_KEY" in _check(report, "model_egress").detail


def test_missing_corpus_blocks(tmp_path):
    report = _report(tmp_path, corpus_dir=tmp_path / "does-not-exist")
    assert report.ready is False
    assert "missing" in _check(report, "corpus").detail


def test_corpus_without_fixtures_blocks(tmp_path):
    corpus = tmp_path / "empty-corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text('{"fixtures": []}', encoding="utf-8")
    report = _report(tmp_path, corpus_dir=corpus)
    assert report.ready is False
    assert "no fixtures" in _check(report, "corpus").detail


def test_unreadable_corpus_manifest_blocks(tmp_path):
    corpus = tmp_path / "bad-corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text("not json", encoding="utf-8")
    report = _report(tmp_path, corpus_dir=corpus)
    assert report.ready is False
    assert "unreadable" in _check(report, "corpus").detail


def test_missing_tool_corpus_only_warns(tmp_path):
    report = _report(tmp_path, tool_corpus_dir=tmp_path / "no-tools")
    assert report.ready is True
    check = _check(report, "tool_corpus")
    assert check.status == live_preflight.WARN
    assert "L2 SKIP" in check.detail


def test_unignored_out_dir_blocks(tmp_path):
    report = _report(tmp_path, ignore_checker=NOT_IGNORED)
    assert report.ready is False
    assert "not git-ignored" in _check(report, "out_dir").detail


def test_unavailable_git_warns_instead_of_blocking(tmp_path):
    report = _report(tmp_path, ignore_checker=lambda _path, _root: None)
    assert report.ready is True
    check = _check(report, "out_dir")
    assert check.status == live_preflight.WARN
    assert "git is unavailable" in check.detail


def test_out_dir_at_repo_root_is_blocked(tmp_path):
    report = _report(tmp_path, out_dir=Path("."))
    assert report.ready is False
    assert "repository root" in _check(report, "out_dir").detail


def test_out_dir_outside_repo_passes(tmp_path):
    report = _report(tmp_path, out_dir=tmp_path / "outside", ignore_checker=NOT_IGNORED)
    assert report.ready is True
    assert "outside the repository" in _check(report, "out_dir").detail


def test_budget_check_pins_the_approved_cap(tmp_path):
    report = _report(tmp_path)
    check = _check(report, "judge_budget")
    assert check.status == live_preflight.PASS
    assert "approved cap 199" in check.detail
    assert "charges before each call" in check.detail


def test_report_dict_and_summary_cover_every_check(tmp_path):
    report = _report(tmp_path)
    payload = report.to_dict()
    assert payload["ready"] is True
    names = [item["name"] for item in payload["checks"]]
    assert names == [
        "plan",
        "judge_budget",
        "redaction_key",
        "model_egress",
        "corpus",
        "tool_corpus",
        "out_dir",
    ]
    summary = report.summary()
    for name in names:
        assert name in summary


def test_git_ignored_handles_directory_patterns(tmp_path):
    """``.eval-live/`` in .gitignore must match the not-yet-created output directory."""
    import shutil
    import subprocess

    assert shutil.which("git"), "git is required for this guard"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text(".artifacts/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    assert live_preflight._git_ignored(repo / ".artifacts", repo) is True
    assert live_preflight._git_ignored(repo / "tracked", repo) is False


def _set_env(monkeypatch, env: dict[str, str]) -> None:
    for key in ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _cli_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--corpus",
        str(_write_corpus(tmp_path)),
        "--tool-corpus",
        str(_write_tools(tmp_path)),
        "--repo-root",
        str(tmp_path / "repo"),
        *extra,
    ]


def test_cli_armed_exits_zero_only_when_ready(tmp_path, monkeypatch):
    _set_env(monkeypatch, ENV)
    ready = _cli_args(tmp_path, "--armed", "--account", "test-account", "--calls-per-sample", "5")
    assert live_preflight.main(ready) == 0

    blocked = _cli_args(tmp_path, "--armed", "--account", "", "--calls-per-sample", "5")
    assert live_preflight.main(blocked) == 1


def test_cli_without_armed_never_fails_the_shell(tmp_path, monkeypatch):
    _set_env(monkeypatch, ENV)
    blocked = _cli_args(tmp_path, "--account", "", "--calls-per-sample", "5")
    assert live_preflight.main(blocked) == 0


def test_cli_json_report_never_prints_credentials(tmp_path, monkeypatch, capsys):
    env = dict(ENV)
    env["MAGPIE_API_KEY"] = "sk-secret-value-must-not-leak"
    env["XHS_EVAL_REDACTION_KEY"] = "hmac-secret-value-must-not-leak"
    _set_env(monkeypatch, env)
    args = _cli_args(tmp_path, "--json", "--account", "test-account", "--calls-per-sample", "5")

    assert live_preflight.main(args) == 0
    output = capsys.readouterr().out
    assert "sk-secret-value-must-not-leak" not in output
    assert "hmac-secret-value-must-not-leak" not in output
    payload = json.loads(output)
    assert payload["ready"] is True
