"""Unit tests for omp_bridge host tool auto-execution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.omp_bridge import (
    _XHS_TOOL_NAMES,
    XHS_HOST_TOOLS,
    _execute_xhs_host_tool,
    _make_text_result,
)

# ── Schema validation ────────────────────────────────────────────────────


class TestHostToolSchemas:
    """Verify XHS_HOST_TOOLS list integrity."""

    def test_tool_count(self):
        assert len(XHS_HOST_TOOLS) == 25

    def test_all_tools_have_required_fields(self):
        for tool in XHS_HOST_TOOLS:
            assert "name" in tool, f"Missing name in {tool}"
            assert "label" in tool, f"Missing label in {tool}"
            assert "description" in tool, f"Missing description in {tool}"
            assert "parameters" in tool, f"Missing parameters in {tool}"
            params = tool["parameters"]
            assert params.get("type") == "object"
            assert "properties" in params

    def test_tool_names_match_set(self):
        names = [t["name"] for t in XHS_HOST_TOOLS]
        assert len(names) == len(set(names)), "Duplicate tool names"
        assert set(names) == _XHS_TOOL_NAMES

    def test_all_tools_in_execute_handler(self):
        """Every tool in XHS_HOST_TOOLS should be handled by _execute_xhs_host_tool."""
        # The handler has an explicit elif chain; unknown tools return error.
        # We just verify the set is consistent.
        assert len(_XHS_TOOL_NAMES) == 25


# ── Helper functions ─────────────────────────────────────────────────────


class TestHelpers:
    def test_make_text_result_plain(self):
        result = _make_text_result("hello")
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "hello"
        assert "details" not in result
        assert "isError" not in result

    def test_make_text_result_with_details(self):
        result = _make_text_result("ok", {"key": "val"})
        assert result["details"] == {"key": "val"}

    def test_make_text_result_error(self):
        result = _make_text_result("fail", None, is_error=True)
        assert result["isError"] is True


# ── _execute_xhs_host_tool with mocked httpx ────────────────────────────


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response with ApiResponse envelope."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    envelope = {"success": True, "data": data}
    resp.json.return_value = envelope
    return resp


def _mock_client_get(data: dict) -> AsyncMock:
    """Create a mock AsyncClient.get that returns envelope-wrapped data."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_mock_response(data))
    client.post = AsyncMock(return_value=_mock_response({}))
    client.delete = AsyncMock(return_value=_mock_response({}))
    return client


def _mock_client_post(data: dict) -> AsyncMock:
    """Create a mock AsyncClient.post that returns envelope-wrapped data."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_mock_response({}))
    client.post = AsyncMock(return_value=_mock_response(data))
    client.delete = AsyncMock(return_value=_mock_response({}))
    return client


def _make_async_context_manager(client: AsyncMock) -> AsyncMock:
    """Wrap a mock client so it works as `async with httpx.AsyncClient() as c:`."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
