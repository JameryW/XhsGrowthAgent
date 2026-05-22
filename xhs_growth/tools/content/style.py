"""风格库工具 — 返回可用的视觉风格列表.

TODO: 接入真实风格库数据库，支持风格预览和热度排序.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


@tool
async def style_library(
    category: str = "全部",
    limit: int = 10,
    include_trending: bool = True,
) -> list[dict[str, Any]]:
    """返回小红书内容可用的视觉风格库.

    Args:
        category: 风格分类（全部/生活方式/美食/穿搭/旅行等）
        limit: 返回数量上限
        include_trending: 是否包含热门风格

    Returns:
        可用风格列表，每个风格包含名称、描述、适用场景、热度值
    """
    # TODO: 接入真实风格库数据源
    # 从数据库或配置文件加载预定义风格
    # 支持按热度、分类筛选

    styles = [
        {
            "name": "现代简约",
            "description": "干净利落，突出核心内容",
            "suitable_for": ["产品展示", "干货分享", "教程"],
            "color_palette": ["#FFFFFF", "#F5F5F5", "#333333"],
            "trending_score": 85 if include_trending else 50,
        },
        {
            "name": "温暖治愈",
            "description": "柔和色调，营造温馨氛围",
            "suitable_for": ["生活记录", "美食分享", "家居"],
            "color_palette": ["#FFE4E1", "#FFDAB9", "#FFFACD"],
            "trending_score": 92 if include_trending else 60,
        },
        {
            "name": "高冷高级",
            "description": "冷色调，突出品质感",
            "suitable_for": ["穿搭", "旅行", "摄影"],
            "color_palette": ["#E8E8E8", "#C0C0C0", "#505050"],
            "trending_score": 78 if include_trending else 45,
        },
        {
            "name": "活力青春",
            "description": "明亮色彩，展现活力",
            "suitable_for": ["运动", "校园", "娱乐"],
            "color_palette": ["#FF6B6B", "#4ECDC4", "#FFE66D"],
            "trending_score": 70 if include_trending else 40,
        },
    ]

    # 按热度排序
    if include_trending:
        styles.sort(key=lambda x: x["trending_score"], reverse=True)

    return styles[:limit]