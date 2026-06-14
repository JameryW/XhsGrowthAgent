"""Workflow API routes — start/pause/resume/list/cancel workflows."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.errors import ValidationError, WorkflowNotFoundError
from backend.api.responses import success
from backend.api.routes import _runner
from backend.db.pool import is_pool_ready
from backend.db.workflows import (
    delete_workflow as db_delete,
)
from backend.db.workflows import (
    get_workflow as db_get,
)
from backend.db.workflows import (
    list_workflows as db_list,
)
from backend.db.workflows import (
    update_workflow as db_update,
)
from backend.realtime import EventBusService
from backend.realtime.events import EventType
from backend.state.enums import WorkflowPhase
from backend.state.machine import WorkflowStatus, derive_status

logger = logging.getLogger(__name__)

router = APIRouter()

# ── History files for completed workflow results ──
_HISTORY_DIR = Path(os.environ.get("XHS_REGISTRY_PATH", ".xhs")) / "history"

# ── In-memory tracking (not persisted — rebuilt on restart from DB) ──
_background_tasks: dict[str, asyncio.Task] = {}
_last_status: dict[str, WorkflowStatus] = {}


def _save_history_file(thread_id: str, data: dict) -> None:
    try:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        path = _HISTORY_DIR / f"{thread_id}.json"
        path.write_text(json.dumps(data, default=str, ensure_ascii=False))
    except Exception:
        logger.exception("Failed to save history for %s", thread_id)


def _load_history_file(thread_id: str) -> dict | None:
    path = _HISTORY_DIR / f"{thread_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            logger.exception("Failed to load history for %s", thread_id)
    return None


# ── DB-aware helpers ──

# Re-export _db_upsert from _runner for use in this module
_db_upsert = _runner._db_upsert


def _on_task_done(thread_id: str):
    """Background task done callback — update DB with task_done_at / stale status."""
    def callback(task: asyncio.Task) -> None:
        task_error = None
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Background task for %s failed: %s", thread_id, e)
            task_error = str(e)

        # Best-effort DB update via ensure_future (can't await in a sync callback,
        # and run_until_complete would crash inside an already-running event loop).
        try:
            updates: dict[str, Any] = {"task_done_at": datetime.now(UTC).isoformat()}
            if task_error:
                updates["task_error"] = task_error

            async def _do_update() -> None:
                if not is_pool_ready():
                    return
                existing = await db_get(thread_id)
                if existing and existing.status == "running":
                    updates["status"] = "stale"
                if existing:
                    await db_update(thread_id, **updates)

            asyncio.ensure_future(_do_update())
        except Exception:
            logger.exception("Failed to update DB in task_done callback for %s", thread_id)
    return callback


def _resume_phase_for_next_nodes(
    next_nodes: tuple[str, ...],
    fallback: str | WorkflowPhase,
) -> str | WorkflowPhase:
    """Infer a non-terminal phase when retrying from a checkpointed next node."""
    phase_by_node: dict[str, WorkflowPhase] = {
        "orchestrator": WorkflowPhase.SCOUTING,
        "trend_scout": WorkflowPhase.SCOUTING,
        "content_strategist": WorkflowPhase.PLANNING,
        "copywriter": WorkflowPhase.CREATING,
        "draft_gate": WorkflowPhase.CREATING,
        "viral_matcher": WorkflowPhase.CREATING,
        "content_analyzer": WorkflowPhase.CREATING,
        "version_generator": WorkflowPhase.CREATING,
        "choice_gate": WorkflowPhase.CREATING,
        "visual_designer": WorkflowPhase.CREATING,
        "review_gate": WorkflowPhase.REVIEWING,
        "revise_content": WorkflowPhase.REVIEWING,
        "publisher": WorkflowPhase.PUBLISHING,
        "analyst": WorkflowPhase.ANALYZING,
        "engagement": WorkflowPhase.ENGAGING,
    }
    for node in next_nodes:
        if node in phase_by_node:
            return phase_by_node[node]
    return fallback


def _persisted_status(phase: str | WorkflowPhase, error: str | None = None) -> str:
    """Derive status for persisted records without live snapshot."""
    if phase == WorkflowPhase.ERROR or error:
        return WorkflowStatus.ERROR.value
    if phase == WorkflowPhase.CANCELLED:
        return WorkflowStatus.CANCELLED.value
    if phase == WorkflowPhase.PAUSED:
        return WorkflowStatus.PAUSED.value
    if phase == WorkflowPhase.COMPLETED:
        return WorkflowStatus.COMPLETED.value
    return WorkflowStatus.RUNNING.value


async def _start_resume_task(
    thread_id: str,
    graph,
    config: dict,
    phase: str | WorkflowPhase,
) -> None:
    """Mark a workflow running and resume graph execution in the background."""
    await _db_upsert(
        thread_id,
        status="running",
        phase=str(phase),
        error=None,
    )

    async def _resume_async():
        await _runner._run_graph_and_persist(
            thread_id, graph, config, None, source="resume",
        )

    task = asyncio.create_task(_resume_async())
    task.add_done_callback(_on_task_done(thread_id))
    _background_tasks[thread_id] = task


# ── Request/Response models ──

class WorkflowStartRequest(BaseModel):
    account_id: str = Field(default="default", description="账号 ID")
    phase: WorkflowPhase = Field(default=WorkflowPhase.SCOUTING, description="起始阶段")
    async_mode: bool = Field(default=True, description="异步执行模式")
    dry_run: bool = Field(default=False, description="试运行模式（不实际发布）")
    auto_publish: bool = Field(default=False, description="审核通过后自动发布")
    topic: str | None = Field(default=None, description="内容主题/关键词")
    niche: str = Field(default="母婴", description="垂类赛道")
    execution_mode: str = Field(default="single", description="执行模式: single/continuous")
    workflow_mode: str = Field(default="trend", description="工作模式: trend/brief")
    brief_text: str | None = Field(default=None, description="商单 brief 文本内容")


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
    agent_timeline: list[AgentTimelineEntry] = Field(
        default_factory=list, description="Agent 执行时间线"
    )
    trend_data: dict = Field(default_factory=dict, description="趋势发现数据")
    content_plan: dict = Field(default_factory=dict, description="内容策略")
    copy_content: dict = Field(default_factory=dict, description="文案内容")
    draft_content: dict = Field(default_factory=dict, description="用户草稿内容")
    optimization_analysis: dict = Field(default_factory=dict, description="优化分析")
    content_versions: list[dict] = Field(default_factory=list, description="优化版本")
    visual_plan: dict = Field(default_factory=dict, description="视觉方案")
    publish_result: dict = Field(default_factory=dict, description="发布结果")
    analytics: dict = Field(default_factory=dict, description="分析数据")
    ripple_prediction: dict = Field(default_factory=dict, description="Ripple 传播预测")
    ripple_pmf: dict = Field(default_factory=dict, description="Ripple PMF 验证")
    ripple_comparison: dict = Field(default_factory=dict, description="Ripple 预测 vs 实际对比")
    ripple_progress: dict = Field(default_factory=dict, description="Ripple 模拟进度")
    workflow_mode: str = Field(default="trend", description="工作模式: trend/brief")
    brief_content: dict = Field(default_factory=dict, description="解析后的 Brief 内容")
    brief_clarification: dict = Field(default_factory=dict, description="Brief 补充问题")
    shooting_plan: dict = Field(default_factory=dict, description="拍摄计划")
    blogger_candidates: list[dict] = Field(default_factory=list, description="候选博主列表")
    selected_blogger: dict = Field(default_factory=dict, description="选中的博主")
    blogger_notes: list[dict] = Field(default_factory=list, description="博主笔记")
    reselect_count: int = Field(default=0, description="重新选题次数")
    label: str = Field(default="", description="工作流名称")
    checkpoint_lost: bool = Field(
        default=False, description="Checkpoint lost after container restart",
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
    trend_data: dict = Field(default_factory=dict)
    content_plan: dict = Field(default_factory=dict)
    copy_content: dict = Field(default_factory=dict)
    draft_content: dict = Field(default_factory=dict)
    optimization_analysis: dict = Field(default_factory=dict)
    content_versions: list[dict] = Field(default_factory=list)
    visual_plan: dict = Field(default_factory=dict)
    publish_result: dict = Field(default_factory=dict)
    analytics: dict = Field(default_factory=dict)
    ripple_prediction: dict = Field(default_factory=dict)
    ripple_pmf: dict = Field(default_factory=dict)
    ripple_comparison: dict = Field(default_factory=dict)
    workflow_mode: str = Field(default="trend")
    brief_content: dict = Field(default_factory=dict)
    shooting_plan: dict = Field(default_factory=dict)


class CheckpointHistoryResponse(BaseModel):
    """Paginated response of checkpoint snapshots."""
    thread_id: str
    checkpoints: list[CheckpointSnapshot]
    has_more: bool = Field(default=False, description="Whether older checkpoints exist")


PHASE_PROGRESS = {
    "idle": 0,
    "scouting": 10,
    "planning": 20,
    "creating": 40,
    "reviewing": 60,
    "publishing": 80,
    "analyzing": 90,
    "engaging": 95,
    "completed": 100,
    "error": 0,
}


def get_progress(phase: str) -> int:
    return PHASE_PROGRESS.get(phase, 0)


def _extract_ripple(values: dict, key: str) -> dict:
    return values.get(key) or values.get("content_plan", {}).get(key) or {}


def _get_ripple_progress(thread_id: str) -> dict:
    """Get current Ripple simulation progress for a thread from RippleService."""
    try:
        from backend.services.ripple_service import RippleService
        return RippleService.get_thread_progress(thread_id)
    except Exception:
        return {}


# ── Endpoints ──

@router.post("/start")
async def start_workflow(req: WorkflowStartRequest, request: Request):
    """启动新的增长引擎工作流"""
    if not req.account_id or req.account_id.strip() == "":
        raise ValidationError("account_id", "account_id cannot be empty")

    graph = request.app.state.graph
    thread_id = f"xhs_{req.account_id}_{uuid.uuid4().hex[:8]}"

    initial_state = {
        "phase": req.phase,
        "current_agent": "orchestrator",
        "error": None,
        "retry_count": 0,
        "execution_mode": req.execution_mode,
        "workflow_mode": req.workflow_mode,
        "messages": [],
        "trend_data": {},
        "content_plan": {},
        "copy_content": {},
        "visual_plan": {},
        "publish_result": {},
        "analytics": {},
        "engagement_actions": [],
        "human_feedback": {},
        "content_history": [],
        "performance_log": [],
        "account_id": req.account_id,
        "session_id": thread_id,
        "thread_id": thread_id,
        "topic": req.topic,
        "niche": req.niche,
        "dry_run": req.dry_run,
        "auto_publish": req.auto_publish,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    if req.workflow_mode == "brief":
        initial_state["phase"] = WorkflowPhase.BRIEFING
        if req.brief_text:
            initial_state["brief_content"] = {
                "raw_text": req.brief_text,
                "source_type": "text",
            }

    config = {"configurable": {"thread_id": thread_id}}
    now = datetime.now(UTC).isoformat()

    # Register workflow in DB (no-op when DB unavailable)
    await _db_upsert(
        thread_id,
        account_id=req.account_id,
        phase=initial_state["phase"].value if isinstance(initial_state["phase"], WorkflowPhase) else initial_state["phase"],
        status="running",
        dry_run=req.dry_run,
        auto_publish=req.auto_publish,
        progress_percent=get_progress(initial_state["phase"].value if isinstance(initial_state["phase"], WorkflowPhase) else initial_state["phase"]),
        workflow_mode=req.workflow_mode,
        label="",
        created_at=now,
        updated_at=now,
    )

    # Brief mode without text: save initial state to checkpoint but don't start
    # execution yet — the PDF upload will trigger the actual start via aupdate_state.
    brief_waiting_for_upload = (
        req.workflow_mode == "brief" and not req.brief_text
    )

    if brief_waiting_for_upload:
        await graph.aupdate_state(config, initial_state, as_node="orchestrator")
        return success(data={
            "thread_id": thread_id,
            "status": "running",
            "phase": WorkflowPhase.BRIEFING.value,
            "progress_percent": get_progress(WorkflowPhase.BRIEFING.value),
            "sse_url": f"/api/workflow/stream/{thread_id}",
            "websocket_url": "/api/realtime/ws",
        })

    if req.async_mode:
        async def _run_async():
            await _runner._run_graph_and_persist(
                thread_id, graph, config, initial_state, source="start",
            )

        task = asyncio.create_task(_run_async())
        task.add_done_callback(_on_task_done(thread_id))
        _background_tasks[thread_id] = task
        return success(data={
            "thread_id": thread_id,
            "status": "running",
            "phase": req.phase.value,
            "progress_percent": get_progress(req.phase.value),
            "sse_url": f"/api/workflow/stream/{thread_id}",
            "websocket_url": "/api/realtime/ws",
        })
    else:
        with contextlib.suppress(asyncio.CancelledError):
            await _runner._run_graph_and_persist(
                thread_id, graph, config, initial_state, source="start",
            )

        # Read final status from DB (fallback to completed when DB unavailable)
        row = await db_get(thread_id) if is_pool_ready() else None
        final_status = row.status if row else "completed"
        final_phase = row.phase if row else "unknown"

        return success(data={
            "thread_id": thread_id,
            "status": final_status,
            "phase": final_phase,
            "progress_percent": 100 if final_status == "completed" else 0,
        })


@router.get("/status/{thread_id}")
async def get_workflow_status(thread_id: str, request: Request):
    """获取工作流状态"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # Check if workflow exists in live graph state
    if state.values and state.values.get("session_id") is not None:
        phase = state.values.get("phase", "unknown")
        progress = get_progress(phase)

        has_active = (
            (thread_id in _background_tasks and not _background_tasks[thread_id].done())
            or (thread_id in _runner._active_sync_executions)
        )
        derived_status = derive_status(state, has_active_task=has_active)
        status_str = str(derived_status.value)

        # Persist completed workflow results to history file
        if phase in ("completed", "error", "cancelled"):
            _save_history_file(thread_id, state.values)

        # Update DB
        update_fields: dict[str, Any] = {
            "phase": phase,
            "status": status_str,
            "progress_percent": progress,
        }
        if state.values.get("error"):
            update_fields["error"] = state.values.get("error")

        # Update label with content summary (brand name for brief, topic for trend)
        values = state.values
        if not update_fields.get("label"):
            bc = values.get("brief_content") or {}
            cp = values.get("content_plan") or {}
            if bc.get("brand_name"):
                update_fields["label"] = bc["brand_name"]
            elif cp.get("selected_topic"):
                update_fields["label"] = cp["selected_topic"]
        if "workflow_mode" not in update_fields:
            wm = values.get("workflow_mode")
            if wm:
                update_fields["workflow_mode"] = wm

        await _db_upsert(thread_id, **update_fields)

        # Resolve label for response: prefer DB/persisted label, then auto-generated
        label = update_fields.get("label", "")
        if not label:
            row = await db_get(thread_id) if is_pool_ready() else None
            label = row.label if row else ""

        perf_log = state.values.get("performance_log") or []
        agent_timeline = [
            AgentTimelineEntry(
                agent=entry.get("agent", "unknown"),
                started_at=entry.get("started_at", ""),
                completed_at=entry.get("completed_at", ""),
                duration_seconds=entry.get("duration_seconds", 0.0),
                status=entry.get("status", "success"),
                error=entry.get("error"),
            )
            for entry in perf_log
        ]

        return success(data=WorkflowStatusResponse(
            thread_id=thread_id,
            phase=phase,
            status=status_str,
            current_agent=state.values.get("current_agent", "unknown"),
            next_steps=list(state.next) if state.next else [],
            error=state.values.get("error"),
            progress_percent=progress,
            created_at=state.values.get("created_at"),
            updated_at=state.values.get("updated_at"),
            agent_timeline=agent_timeline,
            trend_data=state.values.get("trend_data") or {},
            content_plan=state.values.get("content_plan") or {},
            copy_content=state.values.get("copy_content") or {},
            draft_content=state.values.get("draft_content") or {},
            optimization_analysis=state.values.get("optimization_analysis") or {},
            content_versions=state.values.get("content_versions") or [],
            visual_plan=state.values.get("visual_plan") or {},
            publish_result=state.values.get("publish_result") or {},
            analytics=state.values.get("analytics") or {},
            ripple_prediction=_extract_ripple(state.values, "ripple_prediction"),
            ripple_pmf=_extract_ripple(state.values, "ripple_pmf"),
            ripple_comparison=state.values.get("ripple_comparison") or {},
            ripple_progress=_get_ripple_progress(thread_id),
            workflow_mode=state.values.get("workflow_mode") or "trend",
            brief_content=state.values.get("brief_content") or {},
            brief_clarification=state.values.get("brief_clarification") or {},
            shooting_plan=state.values.get("shooting_plan") or {},
            blogger_candidates=state.values.get("blogger_candidates") or [],
            selected_blogger=state.values.get("selected_blogger") or {},
            blogger_notes=state.values.get("blogger_notes") or [],
            reselect_count=state.values.get("reselect_count", 0),
            label=label,
        ).model_dump())

    # Fallback 1: check history file (pre-DB completed workflows)
    saved = _load_history_file(thread_id)
    if saved:
        phase = saved.get("phase", "unknown")
        perf_log = saved.get("performance_log") or []
        agent_timeline = [
            AgentTimelineEntry(
                agent=entry.get("agent", "unknown"),
                started_at=entry.get("started_at", ""),
                completed_at=entry.get("completed_at", ""),
                duration_seconds=entry.get("duration_seconds", 0.0),
                status=entry.get("status", "success"),
                error=entry.get("error"),
            )
            for entry in perf_log
        ]
        return success(data=WorkflowStatusResponse(
            thread_id=thread_id,
            phase=phase,
            status=_persisted_status(phase, saved.get("error")),
            current_agent=saved.get("current_agent", "unknown"),
            next_steps=[],
            error=saved.get("error"),
            progress_percent=get_progress(phase),
            created_at=saved.get("created_at"),
            updated_at=saved.get("updated_at"),
            agent_timeline=agent_timeline,
            trend_data=saved.get("trend_data") or {},
            content_plan=saved.get("content_plan") or {},
            copy_content=saved.get("copy_content") or {},
            draft_content=saved.get("draft_content") or {},
            optimization_analysis=saved.get("optimization_analysis") or {},
            content_versions=saved.get("content_versions") or [],
            visual_plan=saved.get("visual_plan") or {},
            publish_result=saved.get("publish_result") or {},
            analytics=saved.get("analytics") or {},
            ripple_prediction=_extract_ripple(saved, "ripple_prediction"),
            ripple_pmf=_extract_ripple(saved, "ripple_pmf"),
            ripple_comparison=saved.get("ripple_comparison") or {},
            ripple_progress={},  # History file has no live Ripple progress
            label="",
        ).model_dump())

    # Fallback 2: check DB for metadata-only entries (e.g. workflows created but
    # not yet checkpointed by LangGraph)
    if is_pool_ready():
        row = await db_get(thread_id)
    else:
        row = None
    if row:
        # A workflow is only truly "checkpoint lost" if:
        # - It has a non-terminal status in DB (meaning it was running/paused/awaiting)
        # - AND there is no active background task for it in this process
        # - AND there is no live LangGraph checkpoint (we already checked above)
        has_active_task = (
            thread_id in _background_tasks
            and not _background_tasks[thread_id].done()
        )
        checkpoint_lost = (
            row.status in (
                "running", "stale", "paused", "awaiting_review",
                "awaiting_choice", "awaiting_draft", "awaiting_brief",
            )
            and not has_active_task
        )
        data = WorkflowStatusResponse(
            thread_id=thread_id,
            phase=row.phase,
            status=row.status or _persisted_status(row.phase, row.error),
            current_agent="unknown",
            next_steps=[],
            error=row.error,
            progress_percent=row.progress_percent,
            created_at=row.created_at,
            updated_at=row.updated_at,
            label=row.label or "",
            checkpoint_lost=checkpoint_lost,
        ).model_dump()
        return success(data=data)

    raise WorkflowNotFoundError(thread_id)


