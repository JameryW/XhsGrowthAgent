"""Guard tests for POST /api/review/submit binding + review ETag checks (ledger #39/#48)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.review import router
from backend.db.accounts import AccountRow
from backend.db.workflows import WorkflowRow

_OWNERSHIP_PATCHES = (
    patch(
        "backend.db.workflows.get_workflow",
        AsyncMock(return_value=WorkflowRow(thread_id="t1", account_id="acc1")),
    ),
    patch(
        "backend.api.account_scope.get_account",
        AsyncMock(
            return_value=AccountRow(id="acc1", name="acc1", is_active=True, owner_user_id="u1")
        ),
    ),
)


def _client(values: dict) -> tuple[TestClient, MagicMock]:
    graph = MagicMock()
    graph.store = InMemoryStore()
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = ("review_gate",)
    snapshot.tasks = ()
    snapshot.config = {"configurable": {"checkpoint_ns": "ns0"}}
    graph.aget_state = AsyncMock(return_value=snapshot)

    app = FastAPI()
    app.include_router(router, prefix="/api/review")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "u1", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app), graph


def _values() -> dict:
    return {
        "thread_id": "t1",
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "reviewing",
        "copy_content": {"selected_title": "原标题", "body_text": "原正文", "hashtags": []},
    }


def test_submit_rejects_cross_account_binding() -> None:
    client, graph = _client(_values())
    with _OWNERSHIP_PATCHES[0], _OWNERSHIP_PATCHES[1]:
        response = client.post(
            "/api/review/submit/t1",
            json={
                "decision": "approved",
                "expected_account_id": "acc2",
                "publish_options": {"dry_run": True},
            },
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ERROR_REVIEW_DECISION_INVALID"
    assert graph.aget_state.await_count >= 1


def test_submit_rejects_stale_review_etag() -> None:
    client, _graph = _client(_values())
    with _OWNERSHIP_PATCHES[0], _OWNERSHIP_PATCHES[1]:
        pending = client.get("/api/review/pending/t1")
        assert pending.status_code == 200
        assert pending.json()["data"]["review_etag"]
        response = client.post(
            "/api/review/submit/t1",
            json={
                "decision": "needs_revision",
                "expected_account_id": "acc1",
                "expected_review_etag": "stale-etag",
            },
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ERROR_REVIEW_DECISION_INVALID"
