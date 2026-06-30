"""Image prompt generator tool - LLM-enhanced visual prompt generation.

Provides intelligent AI painting prompts for cover images and carousel content.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import yaml
from langchain_core.tools import tool

from backend.config.models import TaskType
from backend.services.llm_enrichment import get_llm_service

logger = logging.getLogger("xhs_growth.tools.image_prompt")


def _load_prompt() -> dict[str, Any]:
    """Load prompt template from YAML file."""
    prompt_path = Path("xhs_growth/config/prompts/tools/image_prompt.yaml")
    with open(prompt_path) as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _algorithmic_fallback(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Algorithmic fallback when LLM fails."""
    topic = data.get("topic", "")
    style = data.get("style", "modern")
    scene = data.get("scene", "general")
    count = data.get("count", 3)
    color_palette = data.get("color_palette", [])

    # Style-specific color palettes
    style_colors = {
        "modern": ["#FFE4E1", "#F5F5F5", "#E8E8E8"],
        "vintage": ["#D4A574", "#8B4513", "#F4A460"],
        "minimalist": ["#FFFFFF", "#F0F0F0", "#333333"],
        "bold": ["#FF6B6B", "#4ECDC4", "#45B7D1"],
    }

    colors = color_palette if color_palette else style_colors.get(style, style_colors["modern"])

    # Prompt templates
    prompts = [
        {
            "prompt": (
                f"A {style} style {scene} scene featuring {topic}, "
                f"soft lighting, {colors[0]} and {colors[1]} accents, "
                f"Xiaohongshu aesthetic, high quality"
            ),
            "prompt_type": "cover",
            "aspect_ratio": "3:4",
            "key_elements": [topic, style, scene],
            "color_suggestions": colors,
            "negative_prompt": "blur, low quality, distorted text",
        },
        {
            "prompt": (
                f"{topic} close-up shot, {style} design, "
                f"clean background, product photography style, "
                f"{colors[0]} highlights"
            ),
            "prompt_type": "carousel",
            "aspect_ratio": "1:1",
            "key_elements": [topic, "close-up", style],
            "color_suggestions": colors[:2],
            "negative_prompt": "messy background, harsh shadows",
        },
        {
            "prompt": (
                f"{scene} environment with {topic}, lifestyle photography, "
                f"{style} atmosphere, natural light, warm tones"
            ),
            "prompt_type": "story",
            "aspect_ratio": "16:9",
            "key_elements": [scene, topic, "lifestyle"],
            "color_suggestions": colors,
            "negative_prompt": "artificial lighting, staged look",
        },
    ]

    return prompts[:count]


@tool
async def image_prompt_generator(
    topic: str,
    style: str = "modern",
    count: int = 3,
    scene: str = "general",
    layout_type: str = "",
    color_palette: list[str] | None = None,
    brand_elements: list[str] | None = None,
) -> list[dict[str, Any]]:
    """生成小红书封面图和配图的 AI 绘画提示词 — 场景化视觉生成.

    Args:
        topic: 内容主题
        style: 视觉风格 (modern/vintage/minimalist/bold)
        count: 提示词数量
        scene: 内容场景 (美食室内/穿搭户外/旅行风景等)
        layout_type: 布局类型（来自 layout_recommender）
        color_palette: 配色方案（来自 style_library）
        brand_elements: 品牌元素

    Returns:
        提示词列表，每个包含:
        - prompt: 完整英文提示词
        - prompt_type: 封面/配图/故事图
        - aspect_ratio: 图片比例
        - key_elements: 关键视觉元素
        - color_suggestions: 颜色建议
        - negative_prompt: 负向提示词
    """
    if color_palette is None:
        color_palette = []
    if brand_elements is None:
        brand_elements = []

    try:
        # Load prompt template
        prompt_template = _load_prompt()

        # Prepare input data
        input_data = {
            "topic": topic,
            "style": style,
            "scene": scene or "通用场景",
            "layout_type": layout_type or "标准布局",
            "color_palette": ", ".join(color_palette) if color_palette else "默认配色",
            "count": count,
        }

        # Use LLM enrichment service (VISUAL task type for visual generation)
        service = get_llm_service()
        result = await service.enrich_with_llm(
            task_type=TaskType.VISUAL,
            prompt_template=prompt_template,
            input_data=input_data,
            fallback_fn=_algorithmic_fallback,
        )

        # Extract prompts from result
        if isinstance(result, dict) and "prompts" in result:
            prompts = cast(list[dict[str, Any]], result["prompts"])
            return prompts[:count]
        elif isinstance(result, list):
            return cast(list[dict[str, Any]], result)[:count]

        # If result structure is unexpected, use fallback
        logger.warning(f"Unexpected result structure: {type(result)}")
        return _algorithmic_fallback(input_data)[:count]

    except Exception as e:
        logger.error(f"image_prompt_generator error: {e}")
        return _algorithmic_fallback(
            {
                "topic": topic,
                "style": style,
                "scene": scene,
                "count": count,
            }
        )[:count]


__all__ = ["image_prompt_generator"]
