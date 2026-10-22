#!/usr/bin/env python3
"""Observe hy-memory candidates at the promotion gate (Slice D, 票 5v).

Reads an account's raw hy-memory rows through the bridge's management API, maps
them onto the Slice A protocol, and records the verdicts in the promotion
ledger. Nothing is promoted and nothing is written into a memory namespace: hy
candidates are ``REVIEW``-only (their trust class is ``MEMORY``), and the SDK
has no trustworthy re-read, so this slice has no write path at all.

The ledger is the only durable output, so a Postgres store is required — an
in-process store would make "recorded" vanish with the process.

Usage::

    python scripts/observe_hy_promotions.py --account-id acc-1
    python scripts/observe_hy_promotions.py --account-id acc-1 --scene working --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from backend.memory.promotion_hy import HyMemoryBatch, batch_from_bridge, observe_hy_candidates
from backend.memory.promotion_ledger import PromotionLedger

_DEFAULT_LIMIT = 50


async def run_hy_pass(
    *,
    store: Any,
    account_id: str,
    batch: HyMemoryBatch,
    dry_run: bool = False,
) -> dict[str, Any]:
    """One hy observation pass; the summary is what the CLI prints."""
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("account_id must be a non-empty string")

    result = await observe_hy_candidates(
        PromotionLedger(store), account_id, batch, record=not dry_run
    )
    summary: dict[str, Any] = {
        "account_id": account_id,
        "scene": batch.scene,
        "dry_run": dry_run,
        "scanned": len(batch.memories),
        "saturated": batch.saturated,
        "ledger_available": result.ledger_available,
        "recorded": result.recorded,
        "refused_batch": result.refused_batch,
        "degraded_reason": result.degraded_reason,
        "reviewed": len(result.promotions),
        "decisions": [
            {
                "candidate_id": item.decision.candidate_id,
                "key": item.candidate.key,
                "source_ref": item.candidate.source_ref,
                "source_version": item.candidate.source_version,
                "disposition": item.decision.disposition.value,
                "reason": item.decision.reason.value,
                "dedupe": item.decision.dedupe.value,
                "verified": item.decision.verified,
            }
            for item in result.promotions
        ],
    }
    if result.batch_refusal is not None:
        summary["batch_refusal"] = {
            "candidate_id": result.batch_refusal.decision.candidate_id,
            "key": result.batch_refusal.candidate.key,
            "reason": result.batch_refusal.decision.reason.value,
            "verified": result.batch_refusal.decision.verified,
        }
    return summary


async def _run_with_postgres(args: argparse.Namespace) -> dict[str, Any]:
    uri = (os.environ.get("XHS_POSTGRES_URI") or os.environ.get("POSTGRES_URI") or "").strip()
    if not uri:
        raise RuntimeError(
            "XHS_POSTGRES_URI/POSTGRES_URI is not set; the promotion ledger must be "
            "durable, so this tool will not fall back to an in-memory store"
        )
    from backend.memory.hy.bridge import get_hy_memory_bridge

    bridge = get_hy_memory_bridge()
    if not bridge.enabled:
        raise RuntimeError(
            "hy-memory is disabled (HYMEMORY_ENABLED=false); enable it before "
            "observing its candidates"
        )
    batch = await batch_from_bridge(
        bridge, account_id=args.account_id, scene=args.scene, limit=args.limit
    )

    from langgraph.store.postgres.aio import AsyncPostgresStore

    context = AsyncPostgresStore.from_conn_string(uri, pool_config={"min_size": 1, "max_size": 2})
    store = await context.__aenter__()
    try:
        await store.setup()
        return await run_hy_pass(
            store=store, account_id=args.account_id, batch=batch, dry_run=args.dry_run
        )
    finally:
        await context.__aexit__(None, None, None)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Observe hy-memory candidates at the promotion gate (REVIEW-only)."
    )
    parser.add_argument("--account-id", required=True, help="account to observe")
    parser.add_argument(
        "--scene",
        default="chat",
        help="hy-memory scene to read raw rows from (chat/working/coding; default chat)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=f"raw rows to read (default {_DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read the ledger and decide, but record nothing",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = asyncio.run(_run_with_postgres(args))
    except (RuntimeError, ValueError) as exc:
        print(f"observe_hy_promotions: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
