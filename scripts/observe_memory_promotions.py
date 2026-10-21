#!/usr/bin/env python3
"""Observe-only Memory Promotion pass — the Slice B2 caller.

Runs one pass over an account's durable Creative Memory **style** rows, decides
a promotion verdict for each (Slice A protocol), and records the verdicts in the
append-only ledger. It **never** writes the target memory namespace: promotion
is Slice C and needs an independent source re-read first (see the PRD).

The ledger is the only durable output, so this tool requires a Postgres-backed
store. It refuses to fall back to an in-process store: a pass whose records
vanish with the process would be indistinguishable from "nothing was decided".

Usage::

    python scripts/observe_memory_promotions.py --account-id acc-1
    python scripts/observe_memory_promotions.py --account-id acc-1 --dry-run

``--dry-run`` still reads the ledger (a decision made without its current
records would be a different decision) but writes nothing and reports
``recorded=0``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from backend.memory.creator_agent_observations import CreativeMemoryObservationSource
from backend.memory.promotion_apply import promote_style_observations
from backend.memory.promotion_ledger import PromotionLedger
from backend.memory.promotion_observations import observe_style_promotions

_DEFAULT_WINDOW = 100


async def run_observation_pass(
    *,
    store: Any,
    account_id: str,
    window: int = _DEFAULT_WINDOW,
    dry_run: bool = False,
    apply: bool = False,
    source: Any | None = None,
    verification_source: Any | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """One pass over ``account_id``; returns the printed summary.

    ``apply=False`` (default) is the observe-only pass: decisions are recorded in
    the ledger, nothing is written to the target namespace. ``apply=True`` is
    Slice C: the source is re-read independently, and a ``PROMOTE`` is recorded
    and then written into ``strategy_notes``.

    ``store`` / ``source`` / ``verification_source`` are injected so the pass is
    testable without Postgres; the CLI below is the only place that constructs
    real ones.
    """
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("account_id must be a non-empty string")
    if window < 1:
        raise ValueError("window must be >= 1")
    if apply and dry_run:
        raise ValueError("apply and dry_run are mutually exclusive")

    observer = source if source is not None else CreativeMemoryObservationSource()
    scan = await observer.observations(account_id, window=window)
    observations = list(scan.observations)

    ledger = PromotionLedger(store)
    summary: dict[str, Any] = {
        "account_id": account_id,
        "mode": "apply" if apply else "observe",
        "dry_run": dry_run,
        "scanned": len(observations),
        "scan_saturated": bool(scan.saturated),
    }
    if apply:
        application = await promote_style_observations(
            ledger,
            store,
            account_id,
            observations,
            source=verification_source,
            dry_run=dry_run,
            recorded_at=recorded_at,
        )
        summary.update(
            {
                "style_candidates": len(application.promotions),
                "ledger_available": application.ledger_available,
                "recorded": application.recorded,
                "applied": application.applied,
                "decisions": [
                    {
                        "candidate_id": item.decision.candidate_id,
                        "key": item.candidate.key,
                        "source_ref": item.candidate.source_ref,
                        "disposition": item.decision.disposition.value,
                        "reason": item.decision.reason.value,
                        "dedupe": item.decision.dedupe.value,
                        "verified": item.decision.verified,
                        "applied": item.applied,
                    }
                    for item in application.promotions
                ],
            }
        )
        return summary

    result = await observe_style_promotions(
        ledger,
        account_id,
        observations,
        record=not dry_run,
    )
    summary.update(
        {
            "style_candidates": len(result.promotions),
            "ledger_available": result.ledger_available,
            "recorded": result.recorded,
            "decisions": [
                {
                    "candidate_id": item.decision.candidate_id,
                    "key": item.candidate.key,
                    "source_ref": item.candidate.source_ref,
                    "disposition": item.decision.disposition.value,
                    "reason": item.decision.reason.value,
                    "dedupe": item.decision.dedupe.value,
                    "verified": item.decision.verified,
                }
                for item in result.promotions
            ],
        }
    )
    return summary


async def _run_with_postgres(args: argparse.Namespace) -> dict[str, Any]:
    uri = (os.environ.get("XHS_POSTGRES_URI") or os.environ.get("POSTGRES_URI") or "").strip()
    if not uri:
        raise RuntimeError(
            "XHS_POSTGRES_URI/POSTGRES_URI is not set; the promotion ledger must be "
            "durable, so this tool will not fall back to an in-memory store"
        )
    from langgraph.store.postgres.aio import AsyncPostgresStore

    context = AsyncPostgresStore.from_conn_string(uri, pool_config={"min_size": 1, "max_size": 2})
    store = await context.__aenter__()
    try:
        await store.setup()
        return await run_observation_pass(
            store=store,
            account_id=args.account_id,
            window=args.window,
            dry_run=args.dry_run,
            apply=args.apply,
        )
    finally:
        await context.__aexit__(None, None, None)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Observe-only Memory Promotion pass (records decisions; writes no memory)."
    )
    parser.add_argument("--account-id", required=True, help="account to observe")
    parser.add_argument(
        "--window",
        type=int,
        default=_DEFAULT_WINDOW,
        help=f"creative-memory rows per family to read (default {_DEFAULT_WINDOW})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read the ledger and decide, but record/write nothing",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Slice C: independently re-read each source and write PROMOTE verdicts into "
            "strategy_notes (ledger row first). Off by default."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.apply and args.dry_run:
        print(
            "observe_memory_promotions: --apply and --dry-run are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    try:
        summary = asyncio.run(_run_with_postgres(args))
    except (RuntimeError, ValueError) as exc:
        print(f"observe_memory_promotions: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
