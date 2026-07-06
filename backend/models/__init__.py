"""模型模块 — LLM 路由与成本追踪.

Components:
- router: 多模型路由器
- retry: ainvoke/invoke exponential-backoff wrapper
- context_cap: prompt token estimation + history trimming
- cost_tracker: Token 使用统计
- visual_types: 视觉分析数据结构
"""

from backend.models.context_cap import cap_context, estimate_tokens
from backend.models.cost_tracker import COST_PER_1K, CostTracker, TokenUsage, calc_cost
from backend.models.retry import with_retry
from backend.models.router import ModelRouter, get_model, get_router
from backend.models.visual_types import (
    ColorPalette,
    LayoutOption,
    SceneAnalysisResult,
    StyleOption,
)

__all__ = [
    "get_model",
    "get_router",
    "ModelRouter",
    "with_retry",
    "estimate_tokens",
    "cap_context",
    "CostTracker",
    "TokenUsage",
    "calc_cost",
    "COST_PER_1K",
    "ColorPalette",
    "LayoutOption",
    "StyleOption",
    "SceneAnalysisResult",
]
