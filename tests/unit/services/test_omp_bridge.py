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
        assert len(XHS_HOST_TOOLS) == 35

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
        # Free-mode thread-less creation/evaluation/publish + draft CRUD tools
        assert "xhs_free_draft_create" in _XHS_TOOL_NAMES
        assert "xhs_free_evaluate" in _XHS_TOOL_NAMES
        assert "xhs_free_publish" in _XHS_TOOL_NAMES
        assert "xhs_free_draft_list" in _XHS_TOOL_NAMES
        assert "xhs_free_draft_update" in _XHS_TOOL_NAMES
        assert "xhs_free_draft_delete" in _XHS_TOOL_NAMES
        assert "xhs_free_guide" in _XHS_TOOL_NAMES


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
        # approved (even with hints present) does NOT trigger the revise cue
        assert "xhs_free_evaluate again" not in text
        # Structured result carries evaluation_result
        assert result["details"]["evaluation_result"]["overall_score"] == 78.5
        # Posted to /free/evaluate with account_id + draft_id
        client.post.assert_awaited_once()
        assert "/free/evaluate" in client.post.await_args.args[0]
        sent_json = client.post.await_args.kwargs["json"]
        assert sent_json["account_id"] == "acc1"
        assert sent_json["draft_id"] == "draft-xyz"

    async def test_free_evaluate_needs_revision_revise_hint(self):
        # needs_revision + non-empty hints → the agent render surfaces the
        # update→re-evaluate next step (evaluate→revise loop, agent-side mirror
        # of the TUI /draft revise hint #229).
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
        # revise-loop next-step cue present
        assert "xhs_free_draft_update" in text
        assert "xhs_free_evaluate again" in text

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
        # re-run cue present (not the revise cue)
        assert "re-run xhs_free_evaluate" in text
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
        # Real publish (non-mock post_id) → analytics next-step cue
        assert "xhs_free_analytics" in text
        assert "engagement" in text
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

    async def test_free_guide_returns_orchestration_text(self):
        """xhs_free_guide returns orchestration text locally — no httpx call."""
        with patch("httpx.AsyncClient") as mock_httpx:
            result = await _execute_xhs_host_tool("xhs_free_guide", {})
        text = result["content"][0]["text"]
        assert "CREATE" in text
        assert "EVALUATE" in text
        assert "PUBLISH" in text
        assert "xhs_free_draft_create" in text
        # evaluate→revise loop rule (#234 sync)
        assert "needs_revision" in text
        # publish-failure recovery rule (#239/#240 sync) — the guide must teach
        # the failure path, not only the success→analytics happy path
        assert "Publish can fail" in text
        assert "re-run xhs_free_publish" in text
        assert "Do NOT call xhs_free_analytics on a failed publish" in text
        assert "[publish failed]" in text  # draft-list badge documented
        # No httpx client was instantiated (branch is local-only)
        mock_httpx.assert_not_called()
        # Not an error
        assert result.get("isError") is not True