def _snapshot_to_checkpoint(snapshot) -> CheckpointSnapshot:
    """Convert a LangGraph StateSnapshot to a CheckpointSnapshot."""
    values = snapshot.values or {}
    meta = snapshot.metadata or {}
    checkpoint_id = ""
    if snapshot.config and snapshot.config.get("configurable"):
        checkpoint_id = snapshot.config["configurable"].get("checkpoint_id", "")
    return CheckpointSnapshot(
        checkpoint_id=checkpoint_id,
        step=meta.get("step", 0),
        source=meta.get("source", ""),
        phase=values.get("phase", "unknown"),
        current_agent=values.get("current_agent", ""),
        created_at=snapshot.created_at,
        next_nodes=list(snapshot.next) if snapshot.next else [],
        trend_data=values.get("trend_data") or {},
        content_plan=values.get("content_plan") or {},
        copy_content=values.get("copy_content") or {},
        draft_content=values.get("draft_content") or {},
        optimization_analysis=values.get("optimization_analysis") or {},
        content_versions=values.get("content_versions") or [],
        visual_plan=values.get("visual_plan") or {},
        publish_result=values.get("publish_result") or {},
        analytics=values.get("analytics") or {},
        ripple_prediction=_extract_ripple(values, "ripple_prediction"),
        ripple_pmf=_extract_ripple(values, "ripple_pmf"),
        ripple_comparison=values.get("ripple_comparison") or {},
        workflow_mode=values.get("workflow_mode") or "trend",
        brief_content=values.get("brief_content") or {},
        shooting_plan=values.get("shooting_plan") or {},
    )


