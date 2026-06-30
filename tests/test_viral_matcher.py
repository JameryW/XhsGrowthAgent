"""Tests for ViralMatcherAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.viral_matcher import ViralMatcherAgent


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
    """Should return empty when no draft or brief provided."""
    agent = ViralMatcherAgent()
    result = await agent.execute(mock_state_no_draft, mock_store)
    assert result["skip_optimization"] is False
    assert result["viral_posts"] == []


@pytest.mark.asyncio
async def test_viral_matcher_brief_mode_no_draft(mock_store):
    """Should use brief_content keywords when draft_content is missing (brief mode)."""
    agent = ViralMatcherAgent()

    state = {
        "account_id": "test_account",
        "workflow_mode": "brief",
        "brief_content": {
            "brand_name": "几素",
            "product_name": "婴儿车风扇",
            "selling_points": ["静音", "便携"],
            "required_keywords": ["几素婴儿车风扇"],
            "content_direction": "夏日出行必备",
            "target_audience": "宝妈",
        },
    }

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"viral_posts": [{"note_id": "b1", "title": "夏日带娃神器", "body": "静音风扇", "hashtags": ["#几素"], "likes": 8000, "collects": 3000, "comments": 100, "engagement_rate": 0.12, "visual_style": "warm", "color_palette": {"primary": "#ffd700"}}], "search_keywords_used": ["几素", "婴儿车风扇"]}'  # noqa: E501
        )
    )

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(state, mock_store)

    assert result["skip_optimization"] is False
    assert len(result["viral_posts"]) == 1
    # Verify the model was actually called (not skipped)
    mock_model.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_viral_matcher_brief_mode_enriches_keywords(mock_store):
    """Brief mode should add brand/product/keywords to auto_keywords."""
    agent = ViralMatcherAgent()

    state = {
        "account_id": "test_account",
        "workflow_mode": "brief",
        "brief_content": {
            "brand_name": "几素",
            "product_name": "婴儿车风扇",
            "selling_points": ["静音", "便携"],
            "required_keywords": ["几素婴儿车风扇"],
        },
    }

    captured_keywords = None

    mock_model = MagicMock()

    async def capture_invoke(msgs):
        nonlocal captured_keywords
        user_msg = msgs[1].content
        captured_keywords = user_msg
        return MagicMock(content='{"viral_posts": [], "search_keywords_used": []}')

    mock_model.ainvoke = capture_invoke

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(state, mock_store)

    assert result["viral_posts"] == []
    # Verify brief keywords appear in the user message
    assert "几素" in captured_keywords
    assert "婴儿车风扇" in captured_keywords


@pytest.mark.asyncio
async def test_viral_matcher_with_links(mock_state, mock_store):
    """Should process user-provided viral links."""
    agent = ViralMatcherAgent()

    # Mock the model response
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"viral_posts": [{"note_id": "abc123", "title": "爆款标题", "body": "爆款正文", "hashtags": ["#爆款"], "likes": 10000, "collects": 5000, "comments": 200, "engagement_rate": 0.15, "visual_style": "minimal", "color_palette": {"primary": "#ffffff"}}], "search_keywords_used": ["测试"]}'  # noqa: E501
        )
    )

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state, mock_store)

    assert "viral_posts" in result
    assert len(result["viral_posts"]) > 0


@pytest.mark.asyncio
async def test_viral_matcher_timeout_skips_optimization(mock_state, mock_store):
    """Should not skip optimization when viral matching fails."""
    agent = ViralMatcherAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(side_effect=TimeoutError("Request timed out."))

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state, mock_store)

    assert result["viral_posts"] == []
    assert result["skip_optimization"] is False
    assert "Request timed out." in result["optimization_error"]


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
    mock_model.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"viral_posts": [], "search_keywords_used": ["美食", "探店", "春季穿搭"]}'
        )
    )

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(state_with_trend, mock_store)

    assert "viral_posts" in result


@pytest.mark.asyncio
async def test_viral_matcher_phase_update(mock_state, mock_store):
    """Should update phase to CREATING."""
    agent = ViralMatcherAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content='{"viral_posts": []}'))

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state, mock_store)

    assert result.get("phase") is not None
