"""Integration tests for API routes.

Tests all endpoints with unified response format verification.
Uses FastAPI TestClient and mocks graph execution.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.state.enums import WorkflowPhase, ContentStatus
from backend.api.responses import ApiResponse


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_graph():
    """Mock compiled graph for testing."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value={"phase": "completed", "session_id": "test_session"})
    graph.aget_state = AsyncMock()
    return graph


@pytest.fixture
def client(mock_graph):
    """Test client with mocked graph."""
    # Set the graph directly on app.state before creating client
    app.state.graph = mock_graph
    yield TestClient(app)
    # Clean up after test
    if hasattr(app.state, "graph"):
        delattr(app.state, "graph")


@pytest.fixture
def mock_state_values():
    """Mock state values for workflow tests."""
    return {
        "phase": WorkflowPhase.SCOUTING.value,
        "session_id": "xhs_test_abc123",
        "account_id": "test_account",
        "current_agent": "orchestrator",
        "created_at": "2026-01-01T00:00:00Z",
    }


# ── Health Check ────────────────────────────────────────────────────────────

class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_returns_success(self, client):
        """Health endpoint returns unified success response."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert data["data"]["status"] == "ok"
        assert data["data"]["version"] == "0.1.0"
        assert "timestamp" in data

    def test_health_no_error_field(self, client):
        """Success response has no error field."""
        response = client.get("/health")
        data = response.json()

        assert data["error"] is None


# ── Workflow Routes ─────────────────────────────────────────────────────────

class TestWorkflowRoutes:
    """Tests for workflow API routes."""

    def test_start_workflow_success(self, client, mock_graph):
        """Start workflow returns unified success response."""
        mock_graph.ainvoke.return_value = {"phase": "scouting"}

        response = client.post(
            "/api/workflow/start",
            json={"account_id": "test_account", "phase": "scouting"}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert "thread_id" in data["data"]
        assert data["data"]["status"] == "running"
        assert data["data"]["phase"] == "scouting"
        assert data["error"] is None

    def test_start_workflow_default_phase(self, client, mock_graph):
        """Start workflow with default phase."""
        mock_graph.ainvoke.return_value = {"phase": "scouting"}

        response = client.post(
            "/api/workflow/start",
            json={"account_id": "test_account"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["phase"] == "scouting"

    def test_start_workflow_invalid_account(self, client):
        """Start workflow with empty account_id returns error."""
        response = client.post(
            "/api/workflow/start",
            json={"account_id": "", "phase": "scouting"}
        )

        assert response.status_code == 400
        data = response.json()

        # Verify unified error response format
        assert data["success"] is False
        assert data["error"] is not None
        assert data["error"]["code"] == "ERROR_VALIDATION"
        assert "account_id" in data["error"]["message"]

    def test_get_workflow_status_success(self, client, mock_graph, mock_state_values):
        """Get workflow status returns unified success response."""
        mock_state = MagicMock()
        mock_state.values = mock_state_values
        mock_state.next = []
        mock_state.created_at = "2026-01-01T00:00:00Z"
        mock_graph.aget_state.return_value = mock_state

        response = client.get("/api/workflow/status/xhs_test_abc123")

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert data["data"]["thread_id"] == "xhs_test_abc123"
        assert "phase" in data["data"]
        assert "current_agent" in data["data"]
        assert "progress_percent" in data["data"]
        assert data["error"] is None

    def test_get_workflow_status_not_found(self, client, mock_graph):
        """Get workflow status for non-existent workflow returns error."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_state.next = []
        mock_graph.aget_state.return_value = mock_state

        response = client.get("/api/workflow/status/nonexistent_thread")

        assert response.status_code == 404
        data = response.json()

        # Verify unified error response format
        assert data["success"] is False
        assert data["error"] is not None
        assert data["error"]["code"] == "ERROR_WORKFLOW_NOT_FOUND"

    def test_pause_workflow_success(self, client, mock_graph, mock_state_values):
        """Pause workflow returns unified success response."""
        mock_state = MagicMock()
        mock_state.values = mock_state_values
        mock_graph.aget_state.return_value = mock_state

        response = client.post("/api/workflow/pause/xhs_test_abc123")

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert data["data"]["thread_id"] == "xhs_test_abc123"
        assert data["data"]["status"] == "paused"
        assert data["error"] is None

    def test_pause_workflow_not_found(self, client, mock_graph):
        """Pause non-existent workflow returns error."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_graph.aget_state.return_value = mock_state

        response = client.post("/api/workflow/pause/nonexistent_thread")

        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "ERROR_WORKFLOW_NOT_FOUND"

    def test_resume_workflow_success(self, client, mock_graph, mock_state_values):
        """Resume workflow with pending steps returns running status."""
        mock_state = MagicMock()
        mock_state.values = mock_state_values
        mock_state.next = ["trend_scout"]
        mock_graph.aget_state.return_value = mock_state
        mock_graph.ainvoke.return_value = {"phase": "scouting"}

        response = client.post("/api/workflow/resume/xhs_test_abc123")

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert data["data"]["status"] == "running"
        assert data["error"] is None

    def test_resume_workflow_completed(self, client, mock_graph, mock_state_values):
        """Resume completed workflow returns completed status."""
        mock_state = MagicMock()
        mock_state.values = mock_state_values
        mock_state.next = []  # No pending steps
        mock_graph.aget_state.return_value = mock_state

        response = client.post("/api/workflow/resume/xhs_test_abc123")

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["data"]["status"] == "completed"

    def test_resume_workflow_not_found(self, client, mock_graph):
        """Resume non-existent workflow returns error."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_graph.aget_state.return_value = mock_state

        response = client.post("/api/workflow/resume/nonexistent_thread")

        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "ERROR_WORKFLOW_NOT_FOUND"


