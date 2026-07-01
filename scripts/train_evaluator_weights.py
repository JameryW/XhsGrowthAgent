#!/usr/bin/env python3
"""Train RQGM evaluator grader weights from accumulated samples.

Statistical fit (no GPU): regresses dimension scores against post-publish
engagement_rate (weak label), writes fitted weights + thresholds back to
evaluator_config. This is the epoch-2 "online weight training" — replaces
epoch-1's manual set_weight with a data-driven loop.

Usage:
  python scripts/train_evaluator_weights.py --dry-run            # show fitted, don't write
  python scripts/train_evaluator_weights.py --apply              # write to evaluator_config
  python scripts/train_evaluator_weights.py --apply --account-id acct1

Env: POSTGRES_URI (DB where evaluator_samples / evaluator_config live)
"""

from __future__ import annotations

import argparse
import asyncio
import sys


async def main() -> int:
    ap = argparse.ArgumentParser(description="Train evaluator grader weights from samples")
    ap.add_argument("--account-id", default=None, help="train per-account (default: global)")
    ap.add_argument("--dry-run", action="store_true", help="show fitted weights, don't write")
    ap.add_argument("--apply", action="store_true", help="write fitted weights to DB")
    ap.add_argument("--limit", type=int, default=5000, help="max samples to use")
    args = ap.parse_args()

    if args.dry_run and args.apply:
        print("✗ --dry-run and --apply are mutually exclusive", file=sys.stderr)
        return 2

    from backend.db.evaluator_config import MIN_TRAIN_SAMPLES, train_weights
    from backend.db.pool import is_pool_ready

    if not is_pool_ready():
        print("⚠ DB pool not ready — cannot fetch samples.", file=sys.stderr)
        return 1

    apply = args.apply and not args.dry_run
    report = await train_weights(args.account_id, apply=apply)

    print("═" * 60)
    print("RQGM Evaluator Weight Training")
    print("═" * 60)
    print(f"Account       : {args.account_id or '(global)'}")
    print(f"Labeled samples: {report.n_samples}  (min required: {MIN_TRAIN_SAMPLES})")
    print(f"R²            : {report.r_squared:.4f}")
    print(f"Applied       : {report.applied}")
    print(f"Note          : {report.note}")
    print("\n─ Fitted dimension weights ─")
    for name, w in report.fitted_weights.items():
        print(f"  {name:14s}: {w:.4f}")
    print("\n─ Thresholds ─")
    print(f"  pass : {report.pass_threshold:.2f}")
    print(f"  reject: {report.reject_threshold:.2f}")

    if report.n_samples < MIN_TRAIN_SAMPLES:
        print(
            f"\n⚠ Too few labeled samples ({report.n_samples} < {MIN_TRAIN_SAMPLES}). "
            "Defaults kept. Collect more post-publish engagement data.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
