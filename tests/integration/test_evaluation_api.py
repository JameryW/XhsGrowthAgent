"""Integration tests for the evaluation API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.agents.evaluator import EvaluatorAgent
from backend.api.app import app
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
    app.state.graph = mock_graph
    yield TestClient(app)
    if hasattr(app.state, "graph"):
        delattr(app.state, "graph")


class TestEvaluationResultRoute:
    def test_get_result_returns_evaluation(self, client, mock_graph):
        mock_graph.aget_state.return_value.values["evaluation_result"] = {
            "overall_score": 82.0,
            "decision": ContentStatus.APPROVED,
        }
        r = client.get("/api/evaluation/result/t1")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["has_evaluation"] is True
        assert data["evaluation_result"]["decision"] == "approved"

    def test_get_result_no_evaluation(self, client, mock_graph):
        mock_graph.aget_state.return_value.values.pop("evaluation_result", None)
        r = client.get("/api/evaluation/result/t1")
        assert r.status_code == 200
        assert r.json()["data"]["has_evaluation"] is False

    def test_get_result_not_found(self, client, mock_graph):
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
    def test_run_returns_evaluation_and_persists(self, client, mock_graph):
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
        assert data["status"] == "evaluated"
        assert data["evaluation_result"]["decision"] == "approved"
        mock_graph.aupdate_state.assert_called_once()

    def test_run_no_content_raises(self, client, mock_graph):
        mock_graph.aget_state.return_value.values = {
            "session_id": "t1",
            "phase": WorkflowPhase.SCOUTING,
        }
        r = client.post("/api/evaluation/run/t1")
        assert r.status_code == 400

    def test_run_not_found(self, client, mock_graph):
        empty = MagicMock()
        empty.values = {}
        empty.next = []
        mock_graph.aget_state.return_value = empty
        r = client.post("/api/evaluation/run/t1")
        assert r.status_code == 404
