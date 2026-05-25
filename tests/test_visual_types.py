"""Tests for visual data types.

Following TDD: This test file is created BEFORE the implementation
to verify the data structures exist and behave correctly.
"""

import pytest


class TestColorPalette:
    """Tests for ColorPalette dataclass."""

    def test_color_palette_creation(self):
        """Test ColorPalette can be created with required fields."""
        from xhs_growth.models.visual_types import ColorPalette

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
        from xhs_growth.models.visual_types import ColorPalette

        palette = ColorPalette(
            primary_colors=["#FF6B6B"],
            secondary_colors=[],
            color_ratios={},
        )

        assert palette.primary_colors == ["#FF6B6B"]
        assert palette.secondary_colors == []
        assert palette.color_ratios == {}


class TestLayoutOption:
    """Tests for LayoutOption dataclass."""

    def test_layout_option_creation(self):
        """Test LayoutOption can be created with required fields."""
        from xhs_growth.models.visual_types import LayoutOption

        layout = LayoutOption(
            layout_type="grid_3x3",
            description="3x3 grid layout for product showcase",
            popularity_score=0.85,
            pros=["Clear organization", "Good for multiple products"],
            cons=["May look crowded", "Fixed structure"],
            reference_posts=["post_id_1", "post_id_2"],
        )

        assert layout.layout_type == "grid_3x3"
        assert layout.description == "3x3 grid layout for product showcase"
        assert layout.popularity_score == 0.85
        assert layout.pros == ["Clear organization", "Good for multiple products"]
        assert layout.cons == ["May look crowded", "Fixed structure"]
        assert layout.reference_posts == ["post_id_1", "post_id_2"]

    def test_layout_option_defaults(self):
        """Test LayoutOption default values for optional fields."""
        from xhs_growth.models.visual_types import LayoutOption

        layout = LayoutOption(
            layout_type="single_image",
            description="Single focal image",
            popularity_score=0.9,
            pros=["Simple and clean"],
            cons=["Limited content"],
            reference_posts=[],
        )

        assert layout.reference_posts == []


class TestStyleOption:
    """Tests for StyleOption dataclass."""

    def test_style_option_creation(self):
        """Test StyleOption can be created with required fields."""
        from xhs_growth.models.visual_types import StyleOption, ColorPalette

        palette = ColorPalette(
            primary_colors=["#FF6B6B", "#4ECDC4"],
            secondary_colors=["#F7F7F7"],
            color_ratios={"primary": 0.8, "secondary": 0.2},
        )

        style = StyleOption(
            style_name="minimalist_clean",
            trending_score=0.78,
            color_palette=palette,
            pros=["Modern look", "Easy to read"],
            cons=["May lack personality"],
        )

        assert style.style_name == "minimalist_clean"
        assert style.trending_score == 0.78
        assert style.color_palette == palette
        assert style.pros == ["Modern look", "Easy to read"]
        assert style.cons == ["May lack personality"]

    def test_style_option_with_none_palette(self):
        """Test StyleOption can have None color_palette."""
        from xhs_growth.models.visual_types import StyleOption

        style = StyleOption(
            style_name="vintage_warm",
            trending_score=0.65,
            color_palette=None,
            pros=["Emotional appeal"],
            cons=["May not suit modern audience"],
        )

        assert style.color_palette is None


class TestSceneAnalysisResult:
    """Tests for SceneAnalysisResult dataclass."""

    def test_scene_analysis_result_creation(self):
        """Test SceneAnalysisResult can be created with required fields."""
        from xhs_growth.models.visual_types import SceneAnalysisResult

        result = SceneAnalysisResult(
            scene="travel_outdoor",
            sample_size=1000,
            distributions={
                "layouts": {"grid": 0.4, "single": 0.6},
                "colors": {"warm": 0.7, "cool": 0.3},
            },
            trending_items={
                "top_layouts": ["grid_3x3", "carousel"],
                "top_colors": ["#FF6B6B", "#4ECDC4"],
                "top_styles": ["minimalist", "vintage"],
            },
        )

        assert result.scene == "travel_outdoor"
        assert result.sample_size == 1000
        assert result.distributions == {
            "layouts": {"grid": 0.4, "single": 0.6},
            "colors": {"warm": 0.7, "cool": 0.3},
        }
        assert result.trending_items == {
            "top_layouts": ["grid_3x3", "carousel"],
            "top_colors": ["#FF6B6B", "#4ECDC4"],
            "top_styles": ["minimalist", "vintage"],
        }

    def test_scene_analysis_result_to_dict(self):
        """Test SceneAnalysisResult has to_dict() method."""
        from xhs_growth.models.visual_types import SceneAnalysisResult

        result = SceneAnalysisResult(
            scene="food_restaurant",
            sample_size=500,
            distributions={"layouts": {"grid": 0.5}},
            trending_items={"top_layouts": ["grid_2x2"]},
        )

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert result_dict["scene"] == "food_restaurant"
        assert result_dict["sample_size"] == 500
        assert result_dict["distributions"] == {"layouts": {"grid": 0.5}}
        assert result_dict["trending_items"] == {"top_layouts": ["grid_2x2"]}