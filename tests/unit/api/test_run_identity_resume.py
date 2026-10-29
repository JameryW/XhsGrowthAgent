"""票 5x: pause/error resume keeps run_id; terminal restart mints a new one."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.workflow import router
from backend.state.enums import WorkflowPhase

_START_RESUME_LEGACY = "backend.api.routes._wf_application._start_resume_task"
_EMIT = "backend.state.events.emit_events"
_HAS_ACTIVE = "backend.api.routes._wf_application._runner.has_active_execution"


def _values(*, phase: WorkflowPhase, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "xhs_acc1_abc",
        "thread_id": "xhs_acc1_abc",
        "account_id": "acc1",
        "phase": phase,
        "prev_phase": WorkflowPhase.CREATING,
        "run_id": "run_oldoldoldold",
        "run_seq": 1,
        "run_cause": "start",
        "current_agent": "copywriter",
        "error": None,
    }
    base.update(overrides)
    return base


def _make_graph(
    values: dict[str, Any],
    *,
    next_nodes: tuple[str, ...] = (),
) -> MagicMock:
    graph = MagicMock()
    graph.store = None
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = next_nodes
    snapshot.tasks = ()
    snapshot.interrupts = []
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    graph.ainvoke = AsyncMock(return_value=values)
    return graph


@contextlib.contextmanager
def _client_for(
    values: dict[str, Any],
    *,
    next_nodes: tuple[str, ...] = (),
    has_active: bool = False,
) -> Iterator[tuple[TestClient, MagicMock, AsyncMock]]:
    from backend.api.deps import get_current_user
    from backend.api.middleware import error_handler_middleware
    from backend.db.accounts import AccountRow
    from backend.db.workflows import WorkflowRow

    graph = _make_graph(values, next_nodes=next_nodes)
    app = FastAPI()
    app.include_router(router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    owned = AccountRow(id="acc1", name="acc1", is_active=True, owner_user_id="user-test")
    with (
        patch("backend.api.account_scope.get_account", AsyncMock(return_value=owned)),
        patch(
            "backend.db.workflows.get_workflow",
            AsyncMock(
                return_value=WorkflowRow(
                    thread_id="xhs_acc1_abc",
                    account_id="acc1",
                    status="paused",
                    phase="paused",
                )
            ),
        ),
        patch(_START_RESUME_LEGACY, new_callable=AsyncMock),
        patch(_HAS_ACTIVE, new_callable=AsyncMock, return_value=has_active),
        patch(_EMIT, new_callable=AsyncMock) as emit,
    ):
        yield TestClient(app), graph, emit


def test_pause_resume_reuses_run_id() -> None:
    values = _values(phase=WorkflowPhase.PAUSED)
    with _client_for(values) as (client, graph, emit):
        resp = client.post("/api/workflow/resume/xhs_acc1_abc")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "running"
        assert body["run_id"] == "run_oldoldoldold"
        assert body["run_seq"] == 1
        emit.assert_not_called()
        patch_arg = graph.aupdate_state.await_args.args[1]
        assert "run_id" not in patch_arg


def test_error_resume_reuses_run_id_without_mint() -> None:
    """Error path must not aupdate_state (retry loop bug) and must not mint."""
    values = _values(phase=WorkflowPhase.ERROR, error="boom")
    with _client_for(values) as (client, graph, emit):
        resp = client.post("/api/workflow/resume/xhs_acc1_abc")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "running"
        assert body["run_id"] == "run_oldoldoldold"
        assert body["run_seq"] == 1
        assert body["run_cause"] == "start"
        emit.assert_not_called()
        graph.aupdate_state.assert_not_awaited()


def test_stale_resume_reuses_run_id_without_mint() -> None:
    values = _values(phase=WorkflowPhase.CREATING)
    with _client_for(values, next_nodes=("copywriter",), has_active=False) as (
        client,
        graph,
        emit,
    ):
        resp = client.post("/api/workflow/resume/xhs_acc1_abc")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "running"
        assert body["run_id"] == "run_oldoldoldold"
        assert body["run_seq"] == 1
        emit.assert_not_called()
        graph.aupdate_state.assert_not_awaited()


def test_terminal_restart_mints_new_run() -> None:
    values = _values(phase=WorkflowPhase.COMPLETED)
    with _client_for(values) as (client, graph, emit):
        resp = client.post("/api/workflow/resume/xhs_acc1_abc")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "running"
        assert body["run_seq"] == 2
        assert body["run_cause"] == "rerun"
        assert body["run_id"] != "run_oldoldoldold"
        assert str(body["run_id"]).startswith("run_")
        emit.assert_awaited()
        entries = emit.await_args.args[1]
        assert entries[0]["kind"] == "run"
        assert entries[0]["cause"] == "rerun"
        assert entries[0]["run_seq"] == 2
        patch_arg = graph.aupdate_state.await_args.args[1]
        assert patch_arg["run_seq"] == 2
        assert patch_arg["run_cause"] == "rerun"
        assert patch_arg["run_id"] == body["run_id"]


def test_cancelled_terminal_restart_mints_new_run() -> None:
    values = _values(phase=WorkflowPhase.CANCELLED)
    with _client_for(values) as (client, graph, emit):
        resp = client.post("/api/workflow/resume/xhs_acc1_abc")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["run_seq"] == 2
        assert body["run_cause"] == "rerun"
        assert body["run_id"] != "run_oldoldoldold"
        emit.assert_awaited()
        assert emit.await_args.args[1][0]["kind"] == "run"
