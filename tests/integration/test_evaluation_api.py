"""Integration tests for the evaluation API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.agents.evaluator import EvaluatorAgent
from backend.api.app import app
from backend.api.deps import get_current_user
from backend.state.enums import ContentStatus, WorkflowPhase


@pytest.fixture
def mock_graph():
    graph = MagicMock()
    snapshot = MagicMock()
    snapshot.values = {
        "session_id": "t1",
        "phase": WorkflowPhase.REVIEWING,
        "copy_content": {"selected_title": "t", "body_text": "b"},
        "visual_plan": {"cover_prompt": "c"},
    }
    snapshot.next = []
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    graph.store = MagicMock()
    return graph


@pytest.fixture
def client(mock_graph):
    async def _user():
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    app.state.graph = mock_graph
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    if hasattr(app.state, "graph"):
        delattr(app.state, "graph")


@pytest.fixture
def owned_thread():
    """Patch workflow/account lookups so thread t1 belongs to user-test."""
    account = MagicMock()
    account.id = "acc-1"
    account.owner_user_id = "user-test"
    row = MagicMock()
    row.account_id = "acc-1"
    with (
        patch("backend.db.workflows.get_workflow", AsyncMock(return_value=row)) as mock_get,
        patch("backend.api.account_scope.get_account", AsyncMock(return_value=account)),
    ):
        yield mock_get


class TestEvaluationResultRoute:
    def test_get_result_returns_evaluation(self, client, mock_graph, owned_thread):
        mock_graph.aget_state.return_value.values["evaluation_result"] = {
            "overall_score": 82.0,
            "decision": ContentStatus.APPROVED,
        }
        r = client.get("/api/evaluation/result/t1")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["has_evaluation"] is True
        assert data["evaluation_result"]["decision"] == "approved"

    def test_get_result_no_evaluation(self, client, mock_graph, owned_thread):
        mock_graph.aget_state.return_value.values.pop("evaluation_result", None)
        r = client.get("/api/evaluation/result/t1")
        assert r.status_code == 200
        assert r.json()["data"]["has_evaluation"] is False

    def test_get_result_not_found(self, client, mock_graph, owned_thread):
        owned_thread.return_value = None
        empty = MagicMock()
        empty.values = {}
        empty.next = []
        mock_graph.aget_state.return_value = empty
        r = client.get("/api/evaluation/result/t1")
        assert r.status_code == 404

    def test_get_result_empty_thread_id(self, client):
        r = client.get("/api/evaluation/result/%20")
        assert r.status_code in (400, 404, 422)


class TestRunEvaluationRoute:
    def test_run_returns_evaluation_and_persists(self, client, mock_graph, owned_thread):
        mock_response = MagicMock()
        mock_response.content = (
            '{"overall_score": 80, "dimensions": ['
            '{"dimension":"copywriting","score":80,"rationale":"r","issues":[],"is_blocking":false}'
            '], "decision": "approved", "revision_hints": [], "bias_warning": "", "summary": "ok"}'
        )
        with patch.object(EvaluatorAgent, "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            r = client.post("/api/evaluation/run/t1")

        assert r.status_code == 200
        data = r.json()["data"]
        # Coverage below the historical safety threshold is explicitly
        # scoreless; workflow evaluation uses the same honest contract rather
        # than turning one returned dimension into a pass.
        assert data["status"] == "partial"
        assert data["evaluation_result"]["decision"] is None
        assert data["evaluation_result"]["overall_score"] is None
        mock_graph.aupdate_state.assert_called_once()

    def test_run_no_content_raises(self, client, mock_graph, owned_thread):
        mock_graph.aget_state.return_value.values = {
            "session_id": "t1",
            "phase": WorkflowPhase.SCOUTING,
        }
        r = client.post("/api/evaluation/run/t1")
        assert r.status_code == 400

    def test_run_not_found(self, client, mock_graph, owned_thread):
        owned_thread.return_value = None
        empty = MagicMock()
        empty.values = {}
        empty.next = []
        mock_graph.aget_state.return_value = empty
        r = client.post("/api/evaluation/run/t1")
        assert r.status_code == 404

    def test_run_merges_performance_log_into_state(self, client, mock_graph, owned_thread):
        """Manual eval must merge result["performance_log"] (LLM cost) into the
        thread checkpoint so /analytics/costs can see the spend. Mirrors PR#493
        upload-brief pattern; the _append_list reducer appends the entries."""
        perf_entry = {
            "kind": "llm",
            "node": "evaluator",
            "cost_usd": 0.05,
            "timestamp": "2026-08-06T00:00:00Z",
        }
        eval_result = {
            "overall_score": 80.0,
            "decision": "approved",
            "dimensions": [],
            "status": "ready",
            "revision_hints": [],
            "bias_warning": "",
            "summary": "ok",
        }
        with patch.object(
            EvaluatorAgent,
            "__call__",
            new=AsyncMock(
                return_value={
                    "evaluation_result": eval_result,
                    "performance_log": [perf_entry],
                }
            ),
        ):
            r = client.post("/api/evaluation/run/t1")

        assert r.status_code == 200
        mock_graph.aupdate_state.assert_called_once()
        _config, values = mock_graph.aupdate_state.call_args.args
        assert values["evaluation_result"] == eval_result
        assert values["performance_log"] == [perf_entry]

    def test_run_skips_performance_log_when_empty(self, client, mock_graph, owned_thread):
        """Empty/missing performance_log must not produce a spurious empty merge
        (match #493's `if perf_entry is not None` guard)."""
        eval_result = {
            "overall_score": 80.0,
            "decision": "approved",
            "dimensions": [],
            "status": "ready",
            "revision_hints": [],
            "bias_warning": "",
            "summary": "ok",
        }
        with patch.object(
            EvaluatorAgent,
            "__call__",
            new=AsyncMock(return_value={"evaluation_result": eval_result}),
        ):
            r = client.post("/api/evaluation/run/t1")

        assert r.status_code == 200
        mock_graph.aupdate_state.assert_called_once()
        _config, values = mock_graph.aupdate_state.call_args.args
        assert values["evaluation_result"] == eval_result
        assert "performance_log" not in values


class TestEvaluationEpochsRoute:
    """GET /evaluation/epochs — prompt epoch evolution history."""

    def test_epochs_db_not_ready_returns_empty(self, client):
        # The route does `from backend.db.pool import is_pool_ready` inside the
        # function, so patch the source module.
        with patch("backend.db.pool.is_pool_ready", return_value=False):
            r = client.get("/api/evaluation/epochs")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["db_ready"] is False
        assert data["epochs"] == []

    def test_epochs_returns_history_with_active_marked(self, client):
        from backend.db.evaluator_config import PromptEpoch

        epochs = [
            PromptEpoch(
                2, "strict", "auto-evolve from lenient panel", True, "2026-07-01T10:00:00Z"
            ),
            PromptEpoch(1, "standard", "epoch-1 default", False, "2026-07-01T09:00:00Z"),
        ]
        with (
            patch("backend.db.pool.is_pool_ready", return_value=True),
            patch(
                "backend.db.evaluator_config.list_epochs",
                AsyncMock(return_value=epochs),
            ),
        ):
            r = client.get("/api/evaluation/epochs")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["db_ready"] is True
        assert len(data["epochs"]) == 2
        assert data["epochs"][0]["epoch_id"] == 2
        assert data["epochs"][0]["active"] is True
        assert data["epochs"][0]["bias_severity"] == "strict"
        assert data["epochs"][1]["active"] is False

    def test_epochs_empty_when_no_history(self, client):
        with (
            patch("backend.db.pool.is_pool_ready", return_value=True),
            patch("backend.db.evaluator_config.list_epochs", AsyncMock(return_value=[])),
        ):
            r = client.get("/api/evaluation/epochs")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["db_ready"] is True
        assert data["epochs"] == []
