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
    # 发布前优化系统
    DraftContent,
    ViralPost,
    OptimizationAnalysis,
    ContentVersion,
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

    # ── 发布前优化系统 ──

    # 用户原始草稿
    draft_content: DraftContent

    # 爆款参考笔记列表
    viral_posts: Annotated[list[ViralPost], _append_list]

    # 用户提供的爆款链接
    user_viral_links: list[str]

    # 优化分析报告
    optimization_analysis: OptimizationAnalysis

    # 生成的版本列表
    content_versions: Annotated[list[ContentVersion], _append_list]

    # 用户选择的版本ID
    selected_version: str


__all__ = ["XHSGrowthState"]