"""Tests for visual data types.

Following TDD: This test file is created BEFORE the implementation
to verify the data structures exist and behave correctly.
"""

import pytest
from datetime import datetime


class TestColorPalette:
    """Tests for ColorPalette dataclass."""

    def test_color_palette_creation(self):
        """Test ColorPalette can be created with required fields."""
        from backend.models.visual_types import ColorPalette

        palette = ColorPalette(
            primary_colors=["#FF6B6B", "#4ECDC4", "#45B7D1"],
            secondary_colors=["#F7F7F7", "#2C3E50"],
            color_ratios={"primary": 0.7, "secondary": 0.3},
        )

        assert palette.primary_colors == ["#FF6B6B", "#4ECDC4", "#45B7D1"]
        assert palette.secondary_colors == ["#F7F7F7", "#2C3E50"]
        assert palette.color_ratios == {"primary": 0.7, "secondary": 0.3}

    def test_color_palette_defaults(self):
        """Test ColorPalette default values."""
        from backend.models.visual_types import ColorPalette

        palette = ColorPalette(
            primary_colors=["#FF6B6B"],
            secondary_colors=[],
            color_ratios={},
        )

        assert palette.primary_colors == ["#FF6B6B"]
        assert palette.secondary_colors == []
        assert palette.color_ratios == {}

    def test_color_palette_to_dict(self):
        """Test ColorPalette has to_dict() method."""
        from backend.models.visual_types import ColorPalette

        palette = ColorPalette(
            primary_colors=["#FF6B6B"],
            secondary_colors=["#F7F7F7"],
            color_ratios={"primary": 0.8},
        )

        result_dict = palette.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["primary_colors"] == ["#FF6B6B"]
        assert result_dict["secondary_colors"] == ["#F7F7F7"]
        assert result_dict["color_ratios"] == {"primary": 0.8}


class TestLayoutOption:
    """Tests for LayoutOption dataclass."""

    def test_layout_option_creation_all_fields(self):
        """Test LayoutOption can be created with all 10 required fields."""
        from backend.models.visual_types import LayoutOption

        layout = LayoutOption(
            layout_type="grid_3x3",
            description="3x3 grid layout for product showcase",
            popularity_score=0.85,
            pros=["Clear organization", "Good for multiple products"],
            cons=["May look crowded", "Fixed structure"],
            reference_posts=[
                {"note_id": "note_1", "title": "Great post", "likes": 1000, "url": "https://xhs.com/note_1"},
                {"note_id": "note_2", "title": "Another post", "likes": 500, "url": "https://xhs.com/note_2"},
            ],
            suitable_for=["product_review", "comparison"],
            image_sequence_strategy="impact_first",
            text_position="overlay",
            avg_engagement=0.12,
        )

        # Check all 10 fields
        assert layout.layout_type == "grid_3x3"
        assert layout.description == "3x3 grid layout for product showcase"
        assert layout.popularity_score == 0.85
        assert layout.pros == ["Clear organization", "Good for multiple products"]
        assert layout.cons == ["May look crowded", "Fixed structure"]
        assert layout.reference_posts == [
            {"note_id": "note_1", "title": "Great post", "likes": 1000, "url": "https://xhs.com/note_1"},
            {"note_id": "note_2", "title": "Another post", "likes": 500, "url": "https://xhs.com/note_2"},
        ]
        assert layout.suitable_for == ["product_review", "comparison"]
        assert layout.image_sequence_strategy == "impact_first"
        assert layout.text_position == "overlay"
        assert layout.avg_engagement == 0.12

    def test_layout_option_defaults(self):
        """Test LayoutOption default values for optional fields."""
        from backend.models.visual_types import LayoutOption

        layout = LayoutOption(
            layout_type="single_image",
            description="Single focal image",
            popularity_score=0.9,
            pros=["Simple and clean"],
            cons=["Limited content"],
        )

        assert layout.reference_posts == []
        assert layout.suitable_for == []
        assert layout.image_sequence_strategy == ""
        assert layout.text_position == ""
        assert layout.avg_engagement == 0.0

    def test_layout_option_to_dict(self):
        """Test LayoutOption has to_dict() method with all fields."""
        from backend.models.visual_types import LayoutOption

        layout = LayoutOption(
            layout_type="carousel",
            description="Carousel swipe layout",
            popularity_score=0.75,
            pros=["Interactive"],
            cons=["Requires engagement"],
            reference_posts=[{"note_id": "p1", "title": "Test", "likes": 100, "url": "https://xhs.com/p1"}],
            suitable_for=["storytelling"],
            image_sequence_strategy="chronological",
            text_position="below",
            avg_engagement=0.08,
        )

        result_dict = layout.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["layout_type"] == "carousel"
        assert result_dict["description"] == "Carousel swipe layout"
        assert result_dict["popularity_score"] == 0.75
        assert result_dict["pros"] == ["Interactive"]
        assert result_dict["cons"] == ["Requires engagement"]
        assert result_dict["reference_posts"] == [{"note_id": "p1", "title": "Test", "likes": 100, "url": "https://xhs.com/p1"}]
        assert result_dict["suitable_for"] == ["storytelling"]
        assert result_dict["image_sequence_strategy"] == "chronological"
        assert result_dict["text_position"] == "below"
        assert result_dict["avg_engagement"] == 0.08


