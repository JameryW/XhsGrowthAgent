"""Title generator tool - LLM-enhanced creative title generation.

Provides multi-style title recommendations with engagement prediction.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from langchain_core.tools import tool

from backend.config.models import TaskType
from backend.services.llm_enrichment import get_llm_service

logger = logging.getLogger("xhs_growth.tools.title")


def _load_prompt() -> dict:
    """Load prompt template from YAML file."""
    prompt_path = Path("xhs_growth/config/prompts/tools/title_generator.yaml")
    with open(prompt_path) as f:
        return yaml.safe_load(f)


def _algorithmic_fallback(data: dict) -> list[dict]:
    """Algorithmic fallback when LLM fails."""
    topic = data.get("topic", "")
    style = data.get("style", "attractive")
    count = data.get("count", 5)

    # Style-specific templates
    templates = {
        "attractive": [
            f"🔥 {topic}必看！超实用攻略",
            f"震惊！{topic}竟然是这样...",
            f"3分钟搞定{topic}！快收藏",
        ],
        "emotional": [
            f"有感动的{topic}，分享给你",
            f"关于{topic}，我想说...",
            f"终于找到了{topic}的答案",
        ],
        "curiosity": [
            f"为什么{topic}这么火？",
            f"{topic}的秘密终于揭开了",
            f"你不知道的{topic}真相",
        ],
        "value": [
            f"{topic}干货合集｜建议收藏",
            f"一文搞定{topic}｜详细教程",
            f"{topic}避坑指南｜新手必看",
        ],
    }

    # Get templates for style, fallback to attractive
    style_templates = templates.get(style, templates["attractive"])

    # Extend with generic templates if needed
    while len(style_templates) < count:
        style_templates.append(f"{topic}分享｜第{len(style_templates) + 1}弹")

    return [
        {
            "title": t,
            "style": style,
            "hook_type": "数字钩子" if "分钟" in t or "一文" in t else "情感钩子",
            "predicted_engagement": "medium",
            "reasoning": "算法生成标题",
        }
        for t in style_templates[:count]
    ]


@tool
async def title_generator(
    topic: str,
    style: str = "attractive",
    count: int = 5,
    content_type: str = "图文笔记",
    target_audience: str = "",
    key_points: list[str] = None,
) -> list[dict]:
    """生成小红书标题候选 — 多风格创意生成.

    Args:
        topic: 内容主题
        style: 标题风格 (attractive/emotional/curiosity/value)
        count: 标题数量上限
        content_type: 内容类型 (图文笔记/视频/轮播)
        target_audience: 目标受众
        key_points: 内容关键点

    Returns:
        标题列表，每个包含:
        - title: 标题文本（含emoji）
        - style: 标题风格
        - hook_type: 钩子类型
        - predicted_engagement: 预测互动等级
        - reasoning: 生成理由
    """
    if key_points is None:
        key_points = []

    try:
        # Load prompt template
        prompt_template = _load_prompt()

        # Prepare input data
        input_data = {
            "topic": topic,
            "style": style,
            "content_type": content_type,
            "target_audience": target_audience or "大众用户",
            "key_points": ", ".join(key_points) if key_points else "无特定关键点",
            "count": count,
        }

        # Use LLM enrichment service
        service = get_llm_service()
        result = await service.enrich_with_llm(
            task_type=TaskType.WRITING,
            prompt_template=prompt_template,
            input_data=input_data,
            fallback_fn=_algorithmic_fallback,
        )

        # Extract titles from result
        if isinstance(result, dict) and "titles" in result:
            titles = result["titles"]
            return titles[:count]
        elif isinstance(result, list):
            return result[:count]

        # If result structure is unexpected, use fallback
        logger.warning(f"Unexpected result structure: {type(result)}")
        return _algorithmic_fallback(input_data)[:count]

    except Exception as e:
        logger.error(f"title_generator error: {e}")
        return _algorithmic_fallback({"topic": topic, "style": style, "count": count})[:count]


__all__ = ["title_generator"]
