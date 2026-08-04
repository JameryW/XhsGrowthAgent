"""Unit tests for omp_bridge host tool auto-execution."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.services.omp_bridge as omp_bridge_module
from backend.services.omp_bridge import (
    _DEFAULT_IDLE_TIMEOUT,
    _EVENT_BUFFER_SIZE,
    _STDOUT_BUFFER_LIMIT,
    _XHS_TOOL_NAMES,
    THREAD_BOUND_TOOLS,
    XHS_HOST_TOOLS,
    OmpBridgeManager,
    OmpSession,
    ServerEventType,
    _execute_xhs_host_tool,
    _make_text_result,
    _tools_for_mode,
    _validate_creator_stats_arguments,
)

# ── Schema validation ────────────────────────────────────────────────────


class TestHostToolSchemas:
    """Verify XHS_HOST_TOOLS list integrity."""

    def test_tool_count(self):
        assert len(XHS_HOST_TOOLS) == 40

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

    def test_creator_stats_schema_matches_backend_bounds(self):
        tool = next(item for item in XHS_HOST_TOOLS if item["name"] == "xhs_creator_stats")
        properties = tool["parameters"]["properties"]
        assert properties["account_id"]["minLength"] == 1
        assert properties["limit"] == {
            "type": "integer",
            "minimum": 1,
            "maximum": 200,
            "default": 20,
            "description": "Maximum imported notes to inspect (1-200)",
        }

    def test_all_tools_in_execute_handler(self):
        """Every tool in XHS_HOST_TOOLS should be handled by _execute_xhs_host_tool.

        The handler has an explicit elif chain; unknown tools return error.
        We verify the set is consistent and that newly added tools are present.
        """
        assert len(_XHS_TOOL_NAMES) == len(XHS_HOST_TOOLS)
        # OMP free orchestration must not expose the fixed workflow starter.
        assert "xhs_workflow_start" not in _XHS_TOOL_NAMES
        assert "xhs_publish_retry" in _XHS_TOOL_NAMES
        # Evaluation tools (RQGM agent-as-a-judge) must be in the auto-exec whitelist
        assert "xhs_evaluation_result" in _XHS_TOOL_NAMES
        assert "xhs_evaluation_run" in _XHS_TOOL_NAMES
        # Imported Creator Center stats must be available through both OMP paths.
        assert "xhs_creator_stats" in _XHS_TOOL_NAMES
        assert "xhs_creator_analysis" in _XHS_TOOL_NAMES
        assert "xhs_creator_suggestions" in _XHS_TOOL_NAMES
        assert "xhs_creator_quality" in _XHS_TOOL_NAMES
        # Free-mode thread-less creation/evaluation/publish + draft CRUD tools
        assert "xhs_free_draft_create" in _XHS_TOOL_NAMES
        assert "xhs_free_evaluate" in _XHS_TOOL_NAMES
        assert "xhs_free_publish" in _XHS_TOOL_NAMES
        assert "xhs_free_draft_list" in _XHS_TOOL_NAMES
        assert "xhs_free_draft_update" in _XHS_TOOL_NAMES
        assert "xhs_free_draft_delete" in _XHS_TOOL_NAMES
        assert "xhs_free_suggestions" in _XHS_TOOL_NAMES
        assert "xhs_free_guide" in _XHS_TOOL_NAMES

    def test_free_tool_descriptions_no_orchestration(self):
        """Free-mode tool descriptions carry only atomic capability — no step
        numbering, no chain hints, no 'call X before Y' sequencing."""
        free_descs = {
            t["name"]: t["description"] for t in XHS_HOST_TOOLS if t["name"].startswith("xhs_free_")
        }
        # xhs_free_draft_create — no "Step 1 of 3", no "feed it to"
        assert "Step 1" not in free_descs["xhs_free_draft_create"]
        assert "feed it to" not in free_descs["xhs_free_draft_create"]
        # xhs_free_evaluate — no "Step 2 of 3", no "Input draft_id from"
        assert "Step 2" not in free_descs["xhs_free_evaluate"]
        assert "Input draft_id from" not in free_descs["xhs_free_evaluate"]
        # xhs_free_publish — no "Step 3 of 3", no "Run xhs_free_evaluate first"
        assert "Step 3" not in free_descs["xhs_free_publish"]
        assert "Run xhs_free_evaluate first" not in free_descs["xhs_free_publish"]
        # xhs_free_analytics — dependency guardrail kept, orchestration removed
        assert "must have been published" in free_descs["xhs_free_analytics"]
        assert "Input draft_id from" not in free_descs["xhs_free_analytics"]
        # xhs_free_draft_list — no "Use to find a draft_id for"
        assert "Use to find a draft_id" not in free_descs["xhs_free_draft_list"]
        # xhs_free_draft_update — no "Use to refine before"
        assert "Use to refine before" not in free_descs["xhs_free_draft_update"]
        # xhs_free_guide — neutral description
        assert "orchestration steps" not in free_descs["xhs_free_guide"]
        assert "Call this first" not in free_descs["xhs_free_guide"]
        assert "Read-only reference" in free_descs["xhs_free_guide"]


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

    @pytest.mark.parametrize(
        ("arguments", "expected"),
        [
            ({"account_id": " acc1 ", "limit": 20}, ("acc1", 20)),
            ({"account_id": "acc1"}, ("acc1", 20)),
            ({"account_id": ""}, "account_id is required"),
            ({"account_id": "   "}, "account_id is required"),
            ({"account_id": "acc1", "limit": True}, "limit must be an integer"),
            ({"account_id": "acc1", "limit": 20.0}, "limit must be an integer"),
            ({"account_id": "acc1", "limit": 0}, "limit must be an integer"),
            ({"account_id": "acc1", "limit": 201}, "limit must be an integer"),
        ],
    )
    def test_validate_creator_stats_arguments(self, arguments, expected):
        result = _validate_creator_stats_arguments(arguments)
        if isinstance(expected, tuple):
            assert result == expected
        else:
            assert isinstance(result, str)
            assert result.startswith(expected)


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
    client.patch = AsyncMock(return_value=_mock_response({}))
    client.delete = AsyncMock(return_value=_mock_response({}))
    return client


def _mock_client_post(data: dict) -> AsyncMock:
    """Create a mock AsyncClient.post that returns envelope-wrapped data."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_mock_response({}))
    client.post = AsyncMock(return_value=_mock_response(data))
    client.patch = AsyncMock(return_value=_mock_response({}))
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
    async def test_workflow_start_disabled_for_omp_free_orchestration(self):
        result = await _execute_xhs_host_tool(
            "xhs_workflow_start",
            {"account_id": "acc1", "workflow_mode": "trend"},
        )
        assert result["isError"] is True
        assert "disabled" in result["content"][0]["text"]

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

    async def test_publish_retry(self):
        data = {"thread_id": "t1", "status": "retrying", "message": "正在重新发布"}
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_publish_retry", {"thread_id": "t1"})
        assert result.get("isError") is not True
        assert "retrying" in result["content"][0]["text"]
        client.post.assert_awaited_once()
        assert "/workflow/publish-retry/t1" in client.post.await_args.args[0]


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

    async def test_creator_stats(self):
        data = {
            "account": {
                "views": 1200,
                "likes": 90,
                "comments": 8,
                "collects": 15,
                "shares": 4,
                "fans": 30,
                "note_count": 2,
                "period": "30d",
                "source": "creator_statistics",
            },
            "notes": [
                {
                    "note_id": "n1",
                    "title": "Top note",
                    "views": 1000,
                    "likes": 80,
                    "comments": 5,
                    "collects": 12,
                    "engagement_rate": 0.097,
                },
                {
                    "note_id": "n2",
                    "title": "Second note",
                    "views": 200,
                    "likes": 10,
                    "comments": 3,
                    "collects": 3,
                    "engagement_rate": 0.08,
                },
            ],
            "total": 2,
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_creator_stats", {"account_id": "acc1", "limit": 20}
            )
        text = result["content"][0]["text"]
        assert "Creator Statistics" in text
        assert "Top note" in text
        assert "9.70%" in text
        assert client.get.await_args.kwargs["params"] == {"limit": 20}
        assert client.get.await_args.args[0].endswith("/analytics/creator-stats/acc1")

    @pytest.mark.parametrize(
        "arguments",
        [
            {"account_id": ""},
            {"account_id": "   "},
            {"account_id": "acc1", "limit": 0},
            {"account_id": "acc1", "limit": 201},
            {"account_id": "acc1", "limit": 2.5},
        ],
    )
    async def test_creator_stats_rejects_invalid_arguments_before_http(self, arguments):
        with patch("httpx.AsyncClient") as http_client:
            result = await _execute_xhs_host_tool("xhs_creator_stats", arguments)

        assert result["isError"] is True
        message = result["content"][0]["text"]
        assert "limit" in message or "account_id" in message
        http_client.assert_not_called()

    async def test_creator_stats_empty(self):
        client = _mock_client_get({"account": None, "notes": [], "total": 0})
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_creator_stats", {"account_id": "acc1"})
        assert "No imported notes" in result["content"][0]["text"]

    async def test_creator_stats_prefers_explicit_fraction_unit_at_one_percent_boundary(self):
        client = _mock_client_get(
            {
                "account": None,
                "notes": [
                    {
                        "note_id": "n1",
                        "title": "Boundary",
                        "views": 100,
                        "engagement_rate": 1.0,
                    }
                ],
                "total": 1,
                "engagement_rate_unit": "fraction",
            }
        )
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_creator_stats", {"account_id": "acc1"})
        assert "100.00%" in result["content"][0]["text"]

    async def test_creator_analysis(self):
        data = {
            "analysis": {
                "note_count": 2,
                "avg_engagement_rate": 0.09,
                "findings": [
                    {
                        "finding_type": "topic",
                        "label": "育儿",
                        "evidence": "高互动",
                        "score": 0.1,
                        "sample_count": 2,
                    }
                ],
            },
            "suggestions": {
                "trend": [
                    {
                        "title": "延续育儿选题",
                        "advice": "复用高互动角度",
                        "evidence": "高互动",
                    }
                ]
            },
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_creator_analysis", {"account_id": "acc1"})
        text = result["content"][0]["text"]
        assert "Creator Data Analysis" in text
        assert "育儿" in text
        assert "延续育儿选题" in text
        assert client.get.await_args.args[0].endswith("/analytics/creator-stats/acc1/analysis")

    async def test_creator_suggestions(self):
        data = {
            "mode": "free",
            "cold_start": False,
            "suggestions": [
                {
                    "priority": 1,
                    "title": "增加收藏引导",
                    "advice": "结尾给出可保存清单",
                    "evidence": "收藏率高",
                }
            ],
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_creator_suggestions", {"account_id": "acc1", "mode": "free"}
            )
        text = result["content"][0]["text"]
        assert "Creator Suggestions" in text
        assert "增加收藏引导" in text
        assert client.get.await_args.kwargs["params"] == {"mode": "free"}
        assert client.get.await_args.args[0].endswith("/analytics/creator-stats/acc1/suggestions")

    async def test_creator_quality(self):
        data = {
            "account_id": "acc1",
            "scope": "all_imported_history",
            "total_notes": 12,
            "notes_analyzed": 12,
            "overall_score": 71.5,
            "grade": "strong",
            "confidence": "high",
            "summary": "Imported history supports a quality assessment.",
            "strengths": [
                {
                    "dimension": "save_value",
                    "title": "Save value is relatively strong",
                    "evidence": "Average save rate is 0.85%.",
                }
            ],
            "weaknesses": [
                {
                    "dimension": "title_craft",
                    "title": "Title hooks have room to improve",
                    "evidence": "Only 6 of 12 titles have a hook.",
                }
            ],
            "recommendations": [
                {
                    "priority": 1,
                    "dimension": "title_craft",
                    "title": "Increase title-hook coverage",
                    "advice": "Try a number, question, comparison, or checklist.",
                }
            ],
            "cold_start": False,
            "insufficient_data": False,
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_creator_quality", {"account_id": "acc1"})
        text = result["content"][0]["text"]
        assert "Historical Creative Quality" in text
        assert "71.5/100" in text
        assert "Save value is relatively strong" in text
        assert "Increase title-hook coverage" in text
        assert result["details"] == data
        assert client.get.await_args.kwargs["params"] == {"locale": "en"}
        assert client.get.await_args.args[0].endswith("/analytics/creator-stats/acc1/quality")

    async def test_creator_quality_insufficient_history(self):
        data = {
            "account_id": "acc1",
            "total_notes": 2,
            "notes_analyzed": 2,
            "overall_score": None,
            "grade": "insufficient_data",
            "confidence": "low",
            "summary": "Only two imported notes are available.",
            "recommendations": [
                {
                    "priority": 1,
                    "dimension": "data_collection",
                    "title": "Build a comparable historical sample first",
                    "advice": "Import more real Creator Center history.",
                }
            ],
            "cold_start": False,
            "insufficient_data": True,
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_creator_quality", {"account_id": "acc1"})
        text = result["content"][0]["text"]
        assert "not yet sufficient" in text
        assert "Build a comparable historical sample first" in text
        assert result["details"] == data


@pytest.mark.asyncio
class TestEvaluationTools:
    """RQGM agent-as-a-judge evaluation host tools."""

    async def test_evaluation_result_with_data(self):
        data = {
            "has_evaluation": True,
            "evaluation_result": {
                "overall_score": 82.0,
                "decision": "approved",
                "bias_warning": "",
                "dimensions": [
                    {"dimension": "copywriting", "score": 85, "is_blocking": False},
                ],
                "revision_hints": [],
            },
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_evaluation_result", {"thread_id": "t1"})
        text = result["content"][0]["text"]
        assert "82.0" in text
        assert "approved" in text
        assert "copywriting" in text

    async def test_evaluation_result_none(self):
        data = {"has_evaluation": False, "evaluation_result": {}}
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_evaluation_result", {"thread_id": "t1"})
        assert "No evaluation result" in result["content"][0]["text"]

    async def test_evaluation_run(self):
        data = {
            "evaluation_result": {
                "overall_score": 45.0,
                "decision": "needs_revision",
                "bias_warning": "对 AI 套路化表达过度宽容",
                "dimensions": [
                    {"dimension": "compliance", "score": 30, "is_blocking": True},
                ],
                "revision_hints": ["[compliance] 修正绝对化用语"],
            },
        }
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_evaluation_run", {"thread_id": "t1"})
        text = result["content"][0]["text"]
        assert "45.0" in text
        assert "needs_revision" in text
        assert "过度宽容" in text
        assert "BLOCKING" in text


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


@pytest.mark.asyncio
class TestFreeModeTools:
    """Thread-less free creation/evaluation/publish host tools."""

    async def test_free_draft_create(self):
        data = {
            "draft_id": "draft-abc123",
            "draft": {
                "title": "我的母婴好物分享",
                "body": "正文内容",
                "hashtags": ["母婴", "好物"],
            },
        }
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_free_draft_create",
                {
                    "account_id": "acc1",
                    "title": "我的母婴好物分享",
                    "body": "正文内容",
                    "hashtags": ["母婴", "好物"],
                    "image_paths": [],
                    "niche": "母婴",
                    "content_angle": "",
                    "target_audience": "",
                },
            )
        assert result.get("isError") is not True
        text = result["content"][0]["text"]
        assert "draft-abc123" in text
        assert "我的母婴好物分享" in text
        # No orchestration next: cue — renders carry only guardrail note: cues
        assert "next:" not in text
        assert "xhs_free_evaluate" not in text
        # Structured result carries draft_id
        assert result["details"]["draft_id"] == "draft-abc123"
        # Posted to /free/draft with the full draft body
        client.post.assert_awaited_once()
        assert "/free/draft" in client.post.await_args.args[0]
        sent_json = client.post.await_args.kwargs["json"]
        assert sent_json["account_id"] == "acc1"
        assert sent_json["title"] == "我的母婴好物分享"
        assert sent_json["hashtags"] == ["母婴", "好物"]

    async def test_free_draft_create_defaults_account_id(self):
        """account_id is optional; defaults to "default" when omitted."""
        data = {"draft_id": "d1", "draft": {"title": "T"}}
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            await _execute_xhs_host_tool(
                "xhs_free_draft_create",
                {"title": "T", "body": "B"},
            )
        sent_json = client.post.await_args.kwargs["json"]
        assert sent_json["account_id"] == "default"

    async def test_free_evaluate(self):
        data = {
            "draft_id": "draft-xyz",
            "account_id": "acc1",
            "evaluation_result": {
                "overall_score": 78.5,
                "decision": "approved",
                "bias_warning": "",
                "dimensions": [
                    {"dimension": "copywriting", "score": 80, "is_blocking": False},
                    {"dimension": "compliance", "score": 60, "is_blocking": True},
                ],
                "revision_hints": ["[compliance] 修正绝对化用语"],
            },
        }
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_free_evaluate",
                {"account_id": "acc1", "draft_id": "draft-xyz"},
            )
        assert result.get("isError") is not True
        text = result["content"][0]["text"]
        assert "draft-xyz" in text
        assert "78.5" in text
        assert "approved" in text
        assert "BLOCKING" in text
        # No orchestration next: cue — renders carry only guardrail note: cues
        assert "next:" not in text
        assert "xhs_free_evaluate again" not in text
        # Structured result carries evaluation_result
        assert result["details"]["evaluation_result"]["overall_score"] == 78.5
        # Posted to /free/evaluate with account_id + draft_id
        client.post.assert_awaited_once()
        assert "/free/evaluate" in client.post.await_args.args[0]
        sent_json = client.post.await_args.kwargs["json"]
        assert sent_json["account_id"] == "acc1"
        assert sent_json["draft_id"] == "draft-xyz"

    async def test_free_evaluate_needs_revision_no_orchestration_cue(self):
        # needs_revision + non-empty hints → the render surfaces the verdict and
        # hints, but NO orchestration next: cue (the omp agent decides the flow).
        data = {
            "draft_id": "draft-rev",
            "account_id": "acc1",
            "evaluation_result": {
                "overall_score": 52.0,
                "decision": "needs_revision",
                "bias_warning": "",
                "dimensions": [],
                "revision_hints": ["[compliance] 修正绝对化用语"],
            },
        }
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_free_evaluate",
                {"account_id": "acc1", "draft_id": "draft-rev"},
            )
        text = result["content"][0]["text"]
        assert "needs_revision" in text
        assert "修正绝对化用语" in text  # revision_hints surfaced
        # No orchestration next: cue — the tool doesn't tell the agent what to do next
        assert "next:" not in text
        assert "xhs_free_draft_update" not in text
        assert "xhs_free_evaluate again" not in text

    async def test_free_evaluate_degraded_markers(self):
        # degraded=True (LLM timeout fallback): the render must surface the
        # degradation marker + cause + a re-run cue, NOT present the fake
        # 100/approved as a real verdict, and NOT the revise cue.
        data = {
            "draft_id": "draft-deg",
            "account_id": "acc1",
            "evaluation_result": {
                "overall_score": 100.0,
                "decision": "approved",
                "bias_warning": "",
                "dimensions": [],
                "revision_hints": [],
                "degraded": True,
                "summary": "评估器 LLM 超时，降级放行: llm slow",
            },
        }
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_free_evaluate",
                {"account_id": "acc1", "draft_id": "draft-deg"},
            )
        text = result["content"][0]["text"]
        assert "Evaluation degraded" in text
        assert "pass-through fallback" in text
        assert "降级放行" in text  # cause summary surfaced
        # No orchestration next: cue — degraded marker is a guardrail, not a
        # "re-run" instruction (the agent decides what to do)
        assert "next:" not in text
        assert "xhs_free_draft_update" not in text

    async def test_free_publish(self):
        data = {
            "draft_id": "draft-pub",
            "account_id": "acc1",
            "publish_result": {
                "post_id": "post-42",
                "post_url": "https://www.xiaohongshu.com/discovery/item/post-42",
                "status": "published",
            },
        }
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_free_publish",
                {"account_id": "acc1", "draft_id": "draft-pub"},
            )
        assert result.get("isError") is not True
        text = result["content"][0]["text"]
        assert "draft-pub" in text
        assert "post-42" in text
        assert "post-42" in text  # post_url contains it too
        assert "published" in text
        # Real publish gets no orchestration next: cue — the agent decides
        assert "next:" not in text
        assert "xhs_free_analytics(" not in text
        # Structured result carries publish_result
        assert result["details"]["publish_result"]["post_id"] == "post-42"
        # Posted to /free/publish with account_id + draft_id
        client.post.assert_awaited_once()
        assert "/free/publish" in client.post.await_args.args[0]
        sent_json = client.post.await_args.kwargs["json"]
        assert sent_json["account_id"] == "acc1"
        assert sent_json["draft_id"] == "draft-pub"

    async def test_free_publish_mock_dry_run_hint(self):
        # mock_published (dry-run, "mock_*" post_id) → flag as simulated so the
        # agent doesn't call analytics (which 400s on a synthetic post_id).
        # Mirrors the TUI mock hint (#223); agent-side render #234 cue pattern.
        data = {
            "draft_id": "draft-mock",
            "account_id": "acc1",
            "publish_result": {
                "post_id": "mock_42",
                "post_url": "",
                "status": "mock_published",
            },
        }
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_free_publish",
                {"account_id": "acc1", "draft_id": "draft-mock"},
            )
        text = result["content"][0]["text"]
        assert "mock_published" in text
        # mock cue present, analytics cue absent
        assert "dry-run mock publish" in text
        assert "analytics not available" in text
        assert "xhs_free_analytics(" not in text

    async def test_free_publish_failed_error_render(self):
        # Failed publish (status==failed/auth_expired/...) → surface the cause
        # (error/error_type) + recovery path (message/hint) that run_publish returns
        # so the agent can tell the user why and what to do. Mirrors #234/#235 cues.
        data = {
            "draft_id": "draft-fail",
            "account_id": "acc1",
            "publish_result": {
                "post_id": "",
                "post_url": "",
                "status": "failed",
                "error": "账号 acc1 已停用，无法发布",
                "error_type": "account_inactive",
                "recovery": {
                    "message": "请在设置页重新启用该账号",
                    "action": "reconfigure",
                    "action_label": "去设置",
                    "hint": "启动该账号浏览器并重新扫码登录",
                },
            },
        }
        client = _mock_client_post(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_free_publish",
                {"account_id": "acc1", "draft_id": "draft-fail"},
            )
        text = result["content"][0]["text"]
        assert "failed" in text
        # cause + recovery surfaced
        assert "Error: 账号 acc1 已停用，无法发布" in text
        assert "Error Type: account_inactive" in text
        assert "Recovery: 请在设置页重新启用该账号" in text
        assert "Hint: 启动该账号浏览器并重新扫码登录" in text
        # no success/mock cues on a failure
        assert "xhs_free_analytics(" not in text
        assert "dry-run mock publish" not in text

    async def test_free_draft_list(self):
        """xhs_free_draft_list GETs /free/drafts/{account_id} and renders the list
        with published/eval badges + count header (mirrors TUI /drafts)."""
        data = {
            "account_id": "acc1",
            "drafts": [
                {
                    "draft_id": "d1",
                    "title": "标题一",
                    "hashtags": [],
                    "last_evaluation": {"overall_score": 82.0, "decision": "approved"},
                    "published": True,
                },
                {"draft_id": "d2", "title": "标题二", "hashtags": []},
                {
                    "draft_id": "d3",
                    "title": "标题三",
                    "hashtags": [],
                    "last_evaluation": {"overall_score": 51.0, "decision": "needs_revision"},
                    "published": False,
                },
                {
                    "draft_id": "d4",
                    "title": "标题四",
                    "hashtags": [],
                    "published": False,
                    "last_publish": {
                        "status": "failed",
                        "error": "账号已停用",
                        "error_type": "account_inactive",
                        "at": "2026-07-12T10:00:00Z",
                    },
                },
                {
                    "draft_id": "d5",
                    "title": "标题五",
                    "hashtags": [],
                    "published": False,
                    "last_evaluation": {
                        "overall_score": 100.0,
                        "decision": "approved",
                        "degraded": True,
                        "summary": "评估器 LLM 超时，降级放行",
                    },
                },
            ],
            "count": 5,
            "truncated": True,
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_free_draft_list", {"account_id": "acc1"})
        assert result.get("isError") is not True
        text = result["content"][0]["text"]
        assert "acc1" in text
        # count header + truncated note
        assert "(5)" in text
        assert "truncated" in text
        assert "d1" in text and "标题一" in text
        assert "d2" in text and "标题二" in text
        # eval badge (score + decision) + published marker on d1
        assert "82.0" in text and "approved" in text
        assert "[published]" in text
        # d2 has no eval/published badge
        assert "needs_revision" in text  # d3
        # d4 — publish-failed badge (last_publish.status non-success)
        assert "[publish failed]" in text
        # d5 — degraded eval shows [degraded] instead of [100 approved]
        assert "[degraded]" in text
        # success-status last_publish does NOT get the badge
        assert text.count("[published]") == 1
        # Structured result carries drafts
        assert len(result["details"]["drafts"]) == 5
        # GET to /free/drafts/{account_id}
        client.get.assert_awaited_once()
        assert "/free/drafts/acc1" in client.get.await_args.args[0]

    async def test_free_draft_list_empty(self):
        data = {"account_id": "acc1", "drafts": []}
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_free_draft_list", {"account_id": "acc1"})
        assert result.get("isError") is not True
        assert "(none)" in result["content"][0]["text"]

    async def test_free_suggestions(self):
        """xhs_free_suggestions GETs /free/suggestions/{account_id} and renders
        the list with a count header + cold-start note + per-suggestion lines.
        Atomic data fetch only — no orchestration cue (编排交给 omp)."""
        data = {
            "account_id": "acc1",
            "mode": "free",
            "suggestions": [
                {
                    "mode": "free",
                    "category": "topic",
                    "title": "高互动选题方向",
                    "advice": "近期母婴类「辅食记录」互动率高于均值 1.4 倍",
                    "priority": 2,
                    "evidence": "note_analytics:engagement_rate",
                },
                {
                    "mode": "free",
                    "category": "style",
                    "title": "暖色调封面",
                    "advice": "前 3 篇高收藏笔记均为暖光、近景",
                    "priority": 1,
                    "evidence": "",
                },
            ],
            "count": 2,
            "cold_start": False,
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_free_suggestions", {"account_id": "acc1"})
        assert result.get("isError") is not True
        text = result["content"][0]["text"]
        assert "acc1" in text
        # count header + per-suggestion lines with category badge
        assert "2" in text
        assert "[topic]" in text and "[style]" in text
        assert "高互动选题方向" in text
        assert "辅食记录" in text
        assert "Evidence:" in text  # only when evidence present (d1 has it)
        # atomic tool — must NOT prescribe next-step orchestration (编排交 omp)
        assert "xhs_free_draft_create" not in text
        assert "next:" not in text
        # no cold-start note when cold_start is False
        assert "cold start" not in text
        # GET to /free/suggestions/{account_id}
        client.get.assert_awaited_once()
        assert "/free/suggestions/acc1" in client.get.await_args.args[0]

    async def test_free_suggestions_cold_start(self):
        """Cold-start (no imported stats) renders the note + the empty advice line."""
        data = {
            "account_id": "acc1",
            "mode": "free",
            "suggestions": [
                {
                    "mode": "free",
                    "category": "cold_start",
                    "title": "暂无创作中心数据",
                    "advice": "尚未导入创作者中心统计数据。",
                    "priority": 0,
                    "evidence": "no_imported_stats",
                }
            ],
            "count": 1,
            "cold_start": True,
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_free_suggestions", {"account_id": "acc1"})
        text = result["content"][0]["text"]
        assert "cold start" in text.lower()

    async def test_free_suggestions_empty(self):
        """No suggestions → empty advice line, no per-suggestion rows."""
        data = {
            "account_id": "acc1",
            "mode": "free",
            "suggestions": [],
            "count": 0,
            "cold_start": False,
        }
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool("xhs_free_suggestions", {"account_id": "acc1"})
        text = result["content"][0]["text"]
        assert "No suggestions" in text

    async def test_free_draft_update(self):
        """xhs_free_draft_update PATCHes /free/draft/{id}?account_id= with the provided fields."""
        data = {
            "draft_id": "d-up",
            "draft": {"title": "新标题", "body": "正文"},
        }
        client = _mock_client_post(data)
        # _mock_client_post sets .patch to return {} — override to return our data
        client.patch = AsyncMock(return_value=_mock_response(data))
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_free_draft_update",
                {"account_id": "acc1", "draft_id": "d-up", "title": "新标题"},
            )
        assert result.get("isError") is not True
        text = result["content"][0]["text"]
        assert "d-up" in text
        assert "新标题" in text
        # PATCH to /free/draft/{draft_id} with account_id as query param
        client.patch.assert_awaited_once()
        assert "/free/draft/d-up" in client.patch.await_args.args[0]
        assert client.patch.await_args.kwargs["params"]["account_id"] == "acc1"
        # Body carries only the provided field (title), not account_id/draft_id
        sent_json = client.patch.await_args.kwargs["json"]
        assert sent_json["title"] == "新标题"
        assert "account_id" not in sent_json
        assert "draft_id" not in sent_json

    async def test_free_draft_delete(self):
        """xhs_free_draft_delete DELETEs /free/draft/{id}?account_id=."""
        data = {"draft_id": "d-del", "deleted": True}
        client = _mock_client_get(data)
        with patch("httpx.AsyncClient", return_value=_make_async_context_manager(client)):
            result = await _execute_xhs_host_tool(
                "xhs_free_draft_delete",
                {"account_id": "acc1", "draft_id": "d-del"},
            )
        assert result.get("isError") is not True
        assert "d-del" in result["content"][0]["text"]
        # DELETE to /free/draft/{draft_id} with account_id as query param
        client.delete.assert_awaited_once()
        assert "/free/draft/d-del" in client.delete.await_args.args[0]
        assert client.delete.await_args.kwargs["params"]["account_id"] == "acc1"

    async def test_free_guide_returns_guardrail_reference(self):
        """xhs_free_guide returns guardrail reference text locally — no httpx call.

        The guide is a pure guardrail reference (no orchestration steps, no
        step numbering, no create→evaluate→publish chain). It lists the
        available tools (no ordering, no → arrows) and documents the rules:
        thread-bound tools disabled, degraded verdict guardrail, publish-
        failure recovery guardrail, draft-list badges.
        """
        with patch("httpx.AsyncClient") as mock_httpx:
            result = await _execute_xhs_host_tool("xhs_free_guide", {})
        text = result["content"][0]["text"]
        # Tool list (neutral, no step numbering)
        assert "xhs_free_draft_create" in text
        assert "xhs_free_evaluate" in text
        assert "xhs_free_publish" in text
        assert "xhs_free_analytics" in text
        assert "xhs_free_draft_list" in text
        assert "xhs_free_draft_update" in text
        assert "xhs_free_draft_delete" in text
        # No orchestration content
        assert "Step 1" not in text
        assert "CREATE:" not in text
        assert "EVALUATE:" not in text
        assert "PUBLISH:" not in text
        assert "create→evaluate→publish" not in text
        assert "Run xhs_free_evaluate before" not in text
        assert "After a successful publish" not in text
        # Guardrail: thread-bound tools disabled
        assert "thread-bound" in text
        assert "xhs_workflow_status" in text
        assert "xhs_workflow_start is disabled" in text
        # Guardrail: degraded verdict (fake 100/approved)
        assert "degraded" in text
        assert "Evaluate can degrade" in text
        assert "FAKE fallback" in text
        assert "[degraded]" in text
        # Guardrail: publish failure recovery
        assert "Publish can fail" in text
        assert "Do NOT call xhs_free_analytics on a failed publish" in text
        assert "[publish failed]" in text  # draft-list badge documented
        # suggestions tool documented in the guide (atomic data fetch, no orchestration cue)
        assert "xhs_free_suggestions" in text
        assert "style/topic/format/timing" in text
        # No httpx client was instantiated (branch is local-only)
        mock_httpx.assert_not_called()
        # Not an error
        assert result.get("isError") is not True


# ── Mode-based tool isolation ────────────────────────────────────────────


class TestToolSubsetIsolation:
    """_tools_for_mode returns the right subset per mode."""

    def test_tools_for_mode_free_excludes_thread_bound(self):
        free_tools = _tools_for_mode("free")
        free_names = {t["name"] for t in free_tools}
        # No thread-bound tools in the free subset
        assert not (free_names & THREAD_BOUND_TOOLS)
        # Free-mode tools present
        assert "xhs_free_draft_create" in free_names
        assert "xhs_free_evaluate" in free_names
        assert "xhs_free_publish" in free_names
        assert "xhs_free_analytics" in free_names
        assert "xhs_free_draft_list" in free_names
        assert "xhs_free_draft_update" in free_names
        assert "xhs_free_draft_delete" in free_names
        assert "xhs_free_guide" in free_names
        # Account-bound general tools present
        assert "xhs_analytics_dashboard" in free_names
        assert "xhs_system_health" in free_names
        assert "xhs_creator_stats" in free_names
        assert "xhs_creator_quality" in free_names

    def test_tools_for_mode_free_no_thread_bound_leak(self):
        """Every thread-bound tool must be absent from the free subset."""
        free_tools = _tools_for_mode("free")
        free_names = {t["name"] for t in free_tools}
        for tb in THREAD_BOUND_TOOLS:
            assert tb not in free_names, f"{tb} leaked into free mode subset"

    def test_tools_for_mode_workflow_returns_full(self):
        wf_tools = _tools_for_mode("workflow")
        assert len(wf_tools) == len(XHS_HOST_TOOLS)
        assert {t["name"] for t in wf_tools} == _XHS_TOOL_NAMES

    def test_tools_for_mode_unknown_returns_full(self):
        """Unknown/None mode defaults to full list (workflow behavior unchanged)."""
        assert len(_tools_for_mode("trend")) == len(XHS_HOST_TOOLS)
        assert len(_tools_for_mode("brief")) == len(XHS_HOST_TOOLS)

    def test_free_subset_smaller_than_full(self):
        free_tools = _tools_for_mode("free")
        assert len(free_tools) < len(XHS_HOST_TOOLS)


@pytest.mark.asyncio
class TestOmpSessionMode:
    """OmpSession carries a mode and registers the right tool subset on start."""

    async def test_session_default_mode_is_workflow(self):
        session = OmpSession("test-1")
        assert session.mode == "workflow"

    async def test_session_free_mode_registers_subset(self):
        """OmpSession(mode='free') start() registers only the free subset."""
        session = OmpSession("test-free", mode="free")
        # Pre-set the ready event so start()'s wait_for(_ready.wait()) resolves
        # immediately. (Patching asyncio.wait_for instead leaks an un-awaited
        # Event.wait coroutine — the arg is still evaluated under the mock.)
        session._ready.set()
        with (
            patch.object(OmpSession, "register_host_tools", new_callable=AsyncMock) as mock_reg,
            patch.object(OmpSession, "_drain_stderr", new_callable=AsyncMock),
            patch.object(OmpSession, "_read_stdout", new_callable=AsyncMock),
            patch("shutil.which", return_value="/fake/omp"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock),
        ):
            await session.start()
        mock_reg.assert_awaited_once()
        registered_tools = mock_reg.await_args.args[0]
        registered_names = {t["name"] for t in registered_tools}
        # Free subset only — no thread-bound tools
        assert not (registered_names & THREAD_BOUND_TOOLS)
        assert "xhs_free_draft_create" in registered_names

    async def test_session_workflow_mode_registers_full(self):
        """OmpSession(mode='workflow') start() registers the full list."""
        session = OmpSession("test-wf", mode="workflow")
        session._ready.set()  # see test_session_free_mode_registers_subset
        with (
            patch.object(OmpSession, "register_host_tools", new_callable=AsyncMock) as mock_reg,
            patch.object(OmpSession, "_drain_stderr", new_callable=AsyncMock),
            patch.object(OmpSession, "_read_stdout", new_callable=AsyncMock),
            patch("shutil.which", return_value="/fake/omp"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock),
        ):
            await session.start()
        mock_reg.assert_awaited_once()
        registered_tools = mock_reg.await_args.args[0]
        assert len(registered_tools) == len(XHS_HOST_TOOLS)

    async def test_set_mode_reregisters_tools(self):
        """set_mode updates self.mode and re-registers the new tool subset."""
        session = OmpSession("test-switch", mode="free")
        with patch.object(OmpSession, "register_host_tools", new_callable=AsyncMock) as mock_reg:
            await session.set_mode("workflow")
        assert session.mode == "workflow"
        mock_reg.assert_awaited_once()
        registered_tools = mock_reg.await_args.args[0]
        assert len(registered_tools) == len(XHS_HOST_TOOLS)

    async def test_set_mode_workflow_to_free_reregisters_subset(self):
        session = OmpSession("test-switch2", mode="workflow")
        with patch.object(OmpSession, "register_host_tools", new_callable=AsyncMock) as mock_reg:
            await session.set_mode("free")
        assert session.mode == "free"
        mock_reg.assert_awaited_once()
        registered_tools = mock_reg.await_args.args[0]
        registered_names = {t["name"] for t in registered_tools}
        assert not (registered_names & THREAD_BOUND_TOOLS)


@pytest.mark.asyncio
class TestGetOrCreateSessionMode:
    """OmpBridgeManager keeps subprocess-local mode and tool isolation coherent."""

    async def test_new_session_with_mode(self):
        manager = OmpBridgeManager()
        with (
            patch.object(OmpSession, "start", new_callable=AsyncMock),
            patch.object(OmpSession, "register_host_tools", new_callable=AsyncMock),
        ):
            session = await manager.get_or_create_session(None, mode="free")
        assert session.mode == "free"
        assert session.session_id in manager._sessions

    async def test_existing_session_same_mode_no_reregister(self):
        manager = OmpBridgeManager()
        session = OmpSession("existing", mode="free")
        # Mark as a live session (started + ready) — dead sessions are
        # replaced instead of reused.
        session._ready.set()
        session._proc = MagicMock()
        manager._sessions["existing"] = session
        with patch.object(OmpSession, "set_mode", new_callable=AsyncMock) as mock_set_mode:
            result = await manager.get_or_create_session("existing", mode="free")
        assert result is session
        mock_set_mode.assert_not_awaited()

    async def test_existing_session_mode_mismatch_restarts_subprocess(self):
        manager = OmpBridgeManager()
        session = OmpSession("existing", mode="workflow")
        # Live session — see test_existing_session_same_mode_no_reregister.
        session._ready.set()
        session._proc = MagicMock()
        manager._sessions["existing"] = session
        with (
            patch.object(session, "stop", new_callable=AsyncMock) as mock_stop,
            patch.object(OmpSession, "start", new_callable=AsyncMock) as mock_start,
        ):
            result = await manager.get_or_create_session("existing", mode="free")
        assert result is not session
        assert result.mode == "free"
        assert result.session_id == "existing"
        mock_stop.assert_awaited_once()
        mock_start.assert_awaited_once()


# ── Session resilience: reader death, seq/replay, busy tracking ────────────


def _make_live_session(session_id: str, readline: AsyncMock) -> OmpSession:
    """An OmpSession posing as started, with a fake subprocess stdout."""
    session = OmpSession(session_id)
    session._ready.set()
    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.readline = readline
    proc.returncode = 1
    session._proc = proc
    return session


class _EventCollector:
    """Async event callback that records emitted events."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


@pytest.mark.asyncio
class TestReadStdoutResilience:
    """Reader exit (EOF or error) must kill the session loudly, not leave a zombie."""

    async def test_reader_eof_marks_session_dead_and_notifies(self):
        session = _make_live_session("s-eof", AsyncMock(return_value=b""))
        collector = _EventCollector()
        session.on_event(collector)
        dropped: list[str] = []

        async def on_dead(sid: str) -> None:
            dropped.append(sid)

        session._on_dead = on_dead
        fut = asyncio.get_running_loop().create_future()
        session._pending["req_1"] = fut

        await session._read_stdout()

        assert session._proc is None
        assert not session.is_ready
        assert not session.is_busy
        # Pending command futures fail fast instead of hanging until timeout
        assert fut.done()
        assert isinstance(fut.exception(), RuntimeError)
        assert "omp process exited unexpectedly" in str(fut.exception())
        # Frontend is unblocked: error + session_end
        types = [e["type"] for e in collector.events]
        assert ServerEventType.ERROR in types
        assert ServerEventType.SESSION_END in types
        error_event = next(e for e in collector.events if e["type"] == ServerEventType.ERROR)
        assert "omp process exited unexpectedly" in error_event["message"]
        # Manager hook fires so the session is dropped
        assert dropped == ["s-eof"]

    async def test_reader_oversized_line_error_kills_session(self):
        """Regression: asyncio's default 64KiB limit killed the reader silently."""
        session = _make_live_session(
            "s-limit",
            AsyncMock(side_effect=ValueError("Separator is found, but chunk is longer than limit")),
        )
        collector = _EventCollector()
        session.on_event(collector)

        await session._read_stdout()

        assert session._proc is None
        assert not session.is_ready
        error_event = next(e for e in collector.events if e["type"] == ServerEventType.ERROR)
        assert "reader error" in error_event["message"]

    async def test_reader_cancelled_by_stop_is_not_a_crash(self):
        session = _make_live_session("s-cancel", AsyncMock(side_effect=asyncio.CancelledError()))
        collector = _EventCollector()
        session.on_event(collector)

        with pytest.raises(asyncio.CancelledError):
            await session._read_stdout()

        # Normal shutdown path: no death handling, no error events
        assert session._proc is not None
        assert collector.events == []

    async def test_death_events_are_buffered_for_replay(self):
        session = _make_live_session("s-buf", AsyncMock(return_value=b""))
        await session._read_stdout()
        replay = session.events_after(0)
        types = [e["type"] for e in replay]
        assert ServerEventType.ERROR in types
        assert ServerEventType.SESSION_END in types


@pytest.mark.asyncio
class TestEventSeqAndReplay:
    """_emit tags events with a monotonic seq and keeps a bounded replay buffer."""

    async def test_emit_assigns_monotonic_seq_and_session_id(self):
        session = OmpSession("s-seq")
        await session._emit({"type": "status", "status": "running"})
        await session._emit({"type": "agent_message", "text": "hi", "done": False})
        await session._emit({"type": "session_end"})

        assert [e["seq"] for e in session._event_buffer] == [1, 2, 3]
        assert session.current_seq == 3
        assert all(e["session_id"] == "s-seq" for e in session._event_buffer)

    async def test_events_after_slices_by_cursor(self):
        session = OmpSession("s-slice")
        for i in range(5):
            await session._emit({"type": "agent_message", "text": str(i)})

        replay = session.events_after(2, session.current_seq)
        assert [e["seq"] for e in replay] == [3, 4, 5]
        assert [e["seq"] for e in session.events_after(0, 2)] == [1, 2]
        assert session.events_after(5) == []

    async def test_buffer_is_bounded_and_drops_oldest(self):
        session = OmpSession("s-bound")
        for _ in range(_EVENT_BUFFER_SIZE + 5):
            await session._emit({"type": "agent_message", "text": "x"})

        assert len(session._event_buffer) == _EVENT_BUFFER_SIZE
        # Oldest surviving event is seq 6 — a client with last_seq < 6 has a gap
        assert session._event_buffer[0]["seq"] == 6


@pytest.mark.asyncio
class TestBusyTracking:
    async def test_busy_tracks_agent_turn(self):
        session = OmpSession("s-busy")
        assert not session.is_busy
        await session._translate_event({"type": "agent_start"})
        assert session.is_busy
        await session._translate_event({"type": "agent_end"})
        assert not session.is_busy

    async def test_process_death_clears_busy(self):
        session = _make_live_session("s-busy-die", AsyncMock(return_value=b""))
        session._busy = True
        await session._read_stdout()
        assert not session.is_busy


@pytest.mark.asyncio
class TestCompactionRetryForwarding:
    """LLM-provider retry/compaction events surface as status, not silence."""

    async def test_retry_and_compaction_forwarded_as_status(self):
        session = OmpSession("s-retry")
        collector = _EventCollector()
        session.on_event(collector)

        await session._translate_event({"type": "auto_retry_start"})
        await session._translate_event({"type": "auto_retry_end"})
        await session._translate_event({"type": "auto_compaction_start"})
        await session._translate_event({"type": "auto_compaction_end"})

        statuses = [e["status"] for e in collector.events if e["type"] == "status"]
        assert statuses == ["retrying", "running", "compacting", "running"]


@pytest.mark.asyncio
class TestSubprocessSpawn:
    async def test_start_passes_large_stdout_limit(self):
        session = OmpSession("s-spawn")
        session._ready.set()  # see test_session_free_mode_registers_subset
        with (
            patch.object(OmpSession, "register_host_tools", new_callable=AsyncMock),
            patch.object(OmpSession, "_drain_stderr", new_callable=AsyncMock),
            patch.object(OmpSession, "_read_stdout", new_callable=AsyncMock),
            patch("shutil.which", return_value="/fake/omp"),
            patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        ):
            await session.start()
        assert mock_exec.await_args.kwargs["limit"] == _STDOUT_BUFFER_LIMIT


@pytest.mark.asyncio
class TestManagerResilience:
    async def test_dead_session_replaced_on_reconnect(self):
        manager = OmpBridgeManager()
        dead = OmpSession("dead-1")  # never started → not ready
        manager._sessions["dead-1"] = dead
        with (
            patch.object(dead, "stop", new_callable=AsyncMock) as mock_stop,
            patch.object(OmpSession, "start", new_callable=AsyncMock),
        ):
            session = await manager.get_or_create_session("dead-1", mode="free")
        assert session is not dead
        assert session.session_id == "dead-1"
        assert manager._sessions["dead-1"] is session
        assert session._on_dead is not None
        mock_stop.assert_awaited_once()

    async def test_drop_session_removes_and_cancels_timer(self):
        manager = OmpBridgeManager(idle_timeout=60)
        manager._sessions["s-drop"] = OmpSession("s-drop")
        manager.start_idle_timer("s-drop")
        assert "s-drop" in manager._idle_timers

        await manager._drop_session("s-drop")

        assert "s-drop" not in manager._sessions
        assert "s-drop" not in manager._idle_timers

    async def test_idle_timer_defers_while_busy(self):
        manager = OmpBridgeManager(idle_timeout=0.01)
        session = OmpSession("s-idle")
        session._busy = True
        manager._sessions["s-idle"] = session
        with patch.object(session, "stop", new_callable=AsyncMock) as mock_stop:
            manager.start_idle_timer("s-idle")
            await asyncio.sleep(0.03)
            # Turn in flight — the timer must not kill the subprocess
            mock_stop.assert_not_awaited()
            assert "s-idle" in manager._sessions

            session._busy = False
            await asyncio.sleep(0.03)
            mock_stop.assert_awaited_once()
            assert "s-idle" not in manager._sessions

    async def test_stop_waits_for_busy_session_within_grace(self):
        manager = OmpBridgeManager()
        session = OmpSession("s-grace")
        session._busy = True
        manager._sessions["s-grace"] = session
        with (
            patch.object(session, "stop", new_callable=AsyncMock) as mock_stop,
            # Shrink the grace poll interval so the 0.5s default doesn't
            # dominate this test — finish_turn completes at 0.05s, the poll
            # just needs to catch that within the 2.0s grace.
            patch.object(omp_bridge_module, "_SHUTDOWN_BUSY_POLL_S", 0.01),
        ):

            async def finish_turn() -> None:
                await asyncio.sleep(0.05)
                session._busy = False

            task = asyncio.create_task(finish_turn())
            await manager.stop(grace_seconds=2.0)
            await task
        mock_stop.assert_awaited_once()
        assert manager._sessions == {}

    async def test_stop_grace_expires_and_stops_anyway(self):
        manager = OmpBridgeManager()
        session = OmpSession("s-grace-x")
        session._busy = True
        manager._sessions["s-grace-x"] = session
        with (
            patch.object(session, "stop", new_callable=AsyncMock) as mock_stop,
            # Shrink the grace poll interval (default 0.5s) — the un-patched
            # poll exceeds the 0.1s grace, so the test would sleep a full 0.5s.
            patch.object(omp_bridge_module, "_SHUTDOWN_BUSY_POLL_S", 0.02),
        ):
            await manager.stop(grace_seconds=0.1)
        mock_stop.assert_awaited_once()
        assert manager._sessions == {}


class TestGetBridgeManager:
    def test_idle_timeout_env_override(self, monkeypatch):
        monkeypatch.setenv("OMP_IDLE_TIMEOUT", "42")
        monkeypatch.setattr(omp_bridge_module, "_manager", None)
        manager = omp_bridge_module.get_bridge_manager()
        assert manager._idle_timeout == 42

    def test_idle_timeout_env_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("OMP_IDLE_TIMEOUT", "not-a-number")
        monkeypatch.setattr(omp_bridge_module, "_manager", None)
        manager = omp_bridge_module.get_bridge_manager()
        assert manager._idle_timeout == _DEFAULT_IDLE_TIMEOUT

    def test_idle_timeout_default(self, monkeypatch):
        monkeypatch.delenv("OMP_IDLE_TIMEOUT", raising=False)
        monkeypatch.setattr(omp_bridge_module, "_manager", None)
        manager = omp_bridge_module.get_bridge_manager()
        assert manager._idle_timeout == _DEFAULT_IDLE_TIMEOUT
