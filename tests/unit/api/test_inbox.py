"""Tests for GET /api/inbox — aggregate at-gate threads for the active account.

Covers: empty inbox (no account / no threads / no at-gate), per-gate snapshot
shape for review/ripple/choice/draft/blogger, and mixed-thread filtering (only
at-gate threads appear, running ones are skipped).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.inbox import router
from backend.db.workflows import WorkflowRow

_DB_LIST = "backend.api.routes.inbox.db_list"
_IS_POOL_READY = "backend.api.routes.inbox.is_pool_ready"
_GET_ACTIVE = "backend.api.account_scope.get_active_account"


def _row(thread_id: str, account_id: str = "acc1", **overrides) -> WorkflowRow:
    base = {
        "thread_id": thread_id,
        "account_id": account_id,
        "status": "running",
        "phase": "scouting",
        "label": "",
        "workflow_mode": "trend",
        "updated_at": "2026-07-01T10:00:00Z",
        "created_at": "2026-07-01T09:00:00Z",
    }
    base.update(overrides)
    return WorkflowRow(**base)


class _Account:
    def __init__(self, id: str) -> None:
        self.id = id
        self.name = id
        self.owner_user_id = "user-test"


def _snapshot(values: dict, next_nodes=(), interrupts=()) -> MagicMock:
    snap = MagicMock()
    snap.values = values
    snap.next = next_nodes
    snap.interrupts = interrupts
    return snap


def _make_graph(state_map: dict[str, MagicMock]) -> MagicMock:
    async def _aget_state(config):
        tid = config["configurable"]["thread_id"]
        return state_map.get(tid, _snapshot({}))

    graph = MagicMock()
    graph.aget_state = AsyncMock(side_effect=_aget_state)
    graph.store = MagicMock()
    return graph


@pytest.fixture
def app_and_client():
    async def _user():
        return {"id": "user-test", "username": "tester"}

    graph = _make_graph({})
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)
    app.dependency_overrides[get_current_user] = _user
    yield app, TestClient(app), graph
    app.dependency_overrides.pop(get_current_user, None)


# ── Empty inbox ───────────────────────────────────────────────────────────


def test_empty_when_no_account(app_and_client):
    """No active account → empty inbox, not 500."""
    app, client, _ = app_and_client
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=None),
        patch(_IS_POOL_READY, return_value=True),
    ):
        resp = client.get("/api/inbox")
    body = resp.json()["data"]
    assert body["inbox"] == []
    assert body["account_id"] is None


def test_empty_when_db_unavailable(app_and_client):
    """DB pool not ready → empty inbox."""
    app, client, _ = app_and_client
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=False),
    ):
        resp = client.get("/api/inbox")
    body = resp.json()["data"]
    assert body["inbox"] == []


def test_empty_when_no_threads(app_and_client):
    """Account active, DB ready, but no workflows → empty."""
    app, client, _ = app_and_client
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, new_callable=AsyncMock, return_value=([], 0)),
    ):
        resp = client.get("/api/inbox")
    body = resp.json()["data"]
    assert body["inbox"] == []


# ── Per-gate snapshots ────────────────────────────────────────────────────


def test_thread_at_review_gate(app_and_client):
    """review_gate in next → entry with review snapshot."""
    app, client, graph = app_and_client
    values = {
        "session_id": "s1",
        "phase": "reviewing",
        "copy_content": {"selected_title": "T", "body_text": "B", "hashtags": ["#x"]},
        "visual_plan": {"image_paths": ["/p/1.jpg"]},
        "content_versions": [{"version_id": "v1"}],
    }
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=("review_gate",)))
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, new_callable=AsyncMock, return_value=([_row("t1")], 1)),
    ):
        resp = client.get("/api/inbox")
    inbox = resp.json()["data"]["inbox"]
    assert len(inbox) == 1
    entry = inbox[0]
    assert entry["thread_id"] == "t1"
    assert entry["gate"] == "review"
    assert entry["phase"] == "reviewing"
    snap = entry["snapshot"]
    assert snap["title"] == "T"
    assert snap["body_text"] == "B"
    assert snap["hashtags"] == ["#x"]
    assert snap["image_paths"] == ["/p/1.jpg"]
    assert snap["content_versions"] == [{"version_id": "v1"}]


def test_thread_at_ripple_gate_via_interrupt(app_and_client):
    """Dynamic interrupt() with gate='ripple' → entry with ripple snapshot."""
    app, client, graph = app_and_client
    values = {
        "session_id": "s1",
        "phase": "planning",
        "ripple_prediction": {"viral_probability": 0.4},
        "ripple_pmf": {"pmf_score": 0.6},
        "ripple_reason": "suboptimal",
        "reselect_count": 1,
    }
    intr = MagicMock()
    intr.value = {"gate": "ripple"}
    graph.aget_state = AsyncMock(return_value=_snapshot(values, interrupts=(intr,)))
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, new_callable=AsyncMock, return_value=([_row("t2")], 1)),
    ):
        resp = client.get("/api/inbox")
    entry = resp.json()["data"]["inbox"][0]
    assert entry["gate"] == "ripple"
    assert entry["snapshot"]["ripple_prediction"]["viral_probability"] == 0.4
    assert entry["snapshot"]["reselect_count"] == 1


def test_thread_at_choice_gate(app_and_client):
    """choice_gate in next → entry with content_versions snapshot."""
    app, client, graph = app_and_client
    values = {
        "session_id": "s1",
        "phase": "creating",
        "content_versions": [{"version_id": "a"}, {"version_id": "b"}],
    }
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=("choice_gate",)))
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, new_callable=AsyncMock, return_value=([_row("t3")], 1)),
    ):
        resp = client.get("/api/inbox")
    entry = resp.json()["data"]["inbox"][0]
    assert entry["gate"] == "choice"
    assert len(entry["snapshot"]["content_versions"]) == 2


def test_thread_at_draft_gate(app_and_client):
    """draft_gate in next → entry with copy_content snapshot."""
    app, client, graph = app_and_client
    values = {
        "session_id": "s1",
        "phase": "creating",
        "copy_content": {"selected_title": "draft title"},
    }
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=("draft_gate",)))
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, new_callable=AsyncMock, return_value=([_row("t4")], 1)),
    ):
        resp = client.get("/api/inbox")
    entry = resp.json()["data"]["inbox"][0]
    assert entry["gate"] == "draft"
    assert entry["snapshot"]["copy_content"]["selected_title"] == "draft title"


def test_thread_at_blogger_gate(app_and_client):
    """blogger_gate in next → entry with blogger snapshot."""
    app, client, graph = app_and_client
    values = {
        "session_id": "s1",
        "phase": "creating",
        "blogger_candidates": [{"user_id": "u1"}],
        "selected_blogger": {},
        "blogger_notes": [{"id": "n1"}],
    }
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=("blogger_gate",)))
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, new_callable=AsyncMock, return_value=([_row("t5")], 1)),
    ):
        resp = client.get("/api/inbox")
    entry = resp.json()["data"]["inbox"][0]
    assert entry["gate"] == "blogger"
    assert entry["snapshot"]["blogger_candidates"] == [{"user_id": "u1"}]
    assert entry["snapshot"]["blogger_notes"] == [{"id": "n1"}]


# ── Filtering ─────────────────────────────────────────────────────────────


def test_running_thread_not_in_inbox(app_and_client):
    """Thread at a non-gate node (running) → excluded from inbox."""
    app, client, graph = app_and_client
    values = {"session_id": "s1", "phase": "scouting"}
    graph.aget_state = AsyncMock(return_value=_snapshot(values, next_nodes=("trend_scout",)))
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, new_callable=AsyncMock, return_value=([_row("t6")], 1)),
    ):
        resp = client.get("/api/inbox")
    assert resp.json()["data"]["inbox"] == []


def test_thread_without_checkpoint_skipped(app_and_client):
    """DB row exists but no live checkpoint (session_id None) → skipped."""
    app, client, graph = app_and_client
    graph.aget_state = AsyncMock(return_value=_snapshot({}))
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, new_callable=AsyncMock, return_value=([_row("t7")], 1)),
    ):
        resp = client.get("/api/inbox")
    assert resp.json()["data"]["inbox"] == []


def test_mixed_threads_only_at_gate_returned(app_and_client):
    """Multiple threads, mixed states → only the at-gate ones appear."""
    app, client, graph = app_and_client
    review_snap = _snapshot(
        {"session_id": "s1", "phase": "reviewing", "copy_content": {"selected_title": "R"}},
        next_nodes=("review_gate",),
    )
    running_snap = _snapshot(
        {"session_id": "s2", "phase": "scouting"},
        next_nodes=("trend_scout",),
    )
    draft_snap = _snapshot(
        {"session_id": "s3", "phase": "creating", "copy_content": {"selected_title": "D"}},
        next_nodes=("draft_gate",),
    )
    graph.aget_state = AsyncMock(
        side_effect=lambda config: {
            "r1": review_snap,
            "r2": running_snap,
            "r3": draft_snap,
        }.get(config["configurable"]["thread_id"], _snapshot({}))
    )
    with (
        patch(_GET_ACTIVE, new_callable=AsyncMock, return_value=_Account("acc1")),
        patch(_IS_POOL_READY, return_value=True),
        patch(
            _DB_LIST,
            new_callable=AsyncMock,
            return_value=([_row("r1"), _row("r2"), _row("r3")], 3),
        ),
    ):
        resp = client.get("/api/inbox")
    inbox = resp.json()["data"]["inbox"]
    gates = sorted(e["gate"] for e in inbox)
    assert gates == ["draft", "review"]
