"""State module — LangGraph state definitions.

Components:
- schema: Main state TypedDict (XHSGrowthState)
- substates: Modular sub-state TypedDict definitions
- reducers: State reducer functions
- enums: Unified enum definitions
"""

from backend.state.enums import (
    WorkflowPhase,
    ContentStatus,
    ContentType,
    Urgency,
)
from backend.state.schema import XHSGrowthState
from backend.state.substates import (
    TrendData,
    ContentPlan,
    CopyContent,
    VisualPlan,
    PublishResult,
    AnalyticsSnapshot,
    HumanFeedback,
    EngagementAction,
    RipplePrediction,
    RipplePMFResult,
    HotTopicItem,
    NicheOpportunity,
    CompetitorPost,
    # 发布前优化子状态
    DraftContent,
    ViralPost,
    GapItem,
    SuggestionItem,
    OptimizationAnalysis,
    ContentVersion,
)
from backend.state.reducers import merge_dict, append_list, replace, max_value

__all__ = [
    # Main state
    "XHSGrowthState",
    # Enums
    "WorkflowPhase",
    "ContentStatus",
    "ContentType",
    "Urgency",
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
    # Reducers
    "merge_dict",
    "append_list",
    "replace",
    "max_value",
]