@router.get("/history/{thread_id}")
async def get_checkpoint_history(
    thread_id: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="Max checkpoints to return"),
    before: str | None = Query(None, description="Checkpoint ID cursor for pagination"),
):
    """获取工作流的检查点历史记录（用于回放）"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    # Build before_config for cursor-based pagination
    before_config = None
    if before:
        before_config = {"configurable": {"thread_id": thread_id, "checkpoint_id": before}}

    checkpoints: list[CheckpointSnapshot] = []
    has_more = False
    found_workflow = False

    try:
        count = 0
        async for snapshot in graph.aget_state_history(
            config, limit=limit + 1, before=before_config,
        ):
            found_workflow = True
            if count >= limit:
                has_more = True
                break
            checkpoints.append(_snapshot_to_checkpoint(snapshot))
            count += 1
    except ValueError:
        # No checkpointer configured — fall through to history file fallback
        pass

    if found_workflow:
        return success(data=CheckpointHistoryResponse(
            thread_id=thread_id,
            checkpoints=checkpoints,
            has_more=has_more,
        ).model_dump())

    # Fallback: check history file for completed workflows (no live checkpoints)
    saved = _load_history_file(thread_id)
    if saved:
        phase = saved.get("phase", "unknown")
        checkpoint = CheckpointSnapshot(
            checkpoint_id="history-final",
            step=0,
            source="history_file",
            phase=phase,
            current_agent=saved.get("current_agent", ""),
            created_at=saved.get("updated_at") or saved.get("created_at"),
            next_nodes=[],
            trend_data=saved.get("trend_data") or {},
            content_plan=saved.get("content_plan") or {},
            copy_content=saved.get("copy_content") or {},
            draft_content=saved.get("draft_content") or {},
            optimization_analysis=saved.get("optimization_analysis") or {},
            content_versions=saved.get("content_versions") or [],
            visual_plan=saved.get("visual_plan") or {},
            publish_result=saved.get("publish_result") or {},
            analytics=saved.get("analytics") or {},
            ripple_prediction=_extract_ripple(saved, "ripple_prediction"),
            ripple_pmf=_extract_ripple(saved, "ripple_pmf"),
            ripple_comparison=saved.get("ripple_comparison") or {},
            workflow_mode=saved.get("workflow_mode") or "trend",
            brief_content=saved.get("brief_content") or {},
            shooting_plan=saved.get("shooting_plan") or {},
        )
        return success(data=CheckpointHistoryResponse(
            thread_id=thread_id,
            checkpoints=[checkpoint],
            has_more=False,
        ).model_dump())

    # Fallback: check DB
    if is_pool_ready():
        row = await db_get(thread_id)
    else:
        row = None
    if row:
        return success(data=CheckpointHistoryResponse(
            thread_id=thread_id,
            checkpoints=[],
            has_more=False,
        ).model_dump())

    raise WorkflowNotFoundError(thread_id)


@router.post("/pause/{thread_id}")
async def pause_workflow(thread_id: str, request: Request):
    """暂停工作流"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    current_phase = state.values.get("phase", "unknown")
    await graph.aupdate_state(config, {"phase": "paused", "prev_phase": current_phase})

    bg_task = _background_tasks.get(thread_id)
    if bg_task and not bg_task.done():
        bg_task.cancel()

    await _db_upsert(thread_id, status="paused", phase="paused")

    return success(data={
        "thread_id": thread_id,
        "status": "paused",
        "message": "工作流已暂停，当前 Agent 完成后将停止",
    })


