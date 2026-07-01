"""State module — LangGraph state definitions.

Components:
- schema: Main state TypedDict (XHSGrowthState)
- substates: Modular sub-state TypedDict definitions
- reducers: State reducer functions
- enums: Unified enum definitions
"""

from backend.state.enums import (
    ContentStatus,
    ContentType,
    Urgency,
    WorkflowPhase,
)
from backend.state.machine import WorkflowStatus, derive_status
from backend.state.reducers import append_list, max_value, merge_dict, replace
from backend.state.schema import XHSGrowthState
from backend.state.substates import (
    AnalyticsSnapshot,
    BloggerNote,
    BloggerProfile,
    CompetitorPost,
    ContentPlan,
    ContentVersion,
    CopyContent,
    DimensionScore,
    # 发布前优化子状态
    DraftContent,
    EngagementAction,
    EvaluationResult,
    GapItem,
    HotTopicItem,
    HumanFeedback,
    NicheOpportunity,
    OptimizationAnalysis,
    PublishResult,
    RippleComparison,
    RipplePMFResult,
    RipplePrediction,
    SuggestionItem,
    TrendData,
    ViralPost,
    VisualPlan,
)

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
