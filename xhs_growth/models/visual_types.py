"""Visual analysis data types.

This module defines data structures for the visual analysis system,
providing unified types for layout, style, color, and scene analysis.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColorPalette:
    """Represents a color palette configuration.

    Attributes:
        primary_colors: List of primary color hex codes (e.g., "#FF6B6B")
        secondary_colors: List of secondary/supporting color hex codes
        color_ratios: Dict mapping color categories to their usage ratios
    """

    primary_colors: list[str] = field(default_factory=list)
    secondary_colors: list[str] = field(default_factory=list)
    color_ratios: dict[str, float] = field(default_factory=dict)


@dataclass
class LayoutOption:
    """Represents a layout recommendation option.

    Attributes:
        layout_type: Identifier for the layout type (e.g., "grid_3x3", "carousel")
        description: Human-readable description of the layout
        popularity_score: Popularity score from 0.0 to 1.0
        pros: List of advantages for this layout
        cons: List of disadvantages for this layout
        reference_posts: List of post IDs using this layout successfully
    """

    layout_type: str
    description: str
    popularity_score: float
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    reference_posts: list[str] = field(default_factory=list)


@dataclass
class StyleOption:
    """Represents a style recommendation option.

    Attributes:
        style_name: Identifier for the style (e.g., "minimalist_clean", "vintage_warm")
        trending_score: Trending score from 0.0 to 1.0
        color_palette: Associated color palette (may be None)
        pros: List of advantages for this style
        cons: List of disadvantages for this style
    """

    style_name: str
    trending_score: float
    color_palette: ColorPalette | None = None
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)


@dataclass
class SceneAnalysisResult:
    """Result of scene-based visual analysis.

    Contains aggregated statistics and trending items for a specific
    content scene (e.g., "travel_outdoor", "food_restaurant").

    Attributes:
        scene: Scene identifier
        sample_size: Number of posts analyzed for this scene
        distributions: Dict of distribution statistics (layouts, colors, etc.)
        trending_items: Dict of trending items (top_layouts, top_colors, top_styles)
    """

    scene: str
    sample_size: int
    distributions: dict[str, Any] = field(default_factory=dict)
    trending_items: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the result to a dictionary for serialization.

        Returns:
            Dict containing all fields of the result.
        """
        return {
            "scene": self.scene,
            "sample_size": self.sample_size,
            "distributions": self.distributions,
            "trending_items": self.trending_items,
        }


__all__ = [
    "ColorPalette",
    "LayoutOption",
    "StyleOption",
    "SceneAnalysisResult",
]