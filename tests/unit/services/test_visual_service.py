"""Tests for VisualAnalysisService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.memory.scene_database import SceneDatabase
from backend.models.visual_types import (
    ColorPalette,
    LayoutOption,
    SceneAnalysisResult,
    StyleOption,
)
from backend.services.visual_analysis import VisualAnalysisService
from backend.services.visual_extractor import VisualDataExtractor
from backend.services.xhs_client import XHSClient, XHSSearchResult

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client() -> MagicMock:
    """Create mock XHSClient."""
    client = MagicMock(spec=XHSClient)
    client.search_posts = AsyncMock()
    return client


@pytest.fixture
def mock_database() -> MagicMock:
    """Create mock SceneDatabase."""
    database = MagicMock(spec=SceneDatabase)
    database.get_scene_analysis = MagicMock(return_value=None)
    database.save_scene_analysis = MagicMock()
    database.get_default_layouts = MagicMock(return_value=[])
    database.get_default_styles = MagicMock(return_value=[])
    return database


@pytest.fixture
def mock_extractor() -> MagicMock:
    """Create mock VisualDataExtractor."""
    extractor = MagicMock(spec=VisualDataExtractor)
    extractor.classify_visual_style = MagicMock(return_value="温暖治愈")
    extractor.detect_layout_type = MagicMock(return_value="网格布局")
    extractor.extract_color_palette = MagicMock(
        return_value=ColorPalette(
            primary_colors=["#FFE4E1", "#FFDAB9"],
            secondary_colors=["#F5DEB3"],
            color_ratios={"primary": 0.6, "secondary": 0.4},
        )
    )
    extractor.identify_visual_elements = MagicMock(return_value={})
    return extractor


@pytest.fixture
def service(
    mock_client: MagicMock,
    mock_database: MagicMock,
    mock_extractor: MagicMock,
) -> VisualAnalysisService:
    """Create VisualAnalysisService with mocked dependencies."""
    return VisualAnalysisService(
        client=mock_client,
        database=mock_database,
        extractor=mock_extractor,
    )


@pytest.fixture
def sample_posts() -> list[XHSSearchResult]:
    """Create sample search results."""
    return [
        XHSSearchResult(
            note_id="note_1",
            title="旅行日记",
            user_name="user1",
            user_id="uid1",
            likes=100,
            comments=20,
            collects=50,
            cover_url="https://example.com/image1.jpg",
        ),
        XHSSearchResult(
            note_id="note_2",
            title="美食分享",
            user_name="user2",
            user_id="uid2",
            likes=200,
            comments=30,
            collects=80,
            cover_url="https://example.com/image2.jpg",
        ),
        XHSSearchResult(
            note_id="note_3",
            title="穿搭推荐",
            user_name="user3",
            user_id="uid3",
            likes=150,
            comments=25,
            collects=60,
            cover_url="https://example.com/image3.jpg",
        ),
    ]


@pytest.fixture
def cached_analysis() -> SceneAnalysisResult:
    """Create cached analysis result."""
    return SceneAnalysisResult(
        scene="travel_outdoor",
        sample_size=100,
        style_distribution={"温暖治愈": 0.5, "现代简约": 0.3, "高冷高级": 0.2},
        layout_distribution={"网格布局": 0.4, "上下结构": 0.3, "全图+文末": 0.3},
        color_palettes=[
            ColorPalette(
                primary_colors=["#FFE4E1", "#FFDAB9"],
                secondary_colors=["#F5DEB3"],
                color_ratios={"primary": 0.6},
            )
        ],
        visual_elements={"icons": 50, "text_overlay": 30},
        trending_styles=["温暖治愈", "现代简约"],
        trending_layouts=["网格布局", "上下结构"],
        analyzed_at=datetime.now(),
    )


# ── analyze_scene Tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_scene_returns_cached_result(
    service: VisualAnalysisService,
    mock_database: MagicMock,
    cached_analysis: SceneAnalysisResult,
) -> None:
    """Test analyze_scene returns cached result when available."""
    # Setup: Return cached analysis
    mock_database.get_scene_analysis.return_value = cached_analysis

    # Execute
    result = await service.analyze_scene("travel_outdoor", limit=100)

    # Verify
    assert result.scene == "travel_outdoor"
    assert result.sample_size == 100
    assert result.style_distribution == cached_analysis.style_distribution
    # Should NOT call search_posts
    service._client.search_posts.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_scene_fetches_and_analyzes_posts(
    service: VisualAnalysisService,
    mock_client: MagicMock,
    mock_database: MagicMock,
    mock_extractor: MagicMock,
    sample_posts: list[XHSSearchResult],
) -> None:
    """Test analyze_scene fetches posts when no cached result."""
    # Setup
    mock_client.search_posts.return_value = sample_posts
    mock_database.get_scene_analysis.return_value = None

    # Execute
    result = await service.analyze_scene("travel_outdoor", limit=50)

    # Verify
    assert result.scene == "travel_outdoor"
    assert result.sample_size == 3
    mock_client.search_posts.assert_called_once_with(
        keyword="旅行户外",
        limit=50,
    )
    # Extractor should be called for each post
    assert mock_extractor.classify_visual_style.call_count == 3
    assert mock_extractor.detect_layout_type.call_count == 3
    # Result should be saved
    mock_database.save_scene_analysis.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_scene_handles_empty_posts(
    service: VisualAnalysisService,
    mock_client: MagicMock,
    mock_database: MagicMock,
) -> None:
    """Test analyze_scene handles empty search results."""
    # Setup
    mock_client.search_posts.return_value = []
    mock_database.get_scene_analysis.return_value = None

    # Execute
    result = await service.analyze_scene("unknown_scene", limit=100)

    # Verify
    assert result.scene == "unknown_scene"
    assert result.sample_size == 0
    assert result.style_distribution == {}
    assert result.layout_distribution == {}


@pytest.mark.asyncio
async def test_analyze_scene_calculates_distributions(
    service: VisualAnalysisService,
    mock_client: MagicMock,
    mock_database: MagicMock,
    mock_extractor: MagicMock,
    sample_posts: list[XHSSearchResult],
) -> None:
    """Test analyze_scene calculates correct distributions."""
    # Setup
    mock_client.search_posts.return_value = sample_posts
    mock_database.get_scene_analysis.return_value = None
    # Different styles for different posts
    mock_extractor.classify_visual_style.side_effect = [
        "温暖治愈",
        "现代简约",
        "温暖治愈",
    ]
    mock_extractor.detect_layout_type.side_effect = [
        "网格布局",
        "上下结构",
        "网格布局",
    ]

    # Execute
    result = await service.analyze_scene("travel_outdoor")

    # Verify distributions
    assert result.style_distribution["温暖治愈"] == 2 / 3
    assert result.style_distribution["现代简约"] == 1 / 3
    assert result.layout_distribution["网格布局"] == 2 / 3
    assert result.layout_distribution["上下结构"] == 1 / 3
    # Trending items
    assert "温暖治愈" in result.trending_styles
    assert "网格布局" in result.trending_layouts


@pytest.mark.asyncio
async def test_analyze_scene_maps_scene_to_keyword(
    service: VisualAnalysisService,
    mock_client: MagicMock,
    mock_database: MagicMock,
) -> None:
    """Test scene to keyword mapping."""
    mock_client.search_posts.return_value = []
    mock_database.get_scene_analysis.return_value = None

    # Test various scenes
    scenes_to_test = {
        "travel_outdoor": "旅行户外",
        "food_restaurant": "美食探店",
        "fashion_outfit": "穿搭分享",
        "lifestyle_home": "家居生活",
    }

    for scene, expected_keyword in scenes_to_test.items():
        mock_client.search_posts.reset_mock()
        await service.analyze_scene(scene)
        mock_client.search_posts.assert_called_once_with(
            keyword=expected_keyword,
            limit=100,
        )


# ── get_layout_recommendations Tests ─────────────────────────────────────────


def test_get_layout_recommendations_from_analysis(
    service: VisualAnalysisService,
    mock_database: MagicMock,
    cached_analysis: SceneAnalysisResult,
) -> None:
    """Test get_layout_recommendations uses cached analysis."""
    mock_database.get_scene_analysis.return_value = cached_analysis

    result = service.get_layout_recommendations(
        scene="travel_outdoor",
        content_type="图文笔记",
        image_count=3,
    )

    # Should return LayoutOption objects
    assert len(result) > 0
    assert all(isinstance(lo, LayoutOption) for lo in result)
    # Should be sorted by popularity
    assert result[0].popularity_score >= result[1].popularity_score


def test_get_layout_recommendations_falls_back_to_defaults(
    service: VisualAnalysisService,
    mock_database: MagicMock,
) -> None:
    """Test get_layout_recommendations falls back to defaults when no analysis."""
    mock_database.get_scene_analysis.return_value = None
    mock_database.get_default_layouts.return_value = [
        LayoutOption(
            layout_type="默认布局",
            description="默认描述",
            popularity_score=0.5,
        )
    ]

    result = service.get_layout_recommendations(
        scene="unknown_scene",
        content_type="图文笔记",
    )

    mock_database.get_default_layouts.assert_called_once_with("unknown_scene")
    assert len(result) > 0


def test_get_layout_recommendations_filters_by_content_type(
    service: VisualAnalysisService,
    mock_database: MagicMock,
) -> None:
    """Test layout recommendations are filtered by content type."""
    # Create analysis with multiple layouts
    cached = SceneAnalysisResult(
        scene="travel_outdoor",
        sample_size=100,
        layout_distribution={
            "全图+文末": 0.5,
            "上下结构": 0.3,
            "轮播图": 0.2,
        },
        analyzed_at=datetime.now(),
    )
    mock_database.get_scene_analysis.return_value = cached

    # Request for 图文笔记 with 1 image
    result = service.get_layout_recommendations(
        scene="travel_outdoor",
        content_type="图文笔记",
        image_count=1,
    )

    # Should prefer "全图+文末" for single image
    assert all(lo.layout_type in ["全图+文末", "封面突出"] for lo in result)


def test_get_layout_recommendations_filters_by_image_count(
    service: VisualAnalysisService,
    mock_database: MagicMock,
) -> None:
    """Test layout recommendations are filtered by image count."""
    cached = SceneAnalysisResult(
        scene="travel_outdoor",
        sample_size=100,
        layout_distribution={
            "全图+文末": 0.3,
            "上下结构": 0.3,
            "网格布局": 0.4,
        },
        analyzed_at=datetime.now(),
    )
    mock_database.get_scene_analysis.return_value = cached

    # 2 images should prefer 上下结构
    result = service.get_layout_recommendations(
        scene="travel_outdoor",
        content_type="图文笔记",
        image_count=2,
    )

    # Should include layouts suitable for 2 images
    assert len(result) > 0


# ── get_style_recommendations Tests ───────────────────────────────────────────


def test_get_style_recommendations_from_analysis(
    service: VisualAnalysisService,
    mock_database: MagicMock,
    cached_analysis: SceneAnalysisResult,
) -> None:
    """Test get_style_recommendations uses cached analysis."""
    mock_database.get_scene_analysis.return_value = cached_analysis

    result = service.get_style_recommendations(
        scene="travel_outdoor",
        content_type="图文笔记",
    )

    # Should return StyleOption objects
    assert len(result) > 0
    assert all(isinstance(s, StyleOption) for s in result)
    # Should be sorted by trending score
    assert result[0].trending_score >= result[1].trending_score


def test_get_style_recommendations_falls_back_to_defaults(
    service: VisualAnalysisService,
    mock_database: MagicMock,
) -> None:
    """Test get_style_recommendations falls back to defaults when no analysis."""
    mock_database.get_scene_analysis.return_value = None
    mock_database.get_default_styles.return_value = [
        StyleOption(
            style_name="默认风格",
            trending_score=0.5,
        )
    ]

    result = service.get_style_recommendations(
        scene="unknown_scene",
        content_type="图文笔记",
    )

    mock_database.get_default_styles.assert_called_once_with("unknown_scene")
    assert len(result) > 0


def test_get_style_recommendations_filters_by_content_type(
    service: VisualAnalysisService,
    mock_database: MagicMock,
) -> None:
    """Test style recommendations are filtered by content type suitability."""
    cached = SceneAnalysisResult(
        scene="travel_outdoor",
        sample_size=100,
        style_distribution={
            "温暖治愈": 0.5,
            "高冷高级": 0.3,
        },
        trending_styles=["温暖治愈"],
        analyzed_at=datetime.now(),
    )
    mock_database.get_scene_analysis.return_value = cached

    result = service.get_style_recommendations(
        scene="travel_outdoor",
        content_type="图文笔记",
    )

    # Should return styles suitable for the content type
    assert len(result) > 0


def test_get_style_recommendations_boosts_trending_styles(
    service: VisualAnalysisService,
    mock_database: MagicMock,
) -> None:
    """Test trending styles get boosted scores."""
    cached = SceneAnalysisResult(
        scene="travel_outdoor",
        sample_size=100,
        style_distribution={
            "温暖治愈": 0.3,
            "现代简约": 0.3,
        },
        trending_styles=["温暖治愈"],
        analyzed_at=datetime.now(),
    )
    mock_database.get_scene_analysis.return_value = cached

    result = service.get_style_recommendations("travel_outdoor")

    # Find the trending style
    warm_healing = next(s for s in result if s.style_name == "温暖治愈")
    # Trending score should be boosted
    assert warm_healing.trending_score > 0.3


# ── Helper Method Tests ───────────────────────────────────────────────────────


def test_map_scene_to_keyword_known_scenes(
    service: VisualAnalysisService,
) -> None:
    """Test scene to keyword mapping for known scenes."""
    assert service._map_scene_to_keyword("travel_outdoor") == "旅行户外"
    assert service._map_scene_to_keyword("food_restaurant") == "美食探店"
    assert service._map_scene_to_keyword("fashion_outfit") == "穿搭分享"


def test_map_scene_to_keyword_unknown_scene(
    service: VisualAnalysisService,
) -> None:
    """Test scene to keyword mapping returns original for unknown."""
    assert service._map_scene_to_keyword("unknown_scene") == "unknown_scene"


def test_build_layout_options_from_distribution(
    service: VisualAnalysisService,
) -> None:
    """Test building LayoutOption objects from distribution."""
    distribution = {
        "网格布局": 0.5,
        "上下结构": 0.3,
        "全图+文末": 0.2,
    }

    result = service._build_layout_options_from_distribution(
        distribution=distribution,
        sample_size=100,
    )

    assert len(result) == 3
    assert all(isinstance(lo, LayoutOption) for lo in result)
    # Check sorted by popularity
    assert result[0].layout_type == "网格布局"
    assert result[0].popularity_score == 0.5


def test_build_style_options_from_distribution(
    service: VisualAnalysisService,
) -> None:
    """Test building StyleOption objects from distribution."""
    distribution = {
        "温暖治愈": 0.5,
        "现代简约": 0.3,
    }
    trending_styles = ["温暖治愈"]
    color_palettes = [
        ColorPalette(primary_colors=["#FFE4E1", "#FFDAB9"]),
    ]

    result = service._build_style_options_from_distribution(
        distribution=distribution,
        trending_styles=trending_styles,
        color_palettes=color_palettes,
        sample_size=100,
    )

    assert len(result) == 2
    assert all(isinstance(s, StyleOption) for s in result)
    # Check sorted by trending score
    assert result[0].style_name == "温暖治愈"
    # Trending boost applied
    assert result[0].trending_score > 0.5


def test_get_content_keywords(
    service: VisualAnalysisService,
) -> None:
    """Test content keyword extraction."""
    keywords = service._get_content_keywords("图文笔记")
    assert "干货分享" in keywords
    assert "教程" in keywords

    keywords = service._get_content_keywords("轮播图")
    assert "教程攻略" in keywords


# ── Integration Tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_workflow_analyze_then_recommend(
    service: VisualAnalysisService,
    mock_client: MagicMock,
    mock_database: MagicMock,
    mock_extractor: MagicMock,
    sample_posts: list[XHSSearchResult],
) -> None:
    """Test full workflow: analyze scene, then get recommendations."""
    # Setup
    mock_client.search_posts.return_value = sample_posts
    mock_database.get_scene_analysis.return_value = None

    # Step 1: Analyze scene
    analysis = await service.analyze_scene("travel_outdoor")
    assert analysis.sample_size > 0

    # Step 2: Now database should have the analysis saved
    # Simulate getting it back
    mock_database.get_scene_analysis.return_value = analysis

    # Step 3: Get recommendations
    _layouts = service.get_layout_recommendations("travel_outdoor")
    _styles = service.get_style_recommendations("travel_outdoor")

    assert len(layouts) > 0
    assert len(styles) > 0


# ── Edge Cases ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_scene_with_posts_without_images(
    service: VisualAnalysisService,
    mock_client: MagicMock,
    mock_database: MagicMock,
    mock_extractor: MagicMock,
) -> None:
    """Test analyze_scene handles posts without cover images."""
    # Posts without cover_url
    posts = [
        XHSSearchResult(
            note_id="note_1",
            title="文字笔记",
            user_name="user1",
            user_id="uid1",
            likes=100,
            comments=20,
            collects=50,
            cover_url="",  # No image
        )
    ]
    mock_client.search_posts.return_value = posts
    mock_database.get_scene_analysis.return_value = None

    result = await service.analyze_scene("travel_outdoor")

    # Should still work with empty image list
    assert result.sample_size == 1


def test_get_recommendations_with_empty_analysis(
    service: VisualAnalysisService,
    mock_database: MagicMock,
) -> None:
    """Test recommendations handle analysis with empty distributions."""
    cached = SceneAnalysisResult(
        scene="travel_outdoor",
        sample_size=30,
        style_distribution={},  # Empty
        layout_distribution={},  # Empty
        analyzed_at=datetime.now(),
    )
    mock_database.get_scene_analysis.return_value = cached
    mock_database.get_default_layouts.return_value = [
        LayoutOption(layout_type="default", description="默认", popularity_score=0.5)
    ]
    mock_database.get_default_styles.return_value = [
        StyleOption(style_name="default", trending_score=0.5)
    ]

    _layouts = service.get_layout_recommendations("travel_outdoor")
    _styles = service.get_style_recommendations("travel_outdoor")

    # Should fall back to defaults
    mock_database.get_default_layouts.assert_called()
    mock_database.get_default_styles.assert_called()