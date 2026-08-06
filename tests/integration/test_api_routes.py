"""Integration tests for API routes.

Tests all endpoints with unified response format verification.
Uses FastAPI TestClient and mocks graph execution.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.deps import get_current_user
from backend.db.accounts import AccountRow
from backend.db.workflows import WorkflowRow
from backend.state.enums import WorkflowPhase

TEST_USER_ID = "user-test"


@contextmanager
def _cm(obj: Any):
    """Wrap a plain object as a context manager (mimics pdfplumber.open)."""
    yield obj


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_graph():
    """Mock compiled graph for testing."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value={"phase": "completed", "session_id": "test_session"})
    # aget_state returns a StateSnapshot-like object with sync .values/.next/.tasks
    mock_snapshot = MagicMock()
    mock_snapshot.values = {"phase": "completed", "session_id": "test_session"}
    mock_snapshot.next = []
    mock_snapshot.tasks = []
    graph.aget_state = AsyncMock(return_value=mock_snapshot)
    graph.aupdate_state = AsyncMock()
    return graph


@pytest.fixture
def client(mock_graph):
    """Test client with mocked graph and an authenticated user."""
    # Set the graph directly on app.state before creating client
    app.state.graph = mock_graph

    async def _user():
        return {"id": TEST_USER_ID, "username": "tester"}

    app.dependency_overrides[get_current_user] = _user

    # Private routes resolve/verify account ownership via account_scope, which
    # imported the DB lookups directly — patch them there (no DB in tests).
    owned = AccountRow(
        id="test_account",
        name="test_account",
        is_active=True,
        owner_user_id=TEST_USER_ID,
    )
    with (
        patch("backend.api.account_scope.get_account", AsyncMock(return_value=owned)),
        patch(
            "backend.api.account_scope.get_active_account",
            AsyncMock(return_value=owned),
        ),
        patch(
            "backend.api.account_scope.list_accounts",
            AsyncMock(return_value=[owned]),
        ),
        # assert_thread_owned looks up the workflow row via a function-level
        # import — patch at the source module (no DB in tests). Returning an
        # owned row for any thread keeps "not found" tests working: they still
        # 404 on empty graph state below.
        patch(
            "backend.db.workflows.get_workflow",
            AsyncMock(return_value=WorkflowRow(thread_id="t", account_id="test_account")),
        ),
    ):
        yield TestClient(app)

    # Clean up after test
    app.dependency_overrides.pop(get_current_user, None)
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
            "/api/workflow/start", json={"account_id": "test_account", "phase": "scouting"}
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

        response = client.post("/api/workflow/start", json={"account_id": "test_account"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["phase"] == "scouting"

    def test_start_workflow_invalid_account(self, client):
        """Start workflow with empty account_id returns error."""
        from backend.api.errors import ValidationError

        # Empty account_id is rejected during account resolution with a
        # field-naming validation error; the endpoint must surface it as a
        # unified 400 response.
        with patch(
            "backend.api.routes.workflow.resolve_required_account_id",
            AsyncMock(side_effect=ValidationError("account_id", "account_id is required")),
        ):
            response = client.post(
                "/api/workflow/start", json={"account_id": "", "phase": "scouting"}
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
        # Owning account is required for multi-account UI (dashboard banner).
        assert data["data"].get("account_id") == mock_state_values.get("account_id", "test_account")
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
        """Resume completed workflow restarts it and returns running status."""
        mock_state = MagicMock()
        mock_state.values = {**mock_state_values, "phase": WorkflowPhase.COMPLETED.value}
        mock_state.next = []  # No pending steps
        mock_graph.aget_state.return_value = mock_state

        response = client.post("/api/workflow/resume/xhs_test_abc123")

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        # Completed workflows are restartable via resume, so status becomes "running"
        assert data["data"]["status"] == "running"

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

    def test_cancel_workflow_success(self, client, mock_graph, mock_state_values):
        """Cancel running workflow returns success."""
        mock_state = MagicMock()
        mock_state.values = mock_state_values
        mock_graph.aget_state.return_value = mock_state

        response = client.post("/api/workflow/cancel/xhs_test_abc123")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "cancelled"

    def test_cancel_workflow_not_found(self, client, mock_graph):
        """Cancel non-existent workflow returns error."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_graph.aget_state.return_value = mock_state

        response = client.post("/api/workflow/cancel/nonexistent_thread")
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False

    def test_list_workflows_returns_success(self, client):
        """List workflows returns unified success response."""
        response = client.get("/api/workflow/list")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "workflows" in data["data"]
        assert "total" in data["data"]

    def test_list_workflows_with_filters(self, client):
        """List workflows with query parameters."""
        response = client.get("/api/workflow/list?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_delete_workflow_not_found(self, client, mock_graph):
        """Delete non-existent workflow returns error."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_graph.aget_state.return_value = mock_state
        response = client.delete("/api/workflow/nonexistent_thread")
        assert response.status_code == 404

    def test_delete_running_workflow_blocked(self, client, mock_graph):
        """Delete a running workflow returns validation error."""
        import backend.api.routes._runner as _runner
        from backend.db import pool as db_pool

        mock_state = MagicMock()
        mock_state.values = {"session_id": "xhs_test_abc123"}
        mock_graph.aget_state.return_value = mock_state

        # Simulate a running background task
        mock_task = MagicMock()
        mock_task.done.return_value = False
        _runner._background_tasks["xhs_test_abc123"] = mock_task

        # DB pool may not be ready in test — mock db_get if needed
        db_pool.get if hasattr(db_pool, "get") else None

        try:
            # Ensure the workflow exists in DB (or skip DB check)
            if not db_pool.is_pool_ready():
                # Make history file so delete_workflow passes the existence check
                import json
                from pathlib import Path

                history_dir = Path(".xhs") / "history"
                history_dir.mkdir(parents=True, exist_ok=True)
                history_file = history_dir / "xhs_test_abc123.json"
                history_file.write_text(json.dumps({"phase": "scouting"}))

            response = client.delete("/api/workflow/xhs_test_abc123")
            # Should get 400 (blocked) not 404 (not found)
            assert response.status_code == 400
        finally:
            _runner._background_tasks.pop("xhs_test_abc123", None)
            # Clean up history file
            history_file = Path(".xhs") / "history" / "xhs_test_abc123.json"
            if history_file.exists():
                history_file.unlink()

    def test_brief_extract_no_file_returns_error(self, client):
        """Brief extract without file returns validation error."""
        response = client.post("/api/workflow/brief/extract")
        assert response.status_code == 400

    def test_trigger_analytics_workflow_not_found(self, client, mock_graph):
        """Trigger analytics for non-existent workflow returns error."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_graph.aget_state.return_value = mock_state

        response = client.post("/api/workflow/trigger-analytics/nonexistent_thread")
        assert response.status_code == 404

    def test_history_workflow_not_found(self, client, mock_graph):
        """History for non-existent workflow returns error."""
        mock_state = MagicMock()
        mock_state.values = {}
        mock_graph.aget_state.return_value = mock_state

        response = client.get("/api/workflow/history/nonexistent_thread")
        assert response.status_code == 404


# ── Brief PDF LLM cost tracking ──────────────────────────────────────────────


class TestBriefPdfCostTracking:
    """Upload path merges the BRIEF_ANALYSIS token cost into performance_log.

    The _extract_pdf_with_llm multimodal call is the last route-local LLM
    invocation invisible to /analytics/costs. The upload path (stateful) merges
    the captured llm_perf_entry into aupdate_state so the cost reader sees it;
    the extract path (stateless) drops the entry.
    """

    def test_upload_merges_llm_cost_entry_into_performance_log(self, client, mock_graph):
        """Upload with PDF + LLM usage → aupdate_state values carry perf entry.

        Forces the LLM fallback (pdfplumber yields no text) and mocks get_model
        to return usage_metadata so llm_perf_entry builds a real cost entry.
        """
        # get_model is imported function-locally inside _extract_pdf_with_llm;
        # the conftest autouse fixture patches backend.models.router.get_model,
        # which that import resolves to — override it here with a usage-bearing
        # response so a real perf entry is constructed end-to-end.
        llm_response = MagicMock()
        llm_response.content = "提取出的PDF文字内容"
        llm_response.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
        llm_response.response_metadata = {}

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=llm_response)

        # pdfplumber returns no text → forces the multimodal LLM fallback path.
        empty_page = MagicMock()
        empty_page.extract_text.return_value = ""
        empty_pdf = MagicMock()
        empty_pdf.pages = [empty_page]

        # aget_state.next == [] (from mock_graph fixture) → no resume task.
        with (
            patch("backend.models.router.get_model", lambda *a, **kw: mock_model),
            patch("pdfplumber.open", return_value=_cm(empty_pdf)),
        ):
            response = client.post(
                "/api/workflow/brief/upload/xhs_test_abc123",
                files={"file": ("brief.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )

        assert response.status_code == 200
        mock_graph.aupdate_state.assert_awaited_once()
        _, kwargs = mock_graph.aupdate_state.call_args
        values = kwargs["values"]
        assert "performance_log" in values
        entry = values["performance_log"][0]
        assert entry["kind"] == "llm"
        assert entry["agent"] == "brief_pdf_extract"
        assert entry["model"] == "astron-code-latest"
        assert entry["cost_usd"] > 0
        assert entry["input_tokens"] == 100
        assert entry["output_tokens"] == 50
        # brief_content still written alongside the perf entry.
        assert values["brief_content"]["raw_text"] == "提取出的PDF文字内容"

    def test_upload_capture_failure_does_not_break_extraction(self, client, mock_graph):
        """llm_perf_entry raising → extraction still returns text, no perf entry."""
        llm_response = MagicMock()
        llm_response.content = "提取出的PDF文字内容"
        llm_response.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=llm_response)

        empty_page = MagicMock()
        empty_page.extract_text.return_value = ""
        empty_pdf = MagicMock()
        empty_pdf.pages = [empty_page]

        with (
            patch("backend.models.router.get_model", lambda *a, **kw: mock_model),
            patch("pdfplumber.open", return_value=_cm(empty_pdf)),
            patch(
                "backend.agents.nodes._base.llm_perf_entry",
                side_effect=RuntimeError("capture boom"),
            ),
        ):
            response = client.post(
                "/api/workflow/brief/upload/xhs_test_abc123",
                files={"file": ("brief.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )

        assert response.status_code == 200
        mock_graph.aupdate_state.assert_awaited_once()
        _, kwargs = mock_graph.aupdate_state.call_args
        # No perf entry merged (capture failed) but brief_content still written.
        assert "performance_log" not in kwargs["values"]
        assert kwargs["values"]["brief_content"]["raw_text"] == "提取出的PDF文字内容"

    def test_upload_pdfplumber_success_skips_performance_log(self, client, mock_graph):
        """pdfplumber extracts text → no LLM call → no perf entry in update."""
        page = MagicMock()
        page.extract_text.return_value = "pdfplumber提取的文字"
        pdf = MagicMock()
        pdf.pages = [page]

        with patch("pdfplumber.open", return_value=_cm(pdf)):
            response = client.post(
                "/api/workflow/brief/upload/xhs_test_abc123",
                files={"file": ("brief.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )

        assert response.status_code == 200
        mock_graph.aupdate_state.assert_awaited_once()
        _, kwargs = mock_graph.aupdate_state.call_args
        assert "performance_log" not in kwargs["values"]
        assert kwargs["values"]["brief_content"]["raw_text"] == "pdfplumber提取的文字"

    def test_extract_stateless_does_not_write_perf_entry(self, client, mock_graph):
        """Extract path has no thread_id → no aupdate_state perf write."""
        # Provide a perf entry via the helper to prove the extract path drops it
        # (no graph interaction for the perf entry regardless of capture).
        with patch(
            "backend.api.routes.workflow._extract_pdf_text",
            AsyncMock(return_value=("预览文字", {"kind": "llm", "agent": "brief_pdf_extract"})),
        ):
            response = client.post(
                "/api/workflow/brief/extract",
                files={"file": ("brief.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )

        assert response.status_code == 200
        assert response.json()["data"]["brief_text"] == "预览文字"
        # Stateless: graph.aupdate_state never called for the perf entry.
        mock_graph.aupdate_state.assert_not_awaited()

    def test_upload_text_file_skips_performance_log(self, client, mock_graph):
        """Non-PDF upload never invokes the LLM → no perf entry, no crash.

        Regression guard: perf_entry is only assigned on the PDF branch; the
        text path must not raise UnboundLocalError when checking the entry.
        """
        response = client.post(
            "/api/workflow/brief/upload/xhs_test_abc123",
            files={"file": ("brief.txt", b"plain text brief content", "text/plain")},
        )

        assert response.status_code == 200
        mock_graph.aupdate_state.assert_awaited_once()
        _, kwargs = mock_graph.aupdate_state.call_args
        # No LLM call on the text path → no performance_log key in the update.
        assert "performance_log" not in kwargs["values"]
        assert kwargs["values"]["brief_content"]["raw_text"] == "plain text brief content"
        assert kwargs["values"]["brief_content"]["source_type"] == "text"


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
            json={"decision": "approved", "comments": "Looks good!", "revisions": []},
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
                "revisions": ["Make title more engaging"],
            },
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
            json={"decision": "approved", "comments": "", "revisions": []},
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
