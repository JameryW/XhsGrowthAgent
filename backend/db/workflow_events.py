"""Durable workflow event log (P1a-S2).

Events are the telemetry tier of the P1a state split: everything that used to
ride the LangGraph checkpoint as ``performance_log`` is written here instead,
so a checkpoint no longer grows on every LLM call (design info.md §一, D3).

The module follows the project's dual-backend convention (see
``.trellis/spec/backend/database-guidelines.md``): PostgreSQL in production and
a process-memory fallback for tests/dev when ``is_pool_ready()`` is false.
``ensure_tables()`` runs from the app lifespan; the memory store needs no
setup and is reset only by the test helper ``_reset_memory_store()``.

Ordering matters: ``seq`` is assigned by the store (Postgres sequence, module
counter in the fallback) and is the only ordering key readers use. Event
timestamps are TEXT and can tie, which would make "latest" undefined and let
the two backends disagree — the same lesson recorded for
``quality_evaluation_runs.seq``.

All writes are best-effort: telemetry must never break a workflow node, so a
storage failure is logged and swallowed.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.db.pool import get_pool, is_pool_ready

logger = logging.getLogger("xhs_growth.db.workflow_events")


# Event kinds. The first four are carried over verbatim from the
# ``performance_log`` entries S2 migrates (``kind`` was already the
# discriminator there); tool/cost/error/action are the forward-looking set from
# the P1a prd that later slices will start emitting.
EVENT_KINDS: frozenset[str] = frozenset(
    {"node", "llm", "ripple", "human_wait", "tool", "cost", "error", "action"}
)

# Payload key the store prefers as the event timestamp, in order.
_TS_KEYS: tuple[str, ...] = ("completed_at", "timestamp", "resumed_at", "started_at")


@dataclass
class WorkflowEvent:
    """One immutable telemetry record for a thread."""

    thread_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = ""
    seq: int = 0


_mem_events: dict[str, list[WorkflowEvent]] = {}
_mem_seq = itertools.count(1)
# Mirrors the creator_agent adapter: the fallback is shared mutable state, so
# appends and reads serialize here the way a Postgres transaction would.
_mem_lock = asyncio.Lock()


def _reset_memory_store() -> None:
    """Test helper for the no-Postgres fallback."""
    _mem_events.clear()


_CREATE_SEQUENCE_SQL = """
CREATE SEQUENCE IF NOT EXISTS workflow_events_seq;
"""

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS workflow_events (
    seq        BIGINT PRIMARY KEY DEFAULT nextval('workflow_events_seq'),
    thread_id  TEXT NOT NULL,
    ts         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    payload    JSONB NOT NULL DEFAULT '{}'::jsonb
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_workflow_events_thread
    ON workflow_events (thread_id, seq);
"""


async def ensure_tables() -> None:
    """Create the event table when the app pool is ready."""
    if not is_pool_ready():
        logger.debug("workflow_events ensure skipped: pool not ready")
        return
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_SEQUENCE_SQL)
        await conn.execute(_CREATE_TABLE_SQL)
        await conn.execute(_CREATE_INDEX_SQL)
    logger.info("workflow_events table ensured")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _event_ts(payload: dict[str, Any]) -> str:
    for key in _TS_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return _now_iso()


def _event_kind(payload: dict[str, Any]) -> str:
    kind = payload.get("kind")
    # Absent kind means a pre-kind performance_log entry, which the timeline
    # reader has always treated as a node entry.
    return str(kind) if kind else "node"


def _normalize_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


async def append_events(thread_id: str, entries: list[dict[str, Any]], /) -> int:
    """Append telemetry entries and return how many were stored.

    ``entries`` are ``performance_log``-shaped dicts; each one's ``kind`` (or
    ``"node"`` when absent) becomes the event kind. Best-effort: returns 0
    instead of raising when storage is unavailable, because a node's real work
    must never fail over telemetry.
    """
    if not thread_id or not entries:
        return 0
    payloads = [entry for entry in entries if isinstance(entry, dict)]
    if not payloads:
        return 0

    if not is_pool_ready():
        async with _mem_lock:
            for entry in payloads:
                kind = _event_kind(entry)
                _mem_events.setdefault(thread_id, []).append(
                    WorkflowEvent(
                        thread_id=thread_id,
                        kind=kind,
                        payload=dict(entry),
                        ts=_event_ts(entry),
                        seq=next(_mem_seq),
                    )
                )
        return len(payloads)

    try:
        pool = get_pool()
        async with pool.connection() as conn:
            for entry in payloads:
                await conn.execute(
                    """INSERT INTO workflow_events (thread_id, ts, kind, payload)
                       VALUES (%s, %s, %s, %s::jsonb)""",
                    (
                        thread_id,
                        _event_ts(entry),
                        _event_kind(entry),
                        json.dumps(entry, default=str),
                    ),
                )
    except Exception as exc:
        logger.warning("workflow_events append failed: %s", exc)
        return 0
    return len(payloads)


async def list_events(thread_id: str, *, kind: str | None = None) -> list[dict[str, Any]]:
    """Return a thread's events in store order (``seq`` ascending).

    Only payloads are returned — that is the shape every reader (agent_timeline,
    cost aggregation, gate-wait lookup) consumed from ``performance_log``, and
    keeping ``seq`` internal leaves the tier free to change its own columns.
    """
    if not thread_id:
        return []
    if not is_pool_ready():
        async with _mem_lock:
            rows = list(_mem_events.get(thread_id, []))
        return [row.payload for row in rows if kind is None or row.kind == kind]

    try:
        pool = get_pool()
        from psycopg.rows import dict_row

        async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            if kind is None:
                await cur.execute(
                    """SELECT payload FROM workflow_events
                           WHERE thread_id = %s ORDER BY seq ASC""",
                    (thread_id,),
                )
            else:
                await cur.execute(
                    """SELECT payload FROM workflow_events
                           WHERE thread_id = %s AND kind = %s ORDER BY seq ASC""",
                    (thread_id, kind),
                )
            fetched = await cur.fetchall()
    except Exception as exc:
        logger.warning("workflow_events read failed: %s", exc)
        return []
    return [_normalize_payload(row.get("payload")) for row in fetched]


__all__ = [
    "EVENT_KINDS",
    "WorkflowEvent",
    "append_events",
    "ensure_tables",
    "list_events",
]
