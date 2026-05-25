"""Main state schema for XHS Growth Agent."""
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from xhs_growth.state.enums import WorkflowPhase
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
)
from xhs_growth.state.reducers import merge_dict as _merge_dict, append_list as _append_list


class XHSGrowthState(TypedDict, total=False):
    """XHS Growth Agent global state."""

    # Workflow control
    phase: WorkflowPhase
    current_agent: str
    error: str | None
    retry_count: int

    # Message history (LangGraph built-in reducer)
    messages: Annotated[list, add_messages]

    # Stage data
    trend_data: TrendData
    content_plan: ContentPlan
    copy_content: CopyContent
    visual_plan: VisualPlan
    publish_result: PublishResult
    analytics: AnalyticsSnapshot
    engagement_actions: Annotated[list[EngagementAction], _append_list]

    # Human review
    human_feedback: HumanFeedback

    # Ripple CAS engine
    ripple_prediction: RipplePrediction
    ripple_pmf: RipplePMFResult
    ripple_job_ids: Annotated[list[str], _append_list]

    # History
    content_history: Annotated[list[dict], _append_list]
    performance_log: Annotated[list[dict], _append_list]

    # Metadata
    account_id: str
    session_id: str
    created_at: str
    updated_at: str


__all__ = ["XHSGrowthState"]