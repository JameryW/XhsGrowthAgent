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
* **l1** — decision replay (L1): every fixture is replayed through the policy's
  four decisions, mandatory invariants are enforced, determinism is checked, and
  any difference from the baseline is reported as a preference diff
  (``decision_replay.py``).  A skipped L1 gap stays visible: no corpus means skip;
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

from decision_replay import run_l1_replay  # noqa: E402  (sibling module, same setup)
from fixtures import (  # noqa: E402  (sibling module, loaded after sys.path setup)
    EXTRACTOR_VERSION,
    REDACTION_VERSION,
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
    l1: dict[str, Any] | None = None
    l1_diff: dict[str, Any] = field(default_factory=dict)

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
            "l1": self.l1,
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


def check_corpus(corpus_dir: Path, *, expect_manifest_sha256: str | None = None) -> CheckResult:
    """Manifest + per-file hash + per-fixture state hash, or a documented skip.

    An **empty** corpus is red, not a pass: a green gate over zero evidence is the
    failure mode this check exists to prevent (an empty local database produces a
    valid-looking zero-fixture manifest).  A *missing* corpus stays a skip with a
    reason, because "you have not extracted anything yet" is genuinely different
    from "your extractor produced an empty dataset".

    ``manifest.sha256`` (written by the extractor) catches an edited manifest;
    ``expect_manifest_sha256`` is the out-of-band value that catches a *paired*
    rewrite of fixtures, manifest and digest together.  Neither claims to make the
    corpus tamper-proof — only self-consistent and auditable.
    """
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
    manifest_bytes = manifest_path.read_bytes()
    actual_digest = hashlib.sha256(manifest_bytes).hexdigest()
    problems: list[str] = []
    digest_path = corpus_dir / "manifest.sha256"
    if digest_path.is_file():
        recorded = digest_path.read_text(encoding="utf-8").strip()
        if recorded != actual_digest:
            problems.append("manifest.sha256 does not match manifest.json")
    elif expect_manifest_sha256 is None:
        # Deleting one file must not silently disable manifest-edit detection.
        problems.append(
            "manifest.sha256 is missing and no --expect-manifest-sha256 was supplied; "
            "re-extract the corpus (or pass the recorded digest)"
        )
    if expect_manifest_sha256 is not None and expect_manifest_sha256.strip() != actual_digest:
        problems.append(
            f"manifest digest {actual_digest[:12]}… != expected {expect_manifest_sha256[:12]}…"
        )
    try:
        manifest = FixtureManifest.model_validate_json(manifest_bytes)
    except ValueError as exc:
        return CheckResult("corpus", "red", f"manifest does not parse: {exc}")
    if manifest.schema_version != SCHEMA_VERSION:
        return CheckResult(
            "corpus",
            "red",
            f"manifest schema {manifest.schema_version!r} != extractor schema {SCHEMA_VERSION!r}",
        )
    if manifest.redaction_version != REDACTION_VERSION:
        return CheckResult(
            "corpus",
            "red",
            f"corpus was built by redaction {manifest.redaction_version!r}, "
            f"current is {REDACTION_VERSION!r}: re-extract it",
        )
    if manifest.extractor_version != EXTRACTOR_VERSION:
        return CheckResult(
            "corpus",
            "red",
            f"corpus was built by extractor {manifest.extractor_version!r}, "
            f"current is {EXTRACTOR_VERSION!r}: re-extract it",
        )
    if manifest.total == 0:
        problems.append("corpus is empty (0 fixtures): nothing to gate on")
    if manifest.total != len(manifest.fixtures):
        problems.append(f"manifest.total {manifest.total} != {len(manifest.fixtures)} entries")
    listed = {entry.file for entry in manifest.fixtures}
    # Anything JSON-shaped that the manifest does not list is unaccounted evidence,
    # including near-misses like fixture_rogue.json that a fixture-* glob misses.
    allowed = listed | {"manifest.json"}
    unlisted = sorted(path.name for path in corpus_dir.glob("*.json") if path.name not in allowed)
    if unlisted:
        problems.append(f"unlisted json files: {', '.join(unlisted[:5])}")
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
    detail = f"{manifest.total} fixtures, hashes intact"
    if digest_path.is_file():
        detail += f", manifest digest {actual_digest[:12]}…"
    if manifest.pseudonym_mode == "sha256":
        # Visible, not fatal: an unsalted corpus is acceptable for a local run but
        # its short ids are dictionary-attackable, so the gate says so every time.
        detail += ", pseudonyms unsalted (sha256)"
    return CheckResult("corpus", "pass", detail)


def check_policy(policy: Any, *, label: str = "policy") -> tuple[CheckResult, dict[str, Any]]:
    """A snapshot must cover all four decisions and answer every task, with types."""
    from backend.config.models import TaskType
    from backend.harness.policy import describe

    try:
        snapshot = describe(policy)
    except Exception as exc:  # noqa: BLE001  (a variant may be broken; that is a red)
        return CheckResult(label, "red", f"describe() failed: {exc}"), {}
    expected = {"models", "context_budget", "context_budgets", "escalation", "tool_limits"}
    if set(snapshot) != expected:
        return (
            CheckResult(label, "red", f"snapshot keys {sorted(snapshot)} != {sorted(expected)}"),
            snapshot,
        )
    problems: list[str] = []
    models = snapshot.get("models")
    if not isinstance(models, dict):
        problems.append("models is not a mapping")
    else:
        for task in TaskType:
            value = models.get(task.value)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"no usable model id for {task.value}")
    budget = snapshot.get("context_budget")
    if budget is not None and (
        not isinstance(budget, int) or isinstance(budget, bool) or budget < 0
    ):
        problems.append("context_budget must be None or a non-negative int")
    budgets = snapshot.get("context_budgets")
    if not isinstance(budgets, dict) or not budgets:
        problems.append("context_budgets must be a non-empty phase mapping")
    else:
        for phase, value in budgets.items():
            if not isinstance(phase, str):
                problems.append("context_budgets phases must be strings")
                break
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                problems.append(f"context_budget[{phase!r}] must be None or a non-negative int")
    escalation = snapshot.get("escalation")
    if not isinstance(escalation, dict) or any(
        not isinstance(targets, list)
        or any(not isinstance(item, str) or not item.strip() for item in targets)
        for targets in escalation.values()
    ):
        problems.append("escalation must map tasks to lists of non-blank model ids")
    limits = snapshot.get("tool_limits")
    if not isinstance(limits, dict) or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("capability"), str)
        or not entry.get("capability", "").strip()
        or (
            entry.get("max_concurrency") is not None
            and (
                not isinstance(entry.get("max_concurrency"), int)
                or isinstance(entry.get("max_concurrency"), bool)
                or entry["max_concurrency"] < 0
            )
        )
        or (
            entry.get("timeout_s") is not None
            and (
                not isinstance(entry.get("timeout_s"), (int, float))
                or isinstance(entry.get("timeout_s"), bool)
                or entry["timeout_s"] <= 0
            )
        )
        for entry in limits.values()
    ):
        problems.append("tool_limits entries have the wrong shape")
    if problems:
        return CheckResult(label, "red", "; ".join(problems[:5])), snapshot
    try:
        json.dumps(snapshot)
    except TypeError as exc:
        return CheckResult(label, "red", f"snapshot is not JSON-able: {exc}"), snapshot
    return CheckResult(label, "pass", "all four decisions answered"), snapshot


