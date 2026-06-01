"""Review API routes — human-in-the-loop content review with version tracking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from langgraph.types import Command
from pydantic import BaseModel

from backend.api.errors import ReviewNotPendingError
from backend.api.responses import success
from backend.api.routes import _runner
from backend.state.enums import ContentStatus

router = APIRouter()


class PublishOptions(BaseModel):
    dry_run: bool = True
    auto_publish: bool = False


class ReviewDecision(BaseModel):
    decision: ContentStatus
    comments: str = ""
    revisions: list[str] = []
    publish_options: PublishOptions | None = None


def _build_version_entry(copy_content: dict, visual_plan: dict, label: str = "draft") -> dict:
    """Build a version entry from current content state."""
    return {
        "version_id": uuid.uuid4().hex[:8],
        "title": copy_content.get("selected_title", ""),
        "body": copy_content.get("body_text", ""),
        "hashtags": copy_content.get("hashtags", []),
        "image_prompts": visual_plan.get("image_prompts", []),
        "style_suggestion": visual_plan.get("layout_style", ""),
        "changes_summary": label,
        "predicted_score": 0.0,
        "created_at": datetime.now(UTC).isoformat(),
    }


@router.get("/pending/{thread_id}")
async def get_pending_review(thread_id: str, request: Request):
    """获取待审核内容 — includes version history if available."""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # 检查是否在审核门等待
    if "review_gate" in state.next:
        values = state.values
        return success(
            data={
                "status": "awaiting_review",
                "content_plan": values.get("content_plan", {}),
                "copy_content": values.get("copy_content", {}),
                "visual_plan": values.get("visual_plan", {}),
                "version_history": values.get("content_versions", []),
            }
        )

    # No pending review - raise exception
    current_phase = state.values.get("phase", "unknown")
    raise ReviewNotPendingError(thread_id=thread_id, current_phase=current_phase)


@router.post("/submit/{thread_id}")
async def submit_review(thread_id: str, decision: ReviewDecision, request: Request):
    """提交审核决定 — saves version before resuming on 'needs_revision'."""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    # Verify workflow is awaiting review before resuming
    state = await graph.aget_state(config)
    if "review_gate" not in state.next:
        current_phase = state.values.get("phase", "unknown")
        raise ReviewNotPendingError(thread_id=thread_id, current_phase=current_phase)

    values = state.values or {}

    # On 'needs_revision', save current content as a version before resuming
    if decision.decision == "needs_revision":
        copy_content = values.get("copy_content") or {}
        visual_plan = values.get("visual_plan") or {}
        label = (
            "AI 初稿" if not values.get("content_versions") else "修改版本"
        )
        version_entry = _build_version_entry(
            copy_content, visual_plan, label=label
        )
        # Append version to state before resuming (reducer appends to existing)
        await graph.aupdate_state(config, {
            "content_versions": [version_entry],
        })

    # On 'approved', write publish options to state so publisher can read them
    if decision.decision == "approved":
        pub_opts = decision.publish_options or PublishOptions(dry_run=True)
        await graph.aupdate_state(config, {
            "publish_options": pub_opts.model_dump(),
        })

    # 用 Command(resume=...) 恢复中断的图 — via unified runner
    try:
        result = await _runner._run_graph_and_persist(
            thread_id, graph, config,
            Command(resume=decision.model_dump()),
            source="review",
        )
    except Exception:
        result = {}

    next_phase = result.get("phase", "unknown") if result else "unknown"

    response_data = {
        "thread_id": thread_id,
        "status": "resumed",
        "decision": decision.decision.value,
        "next_phase": next_phase,
    }

    return success(data=response_data)


@router.get("/versions/{thread_id}")
async def get_version_history(thread_id: str, request: Request):
    """获取内容版本历史 — all revisions for a workflow."""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        from backend.api.errors import WorkflowNotFoundError
        raise WorkflowNotFoundError(thread_id)

    versions = state.values.get("content_versions") or []
    current_copy = state.values.get("copy_content") or {}

    return success(data={
        "thread_id": thread_id,
        "versions": versions,
        "current": {
            "title": current_copy.get("selected_title", ""),
            "body": current_copy.get("body_text", ""),
            "hashtags": current_copy.get("hashtags", []),
        },
    })
