"""Tests for POST /api/workflow/recover/{thread_id}.

Locks the three recovery strategies (retry_failed / retry_from_last_success /
skip_to_next), the error/stale-only eligibility guard, and the 400 diagnostic
when the target node can't be determined.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import _runner
from backend.api.routes.workflow import router

_START_RESUME = "backend.api.routes.workflow._start_resume_task"
_DB_UPSERT = "backend.api.routes.workflow._db_upsert"
_POOL_READY = "backend.api.routes.workflow.is_pool_ready"
_DB_GET = "backend.api.routes.workflow.db_get"


def _make_snapshot(values: dict, next_nodes=(), tasks=()):
    """Build a fake StateSnapshot for graph.aget_state()."""
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = next_nodes
    snapshot.tasks = tasks
    # derive_status checks bool(snapshot.interrupts) — MagicMock attr is truthy,
    # so set it explicitly to an empty tuple to avoid false awaiting_* detection.
    snapshot.interrupts = ()
    return snapshot


def _make_task(name: str, has_error: bool = False) -> MagicMock:
    """Build a fake PregelTask with .name and .error attributes."""
    task = MagicMock()
    task.name = name
    task.error = "boom" if has_error else None
    return task


def _values(**overrides) -> dict:
    base = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "error",
        "error": "something failed",
        "prev_phase": "creating",
    }
    base.update(overrides)
    return base


def _make_graph(snapshot: MagicMock) -> MagicMock:
    graph = MagicMock()
    graph.store = MagicMock(name="store")
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    return graph


@pytest.fixture
def app_and_client():
    """App + client + graph with an ERROR snapshot by default.

    Snapshot is mutable via graph.aget_state.return_value so individual tests
    can swap in different state shapes.
    """
    snapshot = _make_snapshot(_values(), next_nodes=(), tasks=())
    graph = _make_graph(snapshot)
    app = FastAPI()
    app.include_router(router, prefix="/api/workflow")
    app.state.graph = graph
    from backend.api.middleware import error_handler_middleware

    app.middleware("http")(error_handler_middleware)
    return app, TestClient(app), graph


def _clear_active_tasks(thread_id: str) -> None:
    """Ensure no stale fake task lingers in the shared registry between tests."""
    _runner._background_tasks.pop(thread_id, None)
    _runner._active_sync_executions.discard(thread_id)


def test_retry_failed_calls_start_resume_with_none(app_and_client):
    """strategy=retry_failed → _start_resume_task(input_data=None) (native ainvoke)."""
    app, client, graph = app_and_client
    # ERROR state: error present + phase=error + empty next
    graph.aget_state.return_value = _make_snapshot(
        _values(error="boom", phase="error"), next_nodes=(), tasks=()
    )
    _clear_active_tasks("thr1")
    try:
        with (
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
            patch(_DB_UPSERT, new_callable=AsyncMock),
        ):
            resp = client.post("/api/workflow/recover/thr1", json={"strategy": "retry_failed"})
    finally:
        _clear_active_tasks("thr1")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "running"
    assert body["strategy"] == "retry_failed"
    assert body["recovered"] is True
    # retry_failed mirrors /resume: native ainvoke(None) — no Command
    mock_start.assert_awaited_once()
    assert mock_start.call_args.kwargs.get("input_data") is None


def test_retry_from_last_success_uses_command_goto_last_success(app_and_client):
    """strategy=retry_from_last_success → Command(goto=last non-error task)."""
    app, client, graph = app_and_client
    # tasks: orchestrator (ok) → trend_scout (ok) → copywriter (error)
    # last success = "trend_scout"
    tasks = (
        _make_task("orchestrator"),
        _make_task("trend_scout"),
        _make_task("copywriter", has_error=True),
    )
    graph.aget_state.return_value = _make_snapshot(
        _values(error="boom", phase="error"), next_nodes=(), tasks=tasks
    )
    _clear_active_tasks("thr2")
    try:
        with (
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
            patch(_DB_UPSERT, new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/workflow/recover/thr2",
                json={"strategy": "retry_from_last_success"},
            )
    finally:
        _clear_active_tasks("thr2")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["strategy"] == "retry_from_last_success"
    assert body["target_node"] == "trend_scout"
    assert body["recovered"] is True
    mock_start.assert_awaited_once()
    input_data = mock_start.call_args.kwargs.get("input_data")
    # Command(goto="trend_scout")
    assert input_data is not None
    assert getattr(input_data, "goto", None) == "trend_scout"


def test_skip_to_next_uses_command_goto_next_node(app_and_client):
    """strategy=skip_to_next → Command(goto=state.next[0])."""
    app, client, graph = app_and_client
    # STALE state: next non-empty + has_active_task=False + no error/phase=error
    graph.aget_state.return_value = _make_snapshot(
        _values(phase="creating", error=None), next_nodes=("publisher",), tasks=()
    )
    _clear_active_tasks("thr3")
    try:
        with (
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
            patch(_DB_UPSERT, new_callable=AsyncMock),
        ):
            resp = client.post("/api/workflow/recover/thr3", json={"strategy": "skip_to_next"})
    finally:
        _clear_active_tasks("thr3")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["strategy"] == "skip_to_next"
    assert body["target_node"] == "publisher"
    assert body["recovered"] is True
    mock_start.assert_awaited_once()
    input_data = mock_start.call_args.kwargs.get("input_data")
    assert input_data is not None
    assert getattr(input_data, "goto", None) == "publisher"


def test_non_error_state_returns_rejection_message(app_and_client):
    """PAUSED (or any non-error/stale) → recovered=False, no task spawned."""
    app, client, graph = app_and_client
    # PAUSED: phase=paused
    graph.aget_state.return_value = _make_snapshot(
        _values(phase="paused", error=None), next_nodes=(), tasks=()
    )
    _clear_active_tasks("thr4")
    try:
        with (
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
            patch(_DB_UPSERT, new_callable=AsyncMock),
        ):
            resp = client.post("/api/workflow/recover/thr4", json={"strategy": "retry_failed"})
    finally:
        _clear_active_tasks("thr4")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["recovered"] is False
    assert body["status"] == "paused"
    assert "不可 recover" in body["message"]
    mock_start.assert_not_awaited()


def test_skip_to_next_with_empty_next_returns_400(app_and_client):
    """skip_to_next with state.next empty → 400 ValidationError, no task spawned."""
    app, client, graph = app_and_client
    # ERROR with empty next + no successful tasks → skip_to_next can't find a successor
    graph.aget_state.return_value = _make_snapshot(
        _values(error="boom", phase="error"), next_nodes=(), tasks=()
    )
    _clear_active_tasks("thr5")
    try:
        with (
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
            patch(_DB_UPSERT, new_callable=AsyncMock),
        ):
            resp = client.post("/api/workflow/recover/thr5", json={"strategy": "skip_to_next"})
    finally:
        _clear_active_tasks("thr5")

    # ValidationError → 400 error envelope
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "后继" in body["error"]["message"]
    mock_start.assert_not_awaited()


def test_retry_from_last_success_no_successful_task_returns_400(app_and_client):
    """retry_from_last_success with no non-error named task → 400 diagnostic."""
    app, client, graph = app_and_client
    # All tasks errored (or no named tasks) → can't find a last success
    tasks = (_make_task("copywriter", has_error=True),)
    graph.aget_state.return_value = _make_snapshot(
        _values(error="boom", phase="error"), next_nodes=(), tasks=tasks
    )
    _clear_active_tasks("thr6")
    try:
        with (
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
            patch(_DB_UPSERT, new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/workflow/recover/thr6",
                json={"strategy": "retry_from_last_success"},
            )
    finally:
        _clear_active_tasks("thr6")

    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "上次成功节点" in body["error"]["message"]
    mock_start.assert_not_awaited()


# ── checkpoint_lost diagnostics ──


def _make_empty_snapshot() -> MagicMock:
    """A snapshot with no values — simulates a lost LangGraph checkpoint."""
    snapshot = MagicMock()
    snapshot.values = {}
    snapshot.next = ()
    snapshot.tasks = ()
    snapshot.interrupts = ()
    return snapshot


def _make_db_row(status: str = "running") -> MagicMock:
    """A fake WorkflowRow for db_get."""
    row = MagicMock()
    row.status = status
    row.phase = "creating"
    row.error = None
    row.created_at = "2026-07-10T00:00:00"
    row.updated_at = "2026-07-10T00:00:00"
    row.label = ""
    row.progress_percent = 50
    return row


def test_checkpoint_lost_returns_diagnostic_not_404(app_and_client):
    """No checkpoint + DB row running → 200 diagnostic (recovered=False, checkpoint_lost).

    The user sees a clear message instead of a bare 404, telling them to
    /resume restart.
    """
    app, client, graph = app_and_client
    graph.aget_state.return_value = _make_empty_snapshot()
    _clear_active_tasks("thr_cl1")
    try:
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=_make_db_row("running")),
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
        ):
            resp = client.post("/api/workflow/recover/thr_cl1", json={"strategy": "retry_failed"})
    finally:
        _clear_active_tasks("thr_cl1")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["recovered"] is False
    assert body["status"] == "checkpoint_lost"
    assert "checkpoint" in body["message"].lower() or "/resume" in body["message"]
    mock_start.assert_not_awaited()


def test_checkpoint_lost_stale_db_row_also_diagnosed(app_and_client):
    """No checkpoint + DB row stale → 200 diagnostic (same as running)."""
    app, client, graph = app_and_client
    graph.aget_state.return_value = _make_empty_snapshot()
    _clear_active_tasks("thr_cl2")
    try:
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=_make_db_row("stale")),
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
        ):
            resp = client.post("/api/workflow/recover/thr_cl2", json={"strategy": "retry_failed"})
    finally:
        _clear_active_tasks("thr_cl2")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["recovered"] is False
    assert body["status"] == "checkpoint_lost"
    mock_start.assert_not_awaited()


def test_no_checkpoint_no_db_row_still_404(app_and_client):
    """No checkpoint + no DB row → 404 (truly nonexistent thread)."""
    app, client, graph = app_and_client
    graph.aget_state.return_value = _make_empty_snapshot()
    _clear_active_tasks("thr_cl3")
    try:
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=None),
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
        ):
            resp = client.post("/api/workflow/recover/thr_cl3", json={"strategy": "retry_failed"})
    finally:
        _clear_active_tasks("thr_cl3")

    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    mock_start.assert_not_awaited()


def test_checkpoint_lost_terminal_db_row_still_404(app_and_client):
    """No checkpoint + DB row completed (terminal) → 404, not checkpoint_lost.

    A completed/cancelled DB row is not "checkpoint lost" — it finished
    normally. Only non-terminal rows with no live task qualify.
    """
    app, client, graph = app_and_client
    graph.aget_state.return_value = _make_empty_snapshot()
    _clear_active_tasks("thr_cl4")
    try:
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=_make_db_row("completed")),
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
        ):
            resp = client.post("/api/workflow/recover/thr_cl4", json={"strategy": "retry_failed"})
    finally:
        _clear_active_tasks("thr_cl4")

    assert resp.status_code == 404
    mock_start.assert_not_awaited()


def test_checkpoint_lost_pool_not_ready_still_404(app_and_client):
    """No checkpoint + pool not ready (no DB) → 404 (can't check DB)."""
    app, client, graph = app_and_client
    graph.aget_state.return_value = _make_empty_snapshot()
    _clear_active_tasks("thr_cl5")
    try:
        with (
            patch(_POOL_READY, return_value=False),
            patch(_DB_GET, new_callable=AsyncMock) as mock_db_get,
            patch(_START_RESUME, new_callable=AsyncMock) as mock_start,
        ):
            resp = client.post("/api/workflow/recover/thr_cl5", json={"strategy": "retry_failed"})
    finally:
        _clear_active_tasks("thr_cl5")

    assert resp.status_code == 404
    mock_db_get.assert_not_awaited()
    mock_start.assert_not_awaited()
