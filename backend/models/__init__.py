"""模型模块 — LLM 路由与 token 估算.

Components:
- router: 多模型路由器
- retry: ainvoke/invoke exponential-backoff wrapper
- context_cap: prompt token estimation + history trimming
- visual_types: 视觉分析数据结构

Cost tracking lives in backend.config.models.MODEL_COST_PER_1K (canonical rate
table) + backend.agents.nodes._base.llm_perf_entry (writes kind:"llm" perf_log
entries consumed by the analytics cost reader).
"""

from backend.models.context_cap import cap_context, estimate_tokens
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
    "ColorPalette",
    "LayoutOption",
    "StyleOption",
    "SceneAnalysisResult",
]
