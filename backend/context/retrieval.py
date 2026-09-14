"""Recall pipeline (P1b-S2): parallel multi-namespace recall with mode signals.

S2 goal (task info.md §三.2): recall becomes one observable pipeline step —
several namespaces fetched concurrently, every outcome carrying the D6'
degradation signal (``hit`` / ``empty`` / ``degraded``) so the §十五
"exception → warning + ``[]``" silent degradation dies here.  Outcomes are
mirrored to the P1a workflow_events tier (``kind="context"``) when a
``thread_id`` is supplied.

This slice is additive-only: agents keep calling ``BaseAgent._recall_memory``
until their S4 migration slot (consumer-map 销号顺序); nothing wires this
module into the live paths yet.

Namespace rule carried over from P0-W2 via consumer-map §四: only the four
registered namespaces exist; an unknown one is a programming error and raises
``UnknownMemoryNamespaceError`` instead of silently reading another namespace.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from backend.context.models import ContextItem, RetrievalMode, RetrievalResult
from backend.memory.exceptions import UnknownMemoryNamespaceError
from backend.memory.store import MemoryManager

if TYPE_CHECKING:
    # BaseStore only appears in annotations — same deferred-import convention
    # as backend.memory.store (avoids pulling langchain at module load).
    from langgraph.store.base import BaseStore

logger = logging.getLogger("xhs_growth.context.retrieval")

"""Registered recall namespaces (consumer-map §四)."""
NAMESPACE_KEYS: frozenset[str] = frozenset(
    {
        "content_history",
        "audience_preferences",
        "performance_insights",
        "strategy_notes",
    }
)

# Body-key precedence when mapping a raw memory record to a ContextItem body.
# Records are heterogeneous across namespaces (insights carry "insight",
# audience carries "preference", content_history carries "content"-ish keys);
# the first present key wins, otherwise the whole record is serialized.
_BODY_KEYS: tuple[str, ...] = (
    "insight",
    "preference",
    "content",
    "summary",
    "note",
    "text",
)

# Timestamp-key precedence for provenance (all values ISO strings in practice).
_TS_KEYS: tuple[str, ...] = ("timestamp", "created_at", "ts", "recorded_at", "date")


class RecallRequest(BaseModel):
    """One namespace recall to run as part of a parallel batch."""

    model_config = ConfigDict(frozen=True)

    namespace: str
    query: str
    limit: int = 5


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def item_to_context_item(value: dict[str, Any], namespace: str) -> ContextItem:
    """Map one raw memory record to a pipeline ContextItem (deterministic).

    Body extraction follows ``_BODY_KEYS`` precedence; the fallback is a
    sorted-key JSON dump so the mapping never loses information.  Unknown
    shapes keep full provenance via ``source``.
    """
    body = next((str(value[k]) for k in _BODY_KEYS if value.get(k) is not None), "")
    if not body:
        body = json.dumps(value, ensure_ascii=False, sort_keys=True)
    ts = next(
        (parsed for parsed in (_parse_ts(value.get(k)) for k in _TS_KEYS) if parsed),
        None,
    )
    return ContextItem(
        body=body,
        source=f"memory:{namespace}",
        timestamp=ts,
    )


def _ns_of(mm: MemoryManager, namespace: str) -> tuple[str, ...]:
    return {
        "content_history": mm.content_history_ns,
        "audience_preferences": mm.audience_ns,
        "performance_insights": mm.insights_ns,
        "strategy_notes": mm.strategy_ns,
    }[namespace]


async def _recall_one(
    store: BaseStore | None,
    account_id: str,
    request: RecallRequest,
) -> RetrievalResult:
    if store is None:
        # D6': an absent store is a degradation, not an empty memory.
        return RetrievalResult(
            namespace=request.namespace,
            mode=RetrievalMode.DEGRADED,
            error="store_unavailable",
        )
    mm = MemoryManager(account_id)
    try:
        items = await store.asearch(
            _ns_of(mm, request.namespace),
            query=request.query,
            limit=request.limit,
        )
    except Exception as exc:
        logger.warning("recall degraded (ns=%s): %s", request.namespace, exc)
        return RetrievalResult(
            namespace=request.namespace,
            mode=RetrievalMode.DEGRADED,
            error=f"{type(exc).__name__}: {exc}",
        )
    mapped = tuple(item_to_context_item(item.value, request.namespace) for item in items)
    raw = tuple(dict(item.value) for item in items)
    mode = RetrievalMode.HIT if mapped else RetrievalMode.EMPTY
    return RetrievalResult(namespace=request.namespace, mode=mode, items=mapped, raw_items=raw)


def _event_payload(
    requests: list[RecallRequest],
    results: dict[str, RetrievalResult],
    elapsed_ms: float,
) -> dict[str, Any]:
    per_ns: dict[str, dict[str, Any]] = {}
    for req in requests:
        res = results[req.namespace]
        entry: dict[str, Any] = {
            "mode": str(res.mode.value),
            "count": len(res.items),
            "query": req.query,
            "limit": req.limit,
        }
        if res.error:
            entry["error"] = res.error
        per_ns[req.namespace] = entry
    return {
        "kind": "context",
        "event": "recall",
        "completed_at": datetime.now(UTC).isoformat(),
        "elapsed_ms": round(elapsed_ms, 3),
        "results": per_ns,
    }


async def recall_namespaces(
    store: BaseStore | None,
    *,
    account_id: str,
    requests: list[RecallRequest],
    thread_id: str = "",
    emit_events: bool = False,
) -> dict[str, RetrievalResult]:
    """Run several namespace recalls in parallel and report every outcome.

    Returns a mapping keyed by namespace (one entry per request).  Unknown
    namespaces raise before any store call (P0-W2).  With ``emit_events`` and
    a ``thread_id``, one ``kind="context"`` telemetry event lands in the P1a
    workflow_events tier — best-effort, telemetry never breaks recall.
    """
    if not requests:
        return {}
    unknown = sorted({r.namespace for r in requests} - NAMESPACE_KEYS)
    if unknown:
        raise UnknownMemoryNamespaceError(unknown[0])
    started = time.perf_counter()
    results_list = await asyncio.gather(*(_recall_one(store, account_id, req) for req in requests))
    results = {res.namespace: res for res in results_list}
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if emit_events and thread_id:
        try:
            from backend.db.workflow_events import append_events

            await append_events(thread_id, [_event_payload(requests, results, elapsed_ms)])
        except Exception as exc:  # best-effort telemetry
            logger.debug("context event emission failed: %s", exc)
    return results


def apply_freshness_decay(
    result: RetrievalResult,
    *,
    now: datetime,
    half_life_days: float,
) -> RetrievalResult:
    """Deterministic freshness decay (info.md §一 pipeline step).

    Items with a timestamp get ``confidence *= 0.5 ** (age_days / half_life)``
    computed against ``now`` (UTC); undated items keep their confidence.  Pure
    function — same inputs, same outputs, no clock reads inside.
    """
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    decayed: list[ContextItem] = []
    for item in result.items:
        if item.timestamp is None:
            decayed.append(item)
            continue
        ts = item.timestamp if item.timestamp.tzinfo else item.timestamp.replace(tzinfo=UTC)
        age_days = max((now - ts).total_seconds(), 0.0) / 86400.0
        factor = 0.5 ** (age_days / half_life_days)
        decayed.append(item.model_copy(update={"confidence": item.confidence * factor}))
    return result.model_copy(update={"items": tuple(decayed)})


__all__ = [
    "NAMESPACE_KEYS",
    "RecallRequest",
    "apply_freshness_decay",
    "item_to_context_item",
    "recall_namespaces",
]
