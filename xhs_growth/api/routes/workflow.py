"""Workflow API routes — start/pause/resume/list workflows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from xhs_growth.state.schema import WorkflowPhase

router = APIRouter()


class WorkflowStartRequest(BaseModel):
    account_id: str = "default"
    phase: WorkflowPhase = WorkflowPhase.SCOUTING


class WorkflowResponse(BaseModel):
    thread_id: str
    status: str
    phase: str


@router.post("/start", response_model=WorkflowResponse)
async def start_workflow(req: WorkflowStartRequest, request: Request):
    """启动新的增长引擎工作流"""
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
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    config = {"configurable": {"thread_id": thread_id}}

    # 异步启动工作流
    result = await graph.ainvoke(initial_state, config)

    return WorkflowResponse(
        thread_id=thread_id,
        status="running",
        phase=result.get("phase", "unknown"),
    )


@router.get("/status/{thread_id}")
async def get_workflow_status(thread_id: str, request: Request):
    """获取工作流状态"""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    return {
        "thread_id": thread_id,
        "next": state.next,
        "values": state.values,
        "created_at": state.created_at if hasattr(state, "created_at") else None,
    }


@router.post("/pause/{thread_id}")
async def pause_workflow(thread_id: str, request: Request):
    """暂停工作流（状态已通过检查点保存）"""
    return {"thread_id": thread_id, "status": "paused"}


@router.post("/resume/{thread_id}")
async def resume_workflow(thread_id: str, request: Request):
    """恢复暂停的工作流"""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if state.next:
        result = await graph.ainvoke(None, config)
        return {"thread_id": thread_id, "status": "running", "phase": result.get("phase", "unknown")}
    return {"thread_id": thread_id, "status": "completed"}