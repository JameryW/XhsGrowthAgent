"""Timing optimizer tool - LLM-enhanced publishing time optimization.

Provides intelligent timing recommendations based on niche and audience behavior analysis.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import tool

from backend.config.models import TaskType
from backend.services.llm_enrichment import get_llm_service

logger = logging.getLogger("xhs_growth.tools.timing")


def _load_prompt() -> dict:
    """Load prompt template from YAML file."""
    prompt_path = Path("xhs_growth/config/prompts/tools/timing_optimizer.yaml")
    with open(prompt_path) as f:
        return yaml.safe_load(f)


def _algorithmic_fallback(data: dict) -> dict:
    """Algorithmic fallback when LLM fails."""
    niche = data.get("niche", "")
    target_audience = data.get("target_audience", "")
    content_type = data.get("content_type", "图文笔记")

    # Niche-specific timing patterns
    niche_patterns = {
        "美食": {
            "best_times": ["07:00", "11:30", "17:30", "21:00"],
            "best_days": ["周三", "周五", "周六"],
            "reason": "饭点前后是美食内容高峰浏览时段",
        },
        "穿搭": {
            "best_times": ["08:00", "12:00", "20:00", "22:00"],
            "best_days": ["周五", "周六", "周日"],
            "reason": "周末和睡前是穿搭决策高峰",
        },
        "旅行": {
            "best_times": ["09:00", "13:00", "19:00"],
            "best_days": ["周五", "周六", "周日"],
            "reason": "周末出行规划需求旺盛",
        },
        "护肤": {
            "best_times": ["08:00", "21:00", "23:00"],
            "best_days": ["周二", "周四", "周日"],
            "reason": "早晚护肤时段和周末空闲",
        },
        "健身": {
            "best_times": ["06:00", "18:00", "21:00"],
            "best_days": ["周一", "周三", "周五"],
            "reason": "运动前后和健身日",
        },
    }

    # Default pattern for unknown niches
    default_pattern = {
        "best_times": ["08:00", "12:00", "18:00", "21:00"],
        "best_days": ["周三", "周五", "周六"],
        "reason": "大众用户活跃时段",
    }

    # Match niche (substring matching)
    matched_pattern = default_pattern
    for niche_key, pattern in niche_patterns.items():
        if niche_key in niche or niche in niche_key:
            matched_pattern = pattern
            break

    return {
        "best_times": matched_pattern["best_times"],
        "best_days": matched_pattern["best_days"],
        "reasoning": {
            "best_times_reason": matched_pattern["reason"],
            "best_days_reason": f"{target_audience}用户活跃日",
        },
        "audience_active_pattern": f"{target_audience}用户在{matched_pattern['best_times'][0]}-{matched_pattern['best_times'][-1]}时段活跃",
        "niche_specific_insights": f"{niche}内容适合在{matched_pattern['reason']}发布",
        "avoid_times": ["14:00", "15:00"],
        "avoid_reasons": "下午工作时段流量较低",
        "content_type": content_type,
    }


@tool
async def timing_optimizer(
    niche: str = "",
    target_audience: str = "",
    content_type: str = "图文笔记",
    historical_data: dict = None,
) -> dict:
    """优化发布时间 — 基于垂直领域和受众行为分析最佳发布时段.

    Args:
        niche: 垂直领域（美食/穿搭/旅行/护肤/健身等）
        target_audience: 目标受众描述
        content_type: 内容类型 (图文笔记/视频/轮播)
        historical_data: 历史发布数据（可选）

    Returns:
        时段推荐，包含:
        - best_times: 最佳发布时间列表 ["HH:MM"]
        - best_days: 最佳发布日期列表
        - reasoning: 选择理由
        - audience_active_pattern: 受众活跃规律描述
        - niche_specific_insights: 垂直领域特定洞察
        - avoid_times: 避坑时段
        - avoid_reasons: 避坑理由
    """
    if historical_data is None:
        historical_data = {}

    try:
        # Load prompt template
        prompt_template = _load_prompt()

        # Prepare input data
        input_data = {
            "niche": niche or "通用领域",
            "target_audience": target_audience or "大众用户",
            "content_type": content_type,
            "historical_data": str(historical_data) if historical_data else "无历史数据",
        }

        # Use LLM enrichment service (STRATEGY task type)
        service = get_llm_service()
        result = await service.enrich_with_llm(
            task_type=TaskType.STRATEGY,
            prompt_template=prompt_template,
            input_data=input_data,
            fallback_fn=_algorithmic_fallback,
        )

        # Ensure result is a dict with expected structure
        if isinstance(result, dict):
            # Add content_type if not present
            if "content_type" not in result:
                result["content_type"] = content_type
            return result

        # If result structure is unexpected, use fallback
        logger.warning(f"Unexpected result structure: {type(result)}")
        return _algorithmic_fallback(input_data)

    except Exception as e:
        logger.error(f"timing_optimizer error: {e}")
        return _algorithmic_fallback({
            "niche": niche,
            "target_audience": target_audience,
            "content_type": content_type,
        })


__all__ = ["timing_optimizer"]