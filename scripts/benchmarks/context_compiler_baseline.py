#!/usr/bin/env python3
"""P1b-S5 acceptance gate: context compiler token cost + layer stability.

Fully offline and deterministic — it never starts a workflow, touches the
store, or calls a model. It loads the same prompt YAML the agents load,
feeds every agent a shared synthetic recall, and reports:

* token cost vs the pre-migration assembly (dedup / rerank / budget delta)
* layer stability: repeat / shuffle / dedup / budget-trim invariants

Exit code 1 if any stability invariant fails, so CI can gate on it.

Examples:
    python scripts/benchmarks/context_compiler_baseline.py
    python scripts/benchmarks/context_compiler_baseline.py --budget 1200
    python scripts/benchmarks/context_compiler_baseline.py --json report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.context.baseline import DEFAULT_PROMPT_DIR, run_baseline

GATE_NAME = "P1b-S5 context compiler baseline"


def _render_table(report) -> str:
    header = f"{'agent':<22}{'baseline':>10}{'compiled':>10}{'delta':>8}{'pct':>8}  layers"
    lines = [header, "-" * len(header)]
    for row in report.costs:
        layers = " ".join(
            f"{name.split('_')[0]}={tokens}" for name, tokens in row.layer_tokens.items()
        )
        lines.append(
            f"{row.agent:<22}{row.baseline_tokens:>10}{row.compiled_tokens:>10}"
            f"{row.delta:>8}{row.pct:>7.1f}%  {layers}"
        )
    lines.append("-" * len(header))
    delta = report.total_compiled - report.total_baseline
    total_pct = (delta / report.total_baseline * 100) if report.total_baseline else 0.0
    lines.append(
        f"{'TOTAL':<22}{report.total_baseline:>10}{report.total_compiled:>10}"
        f"{delta:>8}{total_pct:>7.1f}%"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--prompt-dir",
        type=Path,
        default=DEFAULT_PROMPT_DIR,
        help="Prompt YAML directory (default: backend/config/prompts)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help="Optional token budget applied to the compiled prompt",
    )
    parser.add_argument("--repeats", type=int, default=3, help="Repeat-compile rounds (>=2)")
    parser.add_argument(
        "--stress-only",
        action="store_true",
        help="Only run the stress scenario (duplicated recall + long L5 tail)",
    )
    parser.add_argument("--json", type=Path, default=None, help="Also write JSON report")
    args = parser.parse_args(argv)

    scenarios = [("stress", True)] if args.stress_only else [("default", False), ("stress", True)]
    reports = [
        run_baseline(
            args.prompt_dir,
            budget=args.budget,
            repeats=max(2, args.repeats),
            stress=stress,
        )
        for _, stress in scenarios
    ]

    print(f"== {GATE_NAME} ==")
    print(f"budget={args.budget} agents={len(reports[0].costs)}\n")
    for report in reports:
        print(f"-- scenario: {report.scenario} --")
        print(_render_table(report))
        print()

    print("-- stability --")
    for report in reports:
        for row in report.stability:
            status = "ok" if row.ok else "FAIL"
            print(
                f"{report.scenario:<8}{row.agent:<22}{status:<6}"
                f"repeat={'y' if row.repeat_ok else 'n'} "
                f"shuffle={'y' if row.shuffle_ok else 'n'} "
                f"dedup={'y' if row.dedup_ok else 'n'} "
                f"budget={'y' if row.budget_ok else 'n'}"
                + (f"  <- {row.detail}" if row.detail else "")
            )

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps([report.to_dict() for report in reports], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nJSON report: {args.json}")

    failed = [row for report in reports for row in report.stability if not row.ok]
    if failed:
        print(f"\n{GATE_NAME}: FAILED ({len(failed)} agent(s))")
        return 1
    print(f"\n{GATE_NAME}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
