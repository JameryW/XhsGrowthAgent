"""Scene database for storing and retrieving visual analysis data.

This module provides JSON-based storage for scene analysis results
with cache management and expiry handling.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backend.models.visual_types import (
    ColorPalette,
    LayoutOption,
    SceneAnalysisResult,
    StyleOption,
)


class SceneDatabase:
    """Database for scene-based visual analysis data.

    Provides storage and retrieval of scene analysis results using JSON files.
    Implements caching with 24-hour expiry and minimum sample size validation.

    Attributes:
        _config_dir: Path to the config directory containing scene data
        _data_dir: Path to the runtime data directory for cached analyses
        _cache_expiry_hours: Number of hours before analysis expires (default: 24)
        _min_sample_size: Minimum sample size for valid analysis (default: 30)
    """

    def __init__(
        self,
        config_dir: Path | None = None,
        data_dir: Path | None = None,
    ) -> None:
        """Initialize the scene database.

        Args:
            config_dir: Optional custom config directory path
            data_dir: Optional custom data directory path for cached analyses
        """
        # Default paths relative to package
        package_root = Path(__file__).parent.parent
        self._config_dir = config_dir or package_root / "config" / "scenes"
        self._data_dir = data_dir or package_root / "data" / "scenes"
        self._cache_expiry_hours = 24
        self._min_sample_size = 30

    def save_scene_analysis(self, result: SceneAnalysisResult) -> None:
        """Save scene analysis to JSON file.

        Args:
            result: SceneAnalysisResult object to save
        """
        # Ensure data directory exists
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Convert result to dict for JSON serialization
        data = result.to_dict()

        # Save to JSON file using scene name from result
        file_path = self._data_dir / f"{result.scene}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_scene_analysis(self, scene: str) -> SceneAnalysisResult | None:
        """Retrieve scene analysis from JSON file.

        Validates cache expiry (24 hours) and minimum sample size (30).

        Args:
            scene: Scene identifier

        Returns:
            SceneAnalysisResult if valid, None if expired, insufficient,
            or not found
        """
        file_path = self._data_dir / f"{scene}.json"

        # Check if file exists
        if not file_path.exists():
            return None

        # Load JSON data
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        # Validate sample size
        if data.get("sample_size", 0) < self._min_sample_size:
            return None

        # Check cache expiry
        analyzed_at_str = data.get("analyzed_at")
        analyzed_at: datetime | None = None
        if analyzed_at_str:
            try:
                analyzed_at = datetime.fromisoformat(analyzed_at_str)
                expiry_time = analyzed_at + timedelta(hours=self._cache_expiry_hours)
                if datetime.now() > expiry_time:
                    return None
            except (ValueError, TypeError):
                # Invalid timestamp, treat as expired
                return None

        # Convert color_palettes dicts to ColorPalette objects
        color_palettes_data = data.get("color_palettes", [])
        color_palettes: list[ColorPalette] = []
        for palette_dict in color_palettes_data:
            palette = ColorPalette(
                primary_colors=palette_dict.get("primary_colors", []),
                secondary_colors=palette_dict.get("secondary_colors", []),
                color_ratios=palette_dict.get("color_ratios", {}),
            )
            color_palettes.append(palette)

        # Build SceneAnalysisResult object
        result = SceneAnalysisResult(
            scene=data.get("scene", scene),
            sample_size=data.get("sample_size", 0),
            style_distribution=data.get("style_distribution", {}),
            layout_distribution=data.get("layout_distribution", {}),
            color_palettes=color_palettes,
            visual_elements=data.get("visual_elements", {}),
            trending_styles=data.get("trending_styles", []),
            trending_layouts=data.get("trending_layouts", []),
            analyzed_at=analyzed_at,
        )

        return result

    def get_default_layouts(self, scene: str) -> list[LayoutOption]:
        """Get default layouts for a scene from config.

        Args:
            scene: Scene identifier

        Returns:
            List of LayoutOption objects, empty list if not found
        """
        file_path = self._config_dir / f"{scene}.json"

        if not file_path.exists():
            return []

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        layouts_data = data.get("default_layouts", [])
        if not layouts_data:
            return []

        # Convert to LayoutOption objects
        layouts: list[LayoutOption] = []
        for layout_dict in layouts_data:
            try:
                layout = LayoutOption(
                    layout_type=layout_dict.get("layout_type", ""),
                    description=layout_dict.get("description", ""),
                    popularity_score=layout_dict.get("popularity_score", 0.0),
                    pros=layout_dict.get("pros", []),
                    cons=layout_dict.get("cons", []),
                    reference_posts=layout_dict.get("reference_posts", []),
                    suitable_for=layout_dict.get("suitable_for", []),
                    image_sequence_strategy=layout_dict.get("image_sequence_strategy", ""),
                    text_position=layout_dict.get("text_position", ""),
                    avg_engagement=layout_dict.get("avg_engagement", 0.0),
                )
                layouts.append(layout)
            except (TypeError, KeyError):
                continue

        return layouts

    def get_default_styles(self, scene: str) -> list[StyleOption]:
        """Get default styles for a scene from config.

        Args:
            scene: Scene identifier

        Returns:
            List of StyleOption objects, empty list if not found
        """
        file_path = self._config_dir / f"{scene}.json"

        if not file_path.exists():
            return []

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        styles_data = data.get("default_styles", [])
        if not styles_data:
            return []

        # Convert to StyleOption objects
        styles: list[StyleOption] = []
        for style_dict in styles_data:
            try:
                style = StyleOption(
                    style_name=style_dict.get("style_name", ""),
                    trending_score=style_dict.get("trending_score", 0.0),
                    color_palette=style_dict.get("color_palette", []),
                    pros=style_dict.get("pros", []),
                    cons=style_dict.get("cons", []),
                    description=style_dict.get("description", ""),
                    suitable_for=style_dict.get("suitable_for", []),
                    usage_rate=style_dict.get("usage_rate", 0.0),
                    avg_engagement=style_dict.get("avg_engagement", 0.0),
                    reference_posts=style_dict.get("reference_posts", []),
                )
                styles.append(style)
            except (TypeError, KeyError):
                continue

        return styles


__all__ = ["SceneDatabase"]