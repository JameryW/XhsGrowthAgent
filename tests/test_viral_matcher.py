"""Tests for ViralMatcherAgent."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from xhs_growth.agents.viral_matcher import ViralMatcherAgent
from xhs_growth.state.schema import XHSGrowthState


@pytest.fixture
def mock_state():
    """Mock state with draft content."""
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "images": [],
            "title": "测试标题",
            "hashtags": ["#测试"],
            "provided_at": "2026-05-26T10:00:00",
        },
        "user_viral_links": ["https://xiaohongshu.com/explore/abc123"],
    }


@pytest.fixture
def mock_state_no_draft():
    """Mock state without draft content."""
    return {
        "account_id": "test_account",
    }


@pytest.fixture
def mock_store():
    """Mock BaseStore."""
    store = MagicMock()
    store.asearch = AsyncMock(return_value=[])
    return store


@pytest.mark.asyncio
async def test_viral_matcher_no_draft(mock_state_no_draft, mock_store):
    """Should skip optimization when no draft provided."""
    agent = ViralMatcherAgent()
    result = await agent.execute(mock_state_no_draft, mock_store)
    assert result.get("skip_optimization") == True


@pytest.mark.asyncio
async def test_viral_matcher_with_links(mock_state, mock_store):
    """Should process user-provided viral links."""
    agent = ViralMatcherAgent()

    # Mock the model response
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"viral_posts": [{"note_id": "abc123", "title": "爆款标题", "body": "爆款正文", "hashtags": ["#爆款"], "likes": 10000, "collects": 5000, "comments": 200, "engagement_rate": 0.15, "visual_style": "minimal", "color_palette": {"primary": "#ffffff"}}], "search_keywords_used": ["测试"]}'
    ))

    with patch.object(agent, '_model', mock_model):
        result = await agent.execute(mock_state, mock_store)

    assert "viral_posts" in result
    assert len(result["viral_posts"]) > 0


@pytest.mark.asyncio
async def test_viral_matcher_auto_keywords(mock_store):
    """Should use trend data keywords for auto-search."""
    agent = ViralMatcherAgent()

    state_with_trend = {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "title": "测试标题",
        },
        "trend_data": {
            "trending_keywords": ["美食", "探店"],
        },
        "content_plan": {
            "selected_topic": "春季穿搭",
        },
    }

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"viral_posts": [], "search_keywords_used": ["美食", "探店", "春季穿搭"]}'
    ))

    with patch.object(agent, '_model', mock_model):
        result = await agent.execute(state_with_trend, mock_store)

    assert "viral_posts" in result


@pytest.mark.asyncio
async def test_viral_matcher_phase_update(mock_state, mock_store):
    """Should update phase to CREATING."""
    agent = ViralMatcherAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(
        content='{"viral_posts": []}'
    ))

    with patch.object(agent, '_model', mock_model):
        result = await agent.execute(mock_state, mock_store)

    assert result.get("phase") is not None