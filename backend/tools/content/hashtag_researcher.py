"""Hashtag researcher tool - LLM-enhanced hashtag analysis.

Provides intelligent hashtag recommendations with competition and traffic analysis.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import yaml
from langchain_core.tools import tool

from backend.config.models import TaskType
from backend.services.llm_enrichment import get_llm_service

logger = logging.getLogger("xhs_growth.tools.hashtag")


def _load_prompt() -> dict[str, Any]:
    """Load prompt template from YAML file."""
    prompt_path = Path("xhs_growth/config/prompts/tools/hashtag_researcher.yaml")
    with open(prompt_path) as f:
        data: Any = yaml.safe_load(f)
    return cast(dict[str, Any], data)


def _algorithmic_fallback(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Algorithmic fallback when LLM fails."""
    keyword = data.get("keyword", "")
    limit = data.get("limit", 10)

    # Generate basic hashtags based on keyword
    base_tags = [
        f"#{keyword}",
        f"#{keyword}推荐",
        f"#{keyword}分享",
        f"#{keyword}攻略",
        f"#小红书{keyword}",
    ]

    # Extend with generic high-traffic tags
    generic_tags = [
        "#小红书爆款",
        "#好物推荐",
        "#日常分享",
        "#生活记录",
    ]

    all_tags = base_tags + generic_tags

    return [
        {
            "tag": tag,
            "heat_score": 50 if tag.startswith(f"#{keyword}") else 70,
            "competition": "medium",
            "traffic_potential": "medium",
            "related_keywords": [keyword],
            "recommended_position": "primary" if i < len(base_tags) else "secondary",
        }
        for i, tag in enumerate(all_tags[:limit])
    ]


@tool
async def hashtag_researcher(
    keyword: str,
    niche: str = "",
    target_audience: str = "",
    limit: int = 10,
    include_long_tail: bool = True,
) -> list[dict[str, Any]]:
    """研究小红书标签 — 分析标签竞争度和流量潜力.

    Args:
        keyword: 核心关键词
        niche: 垂直领域（美食/穿搭/旅行等）
        target_audience: 目标受众描述
        limit: 返回标签数量上限
        include_long_tail: 是否包含长尾标签

    Returns:
        标签列表，每个包含:
        - tag: 标签名
        - heat_score: 热度评分 (0-100)
        - competition: 竞争程度 (low/medium/high)
        - traffic_potential: 流量潜力 (low/medium/high)
        - recommended_position: 推荐位置 (primary/secondary/niche)
        - related_keywords: 相关关键词
    """
    try:
        # Load prompt template
        prompt_template = _load_prompt()

        # Prepare input data
        input_data = {
            "keyword": keyword,
            "niche": niche or "通用",
            "target_audience": target_audience or "大众用户",
            "limit": limit,
            "include_long_tail": "是" if include_long_tail else "否",
        }

        # Use LLM enrichment service
        service = get_llm_service()
        result = await service.enrich_with_llm(
            task_type=TaskType.WRITING,
            prompt_template=prompt_template,
            input_data=input_data,
            fallback_fn=_algorithmic_fallback,
        )

        # Extract hashtags from result
        if isinstance(result, dict) and "hashtags" in result:
            hashtags = result["hashtags"]
            return cast(list[dict[str, Any]], hashtags[:limit])
        elif isinstance(result, list):
            return cast(list[dict[str, Any]], result[:limit])

        # If result structure is unexpected, use fallback
        logger.warning(f"Unexpected result structure: {type(result)}")
        return _algorithmic_fallback(input_data)[:limit]

    except Exception as e:
        logger.error(f"hashtag_researcher error: {e}")
        return _algorithmic_fallback({"keyword": keyword, "limit": limit})[:limit]


__all__ = ["hashtag_researcher"]
