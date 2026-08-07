"""Main state schema for XHS Growth Agent."""

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from backend.state.enums import WorkflowMode, WorkflowPhase
from backend.state.reducers import append_list as _append_list
from backend.state.reducers import merge_dict as _merge_dict
from backend.state.reducers import replace as _replace
from backend.state.substates import (
    AnalyticsSnapshot,
    BloggerNote,
    BloggerProfile,
    BriefClarification,
    BriefContent,
    ContentPlan,
    ContentVersion,
    CopyContent,
    DraftContent,
    EngagementAction,
    EvaluationResult,
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
    messages: Annotated[list[Any], add_messages]

    # Stage data
    trend_data: TrendData
    content_plan: ContentPlan
    copy_content: CopyContent
    visual_plan: VisualPlan
    publish_result: PublishResult
    analytics: AnalyticsSnapshot
    # Legacy interaction history retained for checkpoint/API compatibility;
    # the workflow no longer creates automatic comment/DM actions.
    engagement_actions: Annotated[list[EngagementAction], _append_list]

    # Human review
    human_feedback: HumanFeedback

    # 创作质量评估 (RQGM agent-as-a-judge 面板) — 发布前 AI 质量关卡
    evaluation_result: EvaluationResult

    # Revision loop guard — counts evaluator→revise_content→copywriter cycles.
    # evaluator_outcome force-approves after Settings().workflow.max_revision_count
    # to prevent infinite revision loops when the panel is miscalibrated or adversarial.
    revision_count: int

    # Continuous-mode cycle guard — counts analyst→orchestrator cycles.
    # should_continue force-ends after Settings().workflow.max_cycle_count to
    # prevent runaway workflows in continuous execution mode.
    cycle_count: int

    # Ripple CAS engine
    ripple_prediction: RipplePrediction
    ripple_pmf: RipplePMFResult
    ripple_job_ids: Annotated[list[str], _append_list]
    ripple_comparison: RippleComparison
    ripple_decision: dict[str, Any]  # {"action": "accept"|"reangle"|"retopic"} from ripple_gate
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

    # 生成的版本列表 — replace: 每轮 version_generator 生成 A/B/C 当前轮候选，
    # 多轮增长循环下 replace 而非累加，保证 version_id 全局唯一（choice_gate 匹配正确）
    content_versions: Annotated[list[ContentVersion], _replace]

    # 用户选择的版本ID
    selected_version: str

    # True after first choice_gate (style selection) — signals version_generator
    # to use draft_content from selected style as base for A/B/C variants
    style_selected: bool

    # Optional optimization control
    skip_optimization: bool
    optimization_error: str | None

    # Legacy post-publish interaction error retained for checkpoint/API
    # compatibility. The workflow no longer writes or processes it.
    engagement_error: str | None

    # ── 博主参考系统 ──

    # 候选博主列表 (供用户选择) — replace: each blogger_scout run replaces the full list
    blogger_candidates: Annotated[list[BloggerProfile], _replace]

    # 用户选中的博主 — replace: returning {} clears old selection (vs merge_dict which preserves)
    selected_blogger: Annotated[dict[str, Any], _replace]

    # 选中博主的 top 笔记 — replace: each selection replaces the full list
    blogger_notes: Annotated[list[BloggerNote], _replace]

    # 博主选择被跳过 (无候选或用户跳过)
    blogger_skipped: bool

    # 候选博主数量限制 (默认 5)
    blogger_candidate_limit: int

    # 博主笔记获取深度 (默认 3)
    blogger_note_limit: int

    # History
    content_history: Annotated[list[dict[str, Any]], _append_list]
    performance_log: Annotated[list[dict[str, Any]], _append_list]

    # Metadata
    account_id: str
    session_id: str
    thread_id: str
    created_at: str
    updated_at: str

    # Publish options (set by review decision)
    publish_options: dict[str, Any]
    dry_run: bool
    auto_publish: bool

    # User-specified config
    niche: str  # Track/category (e.g. 母婴, 美妆, 穿搭)
    topic: str  # Optional user-provided topic override


__all__ = ["XHSGrowthState", "WorkflowPhase"]