class TestStyleOption:
    """Tests for StyleOption dataclass."""

    def test_style_option_creation_all_fields(self):
        """Test StyleOption can be created with all 10 required fields."""
        from backend.models.visual_types import StyleOption

        style = StyleOption(
            style_name="minimalist_clean",
            trending_score=0.78,
            color_palette=["#FFE4E1", "#FFDAB9", "#FFFACD"],
            pros=["Modern look", "Easy to read"],
            cons=["May lack personality"],
            description="Clean minimalist style with muted colors",
            suitable_for=["tech", "lifestyle", "education"],
            usage_rate=0.35,
            avg_engagement=0.09,
            reference_posts=[
                {"post_id": "post_1", "engagement": 0.11},
                {"post_id": "post_2", "engagement": 0.08},
            ],
        )

        # Check all 10 fields
        assert style.style_name == "minimalist_clean"
        assert style.trending_score == 0.78
        assert style.color_palette == ["#FFE4E1", "#FFDAB9", "#FFFACD"]
        assert style.pros == ["Modern look", "Easy to read"]
        assert style.cons == ["May lack personality"]
        assert style.description == "Clean minimalist style with muted colors"
        assert style.suitable_for == ["tech", "lifestyle", "education"]
        assert style.usage_rate == 0.35
        assert style.avg_engagement == 0.09
        assert style.reference_posts == [
            {"post_id": "post_1", "engagement": 0.11},
            {"post_id": "post_2", "engagement": 0.08},
        ]

    def test_style_option_with_empty_palette(self):
        """Test StyleOption can have empty color_palette."""
        from backend.models.visual_types import StyleOption

        style = StyleOption(
            style_name="vintage_warm",
            trending_score=0.65,
            color_palette=[],
            pros=["Emotional appeal"],
            cons=["May not suit modern audience"],
        )

        assert style.color_palette == []

    def test_style_option_defaults(self):
        """Test StyleOption default values for optional fields."""
        from backend.models.visual_types import StyleOption

        style = StyleOption(
            style_name="bold_colorful",
            trending_score=0.5,
            pros=["Eye-catching"],
            cons=["May overwhelm"],
        )

        assert style.color_palette == []
        assert style.description == ""
        assert style.suitable_for == []
        assert style.usage_rate == 0.0
        assert style.avg_engagement == 0.0
        assert style.reference_posts == []

    def test_style_option_to_dict(self):
        """Test StyleOption has to_dict() method with all fields."""
        from backend.models.visual_types import StyleOption

        style = StyleOption(
            style_name="minimalist_clean",
            trending_score=0.78,
            color_palette=["#FFE4E1", "#FFDAB9"],
            pros=["Modern"],
            cons=["Plain"],
            description="Minimalist aesthetic",
            suitable_for=["tech"],
            usage_rate=0.25,
            avg_engagement=0.07,
            reference_posts=[{"post_id": "p1", "engagement": 0.07}],
        )

        result_dict = style.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["style_name"] == "minimalist_clean"
        assert result_dict["trending_score"] == 0.78
        assert result_dict["color_palette"] == ["#FFE4E1", "#FFDAB9"]
        assert result_dict["pros"] == ["Modern"]
        assert result_dict["cons"] == ["Plain"]
        assert result_dict["description"] == "Minimalist aesthetic"
        assert result_dict["suitable_for"] == ["tech"]
        assert result_dict["usage_rate"] == 0.25
        assert result_dict["avg_engagement"] == 0.07
        assert result_dict["reference_posts"] == [{"post_id": "p1", "engagement": 0.07}]

    def test_style_option_to_dict_with_empty_palette(self):
        """Test StyleOption to_dict() with empty color_palette."""
        from backend.models.visual_types import StyleOption

        style = StyleOption(
            style_name="vintage",
            trending_score=0.6,
            color_palette=[],
            pros=["Nostalgic"],
            cons=["Limited appeal"],
            description="Vintage style",
            suitable_for=["fashion"],
            usage_rate=0.15,
            avg_engagement=0.05,
            reference_posts=[],
        )

        result_dict = style.to_dict()

        assert result_dict["color_palette"] == []


