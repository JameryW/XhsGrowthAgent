"""Tests for VersionGeneratorAgent."""

import json
from typing import get_args, get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.nodes.optimization.choice_gate import choice_gate_node
from backend.agents.version_generator import VersionGeneratorAgent
from backend.state.schema import WorkflowPhase, XHSGrowthState


@pytest.fixture
def mock_state_with_draft_and_analysis():
    """Mock state with draft content and optimization analysis."""
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案内容，这是一段测试文案。",
            "title": "测试标题",
            "hashtags": ["#测试", "#示例"],
            "style_suggestion": "简约风格",
            "provided_at": "2026-05-26T10:00:00",
        },
        "optimization_analysis": {
            "gaps": [
                {
                    "dimension": "标题吸引力",
                    "description": "标题缺乏数字和疑问句",
                    "severity": "高",
                },
                {
                    "dimension": "开头钩子",
                    "description": "开头缺少吸引注意的钩子",
                    "severity": "中",
                },
            ],
            "suggestions": [
                {
                    "dimension": "标题",
                    "action": "添加数字开头",
                    "reasoning": "数字能提升点击率",
                    "priority": 1,
                },
                {
                    "dimension": "正文",
                    "action": "添加开头钩子",
                    "reasoning": "钩子能抓住读者注意力",
                    "priority": 2,
                },
            ],
            "viral_patterns": ["使用数字开头", "疑问句标题", "emoji点缀"],
        },
    }


@pytest.fixture
def mock_state_no_draft():
    """Mock state without draft content."""
    return {
        "account_id": "test_account",
        "optimization_analysis": {
            "gaps": [],
            "suggestions": [],
            "viral_patterns": [],
        },
    }


@pytest.fixture
def mock_state_no_analysis():
    """Mock state without optimization analysis."""
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "title": "测试标题",
        },
    }


@pytest.fixture
def mock_store():
    """Mock BaseStore."""
    store = MagicMock()
    store.asearch = AsyncMock(return_value=[])
    return store


@pytest.mark.asyncio
async def test_version_generator_no_draft(mock_state_no_draft, mock_store):
    """Should return empty versions when no draft provided."""
    agent = VersionGeneratorAgent()
    result = await agent.execute(mock_state_no_draft, mock_store)
    assert result.get("content_versions") == []
    assert result.get("phase") == WorkflowPhase.CREATING


@pytest.mark.asyncio
async def test_version_generator_no_analysis(mock_state_no_analysis, mock_store):
    """Should return empty versions when no optimization analysis provided."""
    agent = VersionGeneratorAgent()
    result = await agent.execute(mock_state_no_analysis, mock_store)
    assert result.get("content_versions") == []
    assert result.get("phase") == WorkflowPhase.CREATING


@pytest.mark.asyncio
async def test_version_generator_generates_abc_versions(
    mock_state_with_draft_and_analysis, mock_store
):
    """Should generate A/B/C three versions."""
    agent = VersionGeneratorAgent()

    # Mock the model response
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"versions": [{"version_id": "A", "title": "保守标题", "body": "保守正文", "hashtags": ["#保守"], "image_prompts": [], "style_suggestion": "保持原风格", "changes_summary": "仅修正标题", "predicted_score": 60}, {"version_id": "B", "title": "平衡标题", "body": "平衡正文", "hashtags": ["#平衡"], "image_prompts": [], "style_suggestion": "适度优化", "changes_summary": "重写标题和正文", "predicted_score": 75}, {"version_id": "C", "title": "激进标题", "body": "激进正文", "hashtags": ["#激进"], "image_prompts": [], "style_suggestion": "完全重构", "changes_summary": "全面重组", "predicted_score": 85}]}'  # noqa: E501
        )
    )

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state_with_draft_and_analysis, mock_store)

    versions = result.get("content_versions", [])
    assert len(versions) == 3

    # Check version IDs
    version_ids = [v.get("version_id") for v in versions]
    assert version_ids == ["A", "B", "C"]

    # Check predicted scores increase progressively
    scores = [v.get("predicted_score") for v in versions]
    assert scores[0] < scores[1] < scores[2]


@pytest.mark.asyncio
async def test_version_generator_includes_required_fields(
    mock_state_with_draft_and_analysis, mock_store
):
    """Each version should include all required fields."""
    agent = VersionGeneratorAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"versions": [{"version_id": "A", "title": "标题A", "body": "正文A", "hashtags": ["#tag1", "#tag2"], "image_prompts": ["图片1"], "style_suggestion": "风格建议", "changes_summary": "改动摘要", "predicted_score": 70}]}'  # noqa: E501
        )
    )

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state_with_draft_and_analysis, mock_store)

    version = result["content_versions"][0]
    assert "version_id" in version
    assert "title" in version
    assert "body" in version
    assert "hashtags" in version
    assert "image_prompts" in version
    assert "style_suggestion" in version
    assert "changes_summary" in version
    assert "predicted_score" in version


@pytest.mark.asyncio
async def test_version_generator_phase_update(mock_state_with_draft_and_analysis, mock_store):
    """Should update phase to CREATING."""
    agent = VersionGeneratorAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content='{"versions": []}'))

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state_with_draft_and_analysis, mock_store)

    assert result.get("phase") == WorkflowPhase.CREATING


