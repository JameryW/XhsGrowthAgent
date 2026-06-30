"""Visual analysis data types.

This module defines data structures for the visual analysis system,
providing unified types for layout, style, color, and scene analysis.
"""

from dataclasses import dataclass, field
from datetime import datetime
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

    def to_dict(self) -> dict[str, Any]:
        """Convert the palette to a dictionary for serialization.

        Returns:
            Dict containing all fields of the palette.
        """
        return {
            "primary_colors": self.primary_colors,
            "secondary_colors": self.secondary_colors,
            "color_ratios": self.color_ratios,
        }


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
        suitable_for: List of content types this layout is suitable for
        image_sequence_strategy: Strategy for ordering images
            (e.g., "chronological", "impact_first")
        text_position: Recommended text placement (e.g., "overlay", "below", "sidebar")
        avg_engagement: Average engagement rate for posts using this layout
    """

    layout_type: str
    description: str
    popularity_score: float
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    reference_posts: list[dict] = field(default_factory=list)
    suitable_for: list[str] = field(default_factory=list)
    image_sequence_strategy: str = ""
    text_position: str = ""
    avg_engagement: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert the layout to a dictionary for serialization.

        Returns:
            Dict containing all fields of the layout.
        """
        return {
            "layout_type": self.layout_type,
            "description": self.description,
            "popularity_score": self.popularity_score,
            "pros": self.pros,
            "cons": self.cons,
            "reference_posts": self.reference_posts,
            "suitable_for": self.suitable_for,
            "image_sequence_strategy": self.image_sequence_strategy,
            "text_position": self.text_position,
            "avg_engagement": self.avg_engagement,
        }


@dataclass
class StyleOption:
    """Represents a style recommendation option.

    Attributes:
        style_name: Identifier for the style (e.g., "minimalist_clean", "vintage_warm")
        trending_score: Trending score from 0.0 to 1.0
        color_palette: Associated color palette (may be None)
        pros: List of advantages for this style
        cons: List of disadvantages for this style
        description: Human-readable description of the visual style
        suitable_for: List of content categories this style works well with
        usage_rate: Percentage of posts using this style (0.0 to 1.0)
        avg_engagement: Average engagement rate for posts using this style
        reference_posts: List of dicts with post_id and engagement metrics
    """

    style_name: str
    trending_score: float
    color_palette: list[str] = field(default_factory=list)
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    description: str = ""
    suitable_for: list[str] = field(default_factory=list)
    usage_rate: float = 0.0
    avg_engagement: float = 0.0
    reference_posts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert the style to a dictionary for serialization.

        Returns:
            Dict containing all fields of the style.
        """
        return {
            "style_name": self.style_name,
            "trending_score": self.trending_score,
            "color_palette": self.color_palette,
            "pros": self.pros,
            "cons": self.cons,
            "description": self.description,
            "suitable_for": self.suitable_for,
            "usage_rate": self.usage_rate,
            "avg_engagement": self.avg_engagement,
            "reference_posts": self.reference_posts,
        }


@dataclass
class SceneAnalysisResult:
    """Result of scene-based visual analysis.

    Contains aggregated statistics and trending items for a specific
    content scene (e.g., "travel_outdoor", "food_restaurant").

    Attributes:
        scene: Scene identifier
        sample_size: Number of posts analyzed for this scene
        style_distribution: Distribution of styles with their usage percentages
        layout_distribution: Distribution of layouts with their usage percentages
        color_palettes: List of ColorPalette objects found in this scene
        visual_elements: Dict of visual element counts (e.g., {"icons": 50, "text_overlay": 30})
        trending_styles: List of trending style names
        trending_layouts: List of trending layout names
        analyzed_at: Timestamp when this analysis was performed
    """

    scene: str
    sample_size: int
    style_distribution: dict[str, float] = field(default_factory=dict)
    layout_distribution: dict[str, float] = field(default_factory=dict)
    color_palettes: list[ColorPalette] = field(default_factory=list)
    visual_elements: dict[str, int] = field(default_factory=dict)
    trending_styles: list[str] = field(default_factory=list)
    trending_layouts: list[str] = field(default_factory=list)
    analyzed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert the result to a dictionary for serialization.

        Returns:
            Dict containing all fields of the result.
        """
        return {
            "scene": self.scene,
            "sample_size": self.sample_size,
            "style_distribution": self.style_distribution,
            "layout_distribution": self.layout_distribution,
            "color_palettes": [p.to_dict() for p in self.color_palettes],
            "visual_elements": self.visual_elements,
            "trending_styles": self.trending_styles,
            "trending_layouts": self.trending_layouts,
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
        }


__all__ = [
    "ColorPalette",
    "LayoutOption",
    "StyleOption",
    "SceneAnalysisResult",
]
