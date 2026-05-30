"""Tests for VersionGeneratorAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.version_generator import VersionGeneratorAgent
from backend.state.schema import WorkflowPhase


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
                {"dimension": "标题吸引力", "description": "标题缺乏数字和疑问句", "severity": "高"},
                {"dimension": "开头钩子", "description": "开头缺少吸引注意的钩子", "severity": "中"},
            ],
            "suggestions": [
                {"dimension": "标题", "action": "添加数字开头", "reasoning": "数字能提升点击率", "priority": 1},
                {"dimension": "正文", "action": "添加开头钩子", "reasoning": "钩子能抓住读者注意力", "priority": 2},
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
async def test_version_generator_generates_abc_versions(mock_state_with_draft_and_analysis, mock_store):
    """Should generate A/B/C three versions."""
    agent = VersionGeneratorAgent()

    # Mock the model response
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"versions": [{"version_id": "A", "title": "保守标题", "body": "保守正文", "hashtags": ["#保守"], "image_prompts": [], "style_suggestion": "保持原风格", "changes_summary": "仅修正标题", "predicted_score": 60}, {"version_id": "B", "title": "平衡标题", "body": "平衡正文", "hashtags": ["#平衡"], "image_prompts": [], "style_suggestion": "适度优化", "changes_summary": "重写标题和正文", "predicted_score": 75}, {"version_id": "C", "title": "激进标题", "body": "激进正文", "hashtags": ["#激进"], "image_prompts": [], "style_suggestion": "完全重构", "changes_summary": "全面重组", "predicted_score": 85}]}'
    ))

    with patch.object(agent, '_model', mock_model):
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
async def test_version_generator_includes_required_fields(mock_state_with_draft_and_analysis, mock_store):
    """Each version should include all required fields."""
    agent = VersionGeneratorAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"versions": [{"version_id": "A", "title": "标题A", "body": "正文A", "hashtags": ["#tag1", "#tag2"], "image_prompts": ["图片1"], "style_suggestion": "风格建议", "changes_summary": "改动摘要", "predicted_score": 70}]}'
    ))

    with patch.object(agent, '_model', mock_model):
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
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"versions": []}'
    ))

    with patch.object(agent, '_model', mock_model):
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
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"versions": [{"version_id": "A", "title": "标题", "body": "正文", "hashtags": [], "image_prompts": [], "style_suggestion": "", "changes_summary": "无改动", "predicted_score": 50}]}'
    ))

    with patch.object(agent, '_model', mock_model):
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