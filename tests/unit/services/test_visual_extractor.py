"""Tests for VisualDataExtractor service.

This module tests the visual data extraction service which provides
simplified Phase 1 algorithms for color palette, layout, visual elements,
and style classification.
"""

from __future__ import annotations

import pytest

from backend.models.visual_types import ColorPalette
from backend.services.visual_extractor import VisualDataExtractor


class TestVisualDataExtractor:
    """Test suite for VisualDataExtractor."""

    @pytest.fixture
    def extractor(self) -> VisualDataExtractor:
        """Create a VisualDataExtractor instance."""
        return VisualDataExtractor()

    @pytest.fixture
    def sample_images(self) -> list[dict]:
        """Sample image data for testing."""
        return [
            {"url": "https://example.com/image1.jpg", "width": 1080, "height": 1440},
            {"url": "https://example.com/image2.jpg", "width": 1080, "height": 1440},
        ]

    def test_extract_color_palette_basic(
        self,
        extractor: VisualDataExtractor,
        sample_images: list[dict],
    ) -> None:
        """Test that extract_color_palette returns preset warm colors.

        Phase 1: Returns a preset ColorPalette with warm colors.
        """
        result = extractor.extract_color_palette(sample_images)

        assert isinstance(result, ColorPalette)
        # Should have preset warm colors
        assert len(result.primary_colors) > 0
        # Warm colors typically include orange/yellow tones
        assert any("#FF" in color for color in result.primary_colors)

    def test_detect_layout_type_basic(
        self,
        extractor: VisualDataExtractor,
    ) -> None:
        """Test layout type detection based on image count.

        Phase 1: Simple image count logic:
        - 1 image → "全图+文末"
        - 2 images → "上下结构"
        - 3-4 images → "网格布局"
        - >4 images → "轮播图"
        """
        # 1 image should return "全图+文末"
        single_image = [{"url": "https://example.com/single.jpg"}]
        result = extractor.detect_layout_type(single_image)
        assert result == "全图+文末"

        # 2 images should return "上下结构"
        two_images = [
            {"url": "https://example.com/img1.jpg"},
            {"url": "https://example.com/img2.jpg"},
        ]
        result = extractor.detect_layout_type(two_images)
        assert result == "上下结构"

        # 3 images should return "网格布局"
        three_images = [
            {"url": "https://example.com/img1.jpg"},
            {"url": "https://example.com/img2.jpg"},
            {"url": "https://example.com/img3.jpg"},
        ]
        result = extractor.detect_layout_type(three_images)
        assert result == "网格布局"

        # 4 images should return "网格布局"
        four_images = [
            {"url": "https://example.com/img1.jpg"},
            {"url": "https://example.com/img2.jpg"},
            {"url": "https://example.com/img3.jpg"},
            {"url": "https://example.com/img4.jpg"},
        ]
        result = extractor.detect_layout_type(four_images)
        assert result == "网格布局"

        # >4 images should return "轮播图"
        five_images = [
            {"url": "https://example.com/img1.jpg"},
            {"url": "https://example.com/img2.jpg"},
            {"url": "https://example.com/img3.jpg"},
            {"url": "https://example.com/img4.jpg"},
            {"url": "https://example.com/img5.jpg"},
        ]
        result = extractor.detect_layout_type(five_images)
        assert result == "轮播图"

    def test_identify_visual_elements_basic(
        self,
        extractor: VisualDataExtractor,
        sample_images: list[dict],
    ) -> None:
        """Test that identify_visual_elements returns empty dict.

        Phase 1: Returns empty dict as placeholder.
        """
        result = extractor.identify_visual_elements(sample_images)

        assert isinstance(result, dict)
        assert result == {}

    def test_classify_visual_style_basic(
        self,
        extractor: VisualDataExtractor,
        sample_images: list[dict],
    ) -> None:
        """Test that classify_visual_style returns preset style.

        Phase 1: Returns "温暖治愈" as default style.
        """
        result = extractor.classify_visual_style(sample_images)

        assert isinstance(result, str)
        assert result == "温暖治愈"


__all__ = ["TestVisualDataExtractor"]
