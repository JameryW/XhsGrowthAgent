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
    for name in ("lint", "format", "mypy", "gates", "tests", "frontend", "omp"):
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
