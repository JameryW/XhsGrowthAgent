"""S2: the two guards that *start* work still answer for this process.

P2b-S2 moved the status-derivation sites onto the execution lease. Two sites
deliberately did not move, because they ask a different question: they decide
whether *this process* should start (or restart) a task, so they read the
registries that actually hold the Task.

Nothing pinned that. The only pre-existing test that reached either guard
(``test_route_artifact_seams.test_brief_upload_writes_through_seam_on_refd_thread``)
uses ``next_nodes=()``, so the ``if not has_active and next_nodes`` branch was
never taken and both candidate answers looked identical. These two cases take
that branch, one for each direction of the choice:

- a local task with **no lease row** must still refuse (a guard that read only
  the lease would resume here -- the "store failure" direction);
- a **foreign** lease with no local task must still resume (a guard that read
  the lease at all would refuse here -- see that test's docstring for why).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes import _runner
from backend.api.routes.workflow import router as workflow_router
from backend.db import execution_leases as leases
from backend.db.accounts import AccountRow
from backend.db.workflows import WorkflowRow

_OWNED = AccountRow(id="acc1", name="acc1", is_active=True, owner_user_id="user-test")
_OTHER_INSTANCE = "other-host:4242:deadbeef"
_START_RESUME = "backend.api.routes._wf_application._start_resume_task"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch):
    """Memory-backed leases and empty registries, restored afterwards."""
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    leases._reset_memory_store()
    _runner._background_tasks.clear()
    _runner._active_sync_executions.clear()
    yield
    leases._reset_memory_store()
    _runner._background_tasks.clear()
    _runner._active_sync_executions.clear()


@pytest.fixture
def brief_client() -> Iterator[TestClient]:
    """A client for /brief/upload whose thread is paused with work pending."""
    values: dict[str, Any] = {"session_id": "t1", "account_id": "acc1", "phase": "briefing"}
    # Non-empty ``next`` is what reaches the guard at all.
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = ("brief_gate",)
    snapshot.tasks = ()
    snapshot.interrupts = ()

    graph = MagicMock()
    graph.store = InMemoryStore()
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.ainvoke = AsyncMock(return_value={"phase": "briefing"})
    graph.aupdate_state = AsyncMock()

    app = FastAPI()
    app.include_router(workflow_router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user

    db_row = WorkflowRow(thread_id="t1", account_id="acc1")
    with (
        patch("backend.db.workflows.get_workflow", AsyncMock(return_value=db_row)),
        patch("backend.api.account_scope.get_account", AsyncMock(return_value=_OWNED)),
    ):
        yield TestClient(app)


def _upload(client: TestClient) -> Any:
    return client.post(
        "/api/workflow/brief/upload/t1",
        files={"file": ("brief.txt", "brief 正文".encode(), "text/plain")},
    )


def test_brief_upload_does_not_resume_on_a_local_task_without_a_lease(
    brief_client: TestClient,
) -> None:
    """A live task in this process blocks the resume even with no lease row.

    This is the configuration where the two candidate guards disagree, and the
    one a store failure produces in production: the lease write is best-effort
    (``start_lease`` swallows a broken store), so "we are running it" and "a
    lease says so" are not the same set. Reading the lease here would start a
    second execution of a thread this process is already executing.
    """
    task = MagicMock()
    task.done.return_value = False
    _runner._background_tasks["t1"] = task
    try:
        with patch(_START_RESUME, new_callable=AsyncMock) as mock_resume:
            resp = _upload(brief_client)
        assert resp.status_code == 200, resp.text
        mock_resume.assert_not_awaited()
    finally:
        _runner._background_tasks.pop("t1", None)


def test_brief_upload_still_resumes_past_a_foreign_lease(brief_client: TestClient) -> None:
    """A lease we do not hold must not veto a resume this process should do.

    Deliberately *not* claiming that cross-replica starts are safe: this pins
    the trade-off the code makes, and it is why the guard is not simply
    ``has_active_execution``. After a restart the dead owner's lease stays
    renewable for up to ``LEASE_TTL_SECONDS``; refusing on it would silently
    skip the resume the user just asked for (HTTP 200, nothing runs), a worse
    failure than the one it prevents given a single-process deployment
    (``Dockerfile`` runs uvicorn without ``--workers``).
    """
    with patch.object(leases, "_instance_id", _OTHER_INSTANCE):
        assert asyncio.run(leases.acquire("t1")) is True

    # The foreign lease is visible to the ownership question...
    assert asyncio.run(_runner.has_active_execution("t1")) is True
    # ...but this process has no task, so the guard lets the resume through.
    assert _runner.process_has_active_task("t1") is False

    with patch(_START_RESUME, new_callable=AsyncMock) as mock_resume:
        resp = _upload(brief_client)
    assert resp.status_code == 200, resp.text
    mock_resume.assert_awaited_once()
