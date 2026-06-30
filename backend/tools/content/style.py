"""风格库工具 — 返回可用的视觉风格列表.

基于场景分析的智能风格推荐:
1. 从场景数据库获取分析结果
2. 转换分布数据为 StyleOption 列表
3. 按内容类型筛选合适风格
4. 降级到默认风格配置
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from backend.models.visual_types import StyleOption
from backend.services.visual_analysis import VisualAnalysisService

logger = logging.getLogger("xhs_growth.tools.style")


@tool
async def style_library(
    scene: str = "general",
    category: str = "全部",
    limit: int = 10,
    include_trending: bool = True,
) -> list[dict[str, Any]]:
    """返回小红书内容可用的视觉风格库.

    基于场景分析数据,提供最适合的风格推荐:
    - 分析热门内容的风格分布
    - 按内容分类筛选风格
    - 优先展示热门/趋势风格
    - 提供风格优缺点分析

    Args:
        scene: 内容场景标识 (如 "travel_outdoor", "food_restaurant")
        category: 风格分类 (全部/生活方式/美食/穿搭/旅行等)
        limit: 返回数量上限
        include_trending: 是否优先展示热门风格

    Returns:
        可用风格列表,每个风格包含:
        - style_name: 风格名称
        - description: 风格描述
        - trending_score: 热门度 (0.0-1.0)
        - color_palette: 推荐色彩列表
        - pros: 优点列表
        - cons: 缺点列表
        - suitable_for: 适用场景列表
        - usage_rate: 使用率
        - avg_engagement: 平均互动率
    """
    logger.info(f"Style recommendation for scene={scene}, category={category}, limit={limit}")

    # Create service instance
    service = VisualAnalysisService()

    # Determine content type from category
    content_type = _map_category_to_content_type(category)

    # Get style recommendations
    styles = service.get_style_recommendations(
        scene=scene,
        content_type=content_type,
    )

    # Sort by trending if requested
    if include_trending:
        styles.sort(key=lambda s: s.trending_score, reverse=True)
    else:
        # Sort by usage rate instead
        styles.sort(key=lambda s: s.usage_rate, reverse=True)

    # Apply limit
    styles = styles[:limit]

    # Convert to dict format for tool output
    result = [style.to_dict() for style in styles]

    logger.info(f"Returning {len(result)} style recommendations")

    return result


def _map_category_to_content_type(category: str) -> str:
    """将风格分类映射到内容类型.

    Args:
        category: 风格分类名称

    Returns:
        内容类型字符串
    """
    category_mapping = {
        "生活方式": "图文笔记",
        "美食": "图文笔记",
        "穿搭": "图文笔记",
        "旅行": "图文笔记",
        "家居": "图文笔记",
        "护肤美妆": "图文笔记",
        "健身运动": "图文笔记",
        "育儿亲子": "图文笔记",
        "萌宠": "图文笔记",
        "学习干货": "图文笔记",
        "职场分享": "图文笔记",
        "娱乐搞笑": "图文笔记",
    }

    return category_mapping.get(category, "图文笔记")


def get_default_styles() -> list[StyleOption]:
    """获取默认风格配置 (用于无场景数据时的降级).

    Returns:
        默认风格选项列表
    """
    return [
        StyleOption(
            style_name="现代简约",
            trending_score=0.85,
            color_palette=["#FFFFFF", "#F5F5F5", "#333333"],
            pros=["干净利落", "突出核心内容", "专业感强"],
            cons=["可能显得冷淡", "不适合情感类内容"],
            description="干净利落,突出核心内容",
            suitable_for=["产品展示", "干货分享", "教程"],
            usage_rate=0.25,
            avg_engagement=0.0,
        ),
        StyleOption(
            style_name="温暖治愈",
            trending_score=0.92,
            color_palette=["#FFE4E1", "#FFDAB9", "#FFFACD"],
            pros=["亲和力强", "适合生活类内容", "受众广泛"],
            cons=["不适合硬核内容", "可能缺少冲击力"],
            description="柔和色调,营造温馨氛围",
            suitable_for=["生活记录", "美食分享", "家居"],
            usage_rate=0.35,
            avg_engagement=0.0,
        ),
        StyleOption(
            style_name="高冷高级",
            trending_score=0.78,
            color_palette=["#E8E8E8", "#C0C0C0", "#505050"],
            pros=["高级感", "适合品牌内容", "视觉统一"],
            cons=["受众较窄", "不适合生活类"],
            description="冷色调,突出品质感",
            suitable_for=["穿搭", "旅行", "摄影"],
            usage_rate=0.15,
            avg_engagement=0.0,
        ),
        StyleOption(
            style_name="活力青春",
            trending_score=0.70,
            color_palette=["#FF6B6B", "#4ECDC4", "#FFE66D"],
            pros=["吸引年轻用户", "活泼感强", "适合娱乐"],
            cons=["不适合严肃内容", "可能显得幼稚"],
            description="明亮色彩,展现活力",
            suitable_for=["运动", "校园", "娱乐"],
            usage_rate=0.10,
            avg_engagement=0.0,
        ),
        StyleOption(
            style_name="复古文艺",
            trending_score=0.65,
            color_palette=["#D4A5A5", "#9B8AA5", "#7B6B8A"],
            pros=["独特风格", "适合文艺内容", "记忆点强"],
            cons=["受众较窄", "需要配套内容"],
            description="复古色调,文艺气息",
            suitable_for=["摄影", "旅行", "艺术"],
            usage_rate=0.08,
            avg_engagement=0.0,
        ),
        StyleOption(
            style_name="清新自然",
            trending_score=0.75,
            color_palette=["#98D8C8", "#7FCDCD", "#F0E68C"],
            pros=["舒适感", "适合自然内容", "真实感"],
            cons=["可能缺少亮点", "不适合商业内容"],
            description="自然色调,清新舒适",
            suitable_for=["旅行", "美食", "生活方式"],
            usage_rate=0.07,
            avg_engagement=0.0,
        ),
    ]


__all__ = ["style_library", "get_default_styles"]
