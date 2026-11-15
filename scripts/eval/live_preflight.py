"""E4 live-run preflight: everything checkable *before* any model call is spent.

The live L3 experiment runs in the deployment environment, not here (see
``docs/adaptive-harness-runbook.md``).  What belongs in this repository is the
gate that stops an operator from starting it in a half-prepared state:

- the plan gate itself (single source of truth: ``plan_l3.validate``);
- the baseline corpora the post-run E3 comparison needs;
- the pseudonymisation key without which live artifacts must not leave the box;
- the model-egress credential the judge and the workflow both need;
- an output directory git can never pick up.

Run with ``--armed`` right before the live window: exit 1 means *do not start*.
Nothing here launches a workflow, calls a model, or prints an env value.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

# Sibling modules (same pattern as run_gate.py): plan_l3 owns the plan rules and
# judge owns the approved call cap, so this preflight cannot drift from them.
from judge import APPROVED_MAX_CALLS, JudgeBudget  # noqa: E402
from plan_l3 import L3Plan, validate  # noqa: E402

DEFAULT_OUT = Path(".eval-live")
DEFAULT_CORPUS = Path(".eval-fixtures")
DEFAULT_TOOL_CORPUS = Path(".eval-tool-corpus")

PASS = "pass"
WARN = "warn"
BLOCK = "block"

IgnoreChecker = Callable[[Path, Path], "bool | None"]


@dataclass
class LiveCheck:
    name: str
    status: str
    detail: str


@dataclass
class PreflightReport:
    checks: list[LiveCheck] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str) -> None:
        self.checks.append(LiveCheck(name=name, status=status, detail=detail))

    @property
    def blocked(self) -> list[LiveCheck]:
        return [check for check in self.checks if check.status == BLOCK]

    @property
    def ready(self) -> bool:
        return not self.blocked

    def to_dict(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "checks": [
                {"name": check.name, "status": check.status, "detail": check.detail}
                for check in self.checks
            ],
        }

    def summary(self) -> str:
        lines = [f"live preflight: ready={'yes' if self.ready else 'no'}"]
        for check in self.checks:
            lines.append(f"[{check.status.upper()}] {check.name}: {check.detail}")
        return "\n".join(lines)


def _git_ignored(path: Path, repo_root: Path) -> bool | None:
    """True when git ignores ``path``, False when it does not, None when git fails.

    A trailing slash makes git treat the target as a directory: ``.eval-live/`` in
    ``.gitignore`` does not match the not-yet-created directory otherwise.
    """
    target = f"{path}/"
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", target],
            cwd=repo_root,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    # Anything else (not a repository, git error) means we cannot tell.
    return None


def _check_plan(plan: L3Plan, env: dict[str, str]) -> LiveCheck:
    readiness = validate(plan, environ=env)
    if not readiness.ready:
        return LiveCheck("plan", BLOCK, "; ".join(readiness.problems))
    detail = (
        f"samples={plan.samples} judge={plan.judge} "
        f"estimated_total_calls={plan.estimated_total_calls}"
    )
    if readiness.notes:
        detail = f"{detail}; {'; '.join(readiness.notes)}"
    return LiveCheck("plan", PASS, detail)


def _check_budget(plan: L3Plan) -> LiveCheck:
    try:
        budget = JudgeBudget(max_calls=plan.max_calls)
    except ValueError as exc:  # >199 or <1: plan validation should have caught it
        return LiveCheck("judge_budget", BLOCK, f"cannot construct the budget guard: {exc}")
    if budget.used != 0:
        return LiveCheck("judge_budget", BLOCK, "budget is not fresh: one budget per run")
    return LiveCheck(
        "judge_budget",
        PASS,
        f"max_calls={budget.max_calls} (approved cap {APPROVED_MAX_CALLS}); "
        "consume() charges before each call",
    )


def _read_manifest(corpus_dir: Path) -> tuple[dict[str, object] | None, str]:
    manifest = corpus_dir / "manifest.json"
    if not manifest.exists():
        return None, f"{corpus_dir}/manifest.json is missing"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{corpus_dir}/manifest.json is unreadable: {exc}"
    if not isinstance(payload, dict):
        return None, f"{corpus_dir}/manifest.json must be a JSON object"
    return payload, ""


def _check_corpus(corpus_dir: Path) -> LiveCheck:
    payload, problem = _read_manifest(corpus_dir)
    if payload is None:
        return LiveCheck("corpus", BLOCK, f"{problem}; run extract_fixtures.py first")
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        return LiveCheck("corpus", BLOCK, f"{corpus_dir}/manifest.json lists no fixtures")
    return LiveCheck(
        "corpus",
        PASS,
        f"{corpus_dir}: {len(fixtures)} fixture(s) (the post-run E3 baseline)",
    )


def _check_redaction(env: dict[str, str]) -> LiveCheck:
    if env.get("XHS_EVAL_REDACTION_KEY", "").strip():
        return LiveCheck("redaction_key", PASS, "XHS_EVAL_REDACTION_KEY is set (HMAC pseudonyms)")
    return LiveCheck(
        "redaction_key",
        BLOCK,
        "XHS_EVAL_REDACTION_KEY is empty: live artifacts are HMAC-pseudonymised with it, "
        "and without it pseudonyms are dictionary-attackable (runbook section 1)",
    )


def _check_egress(env: dict[str, str]) -> LiveCheck:
    missing = [name for name in ("MAGPIE_API_KEY", "MAGPIE_BASE_URL") if not env.get(name)]
    if missing:
        return LiveCheck(
            "model_egress",
            BLOCK,
            f"{', '.join(missing)} not set: the judge and the workflow both egress through magpie",
        )
    return LiveCheck("model_egress", PASS, "magpie gateway credentials are present")


def _check_tool_corpus(tool_corpus_dir: Path) -> LiveCheck:
    payload, problem = _read_manifest(tool_corpus_dir)
    if payload is None:
        return LiveCheck(
            "tool_corpus",
            WARN,
            f"{problem}; the E3 gate will report L2 SKIP unless it is seeded",
        )
    cases = payload.get("cases")
    count = len(cases) if isinstance(cases, list) else 0
    return LiveCheck("tool_corpus", PASS, f"{tool_corpus_dir}: {count} tool case(s)")


def _check_out_dir(
    out_dir: Path,
    repo_root: Path,
    ignore_checker: IgnoreChecker,
) -> LiveCheck:
    out_abs = (repo_root / out_dir).resolve() if not out_dir.is_absolute() else out_dir.resolve()
    repo_abs = repo_root.resolve()
    if out_abs == repo_abs:
        return LiveCheck("out_dir", BLOCK, f"{out_dir} is the repository root; pick a subdirectory")
    if not out_abs.is_relative_to(repo_abs):
        return LiveCheck("out_dir", PASS, f"{out_dir} is outside the repository")
    ignored = ignore_checker(out_abs, repo_abs)
    if ignored is True:
        return LiveCheck(
            "out_dir", PASS, f"{out_dir} is git-ignored: artifacts cannot be committed"
        )
    if ignored is False:
        return LiveCheck(
            "out_dir",
            BLOCK,
            f"{out_dir} is not git-ignored: add it to .gitignore "
            "before writing live artifacts there",
        )
    return LiveCheck(
        "out_dir",
        WARN,
        f"git is unavailable; confirm {out_dir} is ignored before writing artifacts there",
    )


def run_preflight(
    plan: L3Plan,
    *,
    env: dict[str, str] | None = None,
    repo_root: Path | None = None,
    out_dir: Path = DEFAULT_OUT,
    corpus_dir: Path = DEFAULT_CORPUS,
    tool_corpus_dir: Path = DEFAULT_TOOL_CORPUS,
    ignore_checker: IgnoreChecker | None = None,
) -> PreflightReport:
    """Check every precondition in a fixed order; every blocked check is reported."""
    environ = dict(os.environ) if env is None else env
    root = Path(".") if repo_root is None else repo_root
    checker = _git_ignored if ignore_checker is None else ignore_checker
    report = PreflightReport()
    for check in (
        _check_plan(plan, environ),
        _check_budget(plan),
        _check_redaction(environ),
        _check_egress(environ),
        _check_corpus(corpus_dir),
        _check_tool_corpus(tool_corpus_dir),
        _check_out_dir(out_dir, root, checker),
    ):
        report.add(check.name, check.status, check.detail)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check an E4 live run is fully prepared (offline; launches nothing)"
    )
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--account", default="", help="the test account id for the run")
    parser.add_argument("--judge", choices=("llm", "human", "none"), default="llm")
    parser.add_argument("--max-calls", type=int, default=APPROVED_MAX_CALLS)
    parser.add_argument("--phases", default="reviewing")
    parser.add_argument("--calls-per-sample", type=int, default=0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--tool-corpus", type=Path, default=DEFAULT_TOOL_CORPUS)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--armed",
        action="store_true",
        help="exit 1 when any check blocks (use as a pre-run gate)",
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    options = _build_parser().parse_args(argv)
    plan = L3Plan(
        samples=options.samples,
        account=options.account,
        judge=options.judge,
        max_calls=options.max_calls,
        phases=tuple(part.strip() for part in options.phases.split(",") if part.strip()),
        calls_per_sample=options.calls_per_sample,
    )
    report = run_preflight(
        plan,
        repo_root=options.repo_root,
        out_dir=options.out,
        corpus_dir=options.corpus,
        tool_corpus_dir=options.tool_corpus,
    )
    if options.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.summary())
    if options.armed and not report.ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
