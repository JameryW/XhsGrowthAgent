"""Tests for POST /api/review/update-copy/{thread_id}.

Guards:
- awaiting_review + partial fields → copy_content merged + evaluator called +
  evaluation_result written back + response.
- not awaiting_review → status="skipped", evaluator never called.
- evaluator raises → copy_content still saved, evaluation_result empty,
  response carries a warning.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.review import router
from backend.db.accounts import AccountRow
from backend.db.workflows import WorkflowRow

_EVAL_PATH = "backend.api.routes.review._evaluator"


def _make_graph(values: dict, *, next_nodes=(), store=None) -> tuple[MagicMock, MagicMock]:
    """Fake compiled graph: aget_state returns a snapshot with .values and .next."""
    graph = MagicMock()
    graph.store = store if store is not None else MagicMock(name="store")
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = tuple(next_nodes)
    snapshot.tasks = ()
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    return graph, snapshot


def _values(**overrides) -> dict:
    base = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "reviewing",
        "copy_content": {
            "selected_title": "原标题",
            "body_text": "原正文",
            "hashtags": ["原tag"],
            "tone": "治愈",
            "cta": "关注我",
        },
    }
    base.update(overrides)
    return base


@pytest.fixture
def app_and_client():
    graph, _ = _make_graph(_values(), next_nodes=("review_gate",))
    app = FastAPI()
    app.include_router(router, prefix="/api/review")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user():
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user

    # assert_thread_owned resolves the workflow row (function-level import,
    # patch at source) then checks account ownership via account_scope.
    owned = AccountRow(id="acc1", name="acc1", is_active=True, owner_user_id="user-test")
    with (
        patch(
            "backend.db.workflows.get_workflow",
            AsyncMock(return_value=WorkflowRow(thread_id="t1", account_id="acc1")),
        ),
        patch("backend.api.account_scope.get_account", AsyncMock(return_value=owned)),
    ):
        yield app, TestClient(app), graph
    app.dependency_overrides.pop(get_current_user, None)


def test_partial_update_merges_and_runs_evaluator(app_and_client):
    app, client, graph = app_and_client
    eval_result = {"overall_score": 88.0, "decision": "approved", "dimensions": []}

    with patch(_EVAL_PATH, new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = {"evaluation_result": eval_result}

        resp = client.post(
            "/api/review/update-copy/t1",
            json={"title": "新标题", "hashtags": ["新tag"]},
        )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["thread_id"] == "t1"
    assert body["status"] == "updated"
    assert body["evaluation_result"] == eval_result

    # aupdate_state called twice: copy_content then evaluation_result
    assert graph.aupdate_state.await_count == 2
    first_call = graph.aupdate_state.await_args_list[0]
    assert first_call.args[1] == {
        "copy_content": {
            "selected_title": "新标题",
            "body_text": "原正文",
            "hashtags": ["新tag"],
            "tone": "治愈",
            "cta": "关注我",
        }
    }
    second_call = graph.aupdate_state.await_args_list[1]
    assert second_call.args[1] == {"evaluation_result": eval_result}

    # evaluator received updated copy_content
    eval_state = mock_eval.call_args.args[0]
    assert eval_state["copy_content"]["selected_title"] == "新标题"
    assert eval_state["copy_content"]["tone"] == "治愈"


def test_non_awaiting_review_returns_skipped(app_and_client):
    _, client, graph = app_and_client
    # Override snapshot.next to not contain review_gate
    snapshot = graph.aget_state.return_value
    snapshot.next = ("publisher",)

    with patch(_EVAL_PATH, new_callable=AsyncMock) as mock_eval:
        resp = client.post(
            "/api/review/update-copy/t1",
            json={"title": "新标题"},
        )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "skipped"
    assert body["evaluation_result"] == {}
    assert "仅待审核" in body["message"]
    # evaluator never called, aupdate_state never called
    mock_eval.assert_not_awaited()
    graph.aupdate_state.assert_not_awaited()


def test_evaluator_failure_degrades_with_warning(app_and_client):
    _, client, graph = app_and_client

    with patch(_EVAL_PATH, new_callable=AsyncMock) as mock_eval:
        mock_eval.side_effect = RuntimeError("LLM boom")

        resp = client.post(
            "/api/review/update-copy/t1",
            json={"body_text": "改过的正文"},
        )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] == "updated"
    assert body["evaluation_result"] == {}
    assert "evaluator 降级放行" in body["warning"]

    # copy_content still saved (first aupdate_state call), but only once
    # (no evaluation_result write since evaluator threw before persisting)
    assert graph.aupdate_state.await_count == 1
    saved = graph.aupdate_state.await_args.args[1]
    assert saved["copy_content"]["body_text"] == "改过的正文"
    # preserved fields kept
    assert saved["copy_content"]["tone"] == "治愈"
    assert saved["copy_content"]["selected_title"] == "原标题"