@router.post("/resume/{thread_id}")
async def resume_workflow(thread_id: str, request: Request):
    """恢复暂停或可重试错误的工作流"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        saved = _load_history_file(thread_id)
        if not saved or saved.get("phase") != WorkflowPhase.ERROR:
            raise WorkflowNotFoundError(thread_id)

        resume_node = saved.get("current_agent")
        if not resume_node or resume_node == "unknown":
            return success(data={
                "thread_id": thread_id,
                "status": "error",
                "message": "工作流错误历史缺少可恢复节点，无法恢复。",
            })

        prev_phase = _resume_phase_for_next_nodes(
            (resume_node,),
            saved.get("prev_phase") or WorkflowPhase.CREATING,
        )
        restored_state = {
            **saved,
            "phase": prev_phase,
            "error": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        await graph.aupdate_state(config, restored_state, as_node=resume_node)
        await _start_resume_task(thread_id, graph, config, prev_phase)

        return success(data={
            "thread_id": thread_id,
            "status": "running",
            "phase": prev_phase,
        })

    has_active = (
        (thread_id in _background_tasks and not _background_tasks[thread_id].done())
        or (thread_id in _runner._active_sync_executions)
    )
    derived = derive_status(state, has_active_task=has_active)

    if derived == WorkflowStatus.AWAITING_REVIEW:
        return success(data={
            "thread_id": thread_id,
            "status": "awaiting_review",
            "message": "工作流正在等待审核，请使用 /api/review/submit 端点提交审核决定",
        })

    if derived == WorkflowStatus.AWAITING_CHOICE:
        return success(data={
            "thread_id": thread_id,
            "status": "awaiting_choice",
            "message": "工作流正在等待版本选择，请使用 /api/optimization/select 端点选择版本",
        })

    if derived == WorkflowStatus.AWAITING_DRAFT:
        return success(data={
            "thread_id": thread_id,
            "status": "awaiting_draft",
            "message": "工作流正在等待草稿提交，请使用 /api/optimization/draft 端点提交草稿",
        })

    if derived == WorkflowStatus.AWAITING_BRIEF:
        # Resume from brief_gate interrupt — pass resume value for skip/answer
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        resume_value = body.get("resume_value", {"action": "skip"})
        from langgraph.types import Command
        await graph.ainvoke(Command(resume=resume_value), config)
        return success(data={
            "thread_id": thread_id,
            "status": "running",
            "phase": WorkflowPhase.BRIEFING,
        })

    if derived == WorkflowStatus.AWAITING_RIPPLE_DECISION:
        # Resume from ripple_gate interrupt — accept/reangle/retopic
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        resume_value = body.get("resume_value", {"action": "accept"})
        from langgraph.types import Command
        await graph.ainvoke(Command(resume=resume_value), config)
        return success(data={
            "thread_id": thread_id,
            "status": "running",
            "phase": WorkflowPhase.CREATING,
        })

    if derived == WorkflowStatus.AWAITING_BLOGGER_SELECTION:
        # Resume from blogger_gate interrupt — accept/reselect
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        resume_value = body.get("resume_value", {"action": "accept"})
        from langgraph.types import Command
        await graph.ainvoke(Command(resume=resume_value), config)
        return success(data={
            "thread_id": thread_id,
            "status": "running",
            "phase": WorkflowPhase.BRIEFING,
        })

    next_nodes = tuple(state.next or ())
    can_retry_error = derived == WorkflowStatus.ERROR
    can_resume_stale = derived == WorkflowStatus.STALE
    can_restart_terminal = derived in (WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED)

    if derived != WorkflowStatus.PAUSED and not can_retry_error and not can_resume_stale and not can_restart_terminal:
        return success(data={
            "thread_id": thread_id,
            "status": str(derived.value),
            "message": (
                f"工作流当前状态为 {derived.value}，无法恢复。"
                "只有暂停、过期、错误、已完成或已取消状态可以恢复/重试。"
            ),
        })

    if (can_retry_error or can_resume_stale) and next_nodes:
        prev_phase = _resume_phase_for_next_nodes(
            next_nodes,
            state.values.get("prev_phase") or WorkflowPhase.CREATING,
        )
    else:
        prev_phase = state.values.get("prev_phase") or WorkflowPhase.SCOUTING
    await graph.aupdate_state(config, {"phase": prev_phase, "error": None})

    await _start_resume_task(thread_id, graph, config, prev_phase)

    return success(data={
        "thread_id": thread_id,
        "status": "running",
        "phase": prev_phase,
    })


@router.post("/cancel/{thread_id}")
async def cancel_workflow(thread_id: str, request: Request):
    """取消工作流"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    current_phase = state.values.get("phase", "unknown")
    await graph.aupdate_state(config, {
        "phase": "cancelled",
        "error": "User cancelled",
        "prev_phase": current_phase,
    })

    await _db_upsert(
        thread_id,
        status="cancelled",
        phase="cancelled",
        error="User cancelled",
    )

    bg_task = _background_tasks.get(thread_id)
    if bg_task and not bg_task.done():
        bg_task.cancel()

    return success(data={
        "thread_id": thread_id,
        "status": "cancelled",
        "message": "工作流已取消",
    })


