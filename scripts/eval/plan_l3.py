"""L3 live-run planner and authorisation gate (P3/E4).

A live L3 experiment cannot run from this repository checkout: it needs the
deployment's **test account**, its login state and a run window, and the workflow
itself is launched by the deployment.  What *can* live here is the part that stops
such a run from being started by accident or off-budget: this module validates the
plan against the user's 2026-11-02 decisions (LLM judge allowed, fewer than 200
model calls, test account only) and prints the exact plan an operator will run.

It deliberately does not execute anything.  ``--armed`` exits 0 only when every
precondition is present, so a script can use it as a gate before launching the
external run; otherwise the exit code and the reasons say what is missing.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal

# The user approved "fewer than 200 model calls"; 199 is the literal reading and
# the same default JudgeBudget uses.
APPROVED_MAX_CALLS = 199
MAX_SAMPLES = 50
JudgeKind = Literal["llm", "human", "none"]


@dataclass(frozen=True)
class L3Plan:
    samples: int = 3
    account: str = ""
    judge: JudgeKind = "llm"
    max_calls: int = APPROVED_MAX_CALLS
    phases: tuple[str, ...] = ("reviewing",)

    @property
    def judge_calls(self) -> int:
        """One verdict per sample: human review counts as one slot each."""
        return self.samples


@dataclass
class Readiness:
    ready: bool = False
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def validate(plan: L3Plan, *, environ: dict[str, str] | None = None) -> Readiness:
    """Every precondition for an authorised live run, with the reason it fails."""
    env = environ if environ is not None else dict(os.environ)
    readiness = Readiness()
    if plan.samples < 1:
        readiness.problems.append("samples must be at least 1")
    if plan.samples > MAX_SAMPLES:
        readiness.problems.append(f"samples must be at most {MAX_SAMPLES} for one run")
    if plan.max_calls > APPROVED_MAX_CALLS:
        readiness.problems.append(
            f"max_calls {plan.max_calls} exceeds the approved cap of {APPROVED_MAX_CALLS} "
            "(the user approved fewer than 200 model calls)"
        )
    if plan.max_calls < 1:
        readiness.problems.append("max_calls must be at least 1")
    if plan.judge_calls > plan.max_calls:
        readiness.problems.append(
            f"{plan.judge_calls} judge verdicts would exceed max_calls {plan.max_calls}"
        )
    if plan.judge == "none":
        readiness.problems.append(
            "judge is 'none' but the approved evaluation needs the quality dimension"
        )
    if not plan.account.strip():
        readiness.problems.append("account is required: L3 runs on the test account only")
    if plan.judge == "llm" and env.get("XHS_EVAL_LIVE") != "1":
        readiness.problems.append(
            "XHS_EVAL_LIVE=1 is not set: a live model-spending run must be armed explicitly"
        )
    if plan.judge == "human" and env.get("XHS_EVAL_HUMAN") != "1":
        readiness.notes.append(
            "judge=human: a human reviewer is needed; set XHS_EVAL_HUMAN=1 when arranged"
        )
    readiness.ready = not readiness.problems
    return readiness


def plan_report(plan: L3Plan, readiness: Readiness) -> dict[str, Any]:
    """The plan as JSON-friendly data, for a CI log or an operator's record."""
    return {
        "plan": {
            "samples": plan.samples,
            "account": plan.account,
            "judge": plan.judge,
            "max_calls": plan.max_calls,
            "phases": list(plan.phases),
            "judge_calls": plan.judge_calls,
        },
        "ready": readiness.ready,
        "problems": list(readiness.problems),
        "notes": list(readiness.notes),
        "approved_max_calls": APPROVED_MAX_CALLS,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and print an authorised live L3 plan (does not run it)"
    )
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--account", default="", help="the test account id for the run")
    parser.add_argument("--judge", choices=("llm", "human", "none"), default="llm")
    parser.add_argument("--max-calls", type=int, default=APPROVED_MAX_CALLS)
    parser.add_argument(
        "--phases", default="reviewing", help="comma-separated workflow phases to sample"
    )
    parser.add_argument(
        "--armed",
        action="store_true",
        help="exit 0 only when every precondition is present (gate mode)",
    )
    parser.add_argument("--json", action="store_true", help="print the plan report as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    options = _build_parser().parse_args(argv)
    plan = L3Plan(
        samples=options.samples,
        account=options.account,
        judge=options.judge,
        max_calls=options.max_calls,
        phases=tuple(part.strip() for part in options.phases.split(",") if part.strip()),
    )
    readiness = validate(plan)
    if options.json:
        print(json.dumps(plan_report(plan, readiness), ensure_ascii=False, indent=2))
    else:
        print(
            f"plan: samples={plan.samples} account={plan.account or '<missing>'} "
            f"judge={plan.judge} max_calls={plan.max_calls} phases={','.join(plan.phases)}"
        )
        for problem in readiness.problems:
            print(f"BLOCKED: {problem}")
        for note in readiness.notes:
            print(f"NOTE: {note}")
        print(
            "ready: yes — the operator can run the external workflow on the test account"
            if readiness.ready
            else "ready: no (see BLOCKED above); nothing was launched"
        )
    if options.armed and not readiness.ready:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
