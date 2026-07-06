"""Tests for orphan-running detection (DB running, no live in-process task).

After deploy/restart the in-process task registry is empty, so DB rows left
at status="running" are orphans. /list and /status detect this lazily and
surface the row as stale with orphan=True (no DB mutation on read).
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware import error_handler_middleware
from backend.api.routes import _runner
from backend.api.routes.workflow import router
from backend.db.workflows import WorkflowRow

_POOL_READY = "backend.api.routes.workflow.is_pool_ready"
_DB_LIST = "backend.api.routes.workflow.db_list"
_DB_GET = "backend.api.routes.workflow.db_get"


def _make_row(thread_id: str, status: str = "running") -> WorkflowRow:
    return WorkflowRow(
        thread_id=thread_id,
        account_id="acct",
        status=status,
        phase="scouting",
        progress_percent=10,
        label="",
        workflow_mode="trend",
        created_at="2026-07-06T00:00:00Z",
        updated_at="2026-07-06T00:00:00Z",
    )


def _clear_tasks() -> None:
    _runner._background_tasks.clear()


def _client_with_graph(graph: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)
    return TestClient(app)


def _empty_snapshot() -> MagicMock:
    """StateSnapshot with no live values — triggers DB fallback in /status."""
    snap = MagicMock()
    snap.values = {}
    snap.next = ()
    snap.interrupts = ()
    snap.tasks = ()
    return snap


class TestListOrphanDetection:
    """/list endpoint annotates orphan running rows."""

    @pytest.mark.asyncio
    async def test_list_running_row_no_task_marks_orphan(self):
        """DB running row + no background task → orphan=True, status stale."""
        _clear_tasks()
        rows = [_make_row("orphan_1", status="running")]
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_LIST, new_callable=AsyncMock, return_value=(rows, 1)),
        ):
            client = _client_with_graph(MagicMock())
            resp = client.get("/api/workflow/list")
        assert resp.status_code == 200
        body = resp.json()["data"]
        wf = body["workflows"][0]
        assert wf["orphan"] is True
        assert wf["status"] == "stale"

    @pytest.mark.asyncio
    async def test_list_running_row_active_task_not_orphan(self):
        """DB running row + active (not done) task → orphan=False."""
        _clear_tasks()
        rows = [_make_row("live_1", status="running")]
        task = await _seed_active_task("live_1")
        try:
            with (
                patch(_POOL_READY, return_value=True),
                patch(_DB_LIST, new_callable=AsyncMock, return_value=(rows, 1)),
            ):
                client = _client_with_graph(MagicMock())
                resp = client.get("/api/workflow/list")
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            _clear_tasks()
        assert resp.status_code == 200
        wf = resp.json()["data"]["workflows"][0]
        assert wf["orphan"] is False
        assert wf["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_completed_row_not_orphan(self):
        """DB completed row → orphan=False, status stays completed."""
        _clear_tasks()
        rows = [_make_row("done_1", status="completed")]
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_LIST, new_callable=AsyncMock, return_value=(rows, 1)),
        ):
            client = _client_with_graph(MagicMock())
            resp = client.get("/api/workflow/list")
        assert resp.status_code == 200
        wf = resp.json()["data"]["workflows"][0]
        assert wf["orphan"] is False
        assert wf["status"] == "completed"


class TestStatusOrphanDetection:
    """/status endpoint surfaces orphan rows from DB fallback as stale."""

    @pytest.mark.asyncio
    async def test_status_running_no_task_orphan_stale(self):
        """DB running + no live task (no checkpoint) → orphan=True, status stale."""
        _clear_tasks()
        row = _make_row("orphan_status", status="running")

        graph = MagicMock()
        graph.aget_state = AsyncMock(return_value=_empty_snapshot())

        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=row),
        ):
            client = _client_with_graph(graph)
            resp = client.get("/api/workflow/status/orphan_status")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["orphan"] is True
        assert data["status"] == "stale"


# ── Helpers ──


async def _seed_active_task(thread_id: str) -> asyncio.Task[None]:
    """Register a not-yet-done task so has_active is True."""

    started = asyncio.Event()

    async def _hang() -> None:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(_hang())
    _runner._background_tasks[thread_id] = task
    await started.wait()
    return task
