"""Visual analysis service for scene-based content recommendations.

This module provides the core service for analyzing scenes, generating
layout recommendations, and providing style suggestions based on
aggregated visual data from Xiaohongshu posts.
"""

from __future__ import annotations

import logging
from datetime import datetime

from backend.memory.scene_database import SceneDatabase
from backend.models.visual_types import (
    ColorPalette,
    LayoutOption,
    SceneAnalysisResult,
    StyleOption,
)
from backend.services.visual_extractor import VisualDataExtractor
from backend.services.xhs_client import XHSClient

logger = logging.getLogger("xhs_growth.visual_analysis")


class VisualAnalysisService:
    """Service for scene-based visual analysis and recommendations.

    Orchestrates the full workflow:
    1. Fetch posts from XHSClient for a scene
    2. Extract visual features using VisualDataExtractor
    3. Aggregate and analyze results
    4. Store in SceneDatabase for future use

    Attributes:
        _client: XHSClient instance for fetching posts
        _database: SceneDatabase for storing/retrieving analysis
        _extractor: VisualDataExtractor for feature extraction
    """

    def __init__(
        self,
        client: XHSClient | None = None,
        database: SceneDatabase | None = None,
        extractor: VisualDataExtractor | None = None,
    ) -> None:
        """Initialize the visual analysis service.

        Args:
            client: Optional XHSClient instance (created if None)
            database: Optional SceneDatabase instance (created if None)
            extractor: Optional VisualDataExtractor instance (created if None)
        """
        self._client = client or XHSClient()
        self._database = database or SceneDatabase()
        self._extractor = extractor or VisualDataExtractor()

    async def analyze_scene(
        self,
        scene: str,
        limit: int = 100,
    ) -> SceneAnalysisResult:
        """Analyze visual patterns for a content scene.

        Workflow:
        1. Check if cached analysis exists and is valid
        2. If not, fetch posts from XHS for this scene
        3. Extract visual features from each post
        4. Aggregate statistics (distributions, trends)
        5. Save to database for future use

        Args:
            scene: Scene identifier (e.g., "travel_outdoor", "food_restaurant")
            limit: Maximum number of posts to analyze

        Returns:
            SceneAnalysisResult with aggregated statistics
        """
        # Check for cached analysis
        cached = self._database.get_scene_analysis(scene)
        if cached:
            logger.info(f"Using cached analysis for scene: {scene}")
            return cached

        logger.info(f"Analyzing scene: {scene} (limit: {limit})")

        # Fetch posts for this scene using search
        # Scene keywords are mapped to search terms
        search_keyword = self._map_scene_to_keyword(scene)
        posts = await self._client.search_posts(keyword=search_keyword, limit=limit)

        if not posts:
            logger.warning(f"No posts found for scene: {scene}")
            # Return empty result
            return SceneAnalysisResult(
                scene=scene,
                sample_size=0,
                analyzed_at=datetime.now(),
            )

        # Extract features from each post
        style_counts: dict[str, int] = {}
        layout_counts: dict[str, int] = {}
        color_palettes: list[ColorPalette] = []
        visual_elements: dict[str, int] = {}

        for post in posts:
            # Build image dict from post data
            # Note: Posts from search have cover_url, not full image list
            images = [{"url": post.cover_url}] if post.cover_url else []

            # Extract features
            style = self._extractor.classify_visual_style(images)
            layout = self._extractor.detect_layout_type(images)
            palette = self._extractor.extract_color_palette(images)
            elements = self._extractor.identify_visual_elements(images)

            # Aggregate
            style_counts[style] = style_counts.get(style, 0) + 1
            layout_counts[layout] = layout_counts.get(layout, 0) + 1
            color_palettes.append(palette)

            # Merge visual elements
            for key, value in elements.items():
                increment = value if isinstance(value, int) else 1
                visual_elements[key] = visual_elements.get(key, 0) + increment

        # Calculate distributions (normalize to percentages)
        total_posts = len(posts)
        style_distribution = {
            style: count / total_posts
            for style, count in style_counts.items()
        }
        layout_distribution = {
            layout: count / total_posts
            for layout, count in layout_counts.items()
        }

        # Identify trending items (top 3 by count)
        trending_styles = sorted(
            style_counts.keys(),
            key=lambda s: style_counts[s],
            reverse=True,
        )[:3]
        trending_layouts = sorted(
            layout_counts.keys(),
            key=lambda x: layout_counts[x],
            reverse=True,
        )[:3]

        # Build result
        result = SceneAnalysisResult(
            scene=scene,
            sample_size=total_posts,
            style_distribution=style_distribution,
            layout_distribution=layout_distribution,
            color_palettes=color_palettes[:10],  # Top 10 palettes
            visual_elements=visual_elements,
            trending_styles=trending_styles,
            trending_layouts=trending_layouts,
            analyzed_at=datetime.now(),
        )

        # Save to database
        self._database.save_scene_analysis(result)
        logger.info(f"Saved analysis for scene: {scene} (sample_size: {total_posts})")

        return result

    def get_layout_recommendations(
        self,
        scene: str,
        content_type: str = "图文笔记",
        image_count: int = 3,
    ) -> list[LayoutOption]:
        """Get layout recommendations for a scene and content type.

        Workflow:
        1. Try to get cached scene analysis
        2. Convert layout_distribution to LayoutOption list
        3. Filter by suitability for content_type
        4. If no analysis, fall back to defaults

        Args:
            scene: Scene identifier
            content_type: Content type (e.g., "图文笔记", "轮播图")
            image_count: Number of images in the content

        Returns:
            List of LayoutOption recommendations, sorted by popularity
        """
        # Get scene analysis (may be None if not cached)
        analysis = self._database.get_scene_analysis(scene)

        if analysis and analysis.layout_distribution:
            # Convert distribution to LayoutOption list
            layouts = self._build_layout_options_from_distribution(
                analysis.layout_distribution,
                analysis.sample_size,
            )

            # Filter by suitability for content_type and image_count
            filtered = self._filter_layouts_for_content(
                layouts,
                content_type,
                image_count,
            )

            if filtered:
                return filtered

        # Fall back to defaults
        logger.info(f"Using default layouts for scene: {scene}")
        return self._database.get_default_layouts(scene)

    def get_style_recommendations(
        self,
        scene: str,
        content_type: str = "图文笔记",
    ) -> list[StyleOption]:
        """Get style recommendations for a scene and content type.

        Workflow:
        1. Try to get cached scene analysis
        2. Convert style_distribution to StyleOption list
        3. Filter by suitability for content_type
        4. If no analysis, fall back to defaults

        Args:
            scene: Scene identifier
            content_type: Content type for filtering suitability

        Returns:
            List of StyleOption recommendations, sorted by trending score
        """
        # Get scene analysis (may be None if not cached)
        analysis = self._database.get_scene_analysis(scene)

        if analysis and analysis.style_distribution:
            # Convert distribution to StyleOption list
            styles = self._build_style_options_from_distribution(
                analysis.style_distribution,
                analysis.trending_styles,
                analysis.color_palettes,
                analysis.sample_size,
            )

            # Filter by suitability for content_type
            filtered = self._filter_styles_for_content(styles, content_type)

            if filtered:
                return filtered

        # Fall back to defaults
        logger.info(f"Using default styles for scene: {scene}")
        return self._database.get_default_styles(scene)

    # ── Helper Methods ────────────────────────────────────────────────────────

    def _map_scene_to_keyword(self, scene: str) -> str:
        """Map scene identifier to search keyword.

        Args:
            scene: Scene identifier (e.g., "travel_outdoor")

        Returns:
            Search keyword in Chinese (e.g., "旅行户外")
        """
        # Scene keyword mapping
        scene_keywords = {
            "travel_outdoor": "旅行户外",
            "food_restaurant": "美食探店",
            "food_home": "家常美食",
            "fashion_outfit": "穿搭分享",
            "lifestyle_home": "家居生活",
            "beauty_skincare": "护肤美妆",
            "fitness_health": "健身运动",
            "parenting_baby": "育儿亲子",
            "pet_animal": "萌宠",
            "education_study": "学习干货",
            "career_work": "职场分享",
            "entertainment_fun": "娱乐搞笑",
        }

        return scene_keywords.get(scene, scene)

    def _build_layout_options_from_distribution(
        self,
        distribution: dict[str, float],
        sample_size: int,
    ) -> list[LayoutOption]:
        """Build LayoutOption list from distribution data.

        Args:
            distribution: Layout type to percentage mapping
            sample_size: Total posts analyzed

        Returns:
            List of LayoutOption objects with descriptions and pros/cons
        """
        # Layout descriptions and attributes
        layout_info = {
            "全图+文末": {
                "description": "单张全图配合底部文字说明",
                "pros": ["视觉冲击力强", "适合封面展示", "简洁大气"],
                "cons": ["信息量有限", "不适合多产品展示"],
                "suitable_for": ["产品展示", "风景照片", "单主体内容"],
                "text_position": "below",
            },
            "上下结构": {
                "description": "图片上下排列，每图独立展示",
                "pros": ["对比清晰", "适合前后对比", "层次分明"],
                "cons": ["占用空间大", "需要两张高质量图片"],
                "suitable_for": ["前后对比", "教程步骤", "产品细节"],
                "text_position": "below",
            },
            "左右结构": {
                "description": "图片左右并列展示",
                "pros": ["对比直观", "适合选择对比", "空间利用率高"],
                "cons": ["单图空间有限", "不适合长图"],
                "suitable_for": ["选择对比", "穿搭展示", "左右搭配"],
                "text_position": "overlay",
            },
            "网格布局": {
                "description": "多图网格排列，整齐统一",
                "pros": ["信息量大", "整齐美观", "适合多产品"],
                "cons": ["单图较小", "需要统一风格"],
                "suitable_for": ["多产品展示", "合集内容", "清单推荐"],
                "text_position": "below",
            },
            "轮播图": {
                "description": "多图顺序浏览，适合故事线",
                "pros": ["内容丰富", "适合教程", "用户可自主浏览"],
                "cons": ["需要高质量封面", "用户需要滑动"],
                "suitable_for": ["教程攻略", "旅行记录", "故事分享"],
                "text_position": "overlay",
            },
            "封面突出": {
                "description": "封面图大尺寸，后续图片较小",
                "pros": ["封面吸引力强", "适合商品展示"],
                "cons": ["后续图片不够突出"],
                "suitable_for": ["商品推荐", "合集封面"],
                "text_position": "overlay",
            },
            "内容均匀": {
                "description": "所有图片尺寸均匀",
                "pros": ["公平展示", "整齐统一"],
                "cons": ["缺少重点突出"],
                "suitable_for": ["清单推荐", "合集分享"],
                "text_position": "below",
            },
            "故事线布局": {
                "description": "按时间或逻辑顺序排列",
                "pros": ["故事性强", "适合教程", "逻辑清晰"],
                "cons": ["需要连贯内容", "不适合跳跃主题"],
                "suitable_for": ["旅行vlog", "教程攻略", "成长记录"],
                "text_position": "overlay",
            },
        }

        layouts: list[LayoutOption] = []
        for layout_type, percentage in distribution.items():
            info = layout_info.get(layout_type, {
                "description": f"{layout_type}布局",
                "pros": [],
                "cons": [],
                "suitable_for": [],
                "text_position": "",
            })

            layout = LayoutOption(
                layout_type=layout_type,
                description=info["description"],
                popularity_score=percentage,
                pros=info["pros"],
                cons=info["cons"],
                suitable_for=info["suitable_for"],
                text_position=info.get("text_position", ""),
                avg_engagement=0.0,  # Not tracked in Phase 1
            )
            layouts.append(layout)

        # Sort by popularity
        layouts.sort(key=lambda x: x.popularity_score, reverse=True)
        return layouts

    def _build_style_options_from_distribution(
        self,
        distribution: dict[str, float],
        trending_styles: list[str],
        color_palettes: list[ColorPalette],
        sample_size: int,
    ) -> list[StyleOption]:
        """Build StyleOption list from distribution data.

        Args:
            distribution: Style name to percentage mapping
            trending_styles: List of trending style names
            color_palettes: List of ColorPalette objects
            sample_size: Total posts analyzed

        Returns:
            List of StyleOption objects with descriptions and pros/cons
        """
        # Style descriptions and attributes
        style_info = {
            "温暖治愈": {
                "description": "柔和色调，营造温馨氛围",
                "pros": ["亲和力强", "适合生活类内容", "受众广泛"],
                "cons": ["不适合硬核内容", "可能缺少冲击力"],
                "suitable_for": ["生活记录", "美食分享", "家居"],
            },
            "现代简约": {
                "description": "干净利落，突出核心内容",
                "pros": ["专业感强", "信息清晰", "适合干货"],
                "cons": ["可能显得冷淡", "不适合情感类内容"],
                "suitable_for": ["产品展示", "干货分享", "教程"],
            },
            "高冷高级": {
                "description": "冷色调，突出品质感",
                "pros": ["高级感", "适合品牌内容", "视觉统一"],
                "cons": ["受众较窄", "不适合生活类"],
                "suitable_for": ["穿搭", "旅行", "摄影"],
            },
            "活力青春": {
                "description": "明亮色彩，展现活力",
                "pros": ["吸引年轻用户", "活泼感强", "适合娱乐"],
                "cons": ["不适合严肃内容", "可能显得幼稚"],
                "suitable_for": ["运动", "校园", "娱乐"],
            },
            "复古文艺": {
                "description": "复古色调，文艺气息",
                "pros": ["独特风格", "适合文艺内容", "记忆点强"],
                "cons": ["受众较窄", "需要配套内容"],
                "suitable_for": ["摄影", "旅行", "艺术"],
            },
            "清新自然": {
                "description": "自然色调，清新舒适",
                "pros": ["舒适感", "适合自然内容", "真实感"],
                "cons": ["可能缺少亮点", "不适合商业内容"],
                "suitable_for": ["旅行", "美食", "生活方式"],
            },
        }

        styles: list[StyleOption] = []
        for style_name, percentage in distribution.items():
            info = style_info.get(style_name, {
                "description": f"{style_name}风格",
                "pros": [],
                "cons": [],
                "suitable_for": [],
            })

            # Calculate trending score based on distribution and trending list
            trending_score = percentage
            if style_name in trending_styles:
                trending_score = min(1.0, percentage + 0.2)

            # Get color palette for this style (first matching palette)
            style_colors: list[str] = []
            if color_palettes:
                palette = color_palettes[0]
                style_colors = palette.primary_colors[:3]

            style = StyleOption(
                style_name=style_name,
                trending_score=trending_score,
                color_palette=style_colors,
                pros=info["pros"],
                cons=info["cons"],
                description=info["description"],
                suitable_for=info["suitable_for"],
                usage_rate=percentage,
                avg_engagement=0.0,  # Not tracked in Phase 1
            )
            styles.append(style)

        # Sort by trending score
        styles.sort(key=lambda s: s.trending_score, reverse=True)
        return styles

    def _filter_layouts_for_content(
        self,
        layouts: list[LayoutOption],
        content_type: str,
        image_count: int,
    ) -> list[LayoutOption]:
        """Filter layouts by content type and image count.

        Args:
            layouts: List of LayoutOption to filter
            content_type: Content type for suitability check
            image_count: Number of images

        Returns:
            Filtered list of LayoutOption
        """
        # Content type to layout type mapping
        content_layout_map = {
            "图文笔记": ["全图+文末", "上下结构", "网格布局"],
            "轮播图": ["轮播图", "封面突出", "故事线布局"],
            "视频": ["封面突出", "全图+文末"],
        }

        preferred_types = content_layout_map.get(content_type, [])

        # Image count constraints
        suitable_layouts: list[LayoutOption] = []
        for layout in layouts:
            # Check content type suitability
            if preferred_types and layout.layout_type not in preferred_types:
                # Check if layout.suitable_for matches content_type concept
                content_keywords = self._get_content_keywords(content_type)
                if not any(kw in layout.suitable_for for kw in content_keywords):
                    continue

            # Check image count constraints
            if image_count == 1 and layout.layout_type not in ["全图+文末", "封面突出"]:
                continue
            if image_count == 2 and layout.layout_type not in ["上下结构", "左右结构", "全图+文末"]:
                continue
            if image_count > 4 and layout.layout_type not in ["轮播图", "网格布局", "故事线布局"]:
                continue

            suitable_layouts.append(layout)

        return suitable_layouts[:5] if suitable_layouts else layouts[:5]

    def _filter_styles_for_content(
        self,
        styles: list[StyleOption],
        content_type: str,
    ) -> list[StyleOption]:
        """Filter styles by content type suitability.

        Args:
            styles: List of StyleOption to filter
            content_type: Content type for filtering

        Returns:
            Filtered list of StyleOption
        """
        content_keywords = self._get_content_keywords(content_type)

        suitable_styles: list[StyleOption] = []
        for style in styles:
            # Check if style is suitable for content type
            if style.suitable_for:
                if any(kw in style.suitable_for for kw in content_keywords):
                    suitable_styles.append(style)
            else:
                # No suitability info, include all
                suitable_styles.append(style)

        return suitable_styles[:5] if suitable_styles else styles[:5]

    def _get_content_keywords(self, content_type: str) -> list[str]:
        """Get keywords for content type matching.

        Args:
            content_type: Content type string

        Returns:
            List of related keywords for matching
        """
        content_keywords_map = {
            "图文笔记": ["干货分享", "教程", "产品展示", "生活记录"],
            "轮播图": ["教程攻略", "旅行记录", "故事分享", "清单推荐"],
            "视频": ["旅行vlog", "教程攻略", "成长记录"],
        }

        return content_keywords_map.get(content_type, [content_type])


__all__ = ["VisualAnalysisService"]