@router.get("/stream/{thread_id}")
async def stream_workflow_progress(thread_id: str, request: Request):
    """SSE 流式进度推送 — EventBus驱动"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    async def event_generator():
        bus = EventBusService.get_instance()
        queue = bus.subscribe_thread(thread_id)

        try:
            while True:
                event = await queue.get()
                event_data = json.dumps(event.payload, ensure_ascii=False)
                yield f"event: {event.event_type.value}\ndata: {event_data}\n\n"

                if event.event_type in (EventType.WORKFLOW_COMPLETED, EventType.WORKFLOW_ERROR):
                    break
        finally:
            bus.unsubscribe_thread(thread_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/list")
async def list_workflows_endpoint(
    request: Request,
    account_id: str | None = Query(None, description="筛选账号 ID"),
    status: str | None = Query(None, description="筛选状态: running/completed/error/cancelled"),
    limit: int = Query(20, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="分页偏移"),
):
    """列出工作流 — 从 DB 查询，按创建时间倒序"""
    if is_pool_ready():
        rows, total = await db_list(
            account_id=account_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return success(data={
            "workflows": [r.to_dict() for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        })

    # Fallback when DB is unavailable: return empty list
    return success(data={
        "workflows": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
    })


@router.delete("/{thread_id}")
async def delete_workflow(thread_id: str, request: Request):
    """删除工作流记录 — 只能删除已完成/已取消/出错的工作流"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    row = await db_get(thread_id) if is_pool_ready() else None
    in_history = (_HISTORY_DIR / f"{thread_id}.json").exists()

    if not row and not in_history:
        raise WorkflowNotFoundError(thread_id)

    if row and row.status == "running":
        raise ValidationError(
            "thread_id",
            "Cannot delete a running workflow. Cancel it first.",
        )

    # Delete from DB
    if row:
        await db_delete(thread_id)

    # Delete history file
    history_path = _HISTORY_DIR / f"{thread_id}.json"
    with contextlib.suppress(OSError):
        history_path.unlink()

    # Delete from LangGraph checkpointer
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is not None:
        with contextlib.suppress(Exception):
            await checkpointer.adelete_thread(thread_id)

    return success(data={
        "thread_id": thread_id,
        "message": "Workflow deleted from history",
    })


