"""State module — LangGraph state definitions.

Components:
- schema: Main state TypedDict (XHSGrowthState)
- substates: Modular sub-state TypedDict definitions
- reducers: State reducer functions
- enums: Unified enum definitions

The schema/machine/substates/reducers re-exports are lazy via ``__getattr__``
so that importing ``backend.state.enums`` (stdlib-only) does not trigger the
langchain_core/langgraph chain pulled in by ``schema`` (``add_messages``) and
``machine`` (``StateSnapshot``). Callers that need those symbols pay the cost
on first attribute access instead of on every ``backend.state`` import.
"""

from typing import Any

# Enums are stdlib-only (StrEnum) — safe to import eagerly.
from backend.state.enums import (
    ContentStatus,
    ContentType,
    Urgency,
    WorkflowPhase,
)

# Map of re-exported names to the submodule + attribute that provides them.
# Resolved on first access via ``__getattr__`` (PEP 562).
_LAZY_EXPORTS = {
    # machine
    "WorkflowStatus": ("backend.state.machine", "WorkflowStatus"),
    "derive_status": ("backend.state.machine", "derive_status"),
    # schema
    "XHSGrowthState": ("backend.state.schema", "XHSGrowthState"),
    # reducers
    "merge_dict": ("backend.state.reducers", "merge_dict"),
    "append_list": ("backend.state.reducers", "append_list"),
    "replace": ("backend.state.reducers", "replace"),
    "max_value": ("backend.state.reducers", "max_value"),
    # substates
    "AnalyticsSnapshot": ("backend.state.substates", "AnalyticsSnapshot"),
    "BloggerNote": ("backend.state.substates", "BloggerNote"),
    "BloggerProfile": ("backend.state.substates", "BloggerProfile"),
    "CompetitorPost": ("backend.state.substates", "CompetitorPost"),
    "ContentPlan": ("backend.state.substates", "ContentPlan"),
    "ContentVersion": ("backend.state.substates", "ContentVersion"),
    "CopyContent": ("backend.state.substates", "CopyContent"),
    "DimensionScore": ("backend.state.substates", "DimensionScore"),
    "DraftContent": ("backend.state.substates", "DraftContent"),
    "EngagementAction": ("backend.state.substates", "EngagementAction"),
    "EvaluationResult": ("backend.state.substates", "EvaluationResult"),
    "GapItem": ("backend.state.substates", "GapItem"),
    "HotTopicItem": ("backend.state.substates", "HotTopicItem"),
    "HumanFeedback": ("backend.state.substates", "HumanFeedback"),
    "NicheOpportunity": ("backend.state.substates", "NicheOpportunity"),
    "OptimizationAnalysis": ("backend.state.substates", "OptimizationAnalysis"),
    "PublishResult": ("backend.state.substates", "PublishResult"),
    "RippleComparison": ("backend.state.substates", "RippleComparison"),
    "RipplePMFResult": ("backend.state.substates", "RipplePMFResult"),
    "RipplePrediction": ("backend.state.substates", "RipplePrediction"),
    "SuggestionItem": ("backend.state.substates", "SuggestionItem"),
    "TrendData": ("backend.state.substates", "TrendData"),
    "ViralPost": ("backend.state.substates", "ViralPost"),
    "VisualPlan": ("backend.state.substates", "VisualPlan"),
}

__all__ = [
    # Main state
    "XHSGrowthState",
    # Enums
    "WorkflowPhase",
    "ContentStatus",
    "ContentType",
    "Urgency",
    "WorkflowStatus",
    "derive_status",
    # Sub-states
    "TrendData",
    "ContentPlan",
    "CopyContent",
    "VisualPlan",
    "PublishResult",
    "AnalyticsSnapshot",
    "HumanFeedback",
    "EngagementAction",
    "RipplePrediction",
    "RipplePMFResult",
    "RippleComparison",
    # Nested items
    "HotTopicItem",
    "NicheOpportunity",
    "CompetitorPost",
    # 发布前优化子状态
    "DraftContent",
    "ViralPost",
    "GapItem",
    "SuggestionItem",
    "OptimizationAnalysis",
    "ContentVersion",
    # 博主参考
    "BloggerProfile",
    "BloggerNote",
    # 创作质量评估器 (RQGM agent-as-a-judge)
    "DimensionScore",
    "EvaluationResult",
    # Reducers
    "merge_dict",
    "append_list",
    "replace",
    "max_value",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.state' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
