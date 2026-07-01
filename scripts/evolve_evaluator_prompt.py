#!/usr/bin/env python3
"""Evolve the RQGM evaluator prompt epoch (Red Queen epoch boundary).

Reads recent bias_check scores from evaluator_samples, decides the next epoch's
bias_severity level, and activates a new prompt epoch. This is the prompt-level
co-evolution: when the panel is too lenient (bias_check seldom flags AI content),
the next epoch tightens; when too harsh, it relaxes.

Within an epoch, criteria stay fixed (RQGM self-improvement stability); only the
epoch boundary moves the criteria.

Usage:
  python scripts/evolve_evaluator_prompt.py --dry-run    # show decision, don't create
  python scripts/evolve_evaluator_prompt.py --apply      # create + activate new epoch

Env: POSTGRES_URI
"""

from __future__ import annotations

import argparse
import asyncio
import sys


async def main() -> int:
    ap = argparse.ArgumentParser(description="Evolve evaluator prompt epoch")
    ap.add_argument("--dry-run", action="store_true", help="show decision, don't create epoch")
    ap.add_argument("--apply", action="store_true", help="create + activate new epoch")
    ap.add_argument("--sample-limit", type=int, default=100, help="recent samples to consider")
    args = ap.parse_args()

    if args.dry_run and args.apply:
        print("✗ --dry-run and --apply are mutually exclusive", file=sys.stderr)
        return 2

    from backend.db.evaluator_config import (
        LENIENT_BAND,
        avg_bias_score,
        create_epoch,
        get_active_epoch,
        next_severity,
    )
    from backend.db.pool import is_pool_ready

    if not is_pool_ready():
        print("⚠ DB pool not ready.", file=sys.stderr)
        return 1

    cur_epoch = await get_active_epoch()
    avg = await avg_bias_score(limit=args.sample_limit)
    target = next_severity(cur_epoch.bias_severity, avg)

    print("═" * 60)
    print("RQGM Evaluator Prompt Epoch Evolution")
    print("═" * 60)
    print(f"Current epoch   : #{cur_epoch.epoch_id} ({cur_epoch.bias_severity})")
    print(
        f"Recent bias_check mean: {avg if avg is not None else 'N/A':.2f}"
        if avg is not None
        else "Recent bias_check mean: N/A (no samples)"
    )
    print(f"Decision        : {cur_epoch.bias_severity} → {target}")
    if target == cur_epoch.bias_severity:
        print("→ No epoch change (signal in standard band or no samples).")

    if not args.apply:
        print("(dry-run, no epoch created)")
        return 0
    if target == cur_epoch.bias_severity:
        return 0  # no-op

    note = (
        f"avg bias_check={avg:.1f} ({'lenient' if avg and avg >= LENIENT_BAND else 'harsh'} band) "
        f"from last {args.sample_limit} samples; evolved from {cur_epoch.bias_severity}"
    )
    new_epoch = await create_epoch(target, note=note)
    print(f"✓ Created + activated epoch #{new_epoch.epoch_id} ({new_epoch.bias_severity})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