@router.post("/ripple-retry/{thread_id}")
async def retry_ripple_analysis(thread_id: str, request: Request):
    """重新运行 Ripple 传播预测和 PMF 验证（当之前超时或不可用时）"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    values = state.values
    ripple_reason = values.get("ripple_reason", "")
    content_plan = values.get("content_plan") or values.get("content_plan", {})
    ripple_prediction = values.get("ripple_prediction") or {}

    # Check if Ripple previously failed — explicit flags or fallback-looking prediction
    is_fallback_prediction = (
        ripple_prediction.get("viral_probability") == 0
        and ripple_prediction.get("confidence") == 0
        and ripple_prediction.get("estimated_reach") in (0, None)
    )
    if not ripple_reason and not values.get("ripple_fallback") and not is_fallback_prediction:
        return success(data={
            "thread_id": thread_id,
            "status": "skipped",
            "message": "Ripple 分析之前已成功，无需重试",
        })

    topic = content_plan.get("selected_topic", "") if isinstance(content_plan, dict) else ""
    if not topic:
        return success(data={
            "thread_id": thread_id,
            "status": "skipped",
            "message": "无法重试：缺少 content_plan 或 selected_topic",
        })

    from backend.services.ripple_service import RippleService, RippleTimeoutError

    ripple = RippleService.get_instance()
    ripple_timeout = 1800.0

    async def _run_retry():
        print(f"[ripple-retry] Started for {thread_id}, topic={topic}", flush=True)
        try:
            # Bypass health-check/fallback — retry means we want a real simulation
            pred_task = ripple.submit_and_wait(
                {
                    "skill": "social-media",
                    "platform": "xiaohongshu",
                    "event": {
                        "topic": topic,
                        "content_type": content_plan.get("content_type", "note"),
                        "tags": content_plan.get("hashtags", []),
                        "tone": content_plan.get("content_angle", ""),
                        "description": content_plan.get("content_angle", ""),
                    },
                    "max_waves": 6,
                    "simulation_horizon": "48h",
                },
                max_wait=ripple_timeout,
                thread_id=thread_id,
            )
            pmf_task = ripple.submit_and_wait(
                {
                    "skill": "pmf-validation",
                    "channel": "content-seeding",
                    "vertical": "fmcg",
                    "platform": "xiaohongshu",
                    "event": {
                        "name": content_plan.get("selected_topic", ""),
                        "category": content_plan.get("category", ""),
                        "description": content_plan.get("content_angle", ""),
                        "differentiators": content_plan.get("key_points", []),
                    },
                    "simulation_horizon": "72h",
                },
                max_wait=ripple_timeout,
                thread_id=thread_id,
            )
            raw_pred, raw_pmf = await asyncio.gather(pred_task, pmf_task)
            print(f"[ripple-retry] Simulations completed for {thread_id}", flush=True)

            pred = ripple._parse_spread_result(raw_pred)
            pmf_result = ripple._parse_pmf_result(raw_pmf)
        except (RippleTimeoutError, TimeoutError):
            logger.warning("Ripple retry timed out for %s", thread_id)
            return
        except Exception as e:
            print(f"[ripple-retry] FAILED for {thread_id}: {type(e).__name__}: {e}", flush=True)
            return

        # Update workflow state with new Ripple results
        updates: dict[str, Any] = {}
        ripple_pred_data = pred.get("ripple_prediction")
        if ripple_pred_data:
            updates["ripple_prediction"] = ripple_pred_data
        ripple_pmf_data = pmf_result.get("ripple_pmf")
        if ripple_pmf_data:
            updates["ripple_pmf"] = ripple_pmf_data

        # Both succeeded — clear fallback flags
        if ripple_pred_data and ripple_pmf_data:
            updates["ripple_reason"] = None
            updates["ripple_fallback"] = None
        else:
            reason = pred.get("ripple_reason") or pmf_result.get("ripple_reason") or "unreachable"
            updates["ripple_reason"] = reason
            updates["ripple_fallback"] = True

        if updates:
            await graph.aupdate_state(config, updates)
            print(f"[ripple-retry] State updated for {thread_id}: {list(updates.keys())}", flush=True)

    task = asyncio.create_task(_run_retry(), name=f"ripple-retry-{thread_id}")
    print(f"[ripple-retry] Task created for {thread_id}: {task.get_name()}", flush=True)

    return success(data={
        "thread_id": thread_id,
        "status": "retrying",
        "message": "Ripple 分析正在重新运行",
    })


class BriefUploadResponse(BaseModel):
    thread_id: str
    brief_text: str
    source_type: str


@router.post("/brief/upload/{thread_id}")
async def upload_brief_file(thread_id: str, request: Request):
    """Upload a brief document (PDF) and extract text content."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    form = await request.form()
    file = form.get("file")
    if not file:
        raise ValidationError("file", "No file uploaded")

    filename = file.filename or "unknown"
    content_bytes = await file.read()

    max_upload_size = 20 * 1024 * 1024
    if len(content_bytes) > max_upload_size:
        raise ValidationError("file", f"File too large (max {max_upload_size // 1024 // 1024}MB)")

    brief_text = ""
    source_type = "text"

    if filename.lower().endswith(".pdf"):
        source_type = "pdf"
        brief_text = await _extract_pdf_text(content_bytes)
    else:
        try:
            brief_text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            brief_text = content_bytes.decode("gbk", errors="replace")

    if not brief_text.strip():
        raise ValidationError("file", "Could not extract text from the uploaded file")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    await graph.aupdate_state(config, {
        "brief_content": {
            "raw_text": brief_text,
            "source_type": source_type,
        },
    })

    # If the workflow was started without brief_text (waiting for PDF upload),
    # it paused at the initial checkpoint — start execution now
    state = await graph.aget_state(config)
    next_nodes = state.next if state.next else ()
    has_active = (
        (thread_id in _background_tasks and not _background_tasks[thread_id].done())
        or (thread_id in _runner._active_sync_executions)
    )

    if not has_active and next_nodes:
        # Workflow is paused and waiting — resume execution
        await _start_resume_task(thread_id, graph, config, WorkflowPhase.BRIEFING)

    return success(data=BriefUploadResponse(
        thread_id=thread_id,
        brief_text=brief_text[:500] + "..." if len(brief_text) > 500 else brief_text,
        source_type=source_type,
    ).model_dump())


