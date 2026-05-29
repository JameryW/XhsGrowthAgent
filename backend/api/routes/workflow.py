"""Workflow API routes — start/pause/resume/list/cancel workflows."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import asyncio

from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.api.responses import success, ApiResponse
from backend.api.errors import ValidationError, WorkflowNotFoundError
from backend.state.enums import WorkflowPhase

router = APIRouter()

# Workflow registry with JSON file persistence
_REGISTRY_PATH = Path(os.environ.get("XHS_REGISTRY_PATH", ".xhs/workflow_registry.json"))
_workflow_registry: dict[str, dict] = {}


def _load_registry() -> dict[str, dict]:
    """Load workflow registry from JSON file."""
    if _REGISTRY_PATH.exists():
        try:
            data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_registry() -> None:
    """Persist workflow registry to JSON file."""
    try:
        _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _REGISTRY_PATH.write_text(
            json.dumps(_workflow_registry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass  # Non-critical: registry is also in memory


# Load persisted registry on module import
_workflow_registry = _load_registry()


class WorkflowStartRequest(BaseModel):
    account_id: str = Field(default="default", description="账号 ID")
    phase: WorkflowPhase = Field(default=WorkflowPhase.SCOUTING, description="起始阶段")
    async_mode: bool = Field(default=True, description="异步执行模式")
    dry_run: bool = Field(default=False, description="试运行模式（不实际发布）")
    auto_publish: bool = Field(default=False, description="审核通过后自动发布")
    topic: Optional[str] = Field(default=None, description="内容主题/关键词")
    niche: str = Field(default="母婴", description="垂类赛道")


class AgentTimelineEntry(BaseModel):
    """Per-agent execution detail."""
    agent: str
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    status: str = "success"
    error: Optional[str] = None


class WorkflowStatusResponse(BaseModel):
    """Workflow status response model."""
    thread_id: str
    phase: str
    current_agent: str
    next_steps: list[str]
    error: Optional[str] = None
    progress_percent: int = Field(default=0, description="进度百分比")
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    agent_timeline: list[AgentTimelineEntry] = Field(default_factory=list, description="Agent 执行时间线")


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
    """Calculate progress percentage from phase."""
    return PHASE_PROGRESS.get(phase, 0)


@router.post("/start")
async def start_workflow(req: WorkflowStartRequest, request: Request):
    """启动新的增长引擎工作流

    Returns:
        - thread_id: 工作流唯一标识
        - status: 当前状态 (running/pending)
        - phase: 当前阶段
        - progress_url: SSE 进度推送地址
    """
    # Validate account_id
    if not req.account_id or req.account_id.strip() == "":
        raise ValidationError("account_id", "account_id cannot be empty")

    graph = request.app.state.graph
    thread_id = f"xhs_{req.account_id}_{uuid.uuid4().hex[:8]}"

    initial_state = {
        "phase": req.phase,
        "current_agent": "orchestrator",
        "error": None,
        "retry_count": 0,
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
        "topic": req.topic,
        "niche": req.niche,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    config = {"configurable": {"thread_id": thread_id}}
    now = datetime.now(timezone.utc).isoformat()

    # Register workflow in memory registry
    _workflow_registry[thread_id] = {
        "thread_id": thread_id,
        "account_id": req.account_id,
        "phase": req.phase.value,
        "status": "running",
        "dry_run": req.dry_run,
        "auto_publish": req.auto_publish,
        "progress_percent": get_progress(req.phase.value),
        "created_at": now,
        "updated_at": now,
        "error": None,
    }
    _save_registry()

    if req.async_mode:
        # 异步启动（立即返回，后台执行）
        asyncio.create_task(graph.ainvoke(initial_state, config))
        return success(data={
            "thread_id": thread_id,
            "status": "running",
            "phase": req.phase.value,
            "progress_percent": get_progress(req.phase.value),
            "sse_url": f"/api/workflow/stream/{thread_id}",
            "websocket_url": f"/api/realtime/ws",
        })
    else:
        # 同步执行（等待完成）
        result = await graph.ainvoke(initial_state, config)
        final_phase = result.get("phase", "unknown")
        _workflow_registry[thread_id]["phase"] = final_phase
        _workflow_registry[thread_id]["status"] = "completed"
        _workflow_registry[thread_id]["progress_percent"] = 100
        _save_registry()
        return success(data={
            "thread_id": thread_id,
            "status": "completed",
            "phase": final_phase,
            "progress_percent": 100,
        })


@router.get("/status/{thread_id}")
async def get_workflow_status(thread_id: str, request: Request):
    """获取工作流状态

    Returns:
        - thread_id: 工作流唯一标识
        - phase: 当前阶段
        - current_agent: 当前执行的 Agent
        - next_steps: 下一步操作列表
        - progress_percent: 进度百分比
        - error: 错误信息（如有）
        - created_at: 创建时间
        - updated_at: 最后更新时间
    """
    # Validate thread_id
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # Check if workflow exists (state.values should have content)
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    phase = state.values.get("phase", "unknown")
    progress = get_progress(phase)

    # Update registry if workflow exists there
    if thread_id in _workflow_registry:
        _workflow_registry[thread_id]["phase"] = phase
        _workflow_registry[thread_id]["progress_percent"] = progress
        _workflow_registry[thread_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        if state.values.get("error"):
            _workflow_registry[thread_id]["error"] = state.values.get("error")
            _workflow_registry[thread_id]["status"] = "error"
        elif phase == "completed":
            _workflow_registry[thread_id]["status"] = "completed"
        elif phase == "cancelled":
            _workflow_registry[thread_id]["status"] = "cancelled"
        _save_registry()

    # Build agent timeline from performance_log
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
        current_agent=state.values.get("current_agent", "unknown"),
        next_steps=list(state.next) if state.next else [],
        error=state.values.get("error"),
        progress_percent=progress,
        created_at=state.values.get("created_at"),
        updated_at=state.values.get("updated_at"),
        agent_timeline=agent_timeline,
    ).model_dump())


@router.post("/pause/{thread_id}")
async def pause_workflow(thread_id: str, request: Request):
    """暂停工作流

    设置暂停标志，工作流将在当前 Agent 完成后暂停，不会启动下一个节点。
    """
    # Validate thread_id
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # Check if workflow exists
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    # Update registry with paused flag
    if thread_id in _workflow_registry:
        _workflow_registry[thread_id]["status"] = "paused"
        _workflow_registry[thread_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_registry()

    # Update graph state to signal pause
    await graph.aupdate_state(config, {"phase": "paused"})

    return success(data={
        "thread_id": thread_id,
        "status": "paused",
        "message": "工作流已暂停，当前 Agent 完成后将停止",
    })


@router.post("/resume/{thread_id}")
async def resume_workflow(thread_id: str, request: Request):
    """恢复暂停的工作流

    清除暂停标志并重新启动工作流执行。
    """
    # Validate thread_id
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # Check if workflow exists
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    # Update registry to running
    if thread_id in _workflow_registry:
        _workflow_registry[thread_id]["status"] = "running"
        _workflow_registry[thread_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_registry()

    if state.next:
        # Resume from next interrupt point
        asyncio.create_task(graph.ainvoke(None, config))
        return success(data={
            "thread_id": thread_id,
            "status": "running",
            "phase": state.values.get("phase", "unknown"),
        })

    # No next steps — re-invoke to continue
    current_phase = state.values.get("phase", "unknown")
    if current_phase in ("paused", "cancelled"):
        # Restore to the phase before pause
        prev_phase = state.values.get("prev_phase") or "scouting"
        await graph.aupdate_state(config, {"phase": prev_phase})
        asyncio.create_task(graph.ainvoke(None, config))
        return success(data={
            "thread_id": thread_id,
            "status": "running",
            "phase": prev_phase,
        })

    return success(data={
        "thread_id": thread_id,
        "status": "completed",
    })


@router.post("/cancel/{thread_id}")
async def cancel_workflow(thread_id: str, request: Request):
    """取消工作流

    标记工作流为已取消状态，停止后续执行。
    """
    # Validate thread_id
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # Check if workflow exists
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    # Save previous phase for potential resume
    current_phase = state.values.get("phase", "unknown")

    # Update state to mark as cancelled
    await graph.aupdate_state(config, {
        "phase": "cancelled",
        "error": "User cancelled",
        "prev_phase": current_phase,
    })

    # Update registry
    if thread_id in _workflow_registry:
        _workflow_registry[thread_id]["status"] = "cancelled"
        _workflow_registry[thread_id]["phase"] = "cancelled"
        _workflow_registry[thread_id]["error"] = "User cancelled"
        _workflow_registry[thread_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_registry()

    return success(data={
        "thread_id": thread_id,
        "status": "cancelled",
        "message": "工作流已取消",
    })


@router.get("/stream/{thread_id}")
async def stream_workflow_progress(thread_id: str, request: Request):
    """SSE 流式进度推送

    通过 Server-Sent Events 实时推送工作流进度更新。

    Events:
        - progress: 进度更新 {phase, percent, agent}
        - error: 错误事件 {message}
        - complete: 完成事件 {final_phase}
    """
    # Validate thread_id
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    async def event_generator():
        graph = request.app.state.graph
        config = {"configurable": {"thread_id": thread_id}}

        try:
            # Stream events from LangGraph
            async for event in graph.astream_events(None, config, version="v1"):
                event_type = event.get("event", "")
                event_name = event.get("name", "unknown")

                if event_type == "on_chain_start":
                    yield f"event: progress\ndata: {{\"agent\": \"{event_name}\", \"status\": \"starting\"}}\n\n"
                elif event_type == "on_chain_end":
                    # Get current state
                    state = await graph.aget_state(config)
                    phase = state.values.get("phase", "unknown")
                    progress = get_progress(phase)
                    yield f"event: progress\ndata: {{\"agent\": \"{event_name}\", \"phase\": \"{phase}\", \"percent\": {progress}, \"status\": \"completed\"}}\n\n"

            # Final state
            final_state = await graph.aget_state(config)
            final_phase = final_state.values.get("phase", "unknown")
            yield f"event: complete\ndata: {{\"phase\": \"{final_phase}\", \"percent\": 100}}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {{\"message\": \"{str(e)}\"}}\n\n"

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
async def list_workflows(
    request: Request,
    account_id: Optional[str] = Query(None, description="筛选账号 ID"),
    status: Optional[str] = Query(None, description="筛选状态: running/completed/error/cancelled"),
    limit: int = Query(20, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="分页偏移"),
):
    """列出工作流

    返回工作流列表，支持按账号和状态筛选、分页。
    按创建时间倒序排列。
    """
    workflows = list(_workflow_registry.values())

    # Filter by account_id
    if account_id:
        workflows = [w for w in workflows if w["account_id"] == account_id]

    # Filter by status
    if status:
        workflows = [w for w in workflows if w["status"] == status]

    # Sort by created_at descending
    workflows.sort(key=lambda w: w.get("created_at", ""), reverse=True)

    total = len(workflows)
    paginated = workflows[offset:offset + limit]

    return success(data={
        "workflows": paginated,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


@router.delete("/{thread_id}")
async def delete_workflow(thread_id: str):
    """删除工作流记录

    从历史记录中删除指定工作流。只能删除已完成、已取消或出错的工作流。
    """
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    if thread_id not in _workflow_registry:
        raise WorkflowNotFoundError(thread_id)

    wf = _workflow_registry[thread_id]
    if wf["status"] == "running":
        raise ValidationError("thread_id", "Cannot delete a running workflow. Cancel it first.")

    del _workflow_registry[thread_id]
    _save_registry()

    return success(data={
        "thread_id": thread_id,
        "message": "Workflow deleted from history",
    })