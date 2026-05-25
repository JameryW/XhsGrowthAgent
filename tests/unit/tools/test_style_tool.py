"""Tests for enhanced style_library tool."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from xhs_growth.tools.content.style import style_library, get_default_styles, _map_category_to_content_type
from xhs_growth.models.visual_types import StyleOption, SceneAnalysisResult


# ── get_default_styles Tests ────────────────────────────────────────────────


def test_get_default_styles_returns_list() -> None:
    """Test get_default_styles returns a list of StyleOption."""
    result = get_default_styles()

    assert isinstance(result, list)
    assert len(result) > 0
    assert all(isinstance(s, StyleOption) for s in result)


def test_get_default_styles_has_expected_styles() -> None:
    """Test default styles contain expected style names."""
    result = get_default_styles()
    style_names = [s.style_name for s in result]

    assert "温暖治愈" in style_names
    assert "现代简约" in style_names
    assert "高冷高级" in style_names


def test_get_default_styles_has_pros_and_cons() -> None:
    """Test default styles have pros and cons."""
    result = get_default_styles()

    for style in result:
        assert len(style.pros) > 0
        assert len(style.cons) > 0


def test_get_default_styles_trending_scores() -> None:
    """Test default styles have valid trending scores."""
    result = get_default_styles()

    for style in result:
        assert 0.0 <= style.trending_score <= 1.0


def test_get_default_styles_has_color_palette() -> None:
    """Test default styles have color palettes."""
    result = get_default_styles()

    for style in result:
        assert len(style.color_palette) > 0


# ── _map_category_to_content_type Tests ─────────────────────────────────────


def test_map_category_known_categories() -> None:
    """Test category mapping for known categories."""
    assert _map_category_to_content_type("生活方式") == "图文笔记"
    assert _map_category_to_content_type("美食") == "图文笔记"
    assert _map_category_to_content_type("穿搭") == "图文笔记"


def test_map_category_unknown_category() -> None:
    """Test category mapping returns default for unknown."""
    assert _map_category_to_content_type("未知分类") == "图文笔记"


def test_map_category_empty_string() -> None:
    """Test category mapping handles empty string."""
    assert _map_category_to_content_type("") == "图文笔记"


# ── style_library Tool Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_style_library_returns_list() -> None:
    """Test style_library returns a list of dicts."""
    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = [
        StyleOption(
            style_name="温暖治愈",
            trending_score=0.8,
            color_palette=["#FFE4E1"],
            pros=["亲和力强"],
            cons=["不适合硬核"],
        )
    ]

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke(
            {"scene": "travel_outdoor", "limit": 10}
        )

    assert isinstance(result, list)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_style_library_calls_service() -> None:
    """Test style_library calls VisualAnalysisService."""
    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = []

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        await style_library.ainvoke(
            {"scene": "food_restaurant", "category": "美食"}
        )

    mock_service.get_style_recommendations.assert_called_once()


@pytest.mark.asyncio
async def test_style_library_converts_to_dict() -> None:
    """Test style_library converts StyleOption to dict."""
    style = StyleOption(
        style_name="现代简约",
        trending_score=0.85,
        color_palette=["#FFFFFF", "#F5F5F5"],
        pros=["干净利落"],
        cons=["可能冷淡"],
        description="干净利落,突出核心",
        suitable_for=["产品展示"],
        usage_rate=0.25,
        avg_engagement=0.05,
    )

    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = [style]

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke({"scene": "test_scene"})

    # Check dict structure
    assert isinstance(result[0], dict)
    assert result[0]["style_name"] == "现代简约"
    assert result[0]["trending_score"] == 0.85
    assert "干净利落" in result[0]["pros"]


@pytest.mark.asyncio
async def test_style_library_with_limit() -> None:
    """Test style_library respects limit parameter."""
    styles = [
        StyleOption(style_name="风格1", trending_score=0.9),
        StyleOption(style_name="风格2", trending_score=0.8),
        StyleOption(style_name="风格3", trending_score=0.7),
        StyleOption(style_name="风格4", trending_score=0.6),
        StyleOption(style_name="风格5", trending_score=0.5),
    ]

    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = styles

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke(
            {"scene": "test", "limit": 3}
        )

    assert len(result) == 3


@pytest.mark.asyncio
async def test_style_library_include_trending_sort() -> None:
    """Test style_library sorts by trending when include_trending=True."""
    styles = [
        StyleOption(style_name="低热度", trending_score=0.3),
        StyleOption(style_name="高热度", trending_score=0.9),
        StyleOption(style_name="中热度", trending_score=0.6),
    ]

    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = styles

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke(
            {"scene": "test", "include_trending": True}
        )

    # Should be sorted by trending_score descending
    assert result[0]["style_name"] == "高热度"
    assert result[1]["style_name"] == "中热度"


@pytest.mark.asyncio
async def test_style_library_exclude_trending_sort() -> None:
    """Test style_library sorts by usage_rate when include_trending=False."""
    styles = [
        StyleOption(style_name="低使用", trending_score=0.9, usage_rate=0.1),
        StyleOption(style_name="高使用", trending_score=0.3, usage_rate=0.5),
        StyleOption(style_name="中使用", trending_score=0.6, usage_rate=0.3),
    ]

    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = styles

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke(
            {"scene": "test", "include_trending": False}
        )

    # Should be sorted by usage_rate descending
    assert result[0]["style_name"] == "高使用"


@pytest.mark.asyncio
async def test_style_library_empty_recommendations() -> None:
    """Test style_library handles empty recommendations."""
    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = []

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke({"scene": "unknown_scene"})

    assert result == []


@pytest.mark.asyncio
async def test_style_library_default_parameters() -> None:
    """Test style_library with default parameters."""
    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = [
        StyleOption(style_name="默认风格", trending_score=0.5)
    ]

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke({})

    # Should work with defaults
    assert len(result) > 0


@pytest.mark.asyncio
async def test_style_library_with_category() -> None:
    """Test style_library with category parameter."""
    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = [
        StyleOption(style_name="美食风格", trending_score=0.8)
    ]

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        await style_library.ainvoke(
            {"scene": "food_restaurant", "category": "美食"}
        )

    # Service should be called
    mock_service.get_style_recommendations.assert_called_once()


# ── Integration-style Tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_style_library_full_workflow() -> None:
    """Test style_library full workflow with mock service."""
    cached_analysis = SceneAnalysisResult(
        scene="travel_outdoor",
        sample_size=100,
        style_distribution={
            "温暖治愈": 0.5,
            "现代简约": 0.3,
            "高冷高级": 0.2,
        },
        trending_styles=["温暖治愈"],
        analyzed_at=datetime.now(),
    )

    mock_database = MagicMock()
    mock_database.get_scene_analysis.return_value = cached_analysis

    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = [
        StyleOption(
            style_name="温暖治愈",
            trending_score=0.7,
            color_palette=["#FFE4E1"],
            pros=["亲和力强"],
            cons=["不适合硬核"],
            description="柔和色调",
            suitable_for=["生活记录", "美食分享"],
        ),
        StyleOption(
            style_name="现代简约",
            trending_score=0.3,
            color_palette=["#FFFFFF"],
            pros=["干净利落"],
            cons=["可能冷淡"],
            description="简洁大气",
            suitable_for=["产品展示"],
        ),
    ]

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke(
            {"scene": "travel_outdoor", "include_trending": True, "limit": 5}
        )

    assert len(result) > 0
    # Sorted by trending
    assert result[0]["trending_score"] >= result[1]["trending_score"]


# ── Edge Cases ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_style_library_zero_limit() -> None:
    """Test style_library handles zero limit."""
    styles = [
        StyleOption(style_name="风格1", trending_score=0.9),
    ]

    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = styles

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke({"scene": "test", "limit": 0})

    # Should return empty list
    assert result == []


@pytest.mark.asyncio
async def test_style_library_large_limit() -> None:
    """Test style_library handles large limit."""
    styles = [
        StyleOption(style_name=f"风格{i}", trending_score=0.9 - i * 0.1)
        for i in range(20)
    ]

    mock_service = MagicMock()
    mock_service.get_style_recommendations.return_value = styles

    with patch(
        "xhs_growth.tools.content.style.VisualAnalysisService",
        return_value=mock_service,
    ):
        result = await style_library.ainvoke({"scene": "test", "limit": 100})

    # Should return all styles (up to available count)
    assert len(result) == 20