async def _extract_pdf_text(content_bytes: bytes) -> str:
    """Extract text from PDF using pdfplumber, with multimodal LLM fallback."""
    try:
        import io

        import pdfplumber

        text_parts = []
        with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)

        extracted = "\n".join(text_parts).strip()
        if extracted:
            return extracted

        logger.info("PDF text extraction yielded no text, attempting multimodal LLM fallback")
        return await _extract_pdf_with_llm(content_bytes)
    except ImportError:
        logger.warning("pdfplumber not installed, using LLM fallback for PDF")
        return await _extract_pdf_with_llm(content_bytes)
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return ""


async def _extract_pdf_with_llm(content_bytes: bytes) -> str:
    """Extract text from PDF using multimodal LLM (for scanned documents)."""
    import base64

    try:
        from backend.config.models import TaskType
        from backend.models.router import get_model

        model = get_model(TaskType.BRIEF_ANALYSIS.value)
        b64 = base64.b64encode(content_bytes).decode()

        from langchain_core.messages import HumanMessage

        response = await model.ainvoke([
            HumanMessage(content=[
                {"type": "text", "text": "请提取这份PDF文档中的所有文字内容，保持原始格式。"},
                {"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{b64}"}},
            ])
        ])
        return response.content or ""
    except Exception as e:
        logger.error(f"Multimodal LLM PDF extraction failed: {e}")
        return ""


