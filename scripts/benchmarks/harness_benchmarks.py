"""Harness benchmark suite — the deterministic subset of the F1-F8 matrix.

The design note's benchmark asks one question: does the runtime understand
distributed execution, or does it only loop a model? Each check below runs
**production code** (the Effect Ledger, the compliance policy) against an
injected fault, fully offline — no workflow, no browser, no LLM. That keeps
the suite usable as a CI gate.

Coverage today:

- **F1** crash-in-the-middle recovery: a submit that entered IN_FLIGHT and
  never got a verdict ("process died") must block the next attempt after a
  restart, not re-submit.
- **F2** tool succeeded but the response was lost: the record is UNKNOWN and
  stays blocking; a *definite* failure (FAILED) releases the guard.
- **F4** an injected instruction cannot bypass a policy gate: the dual
  auto-publish guard refuses regardless of who asks.
- **F5/F7/F8** are reported as SKIP with the reason — no workspace concurrency,
  no budget field, no verifier implementation yet. A skipped check is a
  documented gap, not a pass.

Usage::

    python scripts/benchmarks/harness_benchmarks.py          # table + exit code
    python scripts/benchmarks/harness_benchmarks.py --json r.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Same convention as other standalone scripts: runnable from a checkout
# without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from langgraph.store.memory import InMemoryStore  # noqa: E402

from backend.state.effects import (  # noqa: E402
    EffectBlockedError,
    EffectLedger,
    EffectStatus,
)


@dataclass
class CheckResult:
    id: str
    name: str
    status: str  # PASS / FAIL / SKIP
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


async def f1_crash_mid_submit() -> CheckResult:
    """F1: IN_FLIGHT with no verdict survives a process restart as a block."""
    store = InMemoryStore()
    first = EffectLedger(store)
    await first.begin("effect-f1", tool_name="publish")
    # "Process dies here" — no mark() ever runs. A fresh ledger stands in for
    # the restarted process: same store, none of the in-memory claim state.
    restarted = EffectLedger(store)
    try:
        await restarted.begin("effect-f1", tool_name="publish")
    except EffectBlockedError as exc:
        return CheckResult(
            "F1",
            "crash mid-submit blocks re-submit after restart",
            "PASS",
            f"prior status={exc.record.status.value}",
            {"prior_status": exc.record.status.value, "attempt": exc.record.attempt},
        )
    return CheckResult(
        "F1", "crash mid-submit blocks re-submit after restart", "FAIL", "re-submitted"
    )


async def f2_lost_response() -> CheckResult:
    """F2: UNKNOWN blocks, FAILED releases — the two must not collapse."""
    store = InMemoryStore()
    ledger = EffectLedger(store)
    await ledger.begin("effect-f2", tool_name="publish")
    await ledger.mark("effect-f2", EffectStatus.UNKNOWN)  # submitted, no verdict
    blocked = False
    try:
        await ledger.begin("effect-f2", tool_name="publish")
    except EffectBlockedError:
        blocked = True

    await ledger.mark("effect-f2", EffectStatus.FAILED)  # definite "did not happen"
    retried = await ledger.begin("effect-f2", tool_name="publish")

    ok = blocked and retried.attempt == 2
    return CheckResult(
        "F2",
        "UNKNOWN blocks retry, FAILED releases it",
        "PASS" if ok else "FAIL",
        f"unknown_blocked={blocked} retry_attempt={retried.attempt}",
        {"unknown_blocked": blocked, "retry_attempt": retried.attempt},
    )


def f4_policy_gate() -> CheckResult:
    """F4: 'the model asked for it' is not an authorization.

    The guard's real rule is "two automatic gates cannot both be open". Both
    halves are checked: with the second gate open the request is refused, and
    with it closed a single auto-publish is allowed — a guard that refuses
    everything would also "pass" a one-sided test.
    """
    import os

    from backend.services.compliance_policy import (
        DualAutoPublishError,
        assert_not_dual_auto,
    )

    refused = False
    os.environ["AUTO_APPROVE_LOW_RISK"] = "true"
    try:
        assert_not_dual_auto(auto_publish=True)
    except DualAutoPublishError:
        refused = True
    finally:
        os.environ.pop("AUTO_APPROVE_LOW_RISK", None)

    single_gate_allowed = True
    try:
        assert_not_dual_auto(auto_publish=True)  # review gate still human
    except DualAutoPublishError:
        single_gate_allowed = False

    ok = refused and single_gate_allowed
    return CheckResult(
        "F4",
        "dual auto-publish refused, single gate allowed",
        "PASS" if ok else "FAIL",
        f"dual_refused={refused} single_allowed={single_gate_allowed}",
        {"dual_refused": refused, "single_allowed": single_gate_allowed},
    )


async def run_checks() -> list[CheckResult]:
    results = [
        await f1_crash_mid_submit(),
        await f2_lost_response(),
        f4_policy_gate(),
        CheckResult(
            "F5",
            "concurrent workspace conflict detection",
            "SKIP",
            "no sub-agent workspace concurrency in this repo yet",
        ),
        CheckResult(
            "F7",
            "budget exhaustion stops new execution",
            "SKIP",
            "no run-level budget field in state; interrupt path covered elsewhere",
        ),
        CheckResult(
            "F8",
            "verifier false-pass caught by independent regression",
            "SKIP",
            "no LLM verifier implementation yet (P1-B ships the trigger only)",
        ),
    ]
    return results


def _print_table(results: list[CheckResult]) -> None:
    print(f"{'ID':<4} {'STATUS':<6} {'CHECK':<58} DETAIL")
    print("-" * 110)
    for r in results:
        print(f"{r.id:<4} {r.status:<6} {r.name:<58} {r.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="write the report as JSON")
    args = parser.parse_args(argv)

    results = asyncio.run(run_checks())
    _print_table(results)

    failed = [r for r in results if r.status == "FAIL"]
    skipped = [r for r in results if r.status == "SKIP"]
    print(
        f"\n{len(results)} checks | pass={len(results) - len(failed) - len(skipped)} "
        f"fail={len(failed)} skip={len(skipped)}"
    )
    if skipped:
        print("skipped checks are documented gaps, not passes: " + ", ".join(r.id for r in skipped))

    if args.json:
        args.json.write_text(
            json.dumps(
                [
                    {
                        "id": r.id,
                        "name": r.name,
                        "status": r.status,
                        "detail": r.detail,
                        "evidence": r.evidence,
                    }
                    for r in results
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"report written to {args.json}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
