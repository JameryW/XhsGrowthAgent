"""Tests for GET /api/evaluation/list — workflows with evaluation results.

Covers: filtering out workflows without evaluation_result, account_id filter,
pagination (limit/offset), DB-unavailable fallback, and summary extraction
(selected_title / overall_score / decision).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware import error_handler_middleware
from backend.api.routes.evaluation import router
from backend.db.workflows import WorkflowRow

_DB_LIST = "backend.api.routes.evaluation.db_list"
_IS_POOL_READY = "backend.api.routes.evaluation.is_pool_ready"


def _row(thread_id: str, account_id: str = "acc1", **overrides) -> WorkflowRow:
    base = {
        "thread_id": thread_id,
        "account_id": account_id,
        "status": "completed",
        "phase": "reviewing",
        "label": "",
        "workflow_mode": "trend",
        "updated_at": "2026-07-01T10:00:00Z",
        "created_at": "2026-07-01T09:00:00Z",
    }
    base.update(overrides)
    return WorkflowRow(**base)


def _snapshot(values: dict) -> MagicMock:
    snap = MagicMock()
    snap.values = values
    snap.next = []
    return snap


def _make_graph(state_map: dict[str, dict]) -> MagicMock:
    """graph.aget_state returns the snapshot mapped by thread_id."""

    async def _aget_state(config):
        tid = config["configurable"]["thread_id"]
        return _snapshot(state_map.get(tid, {}))

    graph = MagicMock()
    graph.aget_state = AsyncMock(side_effect=_aget_state)
    graph.store = MagicMock()
    return graph


@pytest.fixture
def app_and_client():
    """Minimal FastAPI app mounting only the evaluation router."""
    graph = _make_graph({})
    app = FastAPI()
    app.include_router(router, prefix="/api/evaluation")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)
    return app, TestClient(app), graph


# ── Filtering & enrichment ────────────────────────────────────────────────


def test_returns_only_workflows_with_evaluation(app_and_client):
    """Workflows without evaluation_result are filtered out; titles + scores carried."""
    app, client, graph = app_and_client
    rows = [
        _row("t1"),
        _row("t2"),
        _row("t3"),  # no evaluation → filtered
    ]
    states = {
        "t1": {
            "session_id": "t1",
            "copy_content": {"selected_title": "爆款标题一"},
            "evaluation_result": {"overall_score": 82.5, "decision": "approved"},
        },
        "t2": {
            "session_id": "t2",
            "copy_content": {"selected_title": "标题二"},
            "evaluation_result": {"overall_score": 60.0, "decision": "needs_revision"},
        },
        "t3": {
            "session_id": "t3",
            "copy_content": {"selected_title": "无评估"},
        },
    }
    graph.aget_state = _make_graph(states).aget_state
    with (
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, AsyncMock(return_value=(rows, 3))),
    ):
        resp = client.get("/api/evaluation/list")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    wf = {w["thread_id"]: w for w in data["workflows"]}
    assert wf["t1"]["selected_title"] == "爆款标题一"
    assert wf["t1"]["overall_score"] == 82.5
    assert wf["t1"]["decision"] == "approved"
    assert wf["t1"]["subject_type"] == "workflow_draft"
    assert wf["t1"]["subject_id"] == "t1"
    assert wf["t2"]["decision"] == "needs_revision"
    assert "t3" not in wf
    assert data["scope"] == "all_accounts"
    assert data["snapshot_id"].startswith("snapshot:")


def test_decision_coerced_from_enum_to_string(app_and_client):
    """ContentStatus (StrEnum) decision serializes to its string value."""
    from backend.state.enums import ContentStatus

    app, client, graph = app_and_client
    rows = [_row("t1")]
    states = {
        "t1": {
            "session_id": "t1",
            "copy_content": {},
            "evaluation_result": {
                "overall_score": 45.0,
                "decision": ContentStatus.REJECTED,
            },
        },
    }
    graph.aget_state = _make_graph(states).aget_state
    with (
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, AsyncMock(return_value=(rows, 1))),
    ):
        resp = client.get("/api/evaluation/list")

    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["workflows"][0]["decision"] == "rejected"


def test_missing_selected_title_returns_empty_string(app_and_client):
    """Workflow with evaluation but no copy_content still lists (title='')."""
    app, client, graph = app_and_client
    rows = [_row("t1")]
    states = {
        "t1": {
            "session_id": "t1",
            "evaluation_result": {"overall_score": 70.0, "decision": "approved"},
        },
    }
    graph.aget_state = _make_graph(states).aget_state
    with (
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, AsyncMock(return_value=(rows, 1))),
    ):
        resp = client.get("/api/evaluation/list")

    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["workflows"][0]["selected_title"] == ""
    assert data["workflows"][0]["overall_score"] == 70.0


# ── account_id filter ─────────────────────────────────────────────────────


def test_account_id_filter_passed_to_db_list(app_and_client):
    """account_id query param forwarded to db_list."""
    app, client, graph = app_and_client
    rows = [_row("t1", account_id="accA")]
    states = {
        "t1": {
            "session_id": "t1",
            "copy_content": {"selected_title": "x"},
            "evaluation_result": {"overall_score": 80.0, "decision": "approved"},
        },
    }
    graph.aget_state = _make_graph(states).aget_state
    with (
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, AsyncMock(return_value=(rows, 1))) as mock_list,
    ):
        resp = client.get("/api/evaluation/list?account_id=accA")

    assert resp.status_code == 200
    mock_list.assert_awaited_once()
    kwargs = mock_list.call_args.kwargs
    assert kwargs["account_id"] == "accA"


# ── Pagination ─────────────────────────────────────────────────────────────


def test_pagination_offset_and_limit(app_and_client):
    """limit/offset slice applies to the filtered (has-evaluation) list."""
    app, client, graph = app_and_client
    rows = [_row(f"t{i}") for i in range(5)]
    states = {
        f"t{i}": {
            "session_id": f"t{i}",
            "copy_content": {"selected_title": f"标题{i}"},
            "evaluation_result": {"overall_score": float(i * 10), "decision": "approved"},
        }
        for i in range(5)
    }
    graph.aget_state = _make_graph(states).aget_state
    with (
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, AsyncMock(return_value=(rows, 5))),
    ):
        resp_page1 = client.get("/api/evaluation/list?limit=2&offset=0")
        resp_page2 = client.get("/api/evaluation/list?limit=2&offset=2")

    p1 = resp_page1.json()["data"]
    p2 = resp_page2.json()["data"]
    assert p1["total"] == 5  # total reflects all filtered workflows
    assert len(p1["workflows"]) == 2
    assert p1["workflows"][0]["thread_id"] == "t0"
    assert p1["workflows"][1]["thread_id"] == "t1"
    assert len(p2["workflows"]) == 2
    assert p2["workflows"][0]["thread_id"] == "t2"
    assert p2["workflows"][1]["thread_id"] == "t3"


def test_offset_beyond_end_returns_empty(app_and_client):
    """offset >= total returns empty workflows list (total still full)."""
    app, client, graph = app_and_client
    rows = [_row("t1")]
    states = {
        "t1": {
            "session_id": "t1",
            "copy_content": {"selected_title": "x"},
            "evaluation_result": {"overall_score": 80.0, "decision": "approved"},
        },
    }
    graph.aget_state = _make_graph(states).aget_state
    with (
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, AsyncMock(return_value=(rows, 1))),
    ):
        resp = client.get("/api/evaluation/list?limit=20&offset=10")

    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["workflows"] == []


# ── DB unavailable fallback ──────────────────────────────────────────────


def test_db_not_ready_returns_empty(app_and_client):
    """When DB pool is unavailable, return empty list (no graph reads)."""
    app, client, graph = app_and_client
    with patch(_IS_POOL_READY, return_value=False):
        resp = client.get("/api/evaluation/list")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["workflows"] == []
    assert data["total"] == 0
    graph.aget_state.assert_not_awaited()


# ── Resilience ─────────────────────────────────────────────────────────────


def test_aget_state_failure_skips_thread(app_and_client):
    """If aget_state raises for one thread, that thread is skipped (not crash)."""
    app, client, graph = app_and_client
    rows = [_row("t1"), _row("t2")]

    async def _aget_state(config):
        tid = config["configurable"]["thread_id"]
        if tid == "t2":
            raise RuntimeError("checkpoint read failed")
        return _snapshot(
            {
                "session_id": "t1",
                "copy_content": {"selected_title": "ok"},
                "evaluation_result": {"overall_score": 80.0, "decision": "approved"},
            }
        )

    graph.aget_state = AsyncMock(side_effect=_aget_state)
    with (
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, AsyncMock(return_value=(rows, 2))),
    ):
        resp = client.get("/api/evaluation/list")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["workflows"][0]["thread_id"] == "t1"


def test_checkpoint_lost_state_skipped(app_and_client):
    """Workflow with no session_id in checkpoint (lost state) is skipped."""
    app, client, graph = app_and_client
    rows = [_row("t1"), _row("t2")]
    states = {
        "t1": {},  # no session_id → _get_state_values returns {}
        "t2": {
            "session_id": "t2",
            "copy_content": {"selected_title": "valid"},
            "evaluation_result": {"overall_score": 90.0, "decision": "approved"},
        },
    }
    graph.aget_state = _make_graph(states).aget_state
    with (
        patch(_IS_POOL_READY, return_value=True),
        patch(_DB_LIST, AsyncMock(return_value=(rows, 2))),
    ):
        resp = client.get("/api/evaluation/list")

    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["workflows"][0]["thread_id"] == "t2"
