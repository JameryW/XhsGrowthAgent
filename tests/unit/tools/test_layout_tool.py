"""Tests for enhanced layout_recommender tool."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from backend.tools.content.layout import layout_recommender, get_default_layouts
from backend.models.visual_types import LayoutOption, SceneAnalysisResult


# ── get_default_layouts Tests ────────────────────────────────────────────────


def test_get_default_layouts_returns_list() -> None:
    """Test get_default_layouts returns a list of LayoutOption."""
    result = get_default_layouts()

    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(l, LayoutOption) for l in result)


def test_get_default_layouts_has_expected_layouts() -> None:
    """Test default layouts contain expected layout types."""
    result = get_default_layouts()
    layout_types = [l.layout_type for l in result]

    assert "全图+文末" in layout_types
    assert "上下结构" in layout_types
    assert "网格布局" in layout_types


def test_get_default_layouts_has_pros_and_cons() -> None:
    """Test default layouts have pros and cons."""
    result = get_default_layouts()

    for layout in result:
        assert len(layout.pros) > 0
        assert len(layout.cons) > 0


def test_get_default_layouts_popularity_scores() -> None:
    """Test default layouts have valid popularity scores."""
    result = get_default_layouts()

    for layout in result:
        assert 0.0 <= layout.popularity_score <= 1.0


# ── layout_recommender Tool Tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_layout_recommender_returns_list() -> None:
    """Test layout_recommender returns a list of dicts."""
    # Mock the service
    mock_service = MagicMock()
    mock_service.get_layout_recommendations.return_value = [
        LayoutOption(
            layout_type="网格布局",
            description="多图网格排列",
            popularity_score=0.5,
            pros=["信息量大"],
            cons=["单图较小"],
        )
    ]

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await layout_recommender.ainvoke(
            {"scene": "travel_outdoor", "content_type": "图文笔记", "image_count": 3}
        )

    assert isinstance(result, list)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_layout_recommender_calls_service() -> None:
    """Test layout_recommender calls VisualAnalysisService."""
    mock_service = MagicMock()
    mock_service.get_layout_recommendations.return_value = []

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        await layout_recommender.ainvoke(
            {"scene": "food_restaurant", "content_type": "图文笔记", "image_count": 2}
        )

    mock_service.get_layout_recommendations.assert_called_once_with(
        scene="food_restaurant",
        content_type="图文笔记",
        image_count=2,
    )


@pytest.mark.asyncio
async def test_layout_recommender_converts_to_dict() -> None:
    """Test layout_recommender converts LayoutOption to dict."""
    layout = LayoutOption(
        layout_type="上下结构",
        description="图片上下排列",
        popularity_score=0.4,
        pros=["对比清晰"],
        cons=["占用空间大"],
        suitable_for=["前后对比"],
        text_position="below",
        avg_engagement=0.05,
    )

    mock_service = MagicMock()
    mock_service.get_layout_recommendations.return_value = [layout]

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await layout_recommender.ainvoke(
            {"scene": "test_scene", "content_type": "图文笔记"}
        )

    # Check dict structure
    assert isinstance(result[0], dict)
    assert result[0]["layout_type"] == "上下结构"
    assert result[0]["description"] == "图片上下排列"
    assert result[0]["popularity_score"] == 0.4
    assert "对比清晰" in result[0]["pros"]


@pytest.mark.asyncio
async def test_layout_recommender_with_style_filter() -> None:
    """Test layout_recommender with style parameter."""
    layouts = [
        LayoutOption(layout_type="网格布局", description="desc1", popularity_score=0.5),
        LayoutOption(layout_type="上下结构", description="desc2", popularity_score=0.3),
        LayoutOption(layout_type="全图+文末", description="desc3", popularity_score=0.2),
    ]

    mock_service = MagicMock()
    mock_service.get_layout_recommendations.return_value = layouts

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await layout_recommender.ainvoke(
            {
                "scene": "test_scene",
                "content_type": "图文笔记",
                "image_count": 3,
                "style": "现代简约",
            }
        )

    # Style filter should limit results
    assert len(result) <= 3


@pytest.mark.asyncio
async def test_layout_recommender_empty_recommendations() -> None:
    """Test layout_recommender handles empty recommendations."""
    mock_service = MagicMock()
    mock_service.get_layout_recommendations.return_value = []

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await layout_recommender.ainvoke(
            {"scene": "unknown_scene", "content_type": "图文笔记"}
        )

    # Should return empty list
    assert result == []


@pytest.mark.asyncio
async def test_layout_recommender_multiple_layouts() -> None:
    """Test layout_recommender returns multiple recommendations."""
    layouts = [
        LayoutOption(layout_type="布局1", description="desc1", popularity_score=0.6),
        LayoutOption(layout_type="布局2", description="desc2", popularity_score=0.4),
        LayoutOption(layout_type="布局3", description="desc3", popularity_score=0.3),
    ]

    mock_service = MagicMock()
    mock_service.get_layout_recommendations.return_value = layouts

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await layout_recommender.ainvoke(
            {"scene": "test_scene", "content_type": "图文笔记"}
        )

    assert len(result) == 3


@pytest.mark.asyncio
async def test_layout_recommender_default_parameters() -> None:
    """Test layout_recommender with default parameters."""
    mock_service = MagicMock()
    mock_service.get_layout_recommendations.return_value = [
        LayoutOption(layout_type="default", description="默认布局", popularity_score=0.5)
    ]

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        # Call with minimal args (default params)
        result = await layout_recommender.ainvoke({})

    # Should still work
    mock_service.get_layout_recommendations.assert_called_once_with(
        scene="general",
        content_type="图文笔记",
        image_count=3,
    )


# ── Integration-style Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_layout_recommender_full_workflow() -> None:
    """Test layout_recommender full workflow with mock service."""
    # Create a more complete mock scenario
    cached_analysis = SceneAnalysisResult(
        scene="travel_outdoor",
        sample_size=100,
        layout_distribution={
            "网格布局": 0.5,
            "上下结构": 0.3,
            "全图+文末": 0.2,
        },
        analyzed_at=datetime.now(),
    )

    mock_database = MagicMock()
    mock_database.get_scene_analysis.return_value = cached_analysis

    mock_service = MagicMock()
    # Simulate the service building layouts from distribution
    mock_service.get_layout_recommendations.return_value = [
        LayoutOption(
            layout_type="网格布局",
            description="多图网格排列",
            popularity_score=0.5,
            pros=["信息量大"],
            cons=["单图较小"],
        ),
        LayoutOption(
            layout_type="上下结构",
            description="图片上下排列",
            popularity_score=0.3,
            pros=["对比清晰"],
            cons=["占用空间大"],
        ),
    ]

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await layout_recommender.ainvoke(
            {"scene": "travel_outdoor", "content_type": "图文笔记", "image_count": 4}
        )

    # Should return layouts sorted by popularity
    assert len(result) > 0
    assert result[0]["popularity_score"] >= result[1]["popularity_score"]


# ─-- Edge Cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_layout_recommender_zero_image_count() -> None:
    """Test layout_recommender handles zero image count."""
    mock_service = MagicMock()
    mock_service.get_layout_recommendations.return_value = []

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await layout_recommender.ainvoke(
            {"scene": "test", "content_type": "图文笔记", "image_count": 0}
        )

    mock_service.get_layout_recommendations.assert_called_once_with(
        scene="test",
        content_type="图文笔记",
        image_count=0,
    )


@pytest.mark.asyncio
async def test_layout_recommender_large_image_count() -> None:
    """Test layout_recommender handles large image count."""
    mock_service = MagicMock()
    mock_service.get_layout_recommendations.return_value = [
        LayoutOption(layout_type="轮播图", description="多图", popularity_score=0.8),
    ]

    with patch(
        "backend.tools.content.layout.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await layout_recommender.ainvoke(
            {"scene": "test", "content_type": "轮播图", "image_count": 10}
        )

    assert len(result) > 0