@router.get("/brief/export/{thread_id}")
async def export_shooting_plan(thread_id: str, request: Request):
    """Export shooting plan as formatted text (for copy/download)."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    shooting_plan = state.values.get("shooting_plan", {})
    if not shooting_plan:
        return success(data={"text": "", "message": "No shooting plan available yet"})

    text = _format_shooting_plan(shooting_plan)
    return success(data={"text": text, "format": "markdown"})


def _format_shooting_plan(plan: dict) -> str:
    """Format shooting plan dict into readable markdown text."""
    lines = []

    nickname = plan.get("creator_nickname", "")
    direction = plan.get("content_direction", "")
    type_label = plan.get("content_type_label", "")
    header = f"# {nickname}-{direction}-{type_label}" if nickname else f"# {direction}-{type_label}"
    lines.append(header)
    lines.append("")

    lines.append(f"主页链接：{plan.get('profile_link', '')}")
    lines.append(f"达人量级：{plan.get('creator_level', '')}")
    lines.append(f"预计发布日期：{plan.get('planned_publish_date', '')}")
    lines.append(f"内容方向：{direction}")
    lines.append(f"产品规格：{plan.get('product_specification', '')}")
    lines.append("")

    lines.append("---")
    lines.append("初稿👇")
    for req in plan.get("draft_requirements", []):
        lines.append(f"- {req}")
    for note in plan.get("draft_notes", []):
        lines.append(f"⚠️ {note}")
    lines.append("")

    lines.append("---")
    lines.append("大纲👇")
    titles = plan.get("title_candidates", [])
    lines.append(f"标题（至少给到{len(titles)}个备选）：")
    for i, title in enumerate(titles, 1):
        lines.append(f"{i}. {title}")
    lines.append("")
    lines.append(f"文案：\n{plan.get('body_copy', '')}")
    lines.append("")
    lines.append("话题：")
    lines.append(f"必带话题：{' '.join(plan.get('required_hashtags', []))}")
    lines.append(f"选带话题：{' '.join(plan.get('optional_hashtags', []))}")
    lines.append(f"其他热门话题：{' '.join(plan.get('suggested_hashtags', []))}")
    lines.append("")

    lines.append("---")
    lines.append("拍摄服装")
    outfits = plan.get("outfits", {})
    for role, clothes in outfits.items():
        lines.append(f"\n{role}")
        for item in clothes:
            lines.append(f"- {item}")
    lines.append("")

    lines.append("---")
    lines.append("拍摄角度")
    for angle in plan.get("shooting_angles", []):
        lines.append(f"- {angle.get('description', '')}")

    return "\n".join(lines)
