"""Adaptive Harness A/B gate (P3/E3): run the offline checks and report.

E3 is deliberately **report-only by default** (``--fail-on-red`` opts into blocking)
because the gate hardness and the "may a variant replace the production default"
questions are still open in ``docs/adaptive-harness-eval-plan.md`` §6.  The only
variants this script can run are ones passed explicitly with ``--variant`` — it
never changes a production default, so it is safe to run before those decisions
land.

What it checks:

* **corpus** — the E1 fixture directory: manifest schema, per-file sha256 and the
  fixture's own ``state_sha256`` recompute.  A missing corpus is a *skip* with the
  reason (run the extractor first), not a pass and not a red;
* **policy** — the E2 snapshot is complete and answers every decision (a variant
  that returns an empty model id is red, not "different");
* **variant** — when one is supplied, which decisions moved (informational: a
  difference is the point of an A/B run, not a failure);
* **benchmarks** — the deterministic F1/F2/F4 harness checks must pass and
  F5/F7/F8 must still be reported as SKIP (a skipped gap is not a pass).

Usage::

    python scripts/eval/run_gate.py
    python scripts/eval/run_gate.py --variant mymodule:make_policy --fail-on-red
    python scripts/eval/run_gate.py --skip-benchmarks --json gate.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

_EVAL_DIR = Path(__file__).resolve().parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from fixtures import (  # noqa: E402  (sibling module, loaded after sys.path setup)
    SCHEMA_VERSION,
    EvalFixture,
    FixtureManifest,
    state_sha256,
)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = Path(".eval-fixtures")
_REQUIRED_BENCHMARKS = ("F1", "F2", "F4")
_SKIPPED_GAPS = ("F5", "F7", "F8")
_STATUS = Literal["pass", "red", "skip"]


class BenchmarkRunner(Protocol):
    """Runs the deterministic harness suite and returns its JSON reports."""

    def __call__(self) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: _STATUS
    detail: str


@dataclass
class GateReport:
    mode: str
    generated_at: str
    checks: list[CheckResult] = field(default_factory=list)
    policy_snapshot: dict[str, Any] = field(default_factory=dict)
    variant_snapshot: dict[str, Any] | None = None
    diff: dict[str, Any] = field(default_factory=dict)

    @property
    def red(self) -> bool:
        return any(check.status == "red" for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "generated_at": self.generated_at,
            "red": self.red,
            "checks": [asdict_check(check) for check in self.checks],
            "policy_snapshot": self.policy_snapshot,
            "variant_snapshot": self.variant_snapshot,
            "diff": self.diff,
        }


def asdict_check(check: CheckResult) -> dict[str, str]:
    return {"name": check.name, "status": check.status, "detail": check.detail}


def _scratch_dir() -> Path:
    """A dot-prefixed scratch dir inside the repo (sandbox temp is not writable)."""
    path = REPO / ".eval-tmp"
    path.mkdir(mode=0o777, exist_ok=True)
    return path


def run_harness_benchmarks() -> list[dict[str, Any]]:
    """Run ``harness_benchmarks.py`` through files (piped stdio is blocked here)."""
    scratch = _scratch_dir()
    json_path = scratch / "harness-benchmarks.json"
    out_path = scratch / "harness-benchmarks.stdout"
    err_path = scratch / "harness-benchmarks.stderr"
    with out_path.open("wb") as out, err_path.open("wb") as err:
        completed = subprocess.run(  # noqa: S603  (fixed argv, same interpreter)
            [
                sys.executable,
                str(REPO / "scripts" / "benchmarks" / "harness_benchmarks.py"),
                "--json",
                str(json_path),
            ],
            stdout=out,
            stderr=err,
            cwd=REPO,
            check=False,
        )
    if completed.returncode != 0 or not json_path.is_file():
        raise RuntimeError(
            f"harness benchmarks failed (exit {completed.returncode}); see {out_path}"
        )
    return json.loads(json_path.read_text(encoding="utf-8"))


def check_corpus(corpus_dir: Path) -> CheckResult:
    """Manifest + per-file hash + per-fixture state hash, or a documented skip."""
    if not corpus_dir.is_dir():
        return CheckResult(
            name="corpus",
            status="skip",
            detail=(
                f"{corpus_dir} not found: run scripts/eval/extract_fixtures.py first "
                "(or pass --corpus); a missing corpus is a gap, not a pass"
            ),
        )
    manifest_path = corpus_dir / "manifest.json"
    if not manifest_path.is_file():
        return CheckResult("corpus", "red", f"{manifest_path} is missing")
    try:
        manifest = FixtureManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return CheckResult("corpus", "red", f"manifest does not parse: {exc}")
    if manifest.schema_version != SCHEMA_VERSION:
        return CheckResult(
            "corpus",
            "red",
            f"manifest schema {manifest.schema_version!r} != extractor schema {SCHEMA_VERSION!r}",
        )
    problems: list[str] = []
    if manifest.total != len(manifest.fixtures):
        problems.append(f"manifest.total {manifest.total} != {len(manifest.fixtures)} entries")
    for entry in manifest.fixtures:
        path = corpus_dir / entry.file
        if not path.is_file():
            problems.append(f"{entry.file}: missing")
            continue
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry.sha256:
            problems.append(f"{entry.file}: sha256 does not match the manifest")
            continue
        try:
            fixture = EvalFixture.model_validate_json(payload)
        except ValueError as exc:
            problems.append(f"{entry.file}: fixture does not parse: {exc}")
            continue
        if fixture.state_sha256 != state_sha256(fixture.state):
            problems.append(f"{entry.file}: state hash no longer recomputes")
    if problems:
        return CheckResult("corpus", "red", "; ".join(problems[:5]))
    return CheckResult("corpus", "pass", f"{manifest.total} fixtures, hashes intact")


def check_policy(policy: Any, *, label: str = "policy") -> tuple[CheckResult, dict[str, Any]]:
    """A snapshot must cover all four decisions and answer every task."""
    from backend.config.models import TaskType
    from backend.harness.policy import describe

    try:
        snapshot = describe(policy)
    except Exception as exc:  # noqa: BLE001  (a variant may be broken; that is a red)
        return CheckResult(label, "red", f"describe() failed: {exc}"), {}
    expected = {"models", "context_budget", "escalation", "tool_limits"}
    if set(snapshot) != expected:
        return (
            CheckResult(label, "red", f"snapshot keys {sorted(snapshot)} != {sorted(expected)}"),
            snapshot,
        )
    empty = [task.value for task in TaskType if not snapshot["models"].get(task.value)]
    if empty:
        return CheckResult(label, "red", f"no model routed for: {', '.join(empty)}"), snapshot
    try:
        json.dumps(snapshot)
    except TypeError as exc:
        return CheckResult(label, "red", f"snapshot is not JSON-able: {exc}"), snapshot
    return CheckResult(label, "pass", "all four decisions answered"), snapshot


def diff_snapshots(baseline: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    """Name what moved, per decision point (empty dict = variant changed nothing)."""
    diff: dict[str, Any] = {}
    for key in ("models", "context_budget", "escalation", "tool_limits"):
        if baseline.get(key) != variant.get(key):
            diff[key] = {"baseline": baseline.get(key), "variant": variant.get(key)}
    return diff


def check_benchmarks(results: list[dict[str, Any]]) -> CheckResult:
    """F1/F2/F4 must pass and nothing may fail; gaps stay visible as SKIPs.

    A gap becoming a real check is not a failure — F5/F7/F8 may be implemented
    later, and their status is then whatever that implementation reports.  What
    this check refuses is a *fail* (including inside a previously skipped gap)
    and a suite that silently stopped reporting a required check.
    """
    by_id = {str(item.get("id")): str(item.get("status", "")) for item in results}
    missing = [check for check in _REQUIRED_BENCHMARKS if check not in by_id]
    failed = sorted(check for check, status in by_id.items() if status == "FAIL")
    gaps = [check for check in _SKIPPED_GAPS if by_id.get(check) == "SKIP"]
    problems: list[str] = []
    if missing:
        problems.append(f"missing checks: {', '.join(missing)}")
    if failed:
        problems.append(f"failing checks: {', '.join(failed)}")
    if problems:
        return CheckResult("benchmarks", "red", "; ".join(problems))
    return CheckResult(
        "benchmarks",
        "pass",
        f"{', '.join(_REQUIRED_BENCHMARKS)} pass"
        + (f"; {', '.join(gaps)} still documented gaps" if gaps else ""),
    )


def load_variant(spec: str) -> Any:
    """Load ``module:factory`` and insist the result is a HarnessPolicy."""
    from backend.harness.policy import HarnessPolicy

    module_name, _, attribute = spec.partition(":")
    if not module_name:
        raise ValueError(f"variant spec must be 'module:factory', got {spec!r}")
    module = importlib.import_module(module_name)
    target = getattr(module, attribute) if attribute else module
    policy = target() if callable(target) else target
    if not isinstance(policy, HarnessPolicy):
        raise TypeError(f"{spec!r} did not produce a HarnessPolicy")
    return policy


def run_gate(
    *,
    corpus_dir: Path = DEFAULT_CORPUS,
    variant: Any | None = None,
    benchmark_runner: BenchmarkRunner | None = None,
    skip_benchmarks: bool = False,
) -> GateReport:
    """Run every offline check; the caller decides whether red blocks (§6 open)."""
    from backend.harness.policy import default_policy

    mode = "gate" if variant is not None else "report"
    report = GateReport(mode=mode, generated_at=datetime.now(UTC).isoformat())
    report.checks.append(check_corpus(corpus_dir))

    policy_result, snapshot = check_policy(default_policy(), label="policy")
    report.policy_snapshot = snapshot
    report.checks.append(policy_result)

    if variant is not None:
        variant_result, variant_snapshot = check_policy(variant, label="variant")
        report.variant_snapshot = variant_snapshot
        report.diff = diff_snapshots(snapshot, variant_snapshot)
        detail = (
            f"decisions changed: {', '.join(sorted(report.diff))}"
            if report.diff
            else "variant is decision-identical to the baseline"
        )
        report.checks.append(
            CheckResult("variant", variant_result.status, f"{variant_result.detail}; {detail}")
        )

    if skip_benchmarks:
        report.checks.append(
            CheckResult("benchmarks", "skip", "--skip-benchmarks: not run in this invocation")
        )
    else:
        runner = benchmark_runner or run_harness_benchmarks
        try:
            report.checks.append(check_benchmarks(runner()))
        except Exception as exc:  # noqa: BLE001  (a runner failure is a red, not a crash)
            report.checks.append(CheckResult("benchmarks", "red", f"runner failed: {exc}"))
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline Adaptive Harness A/B gate")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--variant", default=None, help="module:factory producing a HarnessPolicy")
    parser.add_argument("--skip-benchmarks", action="store_true")
    parser.add_argument(
        "--fail-on-red",
        action="store_true",
        help="exit 1 when a check is red (default: report only; see plan §6)",
    )
    parser.add_argument("--json", type=Path, default=None, help="write the report as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    options = _build_parser().parse_args(argv)
    variant = load_variant(options.variant) if options.variant else None
    report = run_gate(
        corpus_dir=options.corpus,
        variant=variant,
        skip_benchmarks=options.skip_benchmarks,
    )
    payload = report.to_dict()
    if options.json is not None:
        options.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for check in report.checks:
        print(f"[{check.status.upper():4}] {check.name}: {check.detail}")
    if report.diff:
        print(f"variant diff: {json.dumps(report.diff, ensure_ascii=False)[:400]}")
    print(f"mode={report.mode} red={report.red}")
    if options.fail_on_red and report.red:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
