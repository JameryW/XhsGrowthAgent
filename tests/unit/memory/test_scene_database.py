"""Tests for SceneDatabase.

Tests cover:
- Saving and retrieving scene analysis
- Cache expiry (24 hours)
- Default layouts and styles retrieval
- Data completeness validation (sample_size >= 30)
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.memory.scene_database import SceneDatabase
from backend.models.visual_types import (
    ColorPalette,
    LayoutOption,
    SceneAnalysisResult,
    StyleOption,
)


@pytest.fixture
def scene_db() -> SceneDatabase:
    """Create a SceneDatabase instance with a temporary data directory."""
    return SceneDatabase()


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for scene data."""
    data_dir = tmp_path / "scene_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def sample_analysis_result() -> SceneAnalysisResult:
    """Create a sample scene analysis result for testing."""
    return SceneAnalysisResult(
        scene="food",
        sample_size=100,
        style_distribution={
            "minimalist_clean": 0.35,
            "vintage_warm": 0.25,
        },
        layout_distribution={
            "carousel_3": 0.40,
            "grid_3x3": 0.30,
        },
        color_palettes=[
            ColorPalette(
                primary_colors=["#FF6B6B", "#FFE66D"],
                secondary_colors=["#4ECDC4", "#95E1D3"],
                color_ratios={"warm": 0.6, "cool": 0.4},
            )
        ],
        visual_elements={"text_overlay": 45, "icons": 30},
        trending_styles=["minimalist_clean", "vintage_warm"],
        trending_layouts=["carousel_3", "grid_3x3"],
        analyzed_at=datetime.now(),
    )


class TestSaveAndGetSceneAnalysis:
    """Tests for save_scene_analysis and get_scene_analysis methods."""

    def test_save_and_get_scene_analysis(
        self, scene_db: SceneDatabase, sample_analysis_result: SceneAnalysisResult, temp_data_dir: Path
    ) -> None:
        """Test that a saved analysis can be retrieved."""
        # Patch the data directory
        with patch.object(scene_db, "_data_dir", temp_data_dir):
            # Save the analysis
            scene_db.save_scene_analysis(sample_analysis_result)

            # Retrieve the analysis
            result = scene_db.get_scene_analysis("food")

            # Verify the result
            assert result is not None
            assert result.scene == "food"
            assert result.sample_size == 100
            assert "minimalist_clean" in result.style_distribution
            assert len(result.color_palettes) == 1
            assert result.color_palettes[0].primary_colors == ["#FF6B6B", "#FFE66D"]

    def test_get_scene_analysis_expired(
        self, scene_db: SceneDatabase, temp_data_dir: Path
    ) -> None:
        """Test that expired analysis (older than 24 hours) returns None."""
        # Create an expired analysis (25 hours old)
        expired_time = datetime.now() - timedelta(hours=25)
        expired_result = SceneAnalysisResult(
            scene="food",
            sample_size=100,
            style_distribution={"minimalist_clean": 0.35},
            layout_distribution={"carousel_3": 0.40},
            color_palettes=[],
            visual_elements={},
            trending_styles=["minimalist_clean"],
            trending_layouts=["carousel_3"],
            analyzed_at=expired_time,
        )

        with patch.object(scene_db, "_data_dir", temp_data_dir):
            # Save the expired analysis
            scene_db.save_scene_analysis(expired_result)

            # Try to retrieve - should return None due to expiry
            result = scene_db.get_scene_analysis("food")

            assert result is None

    def test_get_scene_analysis_insufficient_sample(
        self, scene_db: SceneDatabase, temp_data_dir: Path
    ) -> None:
        """Test that analysis with sample_size < 30 returns None."""
        insufficient_result = SceneAnalysisResult(
            scene="food",
            sample_size=15,  # Less than minimum threshold of 30
            style_distribution={},
            layout_distribution={},
            color_palettes=[],
            visual_elements={},
            trending_styles=[],
            trending_layouts=[],
            analyzed_at=datetime.now(),
        )

        with patch.object(scene_db, "_data_dir", temp_data_dir):
            scene_db.save_scene_analysis(insufficient_result)
            result = scene_db.get_scene_analysis("food")

            assert result is None

    def test_get_scene_analysis_not_found(
        self, scene_db: SceneDatabase, temp_data_dir: Path
    ) -> None:
        """Test that requesting a non-existent scene returns None."""
        with patch.object(scene_db, "_data_dir", temp_data_dir):
            result = scene_db.get_scene_analysis("nonexistent_scene")

            assert result is None


class TestGetDefaultLayouts:
    """Tests for get_default_layouts method."""

    def test_get_default_layouts(
        self, scene_db: SceneDatabase
    ) -> None:
        """Test retrieving default layouts for a scene."""
        layouts = scene_db.get_default_layouts("food")

        assert layouts is not None
        assert len(layouts) >= 2
        assert all(isinstance(lo, LayoutOption) for lo in layouts)
        # Updated to match new Chinese layout names
        assert any(lo.layout_type == "上下结构" for lo in layouts)
        assert any(lo.layout_type == "网格布局" for lo in layouts)

    def test_get_default_layouts_scene_not_found(
        self, scene_db: SceneDatabase
    ) -> None:
        """Test that requesting layouts for non-existent scene returns empty list."""
        layouts = scene_db.get_default_layouts("nonexistent_scene")

        assert layouts == []


class TestGetDefaultStyles:
    """Tests for get_default_styles method."""

    def test_get_default_styles(
        self, scene_db: SceneDatabase
    ) -> None:
        """Test retrieving default styles for a scene."""
        styles = scene_db.get_default_styles("food")

        assert styles is not None
        assert len(styles) >= 2
        assert all(isinstance(s, StyleOption) for s in styles)
        # Updated to match new Chinese style names
        assert any(s.style_name == "温暖治愈" for s in styles)
        assert any(s.style_name == "现代简约" for s in styles)

    def test_get_default_styles_scene_not_found(
        self, scene_db: SceneDatabase
    ) -> None:
        """Test that requesting styles for non-existent scene returns empty list."""
        styles = scene_db.get_default_styles("nonexistent_scene")

        assert styles == []