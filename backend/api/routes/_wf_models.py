"""Request/response models for the workflow routes.

A leaf module: the api layer shapes HTTP and the application layer builds
the payloads, so both read these shapes and neither owns them (a leaf is
what keeps the import graph acyclic without a deferred import).
``backend.api.routes.workflow`` still re-exports every name here, so
``from backend.api.routes.workflow import WorkflowStartRequest`` keeps
working.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.state.enums import WorkflowMode

# ── Request/Response models ──


class WorkflowStartRequest(BaseModel):
    account_id: str = Field(default="default", description="账号 ID")
    # No ``phase`` field, on purpose. A run's start phase is the mode's
    # (``backend/state/goal.py``'s ``Goal.start_phase``): the graph's entry is
    # always ``orchestrator`` and that node unconditionally writes the mode's
    # phase, so a caller-supplied one never chose the entry -- it only made this
    # endpoint's response and the DB row name a phase the graph was not in.
    # Removed rather than ignored: pydantic's default ``extra="ignore"`` means a
    # client still sending it is not refused, only unheard.
    async_mode: bool = Field(default=True, description="异步执行模式")
    dry_run: bool = Field(default=False, description="试运行模式（不实际发布）")
    auto_publish: bool = Field(default=False, description="审核通过后自动发布")
    topic: str | None = Field(default=None, description="内容主题/关键词")
    niche: str = Field(
        default="",
        description="垂类赛道；空字符串=根据历史笔记自动推断，非空=手动指定（优先于推断）",
    )
    execution_mode: str = Field(default="single", description="执行模式: single/continuous")
    # The boundary that refuses an unknown mode. Typed rather than left a bare
    # ``str`` because the mode reads downstream each carried their own
    # ``"trend"`` default, which made an unknown value *behave* as trend without
    # ever saying so;
    # this is the only place a mode can enter a run, so refusing here is the
    # whole fix (see ``backend/state/modes.py``).
    #
    # ``WorkflowStatusResponse.workflow_mode`` just below stays a ``str`` on
    # purpose: it echoes what a stored row holds, including rows written before
    # this boundary existed, and ``/status`` keeps its full response shape.
    workflow_mode: WorkflowMode = Field(
        default=WorkflowMode.TREND,
        description="工作模式: trend/brief；未知值在请求边界被拒绝（P2c-S3a，不再静默按 trend）",
    )
    brief_text: str | None = Field(default=None, description="商单 brief 文本内容")


class RecoverRequest(BaseModel):
    """恢复策略请求体 — /recover 端点入参。

    strategy:
      - retry_failed: 等同 /resume error 路径，native ainvoke(None) 重跑失败 task
      - retry_from_last_success: Command(goto=last_success) 从上次成功节点重跑下游
      - skip_to_next: Command(goto=next) 跳过失败节点，从后继节点继续
    """

    strategy: Literal["retry_failed", "retry_from_last_success", "skip_to_next"] = Field(
        default="retry_failed", description="恢复策略"
    )


class AgentTimelineEntry(BaseModel):
    agent: str
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    status: str = "success"
    error: str | None = None


class WorkflowStatusResponse(BaseModel):
    thread_id: str
    phase: str
    status: str = Field(default="running", description="Derived workflow status")
    current_agent: str
    next_steps: list[str]
    error: str | None = None
    progress_percent: int = Field(default=0, description="进度百分比")
    created_at: str | None = None
    updated_at: str | None = None
    account_id: str = Field(
        default="",
        description="Owning XHS account id (from state/DB, else parsed from thread_id)",
    )
    agent_timeline: list[AgentTimelineEntry] = Field(
        default_factory=list, description="Agent 执行时间线"
    )
    trend_data: dict[str, Any] = Field(default_factory=dict, description="趋势发现数据")
    content_plan: dict[str, Any] = Field(default_factory=dict, description="内容策略")
    copy_content: dict[str, Any] = Field(default_factory=dict, description="文案内容")
    draft_content: dict[str, Any] = Field(default_factory=dict, description="用户草稿内容")
    optimization_analysis: dict[str, Any] = Field(default_factory=dict, description="优化分析")
    content_versions: list[dict[str, Any]] = Field(default_factory=list, description="优化版本")
    visual_plan: dict[str, Any] = Field(default_factory=dict, description="视觉方案")
    publish_result: dict[str, Any] = Field(default_factory=dict, description="发布结果")
    analytics: dict[str, Any] = Field(default_factory=dict, description="分析数据")
    ripple_prediction: dict[str, Any] = Field(default_factory=dict, description="Ripple 传播预测")
    ripple_pmf: dict[str, Any] = Field(default_factory=dict, description="Ripple PMF 验证")
    ripple_comparison: dict[str, Any] = Field(
        default_factory=dict, description="Ripple 预测 vs 实际对比"
    )
    ripple_progress: dict[str, Any] = Field(default_factory=dict, description="Ripple 模拟进度")
    workflow_mode: str = Field(default="trend", description="工作模式: trend/brief")
    brief_content: dict[str, Any] = Field(default_factory=dict, description="解析后的 Brief 内容")
    brief_clarification: dict[str, Any] = Field(default_factory=dict, description="Brief 补充问题")
    shooting_plan: dict[str, Any] = Field(default_factory=dict, description="拍摄计划")
    blogger_candidates: list[dict[str, Any]] = Field(
        default_factory=list, description="候选博主列表"
    )
    selected_blogger: dict[str, Any] = Field(default_factory=dict, description="选中的博主")
    blogger_notes: list[dict[str, Any]] = Field(default_factory=list, description="博主笔记")
    blogger_candidate_limit: int = Field(default=5, description="候选博主上限")
    blogger_note_limit: int = Field(default=3, description="每个博主笔记上限")
    reselect_count: int = Field(default=0, description="重新选题次数")
    ripple_reason: str = Field(default="", description="Ripple 未运行原因")
    label: str = Field(default="", description="工作流名称")
    # P0-W5: set when the evaluator quality gate parked the workflow
    # ("evaluator_fail_closed"). The UI uses it to render an approve/revise
    # decision prompt instead of a plain "resume" button, because /resume on
    # such a thread REQUIRES an explicit human_decision.
    pause_reason: str | None = Field(
        default=None, description="原因：为何工作流停在 paused（如 evaluator_fail_closed）"
    )
    checkpoint_lost: bool = Field(
        default=False,
        description="Checkpoint lost after container restart",
    )
    orphan: bool = Field(
        default=False,
        description="DB running but no live in-process task (restart orphan) — derived stale",
    )


class CheckpointSnapshot(BaseModel):
    """A single checkpoint snapshot from workflow execution history."""

    checkpoint_id: str = Field(description="Checkpoint ID for cursor-based pagination")
    step: int = Field(default=0, description="LangGraph step number")
    source: str = Field(default="", description="Node that produced this checkpoint")
    phase: str = Field(default="unknown", description="Workflow phase at this checkpoint")
    current_agent: str = Field(default="", description="Active agent at this checkpoint")
    created_at: str | None = Field(default=None, description="Checkpoint creation timestamp")
    next_nodes: list[str] = Field(default_factory=list, description="Nodes scheduled to run next")
    # Stage data (non-empty only when populated by that point)
    trend_data: dict[str, Any] = Field(default_factory=dict)
    content_plan: dict[str, Any] = Field(default_factory=dict)
    copy_content: dict[str, Any] = Field(default_factory=dict)
    draft_content: dict[str, Any] = Field(default_factory=dict)
    optimization_analysis: dict[str, Any] = Field(default_factory=dict)
    content_versions: list[dict[str, Any]] = Field(default_factory=list)
    visual_plan: dict[str, Any] = Field(default_factory=dict)
    publish_result: dict[str, Any] = Field(default_factory=dict)
    analytics: dict[str, Any] = Field(default_factory=dict)
    ripple_prediction: dict[str, Any] = Field(default_factory=dict)
    ripple_pmf: dict[str, Any] = Field(default_factory=dict)
    ripple_comparison: dict[str, Any] = Field(default_factory=dict)
    workflow_mode: str = Field(default="trend")
    brief_content: dict[str, Any] = Field(default_factory=dict)
    shooting_plan: dict[str, Any] = Field(default_factory=dict)


class CheckpointHistoryResponse(BaseModel):
    """Paginated response of checkpoint snapshots."""

    thread_id: str
    checkpoints: list[CheckpointSnapshot]
    has_more: bool = Field(default=False, description="Whether older checkpoints exist")


class BriefExtractResponse(BaseModel):
    brief_text: str
    source_type: str


class BriefUploadResponse(BaseModel):
    thread_id: str
    brief_text: str
    source_type: str


# ── Image Upload ─────────────────────────────────────────────────────────


class ImageUploadResponse(BaseModel):
    image_paths: list[str]
    count: int
