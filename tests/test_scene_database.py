"""Tests for SceneDatabase.

Tests cover:
- Saving and retrieving scene analysis
- Cache expiry (24 hours)
- Default layouts and styles retrieval
- Data completeness validation (sample_size >= 30)
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from xhs_growth.memory.scene_database import SceneDatabase
from xhs_growth.models.visual_types import LayoutOption, StyleOption, SceneAnalysisResult


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
def sample_analysis_result() -> dict:
    """Create a sample scene analysis result for testing."""
    return {
        "scene": "food",
        "sample_size": 100,
        "style_distribution": {
            "minimalist_clean": 0.35,
            "vintage_warm": 0.25,
        },
        "layout_distribution": {
            "carousel_3": 0.40,
            "grid_3x3": 0.30,
        },
        "color_palettes": [],
        "visual_elements": {},
        "trending_styles": ["minimalist_clean", "vintage_warm"],
        "trending_layouts": ["carousel_3", "grid_3x3"],
        "analyzed_at": datetime.now().isoformat(),
    }


class TestSaveAndGetSceneAnalysis:
    """Tests for save_scene_analysis and get_scene_analysis methods."""

    def test_save_and_get_scene_analysis(
        self, scene_db: SceneDatabase, sample_analysis_result: dict, temp_data_dir: Path
    ) -> None:
        """Test that a saved analysis can be retrieved."""
        # Patch the data directory
        with patch.object(scene_db, "_data_dir", temp_data_dir):
            # Save the analysis
            scene_db.save_scene_analysis("food", sample_analysis_result)

            # Retrieve the analysis
            result = scene_db.get_scene_analysis("food")

            # Verify the result
            assert result is not None
            assert result["scene"] == "food"
            assert result["sample_size"] == 100
            assert "minimalist_clean" in result["style_distribution"]

    def test_get_scene_analysis_expired(
        self, scene_db: SceneDatabase, sample_analysis_result: dict, temp_data_dir: Path
    ) -> None:
        """Test that expired analysis (older than 24 hours) returns None."""
        # Create an expired analysis (25 hours old)
        expired_time = datetime.now() - timedelta(hours=25)
        expired_result = sample_analysis_result.copy()
        expired_result["analyzed_at"] = expired_time.isoformat()

        with patch.object(scene_db, "_data_dir", temp_data_dir):
            # Save the expired analysis
            scene_db.save_scene_analysis("food", expired_result)

            # Try to retrieve - should return None due to expiry
            result = scene_db.get_scene_analysis("food")

            assert result is None

    def test_get_scene_analysis_insufficient_sample(
        self, scene_db: SceneDatabase, temp_data_dir: Path
    ) -> None:
        """Test that analysis with sample_size < 30 returns None."""
        insufficient_result = {
            "scene": "food",
            "sample_size": 15,  # Less than minimum threshold of 30
            "style_distribution": {},
            "layout_distribution": {},
            "color_palettes": [],
            "visual_elements": {},
            "trending_styles": [],
            "trending_layouts": [],
            "analyzed_at": datetime.now().isoformat(),
        }

        with patch.object(scene_db, "_data_dir", temp_data_dir):
            scene_db.save_scene_analysis("food", insufficient_result)
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
        assert all(isinstance(l, LayoutOption) for l in layouts)
        assert any(l.layout_type == "carousel_3" for l in layouts)
        assert any(l.layout_type == "single_hero" for l in layouts)

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
        assert any(s.style_name == "minimalist_clean" for s in styles)
        assert any(s.style_name == "vintage_warm" for s in styles)

    def test_get_default_styles_scene_not_found(
        self, scene_db: SceneDatabase
    ) -> None:
        """Test that requesting styles for non-existent scene returns empty list."""
        styles = scene_db.get_default_styles("nonexistent_scene")

        assert styles == []