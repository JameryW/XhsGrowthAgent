"""布局推荐工具 — 推荐小红书图文排版布局.

基于场景分析的智能布局推荐:
1. 从场景数据库获取分析结果
2. 转换分布数据为 LayoutOption 列表
3. 按内容类型和图片数量筛选
4. 降级到默认布局配置
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from xhs_growth.services.visual_analysis import VisualAnalysisService
from xhs_growth.models.visual_types import LayoutOption

logger = logging.getLogger("xhs_growth.tools.layout")


@tool
async def layout_recommender(
    scene: str = "general",
    content_type: str = "图文笔记",
    image_count: int = 3,
    style: str = "",
) -> list[dict[str, Any]]:
    """推荐小红书图文内容的排版布局方案.

    基于场景分析数据,提供最适合的布局推荐:
    - 分析热门内容的布局分布
    - 按内容类型筛选合适布局
    - 根据图片数量优化推荐
    - 提供布局优缺点分析

    Args:
        scene: 内容场景标识 (如 "travel_outdoor", "food_restaurant")
        content_type: 内容类型 (图文笔记/轮播图/视频)
        image_count: 图片数量
        style: 视觉风格偏好 (可选,用于进一步筛选)

    Returns:
        推荐布局列表,每个布局包含:
        - layout_type: 布局类型名称
        - description: 布局描述
        - popularity_score: 流行度 (0.0-1.0)
        - pros: 优点列表
        - cons: 缺点列表
        - suitable_for: 适用场景列表
        - text_position: 文字位置建议
        - avg_engagement: 平均互动率
    """
    logger.info(f"Layout recommendation for scene={scene}, type={content_type}, images={image_count}")

    # Create service instance
    service = VisualAnalysisService()

    # Get layout recommendations
    layouts = service.get_layout_recommendations(
        scene=scene,
        content_type=content_type,
        image_count=image_count,
    )

    # Convert to dict format for tool output
    result = [layout.to_dict() for layout in layouts]

    # Add style filter if specified
    if style and result:
        # Filter by style suitability (placeholder logic)
        # In Phase 1, we don't have style-layout mapping
        # Just return top recommendations
        result = result[:3]

    logger.info(f"Returning {len(result)} layout recommendations")

    return result


def get_default_layouts() -> list[LayoutOption]:
    """获取默认布局配置 (用于无场景数据时的降级).

    Returns:
        默认布局选项列表
    """
    return [
        LayoutOption(
            layout_type="全图+文末",
            description="单张全图配合底部文字说明",
            popularity_score=0.35,
            pros=["视觉冲击力强", "适合封面展示", "简洁大气"],
            cons=["信息量有限", "不适合多产品展示"],
            suitable_for=["产品展示", "风景照片", "单主体内容"],
            text_position="below",
            avg_engagement=0.0,
        ),
        LayoutOption(
            layout_type="上下结构",
            description="图片上下排列,每图独立展示",
            popularity_score=0.25,
            pros=["对比清晰", "适合前后对比", "层次分明"],
            cons=["占用空间大", "需要两张高质量图片"],
            suitable_for=["前后对比", "教程步骤", "产品细节"],
            text_position="below",
            avg_engagement=0.0,
        ),
        LayoutOption(
            layout_type="网格布局",
            description="多图网格排列,整齐统一",
            popularity_score=0.30,
            pros=["信息量大", "整齐美观", "适合多产品"],
            cons=["单图较小", "需要统一风格"],
            suitable_for=["多产品展示", "合集内容", "清单推荐"],
            text_position="below",
            avg_engagement=0.0,
        ),
        LayoutOption(
            layout_type="轮播图",
            description="多图顺序浏览,适合故事线",
            popularity_score=0.10,
            pros=["内容丰富", "适合教程", "用户可自主浏览"],
            cons=["需要高质量封面", "用户需要滑动"],
            suitable_for=["教程攻略", "旅行记录", "故事分享"],
            text_position="overlay",
            avg_engagement=0.0,
        ),
    ]


__all__ = ["layout_recommender", "get_default_layouts"]