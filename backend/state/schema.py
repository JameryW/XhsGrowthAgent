"""Main state schema for XHS Growth Agent."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from backend.state.enums import WorkflowMode, WorkflowPhase
from backend.state.reducers import append_list as _append_list
from backend.state.reducers import merge_dict as _merge_dict
from backend.state.substates import (
    AnalyticsSnapshot,
    BriefClarification,
    BriefContent,
    ContentPlan,
    ContentVersion,
    CopyContent,
    DraftContent,
    EngagementAction,
    HumanFeedback,
    OptimizationAnalysis,
    PublishResult,
    RippleComparison,
    RipplePMFResult,
    RipplePrediction,
    ShootingPlan,
    TrendData,
    ViralPost,
    VisualPlan,
)


class XHSGrowthState(TypedDict, total=False):
    """XHS Growth Agent global state."""

    # Workflow control
    phase: WorkflowPhase
    prev_phase: str  # Phase before pause/cancel, for resume
    current_agent: str
    error: str | None
    retry_count: int
    execution_mode: str  # "single" or "continuous" — from ExecutionMode enum
    workflow_mode: WorkflowMode  # "trend" or "brief" — determines pipeline path

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
    ripple_comparison: RippleComparison
    ripple_decision: dict  # {"action": "accept"|"reangle"|"retopic"} from ripple_gate
    reselect_count: int  # Tracks reselect cycles (max 2)

    # ── 商单 Brief 模式 ──

    brief_content: Annotated[BriefContent, _merge_dict]
    brief_clarification: Annotated[BriefClarification, _merge_dict]
    shooting_plan: Annotated[ShootingPlan, _merge_dict]

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

    # Optional optimization control
    skip_optimization: bool
    optimization_error: str | None

    # History
    content_history: Annotated[list[dict], _append_list]
    performance_log: Annotated[list[dict], _append_list]

    # Metadata
    account_id: str
    session_id: str
    thread_id: str
    created_at: str
    updated_at: str

    # Publish options (set by review decision)
    publish_options: dict
    dry_run: bool
    auto_publish: bool


__all__ = ["XHSGrowthState"]
