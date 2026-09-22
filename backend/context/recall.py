"""Account-scoped memory recall with explicit outcomes and deterministic ranking."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.context.estimator import estimate_tokens
from backend.context.models import ContextItem, RetrievalMode, RetrievalResult
from backend.memory.exceptions import UnknownMemoryNamespaceError
from backend.memory.store import MemoryManager
from backend.state.events import emit_events

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

logger = logging.getLogger("xhs_growth.context.recall")


def _number(value: Any, default: float) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return default
    return min(1.0, max(0.0, float(value)))


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def recall_memory(
    store: BaseStore | None,
    account_id: str,
    queries: Mapping[str, str],
    *,
    limit: int = 5,
    thread_id: str = "",
    agent: str = "",
    now: datetime | None = None,
    timeout: float = 10.0,
) -> tuple[RetrievalResult, ...]:
    """Recall namespaces concurrently, preserving request order and partial success.

    Invalid namespaces are programming errors and fail before any I/O. Storage
    errors are degraded outcomes, never empty hits. Cancellation propagates.
    Telemetry contains counts and error types, never queries or memory bodies.
    """
    mm = MemoryManager(account_id)
    namespaces = {
        "content_history": mm.content_history_ns,
        "audience_preferences": mm.audience_ns,
        "performance_insights": mm.insights_ns,
        "strategy_notes": mm.strategy_ns,
    }
    for namespace in queries:
        if namespace not in namespaces:
            raise UnknownMemoryNamespaceError(namespace)
    if not account_id.strip():
        raise ValueError("Memory recall requires account_id")
    if limit < 1 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Memory recall requires positive limit and timeout")
    clock = _timestamp(now) or datetime.now(UTC)

    async def recall_one(namespace: str, query: str) -> RetrievalResult:
        error = ""
        ranked: list[tuple[float, ContextItem]] = []
        if store is None:
            error = "store_unavailable"
        else:
            try:
                async with asyncio.timeout(timeout):
                    hits = await store.asearch(namespaces[namespace], query=query, limit=limit)
                for hit in hits:
                    try:
                        value = dict(hit.value)
                        body = json.dumps(value, ensure_ascii=False, sort_keys=True)
                        timestamp = _timestamp(value.get("timestamp")) or _timestamp(
                            getattr(hit, "updated_at", None)
                        )
                        confidence = _number(value.get("confidence"), 1.0)
                        relevance = _number(getattr(hit, "score", None), 1.0)
                        age = (
                            max(0.0, (clock - timestamp).total_seconds() / 86400)
                            if timestamp
                            else 0.0
                        )
                        freshness = 1.0 / (1.0 + age / 30.0) if timestamp else 0.0
                        rank = confidence * (0.8 * relevance + 0.2 * freshness)
                        ranked.append(
                            (
                                rank,
                                ContextItem(
                                    body=body,
                                    source=f"memory:{namespace}",
                                    scope=f"account:{account_id}",
                                    timestamp=timestamp,
                                    confidence=confidence,
                                    ranking_score=rank,
                                    token_cost=estimate_tokens(body),
                                    value=value,
                                ),
                            )
                        )
                    except (TypeError, ValueError, OverflowError):
                        error = "invalid_memory_record"
            except Exception as exc:
                error = type(exc).__name__
        ranked.sort(key=lambda pair: -pair[0])
        seen: set[str] = set()
        items: list[ContextItem] = []
        for _, item in ranked:
            if item.body not in seen:
                seen.add(item.body)
                items.append(item)
        mode = (
            RetrievalMode.DEGRADED
            if error
            else (RetrievalMode.HIT if items else RetrievalMode.EMPTY)
        )
        if error:
            logger.warning("Memory recall degraded: namespace=%s error=%s", namespace, error)
        return RetrievalResult(namespace=namespace, items=tuple(items), mode=mode, error=error)

    results = tuple(await asyncio.gather(*(recall_one(ns, q) for ns, q in queries.items())))
    await emit_events(
        thread_id,
        [
            {
                "kind": "context",
                "agent": agent,
                "namespace": result.namespace,
                "mode": result.mode.value,
                "degraded": result.mode == RetrievalMode.DEGRADED,
                "item_count": len(result.items),
                "error": result.error,
                "timestamp": clock.isoformat(),
            }
            for result in results
        ],
    )
    return results