class TestSceneAnalysisResult:
    """Tests for SceneAnalysisResult dataclass."""

    def test_scene_analysis_result_creation_all_fields(self):
        """Test SceneAnalysisResult can be created with all 9 required fields."""
        from backend.models.visual_types import SceneAnalysisResult, ColorPalette

        palettes = [
            ColorPalette(
                primary_colors=["#FF6B6B"],
                secondary_colors=["#F7F7F7"],
                color_ratios={"primary": 0.8},
            ),
            ColorPalette(
                primary_colors=["#4ECDC4"],
                secondary_colors=["#2C3E50"],
                color_ratios={"primary": 0.6},
            ),
        ]

        analyzed_time = datetime(2026, 5, 23, 12, 30, 0)

        result = SceneAnalysisResult(
            scene="travel_outdoor",
            sample_size=1000,
            style_distribution={"minimalist": 0.35, "vintage": 0.25, "bold": 0.40},
            layout_distribution={"grid_3x3": 0.40, "carousel": 0.35, "single": 0.25},
            color_palettes=palettes,
            visual_elements={"icons": 50, "text_overlay": 30, "graphics": 20},
            trending_styles=["minimalist", "vintage_warm"],
            trending_layouts=["grid_3x3", "carousel"],
            analyzed_at=analyzed_time,
        )

        # Check all 9 fields
        assert result.scene == "travel_outdoor"
        assert result.sample_size == 1000
        assert result.style_distribution == {"minimalist": 0.35, "vintage": 0.25, "bold": 0.40}
        assert result.layout_distribution == {"grid_3x3": 0.40, "carousel": 0.35, "single": 0.25}
        assert result.color_palettes == palettes
        assert result.visual_elements == {"icons": 50, "text_overlay": 30, "graphics": 20}
        assert result.trending_styles == ["minimalist", "vintage_warm"]
        assert result.trending_layouts == ["grid_3x3", "carousel"]
        assert result.analyzed_at == analyzed_time

    def test_scene_analysis_result_defaults(self):
        """Test SceneAnalysisResult default values for optional fields."""
        from backend.models.visual_types import SceneAnalysisResult

        result = SceneAnalysisResult(
            scene="food_restaurant",
            sample_size=500,
        )

        assert result.style_distribution == {}
        assert result.layout_distribution == {}
        assert result.color_palettes == []
        assert result.visual_elements == {}
        assert result.trending_styles == []
        assert result.trending_layouts == []
        assert result.analyzed_at is None

    def test_scene_analysis_result_to_dict(self):
        """Test SceneAnalysisResult has to_dict() method with all fields."""
        from backend.models.visual_types import SceneAnalysisResult, ColorPalette

        palettes = [
            ColorPalette(
                primary_colors=["#FF6B6B"],
                secondary_colors=["#F7F7F7"],
                color_ratios={"primary": 0.8},
            ),
        ]

        analyzed_time = datetime(2026, 5, 23, 14, 0, 0)

        result = SceneAnalysisResult(
            scene="food_restaurant",
            sample_size=500,
            style_distribution={"minimalist": 0.5},
            layout_distribution={"grid_2x2": 0.6},
            color_palettes=palettes,
            visual_elements={"icons": 10},
            trending_styles=["minimalist"],
            trending_layouts=["grid_2x2"],
            analyzed_at=analyzed_time,
        )

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["scene"] == "food_restaurant"
        assert result_dict["sample_size"] == 500
        assert result_dict["style_distribution"] == {"minimalist": 0.5}
        assert result_dict["layout_distribution"] == {"grid_2x2": 0.6}
        assert result_dict["color_palettes"] == [palettes[0].to_dict()]
        assert result_dict["visual_elements"] == {"icons": 10}
        assert result_dict["trending_styles"] == ["minimalist"]
        assert result_dict["trending_layouts"] == ["grid_2x2"]
        assert result_dict["analyzed_at"] == analyzed_time.isoformat()

    def test_scene_analysis_result_to_dict_with_none_timestamp(self):
        """Test SceneAnalysisResult to_dict() with None analyzed_at."""
        from backend.models.visual_types import SceneAnalysisResult

        result = SceneAnalysisResult(
            scene="test_scene",
            sample_size=100,
            analyzed_at=None,
        )

        result_dict = result.to_dict()

        assert result_dict["analyzed_at"] is None

    def test_scene_analysis_result_no_generic_dicts(self):
        """Test that SceneAnalysisResult does NOT have generic distributions or trending_items dicts."""
        from backend.models.visual_types import SceneAnalysisResult

        result = SceneAnalysisResult(
            scene="test",
            sample_size=100,
        )

        # Ensure old generic fields do NOT exist
        assert not hasattr(result, "distributions")
        assert not hasattr(result, "trending_items")