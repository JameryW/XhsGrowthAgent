"""Tests for ContentAnalyzerAgent."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_analyzer import ContentAnalyzerAgent


@pytest.fixture
def mock_state_with_draft_and_viral():
    """Mock state with draft content and viral posts."""
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "今天分享一个很实用的穿搭技巧，希望对大家有帮助。",
            "images": [],
            "title": "穿搭技巧分享",
            "hashtags": ["#穿搭", "#时尚"],
            "provided_at": "2026-05-26T10:00:00",
        },
        "viral_posts": [
            {
                "note_id": "abc123",
                "title": "3个穿搭公式让你秒变时尚博主！",
                "body": "姐妹们！今天分享3个万能穿搭公式，学会就能轻松提升时尚感...",
                "hashtags": ["#穿搭", "#时尚", "#OOTD"],
                "likes": 10000,
                "collects": 5000,
                "comments": 200,
                "engagement_rate": 0.15,
                "visual_style": "vibrant",
                "color_palette": {"primary": "#FF6B6B", "secondary": "#4ECDC4"},
            }
        ],
    }


@pytest.fixture
def mock_state_no_draft():
    """Mock state without draft content."""
    return {
        "account_id": "test_account",
        "viral_posts": [
            {
                "note_id": "abc123",
                "title": "爆款标题",
                "body": "爆款正文",
                "hashtags": ["#爆款"],
                "likes": 10000,
            }
        ],
    }


@pytest.fixture
def mock_state_no_viral():
    """Mock state without viral posts."""
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
async def test_content_analyzer_no_draft(mock_state_no_draft, mock_store):
    """Should skip analysis when no draft provided."""
    agent = ContentAnalyzerAgent()
    result = await agent.execute(mock_state_no_draft, mock_store)
    assert result.get("skip_analysis")


@pytest.mark.asyncio
async def test_content_analyzer_no_viral(mock_state_no_viral, mock_store):
    """Should skip analysis when no viral posts provided."""
    agent = ContentAnalyzerAgent()
    result = await agent.execute(mock_state_no_viral, mock_store)
    assert result.get("skip_analysis")


@pytest.mark.asyncio
async def test_content_analyzer_with_draft_and_viral(mock_state_with_draft_and_viral, mock_store):
    """Should analyze gap between draft and viral posts."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"optimization_analysis": {"gaps": [{"dimension": "标题", "description": "草稿标题缺乏钩子元素", "severity": "high"}], "suggestions": [{"dimension": "标题", "action": "添加数字钩子", "reasoning": "爆款笔记标题包含数字", "priority": 1}], "viral_patterns": ["标题包含数字钩子"]}}'
    ))

    with patch.object(agent, '_model', mock_model):
        _result = await agent.execute(mock_state_with_draft_and_viral, mock_store)

    assert "optimization_analysis" in result
    assert "gaps" in result["optimization_analysis"]
    assert "suggestions" in result["optimization_analysis"]
    assert "viral_patterns" in result["optimization_analysis"]


@pytest.mark.asyncio
async def test_content_analyzer_builds_viral_summary(mock_state_with_draft_and_viral, mock_store):
    """Should build viral summary JSON correctly."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"optimization_analysis": {"gaps": [], "suggestions": [], "viral_patterns": []}}'
    ))

    with patch.object(agent, '_model', mock_model):
        _result = await agent.execute(mock_state_with_draft_and_viral, mock_store)

    # Verify viral summary was built correctly
    viral_summary = agent._build_viral_summary(mock_state_with_draft_and_viral["viral_posts"])
    assert "abc123" not in viral_summary  # note_id should not be in summary
    assert "likes" in viral_summary
    assert "engagement_rate" in viral_summary


@pytest.mark.asyncio
async def test_content_analyzer_phase_update(mock_state_with_draft_and_viral, mock_store):
    """Should update phase to CREATING."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"optimization_analysis": {"gaps": [], "suggestions": [], "viral_patterns": []}}'
    ))

    with patch.object(agent, '_model', mock_model):
        _result = await agent.execute(mock_state_with_draft_and_viral, mock_store)

    assert result.get("phase") is not None


@pytest.mark.asyncio
async def test_content_analyzer_empty_viral_posts(mock_store):
    """Should skip analysis when viral_posts is empty list."""
    agent = ContentAnalyzerAgent()

    state_with_empty_viral = {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "title": "测试标题",
        },
        "viral_posts": [],  # Empty list
    }

    result = await agent.execute(state_with_empty_viral, mock_store)
    assert result.get("skip_analysis")


@pytest.mark.asyncio
async def test_content_analyzer_handles_invalid_json(mock_state_with_draft_and_viral, mock_store):
    """Should return default structure when LLM returns invalid JSON."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='Invalid response without JSON'
    ))

    with patch.object(agent, '_model', mock_model):
        _result = await agent.execute(mock_state_with_draft_and_viral, mock_store)

    assert "optimization_analysis" in result
    assert result["optimization_analysis"]["gaps"] == []
    assert result["optimization_analysis"]["suggestions"] == []


@pytest.fixture
def mock_state_with_many_viral():
    """Mock state with many viral posts (more than 5)."""
    viral_posts = []
    for i in range(10):
        viral_posts.append({
            "note_id": f"note_{i}",
            "title": f"爆款标题 {i}",
            "body": f"爆款正文 {i}",
            "hashtags": ["#爆款"],
            "likes": 10000 + i * 100,
            "collects": 5000,
            "comments": 200,
            "engagement_rate": 0.15,
            "visual_style": "minimal",
            "color_palette": {"primary": "#ffffff"},
        })
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "title": "测试标题",
        },
        "viral_posts": viral_posts,
    }


@pytest.mark.asyncio
async def test_content_analyzer_limits_viral_posts(mock_state_with_many_viral, mock_store):
    """Should limit viral summary to 5 posts."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"optimization_analysis": {"gaps": [], "suggestions": [], "viral_patterns": []}}'
    ))

    with patch.object(agent, '_model', mock_model):
        _result = await agent.execute(mock_state_with_many_viral, mock_store)

    viral_summary = agent._build_viral_summary(mock_state_with_many_viral["viral_posts"])
    summary_data = json.loads(viral_summary)
    assert len(summary_data) == 5  # Should only include 5 posts