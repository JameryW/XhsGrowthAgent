"""Tests for orphan-running detection (DB running, but nobody holds the lease).

After deploy/restart the process that held the lease is gone and nothing renews
it, so DB rows left at status="running" are orphans. /list and /status detect
this lazily and surface the row as stale with orphan=True (no DB mutation on
read).

P2b-S2 moved the judgement to the execution lease; these cases exercise it
through the real readers. None of them seeds a lease, so every "orphan" case
here is the lease-is-absent case, and the one "not an orphan" case below
(test_list_running_row_active_task_not_orphan) passes because the *process*
registry is OR-ed in as a fallback -- which is the property that keeps a live
run from being reported as stale when the lease store cannot be reached.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes import _runner
from backend.api.routes.workflow import router
from backend.db.accounts import AccountRow
from backend.db.workflows import WorkflowRow

_POOL_READY = "backend.api.routes._wf_application.is_pool_ready"
_DB_LIST = "backend.api.routes._wf_application.db_list"
_DB_GET = "backend.api.routes._wf_application.db_get"
_ACTIVE_ACCOUNT = "backend.api.account_scope.get_active_account"
# assert_thread_owned looks up the workflow row via a function-level import
# inside account_scope — patch at the source module (no DB in tests).
_DB_GET_SRC = "backend.db.workflows.get_workflow"
_GET_ACCOUNT = "backend.api.account_scope.get_account"


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

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def _owned_account() -> AccountRow:
    """Account owned by the overridden test user (passes account_scope checks)."""
    return AccountRow(
        id="acct",
        name="acct",
        is_active=True,
        owner_user_id="user-test",
    )


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
            patch(_ACTIVE_ACCOUNT, new_callable=AsyncMock, return_value=_owned_account()),
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
                patch(_ACTIVE_ACCOUNT, new_callable=AsyncMock, return_value=_owned_account()),
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
            patch(_ACTIVE_ACCOUNT, new_callable=AsyncMock, return_value=_owned_account()),
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
            patch(_DB_GET_SRC, new_callable=AsyncMock, return_value=row),
            patch(_GET_ACCOUNT, new_callable=AsyncMock, return_value=_owned_account()),
        ):
            client = _client_with_graph(graph)
            resp = client.get("/api/workflow/status/orphan_status")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["orphan"] is True
        assert data["status"] == "stale"
        # P2b-S2: the same lease read also decides checkpoint_lost. Asserted here
        # because "orphan" alone comes from a different site -- a fallback that
        # simply assumed a live task would keep orphan correct and still report
        # a thread with no process behind it as neither lost nor recoverable.
        assert data["checkpoint_lost"] is True


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


# ── S2: the live /status branch answers running vs stale from the lease ──

_LEASE_OTHER = "other-host:4242:deadbeef"
_DB_UPSERT = "backend.api.routes._wf_application._db_upsert"


def _running_snapshot(thread_id: str) -> MagicMock:
    """State with a session but no gate: derive_status reaches its lease branch."""
    snap = MagicMock()
    snap.values = {"session_id": thread_id, "account_id": "acct", "phase": "scouting"}
    snap.next = ("trend_scout",)
    snap.tasks = ()
    snap.interrupts = ()
    snap.metadata = {}
    return snap


class TestStatusLiveBranchReadsTheLease:
    """/status over live graph state: only the lease distinguishes the two answers."""

    def _get(self, thread_id: str, row: WorkflowRow) -> dict:
        graph = MagicMock()
        graph.store = MagicMock()
        graph.aget_state = AsyncMock(return_value=_running_snapshot(thread_id))
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=row),
            patch(_DB_GET_SRC, new_callable=AsyncMock, return_value=row),
            patch(_GET_ACCOUNT, new_callable=AsyncMock, return_value=_owned_account()),
            patch(_DB_UPSERT, new_callable=AsyncMock, return_value=row),
        ):
            resp = _client_with_graph(graph).get(f"/api/workflow/status/{thread_id}")
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    def test_a_foreign_lease_flips_stale_to_running(self, monkeypatch) -> None:
        """Same state twice; a lease held elsewhere is the only difference.

        This is the S2 behaviour in one assertion pair. Without the lease the
        route reports stale + orphan -- "nobody is running it", which is what it
        used to mean. With a foreign lease it must report running and drop the
        orphan flag: the run belongs to the workflow, not to whichever process
        happens to be answering. A branch still reading its own registries
        cannot tell these two apart, and that is the whole point of the slice.
        """
        from backend.db import execution_leases as leases

        thread_id = "lease_live"
        row = _make_row(thread_id, status="running")
        _clear_tasks()

        monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
        leases._reset_memory_store()

        before = self._get(thread_id, row)
        assert before["status"] == "stale"
        assert before["orphan"] is True

        with patch.object(leases, "_instance_id", _LEASE_OTHER):
            assert asyncio.run(leases.acquire(thread_id)) is True

        after = self._get(thread_id, row)
        assert after["status"] == "running"
        assert after["orphan"] is False
