"""Local CI parity runner.

CI runs nine jobs; several of them are not directly runnable in a sandboxed
Windows checkout.  This script runs the ones that *are* locally runnable, with
the two environment workarounds written down instead of rediscovered:

* ``ruff format --check .`` false-positives on mixed CRLF checkouts, so the
  format job copies the tracked ``.py`` files into a temporary tree with LF line
  endings (plus ``pyproject.toml``) and checks that instead;
* ``mypy backend`` cannot parse modern numpy stubs under ``python_version=3.11``;
  when that specific failure is seen, the job retries with ``--python-version
  3.12`` and says so (CI installs no numpy, so CI itself has no such problem).

Jobs that genuinely need CI infrastructure are reported as SKIP with the reason
(no Postgres service, missing ``node_modules``, sandbox-blocked vitest) rather
than silently passing.

Usage::

    python scripts/ci_local.py                 # all locally runnable jobs
    python scripts/ci_local.py --list
    python scripts/ci_local.py --skip-tests
    python scripts/ci_local.py --only lint,format,mypy
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

_GATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "context-compiler-baseline",
        (
            "scripts/benchmarks/context_compiler_baseline.py",
            "--compare",
            "--drift-pct",
            "5",
        ),
    ),
    ("harness-benchmarks", ("scripts/benchmarks/harness_benchmarks.py",)),
    ("tool-runtime-gate", ("scripts/gates/tool_runtime_gate.py",)),
    ("compliance-gate", ("scripts/gates/stealth_default_off.py",)),
)


def _run(argv: Sequence[str], *, cwd: Path = REPO) -> tuple[int, str]:
    """Run one child process and return ``(exit_code, output)``.

    Output is redirected to a temporary file instead of a pipe: the sandbox this
    repo is often developed in refuses piped stdio between processes, and a file
    redirect needs no named pipe.
    """
    argv = [str(part) for part in argv]
    handle, log_path = tempfile.mkstemp(prefix="ci-local-", suffix=".log")
    try:
        with open(handle, "wb") as sink:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                argv, cwd=str(cwd), stdout=sink, stderr=subprocess.STDOUT
            )
        output = Path(log_path).read_text(encoding="utf-8", errors="replace")
        return completed.returncode, output
    finally:
        Path(log_path).unlink(missing_ok=True)


def _tail(text: str, limit: int = 4000) -> str:
    text = text.strip()
    return text if len(text) <= limit else "...\n" + text[-limit:]


def _make_temp_dir(prefix: str) -> Path:
    """A writable temp dir.

    ``tempfile.mkdtemp`` creates the directory with mode 0700; the sandbox this
    repo is developed in then refuses to create files inside it.  An explicit
    0o777 mkdir in the workspace is writable, and the caller removes it.
    """
    path = REPO / f"{prefix}{os.getpid()}-{time.time_ns()}"
    path.mkdir(mode=0o777)
    return path


def _tracked_python_files() -> list[str]:
    code, output = _run(["git", "ls-files", "*.py"])
    if code != 0:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def _expect_ok(argv: Sequence[str], *, cwd: Path = REPO, detail: str = "") -> tuple[str, str]:
    code, output = _run(argv, cwd=cwd)
    if code == 0:
        return PASS, detail or "ok"
    return FAIL, _tail(output)


def job_lint() -> tuple[str, str]:
    return _expect_ok(
        [PY, "-m", "ruff", "check", "backend", "tests", "scripts"], detail="ruff check"
    )


def job_format() -> tuple[str, str]:
    tracked = _tracked_python_files()
    if not tracked:
        return FAIL, "git ls-files '*.py' returned nothing"
    tmp_root = _make_temp_dir(".ci-local-format-")
    try:
        shutil.copy2(REPO / "pyproject.toml", tmp_root / "pyproject.toml")
        for relative in tracked:
            source = REPO / relative
            if not source.is_file():
                continue
            destination = tmp_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        code, output = _run([PY, "-m", "ruff", "format", "--check", "."], cwd=tmp_root)
        if code == 0:
            return PASS, f"ruff format: {len(tracked)} tracked .py files clean (LF-normalised)"
        return FAIL, _tail(output)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
        if tmp_root.exists():  # best-effort: a leftover is gitignored, not fatal
            for child in sorted(tmp_root.rglob("*"), reverse=True):
                with contextlib.suppress(OSError):
                    child.chmod(0o777)
            shutil.rmtree(tmp_root, ignore_errors=True)


def job_mypy() -> tuple[str, str]:
    code, output = _run([PY, "-m", "mypy", "backend"])
    if code == 0:
        return PASS, "mypy backend: no issues"
    if "Type statement is only supported in Python 3.12" in output:
        code, output = _run([PY, "-m", "mypy", "--python-version", "3.12", "backend"])
        if code == 0:
            return PASS, (
                "mypy backend: no issues with --python-version 3.12 "
                "(local numpy stubs cannot be parsed under 3.11; CI installs no numpy)"
            )
    return FAIL, _tail(output)


def job_gates() -> tuple[str, str]:
    failures: list[str] = []
    lines: list[str] = []
    for name, argv in _GATES:
        code, output = _run([PY, *argv])
        lines.append(f"{name}: {'ok' if code == 0 else 'FAIL'}")
        if code != 0:
            failures.append(f"{name}\n{_tail(output)}")
    detail = "; ".join(lines)
    if failures:
        return FAIL, "\n\n".join(failures)
    return PASS, detail


def _npm_argv(args: Sequence[str]) -> list[str] | None:
    executable = shutil.which("npm")
    if executable is None:
        return None
    # Windows installs npm as a .cmd shim, which CreateProcess cannot start
    # directly; cmd /c is the portable way to run it without a shell string.
    if executable.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", executable, *args]
    return [executable, *args]


def job_frontend() -> tuple[str, str]:
    frontend = REPO / "frontend"
    if not (frontend / "node_modules").is_dir():
        return SKIP, "frontend/node_modules missing (run npm install; sandbox may block npm cache)"
    argv = _npm_argv(["run", "type-check"])
    if argv is None:
        return SKIP, "npm not found on PATH"
    type_check = _run(argv, cwd=frontend)
    i18n_argv = _npm_argv(["run", "i18n:check"])
    assert i18n_argv is not None
    i18n = _run(i18n_argv, cwd=frontend)
    if type_check[0] == 0 and i18n[0] == 0:
        return PASS, "vue-tsc + i18n check ok"
    return FAIL, _tail(type_check[1] if type_check[0] else i18n[1])


def job_omp() -> tuple[str, str]:
    extension = REPO / "backend" / "omp" / "extensions" / "xhsagent-ext"
    if not (extension / "node_modules").is_dir():
        return SKIP, (
            f"{extension.relative_to(REPO).as_posix()}/node_modules missing "
            "(npm install with --cache <workspace>/.npm-cache)"
        )
    argv = _npm_argv(["run", "typecheck"])
    if argv is None:
        return SKIP, "npm not found on PATH"
    return _expect_ok(argv, cwd=extension, detail="tsc --noEmit")


def job_tests(*, skip: bool) -> tuple[str, str]:
    if skip:
        return SKIP, "--skip-tests"
    return _expect_ok([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider"], detail="pytest -q")


@dataclass(frozen=True)
class _Job:
    name: str
    description: str
    run: Callable[[], tuple[str, str]]


def _jobs(skip_tests: bool) -> tuple[_Job, ...]:
    return (
        _Job("lint", "ruff check backend tests scripts", job_lint),
        _Job("format", "ruff format --check over LF-normalised tracked files", job_format),
        _Job("mypy", "mypy backend (retries with target 3.12 on local numpy stubs)", job_mypy),
        _Job(
            "gates", "context compiler / harness benchmarks / tool runtime / compliance", job_gates
        ),
        _Job(
            "tests",
            "pytest -q (full suite; --skip-tests to skip)",
            lambda: job_tests(skip=skip_tests),
        ),
        _Job("frontend", "frontend type-check + i18n (SKIP without node_modules)", job_frontend),
        _Job("omp", "OMP extension tsc --noEmit (SKIP without node_modules)", job_omp),
    )


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--list", action="store_true", help="print the job names and exit")
    parser.add_argument("--skip-tests", action="store_true", help="skip the full pytest job")
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated job names to run (default: all locally runnable)",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    options = _parse(argv)
    all_jobs = _jobs(options.skip_tests)
    if options.list:
        for job in all_jobs:
            print(f"{job.name:<10} {job.description}")
        return 0
    selected = {name.strip() for name in options.only.split(",") if name.strip()}
    known = {job.name for job in all_jobs}
    unknown = sorted(selected - known)
    if unknown:
        print(f"unknown job(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}")
        return 2
    jobs = [job for job in all_jobs if not selected or job.name in selected]
    results: list[tuple[str, str, str]] = []
    for job in jobs:
        try:
            status, detail = job.run()
        except Exception as exc:  # noqa: BLE001 - a local runner reports, it does not crash
            status, detail = FAIL, f"{type(exc).__name__}: {exc}"
        results.append((job.name, status, detail))
        print(f"[{status}] {job.name}: {detail.splitlines()[0] if detail else ''}")
    failed = [name for name, status, _ in results if status == FAIL]
    print()
    for name, status, detail in results:
        suffix = "" if status == PASS else f"  ({detail.splitlines()[0] if detail else ''})"
        print(f"{status:<4} {name}{suffix}")
    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        return 1
    print("\nlocal CI parity: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
