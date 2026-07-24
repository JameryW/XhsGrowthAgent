"""Tests for concurrent checkpoint reads in _get_completed_workflows."""

from __future__ import annotations

import asyncio

import pytest

from backend.api.routes import analytics
from backend.db.workflows import WorkflowRow


@pytest.fixture(autouse=True)
def _clear_route_cache():
    analytics._cache.clear()
    yield
    analytics._cache.clear()


def _rows(*thread_ids: str) -> list[WorkflowRow]:
    return [
        WorkflowRow(thread_id=tid, account_id="acc-a", status="completed") for tid in thread_ids
    ]


class _FakeGraph:
    """agraph stub whose aget_state records concurrency and per-thread state."""

    def __init__(self, *, delay: float = 0.01, fail_on: set[str] | None = None):
        self.delay = delay
        self.fail_on = fail_on or set()
        self.calls: list[str] = []
        self.current = 0
        self.max_concurrent = 0

    async def aget_state(self, config):
        thread_id = config["configurable"]["thread_id"]
        self.calls.append(thread_id)
        if thread_id in self.fail_on:
            raise RuntimeError(f"boom:{thread_id}")
        self.current += 1
        self.max_concurrent = max(self.max_concurrent, self.current)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.current -= 1

        class _Snapshot:
            values = {"thread_id": thread_id}

        return _Snapshot()


def _patch_db(monkeypatch: pytest.MonkeyPatch, rows: list[WorkflowRow]) -> None:
    async def fake_db_list(account_id=None, status=None, limit=100, offset=0):
        if status == "analyzing":
            return [], 0
        return rows, len(rows)

    monkeypatch.setattr(analytics, "is_pool_ready", lambda: True)
    monkeypatch.setattr(analytics, "db_list", fake_db_list)


@pytest.mark.asyncio
async def test_state_reads_run_concurrently_and_preserve_row_order(monkeypatch):
    thread_ids = [f"thread-{i}" for i in range(16)]
    _patch_db(monkeypatch, _rows(*thread_ids))
    graph = _FakeGraph()

    results = await analytics._get_completed_workflows(graph, "acc-a")

    assert [r["thread_id"] for r in results] == thread_ids
    assert [r["_state"]["thread_id"] for r in results] == thread_ids
    # Serial reads would never overlap; the semaphore bounds the overlap.
    assert graph.max_concurrent > 1
    assert graph.max_concurrent <= analytics._STATE_FETCH_CONCURRENCY


@pytest.mark.asyncio
async def test_individual_state_failures_are_skipped(monkeypatch):
    _patch_db(monkeypatch, _rows("ok-1", "bad", "ok-2"))
    graph = _FakeGraph(fail_on={"bad"})

    results = await analytics._get_completed_workflows(graph, "acc-a")

    assert [r["thread_id"] for r in results] == ["ok-1", "ok-2"]


@pytest.mark.asyncio
async def test_cache_hit_avoids_refetch(monkeypatch):
    _patch_db(monkeypatch, _rows("thread-1"))
    graph = _FakeGraph()

    first = await analytics._get_completed_workflows(graph, "acc-a")
    second = await analytics._get_completed_workflows(graph, "acc-a")

    assert first == second
    assert graph.calls == ["thread-1"]


@pytest.mark.asyncio
async def test_pool_not_ready_returns_empty(monkeypatch):
    monkeypatch.setattr(analytics, "is_pool_ready", lambda: False)
    graph = _FakeGraph()

    assert await analytics._get_completed_workflows(graph, "acc-a") == []
    assert graph.calls == []
