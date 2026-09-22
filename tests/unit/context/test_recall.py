"""Recall failures, account isolation and ranking at the real storage boundary."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.context.models import RetrievalMode
from backend.context.recall import recall_memory
from backend.memory.exceptions import UnknownMemoryNamespaceError
from backend.state.events import load_perf_log, reset_memory_store


@pytest.fixture(autouse=True)
def clean_events():
    reset_memory_store()
    yield
    reset_memory_store()


async def test_parallel_namespaces_preserve_partial_success_and_emit_modes():
    entered = set()
    barrier = asyncio.Event()

    async def search(namespace, **kwargs):
        assert namespace[:2] == ("accounts", "account-a")
        entered.add(namespace[-1])
        if len(entered) == 3:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=1)
        if namespace[-1] == "performance_insights":
            raise RuntimeError("private provider error")
        if namespace[-1] == "audience_preferences":
            return []
        return [SimpleNamespace(value={"title": "private memory"})]

    store = SimpleNamespace(asearch=search)
    results = await recall_memory(
        store,
        "account-a",
        {
            "content_history": "private query",
            "audience_preferences": "q",
            "performance_insights": "q",
        },
        thread_id="thread-a",
    )
    assert [r.mode for r in results] == [
        RetrievalMode.HIT,
        RetrievalMode.EMPTY,
        RetrievalMode.DEGRADED,
    ]
    assert results[0].items[0].value == {"title": "private memory"}
    assert results[0].items[0].scope == "account:account-a"
    events = await load_perf_log("thread-a")
    assert [e["mode"] for e in events] == ["hit", "empty", "degraded"]
    assert all(e["kind"] == "context" for e in events)
    assert "private" not in str(events)


async def test_dedup_keeps_highest_rank_and_naive_timestamp_is_utc():
    now = datetime(2026, 9, 20, tzinfo=UTC)
    store = AsyncMock()
    store.asearch.return_value = [
        SimpleNamespace(value={"text": "duplicate"}, score=0.1, updated_at=now),
        SimpleNamespace(value={"text": "old"}, score=1, updated_at=now - timedelta(days=365)),
        SimpleNamespace(value={"text": "duplicate"}, score=1, updated_at=now),
        SimpleNamespace(value={"text": "recent"}, score=1, updated_at=now.replace(tzinfo=None)),
        SimpleNamespace(value={"text": "uncertain", "confidence": 0}, score=1, updated_at=now),
    ]
    (result,) = await recall_memory(store, "a", {"content_history": "q"}, now=now)
    assert [i.value["text"] for i in result.items] == [
        "duplicate",
        "recent",
        "old",
        "uncertain",
    ]
    assert result.items[1].timestamp == now
    assert all(i.token_cost > 0 for i in result.items)


async def test_unknown_namespace_fails_before_any_reads_even_without_store():
    store = AsyncMock()
    for source in (store, None):
        with pytest.raises(UnknownMemoryNamespaceError):
            await recall_memory(source, "a", {"content_history": "q", "typo": "q"})
    store.asearch.assert_not_called()


async def test_absent_store_is_degraded_not_empty():
    (result,) = await recall_memory(None, "a", {"content_history": "q"})
    assert result.mode == RetrievalMode.DEGRADED
    assert result.error == "store_unavailable"


async def test_timeout_is_degraded_but_cancellation_propagates():
    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()

    store = SimpleNamespace(asearch=stalled)
    (result,) = await recall_memory(store, "a", {"content_history": "q"}, timeout=0.001)
    assert result.mode == RetrievalMode.DEGRADED
    assert result.error == "TimeoutError"
    store = AsyncMock()
    store.asearch.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await recall_memory(store, "a", {"content_history": "q"})


async def test_invalid_record_keeps_valid_neighbors_with_degraded_signal():
    store = AsyncMock()
    store.asearch.return_value = [
        SimpleNamespace(value={"text": "valid"}),
        SimpleNamespace(value=None),
    ]
    (result,) = await recall_memory(store, "a", {"content_history": "q"})
    assert result.mode == RetrievalMode.DEGRADED
    assert result.error == "invalid_memory_record"
    assert len(result.items) == 1


async def test_concurrent_accounts_and_events_do_not_mix():
    async def search(namespace, **kwargs):
        return [SimpleNamespace(value={"account": namespace[1]})]

    store = SimpleNamespace(asearch=search)
    results = await asyncio.gather(
        *(
            recall_memory(store, account, {"content_history": "q"}, thread_id=account)
            for account in ("a", "b")
        )
    )
    for account, (result,) in zip(("a", "b"), results, strict=True):
        assert result.items[0].value == {"account": account}
        assert len(await load_perf_log(account)) == 1


async def test_base_adapter_records_failure_in_event_store():
    from backend.agents.copywriter import CopywriterAgent

    store = AsyncMock()
    store.asearch.side_effect = OSError("unavailable")
    values = await CopywriterAgent()._recall_memory(
        store,
        "a",
        "q",
        "content_history",
        thread_id="thread-a",
    )
    assert values.items == ()
    assert values.mode == RetrievalMode.DEGRADED
    (event,) = await load_perf_log("thread-a")
    assert event["mode"] == "degraded"
    assert event["agent"] == "copywriter"