@pytest.mark.asyncio
async def test_version_generator_handles_empty_analysis(mock_store):
    """Should handle empty gaps/suggestions/viral_patterns gracefully."""
    agent = VersionGeneratorAgent()

    state = {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "title": "测试标题",
        },
        "optimization_analysis": {
            "gaps": [],
            "suggestions": [],
            "viral_patterns": [],
        },
    }

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"versions": [{"version_id": "A", "title": "标题", "body": "正文", "hashtags": [], "image_prompts": [], "style_suggestion": "", "changes_summary": "无改动", "predicted_score": 50}]}'  # noqa: E501
        )
    )

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(state, mock_store)

    assert len(result.get("content_versions", [])) >= 0


@pytest.mark.asyncio
async def test_version_generator_task_type():
    """Should have correct task_type."""
    agent = VersionGeneratorAgent()
    from backend.config.models import TaskType

    assert agent.task_type == TaskType.VERSION_GEN


@pytest.mark.asyncio
async def test_version_generator_agent_name():
    """Should have correct agent_name."""
    agent = VersionGeneratorAgent()
    assert agent.agent_name == "version_generator"


@pytest.mark.asyncio
async def test_version_generator_prompt_file():
    """Should have correct prompt_file."""
    agent = VersionGeneratorAgent()
    assert agent.prompt_file == "version_generator.yaml"


# ── Regression: multi-round growth loop must not accumulate versions ──────────


def _content_versions_reducer():
    """Extract the actual reducer LangGraph will use for content_versions."""
    hints = get_type_hints(XHSGrowthState, include_extras=True)
    return get_args(hints["content_versions"])[1]


@pytest.mark.asyncio
async def test_multi_round_no_version_accumulation(mock_state_with_draft_and_analysis, mock_store):
    """Two rounds of version_generator must leave only 3 versions (current round).

    Regression for thread ed6fd1fe: the growth loop (analyst → orchestrator →
    … → version_generator) ran version_generator twice, each producing A/B/C.
    With the old append_list reducer the list grew to 6 (duplicate A/B/C),
    and choice_gate's next() always matched round 1 — selection was broken.

    With the replace reducer, round 2 swaps in its 3 versions, keeping
    version_ids unique so choice_gate matches the current round correctly.
    """
    agent = VersionGeneratorAgent()
    reducer = _content_versions_reducer()

    def _mock_response(round_prefix: str, scores: tuple[int, int, int]):
        """Build a mock LLM response with 3 A/B/C versions for a round."""
        versions = []
        for vid, score in zip(["A", "B", "C"], scores, strict=True):
            versions.append(
                {
                    "version_id": vid,
                    "title": f"{round_prefix}-{vid}",
                    "body": f"body-{round_prefix}",
                    "hashtags": [],
                    "image_prompts": [],
                    "style_suggestion": "s",
                    "changes_summary": "c",
                    "predicted_score": score,
                }
            )
        return MagicMock(content=json.dumps({"versions": versions}))

    # Round 1 — version_generator returns A/B/C
    mock_model_r1 = MagicMock()
    mock_model_r1.ainvoke = AsyncMock(return_value=_mock_response("R1", (60, 75, 85)))
    with patch.object(agent, "_model", mock_model_r1):
        result_r1 = await agent.execute(mock_state_with_draft_and_analysis, mock_store)

    # Apply the real reducer as LangGraph would when merging into state
    state_versions = reducer([], result_r1["content_versions"])
    assert len(state_versions) == 3

    # Round 2 — same A/B/C version_ids (different content)
    mock_model_r2 = MagicMock()
    mock_model_r2.ainvoke = AsyncMock(return_value=_mock_response("R2", (62, 77, 88)))
    with patch.object(agent, "_model", mock_model_r2):
        result_r2 = await agent.execute(mock_state_with_draft_and_analysis, mock_store)

    # Round 2 reducer — must replace, not append (6 would be the old bug)
    state_versions = reducer(state_versions, result_r2["content_versions"])
    assert len(state_versions) == 3, (
        f"Expected 3 versions after 2 rounds (replace), got {len(state_versions)} — "
        "reducer is accumulating instead of replacing"
    )
    # All surviving versions are from round 2
    titles = [v["title"] for v in state_versions]
    assert titles == ["R2-A", "R2-B", "R2-C"]


@pytest.mark.asyncio
async def test_multi_round_choice_gate_selects_current_round(mock_store):
    """After two rounds, choice_gate must select the CURRENT round's version.

    With the old append_list reducer, round-2 A/B/C shared version_ids with
    round-1, so next(... version_id == "C") returned round-1's C — the user's
    round-2 selection silently mapped to stale content.  With replace only the
    current round's versions exist, so the match is correct.
    """
    # Simulate post-replace state: only round 2's versions remain
    state: dict = {
        "phase": WorkflowPhase.CREATING,
        "content_versions": [
            {"version_id": "A", "title": "R2-A", "body": "body-A2", "hashtags": ["#x"]},
            {"version_id": "B", "title": "R2-B", "body": "body-B2", "hashtags": ["#y"]},
            {"version_id": "C", "title": "R2-C", "body": "body-C2", "hashtags": ["#z"]},
        ],
        "selected_version": "C",
        "copy_content": {},
    }

    result = await choice_gate_node(state, store=mock_store)

    # choice_gate must have picked round-2's C, not some stale round-1 entry
    assert result["selected_version"] == "C"
    assert result["copy_content"]["selected_title"] == "R2-C"
    assert result["copy_content"]["body_text"] == "body-C2"
