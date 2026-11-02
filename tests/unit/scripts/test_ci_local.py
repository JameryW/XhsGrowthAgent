"""Coverage for the local CI parity runner (scripts/ci_local.py).

The runner is a developer tool, not production code, but two of its parts answer
questions that can silently rot: the job list (which must stay in step with what
CI actually runs) and the LF-normalisation assumption (the reason the format job
does not simply call ``ruff format --check .``).  These tests pin the cheap,
deterministic halves; the heavy jobs are exercised by running the script.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "ci_local.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_local_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The script uses ``from __future__ import annotations``, so dataclasses
    # resolves its string annotations through ``sys.modules[cls.__module__]``.
    # Without this registration the exec below fails inside dataclasses.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_list_prints_every_job_name(capsys):
    assert _module().main(["--list"]) == 0
    output = capsys.readouterr().out
    for name in ("lint", "format", "mypy", "gates", "eval-gate", "tests", "frontend", "omp"):
        assert name in output, f"{name} missing from --list output"


def test_an_unknown_only_value_is_a_usage_error(capsys):
    assert _module().main(["--only", "nope"]) == 2
    output = capsys.readouterr().out
    assert "unknown job" in output
    assert "lint" in output  # the message lists the known names


def test_skip_tests_marks_the_tests_job_skipped():
    jobs = {job.name: job for job in _module()._jobs(skip_tests=True)}
    status, detail = jobs["tests"].run()
    assert status == "SKIP"
    assert "--skip-tests" in detail


def test_tail_keeps_the_end_and_marks_truncation():
    module = _module()
    assert module._tail("abc") == "abc"
    truncated = module._tail("x" * 50, limit=10)
    assert truncated.startswith("...")
    assert truncated.endswith("x" * 10)


def test_tracked_python_files_lists_repo_modules():
    files = _module()._tracked_python_files()
    assert "backend/agents/publisher.py" in files
    # Newly added files are untracked until committed, so the assertion is about
    # a tracked module and the scale of the list, not about this script itself.
    assert len(files) > 500


def test_the_tests_job_says_when_postgres_parity_will_skip(monkeypatch):
    """No URI -> PASS, but the summary must not imply parity coverage."""
    module = _module()
    monkeypatch.delenv("XHS_PG_PARITY_URI", raising=False)
    module._run = lambda argv, *, cwd=None: (0, "4823 passed")
    status, detail = module.job_tests(skip=False)
    assert status == "PASS"
    assert "Postgres parity skipped" in detail


def test_the_tests_job_reruns_the_parity_module_when_a_uri_is_set(monkeypatch):
    """Mirror CI: the parity module is re-run and must report 'passed'."""
    module = _module()
    monkeypatch.setenv("XHS_PG_PARITY_URI", "postgresql://example/db")
    calls: list[list[str]] = []

    def fake_run(argv, *, cwd=None):
        calls.append(list(argv))
        if any("test_creator_agent_backend_parity" in str(part) for part in argv):
            return 0, "3 passed"
        return 0, "4823 passed"

    module._run = fake_run
    status, detail = module.job_tests(skip=False)
    assert status == "PASS"
    assert "parity executed" in detail
    assert len(calls) == 2, calls


def test_the_tests_job_fails_when_parity_is_silently_skipped(monkeypatch):
    """Exit 0 with no 'passed' is the failure mode CI exists to catch."""
    module = _module()
    monkeypatch.setenv("XHS_PG_PARITY_URI", "postgresql://example/db")

    def fake_run(argv, *, cwd=None):
        if any("test_creator_agent_backend_parity" in str(part) for part in argv):
            return 0, "1 skipped in 0.1s"
        return 0, "4823 passed"

    module._run = fake_run
    status, detail = module.job_tests(skip=False)
    assert status == "FAIL"
    assert "did not execute" in detail


def test_the_eval_gate_skips_when_no_local_corpus_exists(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(module, "REPO", tmp_path)
    status, detail = module.job_eval_gate()
    assert status == "SKIP"
    assert ".eval-fixtures" in detail


def test_the_eval_gate_runs_when_a_local_corpus_exists(monkeypatch, tmp_path):
    module = _module()
    monkeypatch.setattr(module, "REPO", tmp_path)
    (tmp_path / ".eval-fixtures").mkdir()
    calls = []

    def fake_expect_ok(argv, *, cwd=None, detail=""):
        calls.append([str(part) for part in argv])
        return "PASS", detail

    monkeypatch.setattr(module, "_expect_ok", fake_expect_ok)
    status, detail = module.job_eval_gate()
    assert status == "PASS"
    assert "run_gate.py" in " ".join(calls[0])
    assert "--fail-on-red" in calls[0]
    assert "E3 offline A/B gate" in detail
