"""Main state schema for XHS Growth Agent."""

from typing import Annotated, Any, TypedDict

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
    # P0-W5 (additive, checkpoint-compatible): WHY the workflow is paused.
    # "evaluator_fail_closed" is written by the evaluator node exactly when the
    # shared router predicate says a human is required, and is the contract
    # POST /resume uses to demand an explicit {"human_decision": ...} instead of
    # the legacy whole-pipeline restart. Any other pause (user pause, cancel)
    # leaves it None/absent. Add-only: never rename/remove.
    pause_reason: str | None
    # P0-W3 (additive, checkpoint-compatible): error taxonomy class of the
    # last recorded failure — transient / semantic / side_effect_unknown /
    # policy_violation / auth_expired. Written by handle_agent_error; no
    # router reads it yet (default transient = old behavior).
    error_class: str | None
    retry_count: int
    execution_mode: str  # "single" or "continuous" — from ExecutionMode enum
    workflow_mode: WorkflowMode  # "trend" or "brief" — determines pipeline path

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

    # 发布授权（P2a-S4b）—— 与 human_feedback 分开，因为它们是两个决定：
    # human_feedback 回答"这篇内容能不能过"，这里回答"这次不可逆的外部动作
    # 做不做"。合成一个键会让 publish_gate 的写入覆盖 review_gate 的判据
    # （review_outcome 正是读 human_feedback.decision 路由）。
    publish_confirmation: dict[str, Any]

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

    # Telemetry (P1a-S2) lives in the Event store, not in the checkpoint —
    # see backend/state/events.py. Nothing here keeps it in state: every
    # superstep would have re-serialized the whole log.

    # ── Artifact references (P1a-S3) ──
    # Large business bodies (copy_content, visual_plan, …) live in the
    # Artifact Store (backend/state/artifacts.py, namespace
    # ("artifacts", thread_id, kind)); this mapping holds one ArtifactRef per
    # state key and is merged on every write. Its absence = legacy full-blob
    # thread (hydration passthrough). Never read bodies from here — resolve
    # through backend.state.artifacts.resolve_state.
    artifacts: Annotated[dict[str, Any], _merge_dict]

    # 摘要化 meta（P1a-S3）：正文外置后路由谓词仍需的长度/真值/列表。
    # versions_meta 与 content_versions 写序一致、version_id 逐字复制（free-draft
    # 排序承重教训：任何给路由/UI 的列表必须保全序与 id 稳定）；blogger_notes_meta
    # 为 {"count": N, "ids": [...]}。replace reducer：每次写入整体替换。
    versions_meta: Annotated[list[dict[str, Any]], _replace]
    blogger_notes_meta: Annotated[dict[str, Any], _replace]

    # P1a-S4-1 (additive)：trend_data 正文外置到 Artifact Store 后，should_plan
    # 路由仍需"是否有可操作话题"的真值。trend_summary 由
    # artifacts.trend_summary_of 从写入值推导（{"has_topics": bool,
    # "hot_topic_count": int}，镜像路由的 hot_topics/trending_topics/topics
    # 别名链）；replace reducer：每次写入整体替换。legacy 线程无此字段，
    # routers._has_actionable_trends 走 inline fallback。
    trend_summary: Annotated[dict[str, Any], _replace]

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
