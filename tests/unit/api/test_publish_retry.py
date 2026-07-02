"""Tests for POST /api/workflow/publish-retry/{thread_id}.

Locks the eligibility guards (no content / already published / active workflow /
not found) and the background retry write-back (aupdate_state + _db_upsert + events).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.workflow import router

_RUN_PUBLISH = "backend.api.routes.workflow.run_publish"
_DB_UPSERT = "backend.api.routes.workflow._db_upsert"
_EVENT_BUS = "backend.api.routes.workflow.EventBusService"


def _make_graph(values: dict, store=None):
    """A fake compiled graph: aget_state returns a snapshot with .values."""
    graph = MagicMock()
    graph.store = store if store is not None else MagicMock(name="store")
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = ()
    snapshot.tasks = ()
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    return graph, snapshot


def _values(**overrides) -> dict:
    base = {
        "session_id": "s1",
        "account_id": "acc1",
        "copy_content": {"selected_title": "t", "body_text": "b"},
        "publish_result": {"status": "failed", "post_id": ""},
    }
    base.update(overrides)
    return base


@pytest.fixture
def app_and_client():
    graph, _ = _make_graph(_values())
    app = FastAPI()
    app.include_router(router, prefix="/api/workflow")
    app.state.graph = graph
    # Mount the same APIError→envelope middleware the real app uses, so
    # WorkflowNotFoundError surfaces as a JSON error body, not a raised exc.
    from backend.api.middleware import error_handler_middleware

    app.middleware("http")(error_handler_middleware)
    return app, TestClient(app), graph


def test_returns_retrying_and_schedules_task(app_and_client):
    """Eligible failed-publish workflow → status=retrying + background task scheduled.

    The background task's write-back is covered by run_publish unit tests + the
    aupdate_state call shape asserted here via a patched create_task that returns
    a fake task whose body we drive.
    """
    app, client, graph = app_and_client
    pr = {"post_id": "p1", "post_url": "u", "status": "published", "published_at": "now"}

    captured_coro = {}

    def fake_create_task(coro, **kw):
        captured_coro["coro"] = coro
        task = MagicMock()
        task.add_done_callback = MagicMock()
        task.get_name = lambda: kw.get("name", "")
        return task

    with (
        patch(_RUN_PUBLISH, new_callable=AsyncMock, return_value={"publish_result": pr}),
        patch(_DB_UPSERT, new_callable=AsyncMock),
        patch(_EVENT_BUS) as mock_bus_cls,
        patch("backend.api.routes.workflow.asyncio.create_task", side_effect=fake_create_task),
    ):
        mock_bus_cls.get_instance.return_value = MagicMock()
        resp = client.post("/api/workflow/publish-retry/thr1")
        body = resp.json()["data"]
        assert body["status"] == "retrying"
        # Drive the captured coroutine body to completion WITHIN the patch scope
        coro = captured_coro["coro"]
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    graph.aupdate_state.assert_awaited()
    # aupdate_state(config, {updates...}, as_node=...) — updates is positional arg[1]
    assert graph.aupdate_state.call_args.args[1]["publish_result"] == pr


def test_rejects_already_published(app_and_client):
    """publish_result.status=published → skipped, no retry task spawned."""
    app, client, graph = app_and_client
    graph.aget_state.return_value.values = _values(
        publish_result={"status": "published", "post_id": "p1"}
    )

    with (
        patch(_RUN_PUBLISH, new_callable=AsyncMock) as mock_rp,
        patch(_DB_UPSERT, new_callable=AsyncMock),
    ):
        resp = client.post("/api/workflow/publish-retry/thr1")

    body = resp.json()["data"]
    assert body["status"] == "skipped"
    assert "已发布" in body["message"] or "重复" in body["message"]
    mock_rp.assert_not_awaited()


def test_rejects_no_content(app_and_client):
    """No copy_content → skipped, no retry."""
    app, client, graph = app_and_client
    graph.aget_state.return_value.values = _values(copy_content={})

    with (
        patch(_RUN_PUBLISH, new_callable=AsyncMock) as mock_rp,
        patch(_DB_UPSERT, new_callable=AsyncMock),
    ):
        resp = client.post("/api/workflow/publish-retry/thr1")

    body = resp.json()["data"]
    assert body["status"] == "skipped"
    mock_rp.assert_not_awaited()


def test_rejects_when_active(app_and_client):
    """Workflow currently running (background task active) → skipped."""
    app, client, graph = app_and_client
    # Plant an active (non-done) task in the registry
    from backend.api.routes import _runner

    fake_task = MagicMock()
    fake_task.done.return_value = False
    _runner._background_tasks["thr1"] = fake_task
    try:
        with (
            patch(_RUN_PUBLISH, new_callable=AsyncMock) as mock_rp,
            patch(_DB_UPSERT, new_callable=AsyncMock),
        ):
            resp = client.post("/api/workflow/publish-retry/thr1")
    finally:
        _runner._background_tasks.pop("thr1", None)

    body = resp.json()["data"]
    assert body["status"] == "skipped"
    mock_rp.assert_not_awaited()


def test_not_found_when_no_state(app_and_client):
    """Empty state (no session_id) → WorkflowNotFoundError (404-ish)."""
    app, client, graph = app_and_client
    graph.aget_state.return_value.values = {}

    with patch(_RUN_PUBLISH, new_callable=AsyncMock):
        resp = client.post("/api/workflow/publish-retry/thr1")

    # WorkflowNotFoundError → error envelope (not success)
    body = resp.json()
    assert body["success"] is False
