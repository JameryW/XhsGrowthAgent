"""The guards that *start* work still answer for this process.

P2b-S2 moved the status-derivation sites onto the execution lease. The sites
here deliberately did not move, because they ask a different question: they
decide whether *this process* should start (or restart) a task, so they read the
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

A third guard joined them later: ``retry_ripple_analysis``. It asks the same
question with the same predicate, and its two cases pin the *ruling* §7 of
``docs/execution-plane.md`` records -- guard yes, task-registry write no. The
registry is keyed by ``thread_id``, so it holds one task per thread, and three
call sites (``pause_workflow``, ``cancel_workflow``, ``_start_resume_task``)
cancel whatever sits in that slot: a retry that registered there would displace
the workflow's own entry and turn those three into cancels of the *retry*.

The verdict is only half of it; the *predicate* is the other half. Both retry
guards must answer from the process registries, so a lease held by another
instance may not veto either of them -- the same trade-off, one guard over,
that ``test_brief_upload_still_resumes_past_a_foreign_lease`` pins above.
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


# ── the third guard: ripple-retry ────────────────────────────────────────────
# §7 of docs/execution-plane.md lists four properties the publish-retry path has
# and the ripple-retry path does not.  This slice ruled on them: the guard is
# adopted (same predicate, same sentence as the sibling), the task-registry
# write, the done callback and the self-cleanup are not -- each for a reason
# recorded there.  The two cases below pin the adopted half *and* the refused
# half, so a later "just make it match the sibling" edit has to argue with a
# failing test rather than a comment.

_RIPPLE_SERVICE = "backend.services.ripple_service.RippleService.get_instance"
_SERIALIZATION_SENTENCE = "工作流正在运行，无法重试。"


@pytest.fixture
def ripple_client() -> Iterator[TestClient]:
    """A client for /ripple-retry whose thread has a failed ripple to redo."""
    values: dict[str, Any] = {
        "session_id": "t1",
        "account_id": "acc1",
        "phase": "planning",
        "ripple_reason": "timeout",
        "content_plan": {"selected_topic": "露营咖啡", "hashtags": []},
    }
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = ("ripple_gate",)
    snapshot.tasks = ()
    snapshot.interrupts = ()

    graph = MagicMock()
    graph.store = InMemoryStore()
    graph.aget_state = AsyncMock(return_value=snapshot)
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


def _retry_ripple(client: TestClient) -> Any:
    return client.post("/api/workflow/ripple-retry/t1")


def test_ripple_retry_refuses_while_this_process_is_running_the_thread(
    ripple_client: TestClient,
) -> None:
    """The adopted half: refuse, with the sibling's own sentence.

    The sentence is asserted verbatim rather than by prefix -- §7 says the two
    paths answer the same question, so a message that drifted apart is the first
    sign they stopped being the same rule.
    """
    sentinel = MagicMock()
    sentinel.done.return_value = False
    _runner._background_tasks["t1"] = sentinel
    try:
        resp = _retry_ripple(ripple_client)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["status"] == "skipped", data
        assert data["message"] == _SERIALIZATION_SENTENCE, data
        # The occupant of the slot is untouched. A guard that fired *after*
        # taking the slot would leave its own task here.
        assert _runner._background_tasks["t1"] is sentinel
    finally:
        _runner._background_tasks.pop("t1", None)


def test_ripple_retry_starts_without_taking_the_task_slot(ripple_client: TestClient) -> None:
    """The refused half: it starts, and the registry is still empty afterwards.

    This is the assertion that makes "no registry write" a decision instead of a
    gap.  If someone later copies the sibling's three-line tail, the slot here
    gains an entry and this test fails -- pointing at §7, which explains why the
    three lines are not copyable.
    """
    with patch(_RIPPLE_SERVICE, return_value=MagicMock()):
        resp = _retry_ripple(ripple_client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "retrying", resp.json()
    assert "t1" not in _runner._background_tasks, _runner._background_tasks


def test_ripple_retry_still_runs_past_a_foreign_lease(ripple_client: TestClient) -> None:
    """The predicate is the process-local one, not the lease one.

    Identical configuration to ``test_brief_upload_still_resumes_past_a_foreign_lease``,
    one guard over: another instance holds the lease, this process holds no task.
    A guard written as ``has_active_execution`` would refuse here -- and would go
    on refusing for up to ``LEASE_TTL_SECONDS`` after the owner died, so the retry
    button would answer "工作流正在运行" at a thread where nothing runs.  Swapping
    the predicate was the one edit that kept every other case in this file green.
    """
    with patch.object(leases, "_instance_id", _OTHER_INSTANCE):
        assert asyncio.run(leases.acquire("t1")) is True

    # Visible to the ownership question, invisible to the serialization one.
    assert asyncio.run(_runner.has_active_execution("t1")) is True
    assert _runner.process_has_active_task("t1") is False

    with patch(_RIPPLE_SERVICE, return_value=MagicMock()):
        resp = _retry_ripple(ripple_client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "retrying", resp.json()
