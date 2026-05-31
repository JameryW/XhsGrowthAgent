"""Optimization API routes — draft submission and version selection."""

from __future__ import annotations

from fastapi import APIRouter, Request
from langgraph.types import Command
from pydantic import BaseModel, Field

from backend.api.errors import ChoiceNotPendingError, ValidationError, WorkflowNotFoundError
from backend.api.responses import success

router = APIRouter()


class DraftSubmission(BaseModel):
    title: str = Field(default="", description="标题")
    text: str = Field(default="", description="正文")
    hashtags: list[str] = Field(default_factory=list, description="话题标签")
    viral_links: list[str] = Field(default_factory=list, description="用户提供的爆款链接")


class VersionChoice(BaseModel):
    version_id: str = Field(description="选择的版本ID")
    version_type: str | None = Field(default=None, description="版本类型 A/B/C")


@router.post("/draft/{thread_id}")
async def submit_draft(thread_id: str, draft: DraftSubmission, request: Request):
    """提交用户草稿 — 更新状态."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    await graph.aupdate_state(config, {
        "draft_content": draft.model_dump(),
        "user_viral_links": draft.viral_links,
    })

    return success(data={"thread_id": thread_id, "status": "draft_submitted"})


@router.post("/select/{thread_id}")
async def select_version(thread_id: str, choice: VersionChoice, request: Request):
    """选择版本 — 从 choice_gate 中断恢复."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    if "choice_gate" not in state.next:
        current_phase = state.values.get("phase", "unknown")
        raise ChoiceNotPendingError(thread_id=thread_id, current_phase=current_phase)

    result = await graph.ainvoke(Command(resume=choice.model_dump()), config)
    next_phase = result.get("phase", "unknown") if result else "unknown"

    return success(data={"thread_id": thread_id, "status": "resumed", "next_phase": next_phase})