def diff_snapshots(baseline: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    """Name what moved, per decision point (empty dict = variant changed nothing)."""
    diff: dict[str, Any] = {}
    for key in ("models", "context_budget", "context_budgets", "escalation", "tool_limits"):
        if baseline.get(key) != variant.get(key):
            diff[key] = {"baseline": baseline.get(key), "variant": variant.get(key)}
    return diff


def check_benchmarks(results: list[dict[str, Any]]) -> CheckResult:
    """F1/F2/F4 must be reported as PASS; nothing may fail; unknown status is red.

    Presence alone is not enough: a required check reported as SKIP/ERROR would
    otherwise read as "pass" (the old code only rejected FAIL).  Gaps (F5/F7/F8)
    may stay SKIP or become PASS later; a FAIL anywhere is red.
    """
    by_id = {str(item.get("id")): str(item.get("status", "")) for item in results}
    missing = [check for check in _REQUIRED_BENCHMARKS if check not in by_id]
    not_passing = sorted(check for check in _REQUIRED_BENCHMARKS if by_id.get(check) != "PASS")
    unknown = sorted(
        check for check, status in by_id.items() if status not in {"PASS", "FAIL", "SKIP"}
    )
    failed = sorted(check for check, status in by_id.items() if status == "FAIL")
    gaps = [check for check in _SKIPPED_GAPS if by_id.get(check) == "SKIP"]
    problems: list[str] = []
    if missing:
        problems.append(f"missing checks: {', '.join(missing)}")
    if not_passing:
        problems.append(f"required checks not PASS: {', '.join(not_passing)}")
    if unknown:
        problems.append(f"unknown statuses: {', '.join(unknown)}")
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
    skip_l1: bool = False,
    fail_on_red: bool = False,
    expect_manifest_sha256: str | None = None,
) -> GateReport:
    """Run every offline check; ``fail_on_red`` decides whether red is a gate."""
    from backend.harness.policy import default_policy

    report = GateReport(
        mode="block" if fail_on_red else "report", generated_at=datetime.now(UTC).isoformat()
    )
    report.checks.append(check_corpus(corpus_dir, expect_manifest_sha256=expect_manifest_sha256))

    baseline = default_policy()
    policy_result, snapshot = check_policy(baseline, label="policy")
    report.policy_snapshot = snapshot
    report.checks.append(policy_result)

    if skip_l1:
        report.checks.append(CheckResult("l1", "skip", "--skip-l1: not run in this invocation"))
    else:
        outcome = run_l1_replay(
            variant if variant is not None else baseline,
            corpus_dir,
            baseline_policy=baseline,
            variant=variant is not None,
        )
        report.l1 = outcome.summary()
        report.l1_diff = outcome.diff
        report.checks.append(CheckResult("l1", outcome.status, outcome.detail))

    if variant is not None:
        variant_result, variant_snapshot = check_policy(variant, label="variant")
        report.variant_snapshot = variant_snapshot
        report.diff = diff_snapshots(snapshot, variant_snapshot)
        if variant_result.status == "pass" and not report.diff:
            # A variant that changes nothing is indistinguishable from a mistyped
            # module path whose factory quietly returned the default policy.
            report.checks.append(
                CheckResult(
                    "variant",
                    "red",
                    "variant is decision-identical to the baseline; "
                    "check that --variant actually produced a different policy",
                )
            )
        else:
            detail = (
                f"decisions changed: {', '.join(sorted(report.diff))}"
                if report.diff
                else "variant could not be described"
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
        "--skip-l1",
        action="store_true",
        help="skip the L1 decision replay (reported as an explicit skip, not a pass)",
    )
    parser.add_argument(
        "--fail-on-red",
        action="store_true",
        help="exit 1 when a check is red (default: report only; see plan §6)",
    )
    parser.add_argument("--json", type=Path, default=None, help="write the report as JSON")
    parser.add_argument(
        "--expect-manifest-sha256",
        default=None,
        help="out-of-band manifest digest recorded when the corpus was extracted "
        "(catches a paired rewrite of fixtures + manifest + digest)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    options = _build_parser().parse_args(argv)
    variant = load_variant(options.variant) if options.variant else None
    report = run_gate(
        corpus_dir=options.corpus,
        variant=variant,
        skip_benchmarks=options.skip_benchmarks,
        skip_l1=options.skip_l1,
        fail_on_red=options.fail_on_red,
        expect_manifest_sha256=options.expect_manifest_sha256,
    )
    payload = report.to_dict()
    if options.json is not None:
        options.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for check in report.checks:
        print(f"[{check.status.upper():4}] {check.name}: {check.detail}")
    if report.diff:
        print(f"variant diff: {json.dumps(report.diff, ensure_ascii=False)[:400]}")
    if report.l1_diff:
        print(f"l1 preference diff: {json.dumps(report.l1_diff, ensure_ascii=False)[:400]}")
    print(f"mode={report.mode} red={report.red}")
    if options.fail_on_red and report.red:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
