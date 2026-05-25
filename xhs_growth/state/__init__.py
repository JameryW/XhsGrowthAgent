"""State module — LangGraph state definitions.

Components:
- schema: Main state TypedDict (XHSGrowthState)
- substates: Modular sub-state TypedDict definitions
- reducers: State reducer functions
- enums: Unified enum definitions
"""

from xhs_growth.state.enums import (
    WorkflowPhase,
    ContentStatus,
    ContentType,
    Urgency,
)
from xhs_growth.state.schema import XHSGrowthState
from xhs_growth.state.substates import (
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
)
from xhs_growth.state.reducers import merge_dict, append_list, replace, max_value

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
    # Reducers
    "merge_dict",
    "append_list",
    "replace",
    "max_value",
]