# ── Review Routes ────────────────────────────────────────────────────────────

class TestReviewRoutes:
    """Tests for review API routes."""

    def test_get_pending_review_success(self, client, mock_graph, mock_state_values):
        """Get pending review when awaiting returns success."""
        mock_state = MagicMock()
        mock_state.values = {
            **mock_state_values,
            "content_plan": {"selected_topic": "test"},
            "copy_content": {"title": "Test Title"},
            "visual_plan": {"layout": "grid"},
        }
        mock_state.next = ["review_gate"]  # At review gate
        mock_graph.aget_state.return_value = mock_state

        response = client.get("/api/review/pending/xhs_test_abc123")

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert data["data"]["status"] == "awaiting_review"
        assert "content_plan" in data["data"]
        assert "copy_content" in data["data"]
        assert "visual_plan" in data["data"]
        assert data["error"] is None

    def test_get_pending_review_not_pending(self, client, mock_graph, mock_state_values):
        """Get pending review when not awaiting returns error."""
        mock_state = MagicMock()
        mock_state.values = mock_state_values
        mock_state.next = ["trend_scout"]  # Not at review gate
        mock_graph.aget_state.return_value = mock_state

        response = client.get("/api/review/pending/xhs_test_abc123")

        assert response.status_code == 400
        data = response.json()

        # Verify unified error response format
        assert data["success"] is False
        assert data["error"] is not None
        assert data["error"]["code"] == "ERROR_REVIEW_NOT_PENDING"

    def test_submit_review_success(self, client, mock_graph, mock_state_values):
        """Submit review decision returns success."""
        mock_state = MagicMock()
        mock_state.values = mock_state_values
        mock_state.next = ["review_gate"]
        mock_graph.aget_state.return_value = mock_state
        mock_graph.ainvoke.return_value = {"phase": "publishing"}

        response = client.post(
            "/api/review/submit/xhs_test_abc123",
            json={"decision": "approved", "comments": "Looks good!", "revisions": []}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert data["data"]["thread_id"] == "xhs_test_abc123"
        assert data["data"]["status"] == "resumed"
        assert data["data"]["decision"] == "approved"
        assert data["error"] is None

    def test_submit_review_with_revisions(self, client, mock_graph, mock_state_values):
        """Submit review with needs_revision decision."""
        mock_state = MagicMock()
        mock_state.values = mock_state_values
        mock_state.next = ["review_gate"]
        mock_graph.aget_state.return_value = mock_state
        mock_graph.ainvoke.return_value = {"phase": "creating"}

        response = client.post(
            "/api/review/submit/xhs_test_abc123",
            json={
                "decision": "needs_revision",
                "comments": "Please revise the title",
                "revisions": ["Make title more engaging"]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["decision"] == "needs_revision"

    def test_submit_review_not_pending(self, client, mock_graph, mock_state_values):
        """Submit review when not pending returns error."""
        mock_state = MagicMock()
        mock_state.values = mock_state_values
        mock_state.next = ["trend_scout"]  # Not at review gate
        mock_graph.aget_state.return_value = mock_state

        response = client.post(
            "/api/review/submit/xhs_test_abc123",
            json={"decision": "approved", "comments": "", "revisions": []}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "ERROR_REVIEW_NOT_PENDING"


# ── Analytics Routes ──────────────────────────────────────────────────────────

class TestAnalyticsRoutes:
    """Tests for analytics API routes."""

    def test_get_costs_success(self, client):
        """Get costs returns unified success response."""
        response = client.get("/api/analytics/costs")

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert "total_cost_usd" in data["data"]
        assert "today_cost_usd" in data["data"]
        assert "circuit_open" in data["data"]
        assert data["error"] is None

    def test_get_performance_success(self, client):
        """Get performance returns unified success response."""
        response = client.get("/api/analytics/performance/test_account")

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert data["data"]["account_id"] == "test_account"
        assert "posts" in data["data"]
        assert data["error"] is None

    def test_get_performance_with_limit(self, client):
        """Get performance with custom limit."""
        response = client.get("/api/analytics/performance/test_account?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_get_growth_report_success(self, client):
        """Get growth report returns unified success response."""
        response = client.get("/api/analytics/report/test_account")

        assert response.status_code == 200
        data = response.json()

        # Verify unified response format
        assert data["success"] is True
        assert data["data"] is not None
        assert data["data"]["account_id"] == "test_account"
        assert "period" in data["data"]
        assert data["error"] is None

    def test_get_growth_report_with_period(self, client):
        """Get growth report with custom period."""
        response = client.get("/api/analytics/report/test_account?period=daily")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["period"] == "daily"


# ── Unified Response Format Verification ──────────────────────────────────────

class TestUnifiedResponseFormat:
    """Verify all endpoints use unified response format."""

    def test_all_success_responses_have_success_true(self, client, mock_graph, mock_state_values):
        """All successful responses have success=True."""
        endpoints = [
            ("/health", "get"),
            ("/api/analytics/costs", "get"),
            ("/api/analytics/performance/test_account", "get"),
            ("/api/analytics/report/test_account", "get"),
        ]

        for endpoint, method in endpoints:
            response = getattr(client, method)(endpoint)
            data = response.json()
            assert data["success"] is True, f"{endpoint} should have success=True"

    def test_all_success_responses_have_data_field(self, client):
        """All successful responses have data field."""
        endpoints = [
            "/health",
            "/api/analytics/costs",
            "/api/analytics/performance/test_account",
            "/api/analytics/report/test_account",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            data = response.json()
            assert "data" in data, f"{endpoint} should have data field"
            assert data["data"] is not None, f"{endpoint} data should not be None"

    def test_all_success_responses_have_timestamp(self, client):
        """All responses have timestamp field."""
        endpoints = [
            "/health",
            "/api/analytics/costs",
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            data = response.json()
            assert "timestamp" in data, f"{endpoint} should have timestamp"

    def test_all_error_responses_have_success_false(self, client, mock_graph):
        """All error responses have success=False."""
        # Mock empty state to trigger not found error
        mock_state = MagicMock()
        mock_state.values = {}
        mock_graph.aget_state.return_value = mock_state

        error_endpoints = [
            ("/api/workflow/status/nonexistent", "get"),
            ("/api/workflow/pause/nonexistent", "post"),
            ("/api/workflow/resume/nonexistent", "post"),
        ]

        for endpoint, method in error_endpoints:
            response = getattr(client, method)(endpoint)
            data = response.json()
            assert data["success"] is False, f"{endpoint} error should have success=False"

    def test_all_error_responses_have_error_field(self, client, mock_graph):
        """All error responses have error field."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_graph.aget_state.return_value = mock_state

        error_endpoints = [
            ("/api/workflow/status/nonexistent", "get"),
            ("/api/workflow/pause/nonexistent", "post"),
        ]

        for endpoint, method in error_endpoints:
            response = getattr(client, method)(endpoint)
            data = response.json()
            assert "error" in data, f"{endpoint} should have error field"
            assert data["error"] is not None, f"{endpoint} error should not be None"

    def test_error_responses_have_code_and_message(self, client, mock_graph):
        """Error responses have code and message in error field."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_graph.aget_state.return_value = mock_state

        response = client.get("/api/workflow/status/nonexistent")
        data = response.json()

        assert "code" in data["error"]
        assert "message" in data["error"]
        assert data["error"]["code"] == "ERROR_WORKFLOW_NOT_FOUND"