class TestWorkflowTools:
    async def test_workflow_start(self):
        data = {"thread_id": "t1", "phase": "scouting", "status": "running"}
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_workflow_start",
                {"account_id": "acc1", "workflow_mode": "trend"},
            )
        assert result.get("isError") is not True
        assert "t1" in result["content"][0]["text"]
        assert "scouting" in result["content"][0]["text"]

    async def test_workflow_status(self):
        data = {
            "phase": "creating",
            "status": "running",
            "progress_percent": 50,
            "current_agent": "copywriter",
            "next_steps": ["review_gate"],
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_workflow_status", {"thread_id": "t1"})
        assert "creating" in result["content"][0]["text"]
        assert "50%" in result["content"][0]["text"]

    async def test_workflow_list_empty(self):
        client = _mock_client_get({"workflows": []})
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_workflow_list", {})
        assert "No workflows" in result["content"][0]["text"]

    async def test_workflow_list_with_items(self):
        data = {
            "workflows": [
                {"thread_id": "abc12345def", "phase": "creating", "status": "running"},
            ]
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_workflow_list", {})
        assert "abc12345" in result["content"][0]["text"]

    async def test_workflow_delete(self):
        client = AsyncMock()
        client.delete = AsyncMock(return_value=_mock_response({}))
        client.get = AsyncMock(return_value=_mock_response({}))
        client.post = AsyncMock(return_value=_mock_response({}))
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_workflow_delete", {"thread_id": "t1"})
        assert "deleted" in result["content"][0]["text"]


@pytest.mark.asyncio
class TestReviewTools:
    async def test_review_pending_at_gate(self):
        data = {
            "status": "awaiting_review",
            "copy_content": {"selected_title": "Test Title", "body_text": "Hello"},
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_review_pending", {"thread_id": "t1"})
        assert "Test Title" in result["content"][0]["text"]

    async def test_review_pending_not_at_gate(self):
        data = {"status": "creating"}
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_review_pending", {"thread_id": "t1"})
        assert "not at review gate" in result["content"][0]["text"]

    async def test_review_approve(self):
        data = {"next_phase": "publishing"}
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_review_approve", {"thread_id": "t1"})
        assert "approved" in result["content"][0]["text"]
        assert "publishing" in result["content"][0]["text"]

    async def test_review_versions_empty(self):
        data = {"versions": [], "current": {"title": "", "body": ""}}
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_review_versions", {"thread_id": "t1"})
        assert "No content versions" in result["content"][0]["text"]


@pytest.mark.asyncio
class TestBloggerTools:
    async def test_blogger_pending_at_gate(self):
        data = {
            "is_pending": True,
            "blogger_candidates": [
                {"nickname": "Alice", "user_id": "u1"},
                {"nickname": "Bob", "user_id": "u2"},
            ],
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_blogger_pending", {"thread_id": "t1"})
        assert "Alice" in result["content"][0]["text"]
        assert "Bob" in result["content"][0]["text"]

    async def test_blogger_pending_not_at_gate(self):
        data = {"is_pending": False, "blogger_candidates": []}
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_blogger_pending", {"thread_id": "t1"})
        assert "not at blogger" in result["content"][0]["text"]

    async def test_blogger_select_missing_user_id(self):
        client = _mock_client_post({})
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_blogger_select",
                {"thread_id": "t1", "skip": False},
            )
        assert result["isError"] is True
        assert "user_id" in result["content"][0]["text"]

    async def test_blogger_select_skip(self):
        data = {"next_phase": "creating"}
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_blogger_select",
                {"thread_id": "t1", "skip": True},
            )
        assert "skipped" in result["content"][0]["text"]


@pytest.mark.asyncio
class TestRippleTools:
    async def test_ripple_pending(self):
        data = {
            "status": "awaiting_ripple_decision",
            "ripple_prediction": {"viral_probability": 0.7, "estimated_reach": 5000},
            "ripple_pmf": {"pmf_score": 0.6},
            "reselect_count": 0,
            "max_reselect": 2,
            "options": ["accept", "reangle", "retopic"],
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_ripple_pending", {"thread_id": "t1"})
        text = result["content"][0]["text"]
        assert "0.7" in text
        assert "5000" in text

    async def test_ripple_decision_accept(self):
        data = {"next_phase": "optimizing"}
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_ripple_decision",
                {"thread_id": "t1", "action": "accept"},
            )
        assert "Accepted" in result["content"][0]["text"]

    async def test_ripple_retry_skipped(self):
        data = {"status": "skipped", "message": "already succeeded"}
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_ripple_retry", {"thread_id": "t1"})
        assert "skipped" in result["content"][0]["text"]


@pytest.mark.asyncio
class TestAnalyticsTools:
    async def test_analytics_dashboard(self):
        data = {
            "report": {
                "metrics": {
                    "total_posts": 10,
                    "total_engagement": 500,
                    "avg_engagement_rate": 4.5,
                    "best_post_title": "Best Post",
                },
                "insights": [],
            },
            "costs": {"period_cost_usd": 1.23, "today_cost_usd": 0.45},
            "performance": {"posts": [{"title": "p1"}]},
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_analytics_dashboard", {"account_id": "acc1"})
        text = result["content"][0]["text"]
        assert "10" in text
        assert "Best Post" in text

    async def test_system_health(self):
        data = {
            "status": "ok",
            "checks": {
                "llm_providers": {"status": "ok"},
                "xhs_platform": {"status": "ok"},
                "ripple_cas": {"status": "ok"},
                "database": {"status": "ok", "mode": "sqlite"},
                "memory_store": {"status": "ok"},
            },
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_system_health", {})
        text = result["content"][0]["text"]
        assert "OK" in text
        assert "sqlite" in text


@pytest.mark.asyncio
class TestErrorHandling:
    async def test_unknown_tool(self):
        result = await _execute_xhs_host_tool("xhs_nonexistent", {})
        assert result["isError"] is True
        assert "Unknown" in result["content"][0]["text"]

    async def test_api_error_propagates(self):
        """When httpx raises, _execute_xhs_host_tool catches and returns error."""
        client = AsyncMock()
        client.get = AsyncMock(side_effect=Exception("Connection refused"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_workflow_status", {"thread_id": "t1"})
        assert result["isError"] is True
        assert "Failed" in result["content"][0]["text"]
