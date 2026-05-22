"""Review API routes — human-in-the-loop content review."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from langgraph.types import Command

from xhs_growth.state.schema import ContentStatus

router = APIRouter()


class ReviewDecision(BaseModel):
    decision: ContentStatus
    comments: str = ""
    revisions: list[str] = []


@router.get("/pending/{thread_id}")
async def get_pending_review(thread_id: str, request: Request):
    """获取待审核内容"""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # 检查是否在审核门等待
    if "review_gate" in state.next:
        values = state.values
        return {
            "status": "awaiting_review",
            "content_plan": values.get("content_plan", {}),
            "copy_content": values.get("copy_content", {}),
            "visual_plan": values.get("visual_plan", {}),
        }
    return {"status": "no_pending_review"}


@router.post("/submit/{thread_id}")
async def submit_review(thread_id: str, decision: ReviewDecision, request: Request):
    """提交审核决定"""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    # 用 Command(resume=...) 恢复中断的图
    result = await graph.ainvoke(
        Command(resume=decision.model_dump()),
        config,
    )

    return {
        "thread_id": thread_id,
        "status": "resumed",
        "decision": decision.decision.value,
        "next_phase": result.get("phase", "unknown") if result else "unknown",
    }