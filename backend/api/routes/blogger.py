"""Blogger selection API routes — select or skip blogger candidates."""

from __future__ import annotations

from fastapi import APIRouter, Request
from langgraph.types import Command, StateSnapshot
from pydantic import BaseModel, Field

from backend.api.errors import ValidationError, WorkflowNotFoundError
from backend.api.responses import success
from backend.api.routes import _runner

router = APIRouter()


class BloggerSelection(BaseModel):
    user_id: str = Field(default="", description="选中的博主 user_id")
    nickname: str = Field(default="", description="选中的博主昵称")
    skip: bool = Field(default=False, description="跳过博主选择")


class BloggerSkip(BaseModel):
    skip: bool = Field(default=True, description="跳过博主选择")


def _is_at_blogger_gate(state: StateSnapshot) -> bool:
    """Check if workflow is paused at blogger_gate.

    Handles both interrupt_before (next_nodes contains 'blogger_gate')
    and dynamic interrupt() (snapshot.interrupts has gate='blogger').
    """
    if "blogger_gate" in (state.next or []):
        return True
    if state.interrupts:
        for intr in state.interrupts:
            if isinstance(intr.value, dict) and intr.value.get("gate") == "blogger":
                return True
    return False


@router.get("/blogger-pending/{thread_id}")
async def get_pending_blogger_selection(thread_id: str, request: Request):
    """获取候选博主列表 — 返回 blogger_candidates 和配置."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    values = state.values
    return success(data={
        "thread_id": thread_id,
        "blogger_candidates": values.get("blogger_candidates", []),
        "blogger_candidate_limit": values.get("blogger_candidate_limit", 5),
        "blogger_note_limit": values.get("blogger_note_limit", 3),
        "is_pending": _is_at_blogger_gate(state),
    })


@router.post("/blogger-select/{thread_id}")
async def select_blogger(thread_id: str, selection: BloggerSelection, request: Request):
    """选择博主 — 从 blogger_gate 中断恢复."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    # Build resume value based on selection or skip
    if selection.skip:
        resume_value = {"skip": True}
    else:
        if not selection.user_id:
            raise ValidationError("user_id", "user_id is required when not skipping")
        resume_value = {
            "user_id": selection.user_id,
            "nickname": selection.nickname,
        }

    # If graph is interrupted at blogger_gate, resume it
    if _is_at_blogger_gate(state):
        result = await _runner._run_graph_and_persist(
            thread_id, graph, config,
            Command(resume=resume_value),
            source="blogger_select",
        )
        next_phase = result.get("phase", "unknown") if result else "unknown"
        return success(data={
            "thread_id": thread_id,
            "status": "resumed",
            "next_phase": next_phase,
        })

    # Not at blogger_gate — just update state
    await graph.aupdate_state(config, {
        "selected_blogger": resume_value if not selection.skip else {},
    }, as_node=_runner._get_as_node(state))

    return success(data={
        "thread_id": thread_id,
        "status": "updated",
    })
