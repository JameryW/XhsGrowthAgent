"""P1b-S2 recall pipeline tests: parallel multi-ns recall with mode signals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.context.models import RetrievalMode
from backend.context.retrieval import (
    NAMESPACE_KEYS,
    RecallRequest,
    apply_freshness_decay,
    item_to_context_item,
    recall_namespaces,
)
from backend.db.workflow_events import _reset_memory_store, list_events
from backend.memory.exceptions import UnknownMemoryNamespaceError


class FakeSearchItem:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value


class FakeStore:
    """Records asearch calls; per-namespace scripted results or errors."""

    def __init__(
        self,
        results: dict[str, list[dict[str, Any]]] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self.results = results or {}
        self.errors = errors or {}
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    async def asearch(
        self, namespace: tuple[str, ...], *, query: str, limit: int
    ) -> list[FakeSearchItem]:
        self.calls.append((namespace, query, limit))
        ns = namespace[-1]
        if ns in self.errors:
            raise self.errors[ns]
        return [FakeSearchItem(v) for v in self.results.get(ns, [])]


# ── item_to_context_item ──


def test_item_body_key_precedence() -> None:
    item = item_to_context_item(
        {"insight": "连衣长裙在 7 月转化高", "note": "次要"}, "performance_insights"
    )
    assert item.body == "连衣长裙在 7 月转化高"
    assert item.source == "memory:performance_insights"


def test_item_body_fallback_serializes_record() -> None:
    raw = {"weird_key": "值", "n": 1}
    item = item_to_context_item(raw, "content_history")
    assert "weird_key" in item.body
    assert item.timestamp is None


def test_item_timestamp_parsed_and_bad_ts_ignored() -> None:
    item = item_to_context_item(
        {"preference": "偏好测评体", "timestamp": "2026-09-14T08:00:00+00:00"},
        "audience_preferences",
    )
    assert item.timestamp == datetime(2026, 9, 14, 8, 0, 0, tzinfo=UTC)
    bad = item_to_context_item({"note": "x", "timestamp": "not-a-date"}, "strategy_notes")
    assert bad.timestamp is None


# ── recall_namespaces ──


async def test_recall_hit_empty_and_parallel_calls() -> None:
    store = FakeStore(
        results={
            "content_history": [{"content": "旧文案 A"}, {"content": "旧文案 B"}],
            "audience_preferences": [],
        }
    )
    results = await recall_namespaces(
        store,
        account_id="acct",
        requests=[
            RecallRequest(namespace="content_history", query="文案", limit=5),
            RecallRequest(namespace="audience_preferences", query="偏好", limit=5),
        ],
    )
    assert len(store.calls) == 2  # both namespaces actually queried
    hit = results["content_history"]
    assert hit.mode is RetrievalMode.HIT
    assert hit.bodies == ("旧文案 A", "旧文案 B")
    empty = results["audience_preferences"]
    assert empty.mode is RetrievalMode.EMPTY
    assert empty.error == ""


async def test_recall_store_none_is_degraded_not_empty() -> None:
    results = await recall_namespaces(
        None,
        account_id="acct",
        requests=[RecallRequest(namespace="performance_insights", query="q")],
    )
    res = results["performance_insights"]
    assert res.mode is RetrievalMode.DEGRADED
    assert res.error == "store_unavailable"
    assert res.items == ()


async def test_recall_exception_is_degraded_with_error_summary() -> None:
    store = FakeStore(errors={"content_history": RuntimeError("db down")})
    results = await recall_namespaces(
        store,
        account_id="acct",
        requests=[RecallRequest(namespace="content_history", query="q")],
    )
    res = results["content_history"]
    assert res.mode is RetrievalMode.DEGRADED
    assert "RuntimeError" in res.error and "db down" in res.error


async def test_recall_unknown_namespace_fail_fast() -> None:
    store = FakeStore()
    with pytest.raises(UnknownMemoryNamespaceError):
        await recall_namespaces(
            store,
            account_id="acct",
            requests=[RecallRequest(namespace="typo_ns", query="q")],
        )
    assert store.calls == []  # raised before any store call


async def test_recall_empty_requests_returns_empty_mapping() -> None:
    assert await recall_namespaces(FakeStore(), account_id="a", requests=[]) == {}


async def test_recall_emits_context_event() -> None:
    _reset_memory_store()
    store = FakeStore(
        results={"performance_insights": [{"insight": "爆点在封面"}]},
        errors={"content_history": RuntimeError("boom")},
    )
    await recall_namespaces(
        store,
        account_id="acct",
        requests=[
            RecallRequest(namespace="performance_insights", query="q", limit=3),
            RecallRequest(namespace="content_history", query="q"),
        ],
        thread_id="thread-1",
        emit_events=True,
    )
    events = await list_events("thread-1", kind="context")
    assert len(events) == 1
    payload = events[0]
    assert payload["event"] == "recall"
    assert payload["results"]["performance_insights"]["mode"] == "hit"
    assert payload["results"]["performance_insights"]["count"] == 1
    assert payload["results"]["content_history"]["mode"] == "degraded"
    assert "boom" in payload["results"]["content_history"]["error"]


async def test_recall_no_emit_by_default() -> None:
    _reset_memory_store()
    await recall_namespaces(
        FakeStore(results={"content_history": [{"content": "x"}]}),
        account_id="acct",
        requests=[RecallRequest(namespace="content_history", query="q")],
        thread_id="thread-2",
    )
    assert await list_events("thread-2") == []


def test_namespace_keys_match_consumer_map() -> None:
    expected = {
        "content_history",
        "audience_preferences",
        "performance_insights",
        "strategy_notes",
    }
    assert frozenset(expected) == NAMESPACE_KEYS


# ── apply_freshness_decay ──


def test_freshness_decay_halves_at_half_life() -> None:
    now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
    item = item_to_context_item(
        {"insight": "x", "timestamp": "2026-09-13T12:00:00+00:00"},
        "performance_insights",
    )
    from backend.context.models import RetrievalResult

    result = RetrievalResult(
        namespace="performance_insights", mode=RetrievalMode.HIT, items=(item,)
    )
    decayed = apply_freshness_decay(result, now=now, half_life_days=1.0)
    assert decayed.items[0].confidence == pytest.approx(0.5)


def test_freshness_decay_undated_item_untouched() -> None:
    now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
    undated = item_to_context_item({"insight": "no ts"}, "performance_insights")
    from backend.context.models import RetrievalResult

    result = RetrievalResult(
        namespace="performance_insights", mode=RetrievalMode.HIT, items=(undated,)
    )
    decayed = apply_freshness_decay(result, now=now, half_life_days=1.0)
    assert decayed.items[0].confidence == 1.0


def test_freshness_decay_future_timestamp_clamped() -> None:
    now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
    future_ts = (now + timedelta(days=2)).isoformat()
    item = item_to_context_item(
        {"insight": "future", "timestamp": future_ts}, "performance_insights"
    )
    from backend.context.models import RetrievalResult

    result = RetrievalResult(
        namespace="performance_insights", mode=RetrievalMode.HIT, items=(item,)
    )
    decayed = apply_freshness_decay(result, now=now, half_life_days=1.0)
    assert decayed.items[0].confidence == 1.0  # negative age clamped to 0


def test_freshness_decay_rejects_bad_half_life() -> None:
    from backend.context.models import RetrievalResult

    result = RetrievalResult(namespace="content_history")
    with pytest.raises(ValueError):
        apply_freshness_decay(result, now=datetime.now(UTC), half_life_days=0)
