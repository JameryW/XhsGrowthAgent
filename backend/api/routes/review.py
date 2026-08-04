"""Review API routes — human-in-the-loop content review with version tracking."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

if TYPE_CHECKING:
    # Annotation-only; deferring langgraph.types + state.schema keeps them off
    # the app cold-start import chain. Command is imported locally where
    # constructed.
    from langgraph.types import StateSnapshot

    from backend.state.schema import XHSGrowthState

from backend.agents.evaluator import EvaluatorAgent
from backend.api.account_scope import assert_thread_owned
from backend.api.deps import get_current_user
from backend.api.errors import ReviewNotPendingError
from backend.api.responses import ApiResponse, success
from backend.api.routes import _runner
from backend.state.enums import ContentStatus

logger = logging.getLogger("xhs_growth.api.review")

router = APIRouter()

# Reuse a single EvaluatorAgent instance (same pattern as evaluation routes).
_evaluator = EvaluatorAgent()


def _is_at_ripple_gate(state: StateSnapshot) -> bool:
    """Check if workflow is paused at ripple_gate.

    Handles both interrupt_before (next_nodes contains 'ripple_gate')
    and dynamic interrupt() (snapshot.interrupts has gate='ripple').
    """
    if "ripple_gate" in (state.next or []):
        return True
    if state.interrupts:
        for intr in state.interrupts:
            if isinstance(intr.value, dict) and intr.value.get("gate") == "ripple":
                return True
    return False


def _is_at_review_gate(state: StateSnapshot) -> bool:
    """Check if workflow is paused at review_gate.

    review_gate now uses dynamic interrupt() (like ripple_gate), so the pause
    shows up as snapshot.interrupts with gate='review'. The next_nodes check is
    kept as a fallback for any interrupt_before legacy path.
    """
    if "review_gate" in (state.next or []):
        return True
    if state.interrupts:
        for intr in state.interrupts:
            if isinstance(intr.value, dict) and intr.value.get("gate") == "review":
                return True
    return False


class PublishOptions(BaseModel):
    dry_run: bool = False
    auto_publish: bool = False
    account_id: str | None = None  # publish as this account; None = global active account


class ReviewDecision(BaseModel):
    decision: ContentStatus
    comments: str = ""
    revisions: list[str] = []
    publish_options: PublishOptions | None = None


class RippleDecision(BaseModel):
    action: str  # "accept" | "reangle" | "retopic"


def _build_version_entry(
    copy_content: dict[str, Any], visual_plan: dict[str, Any], label: str = "draft"
) -> dict[str, Any]:
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
async def get_pending_review(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取待审核内容 — includes version history if available."""
    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # 检查是否在审核门等待（动态 interrupt 或 interrupt_before 兜底）
    if _is_at_review_gate(state):
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
async def submit_review(
    thread_id: str,
    decision: ReviewDecision,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """提交审核决定 — saves version before resuming on 'needs_revision'."""
    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    # Verify workflow is awaiting review before resuming (dynamic interrupt or
    # interrupt_before fallback).
    state = await graph.aget_state(config)
    if not _is_at_review_gate(state):
        current_phase = state.values.get("phase", "unknown")
        raise ReviewNotPendingError(thread_id=thread_id, current_phase=current_phase)

    values = state.values or {}

    # Side updates written via aupdate_state before resuming. human_feedback is
    # NOT written here — review_gate_node reads the decision from the
    # Command(resume=...) value and writes human_feedback itself (mirrors
    # ripple_gate). review_outcome routes on human_feedback in state.
    updates: dict[str, Any] = {}

    # On 'needs_revision', save current content as a version before resuming
    if decision.decision == "needs_revision":
        copy_content = values.get("copy_content") or {}
        visual_plan = values.get("visual_plan") or {}
        label = "AI 初稿" if not values.get("content_versions") else "修改版本"
        version_entry = _build_version_entry(copy_content, visual_plan, label=label)
        updates["content_versions"] = [version_entry]

    # On 'approved', write publish options to state so publisher can read them
    if decision.decision == "approved":
        pub_opts = decision.publish_options or PublishOptions(dry_run=True)
        updates["publish_options"] = pub_opts.model_dump()

    # ponytail: record how long the user waited at review_gate (PRD 节点级指标).
    # entered_at = last node completion before the gate; merged via _append_list.
    from backend.agents.nodes._base import record_human_wait

    updates["performance_log"] = [record_human_wait(values, "review_gate")]

    # Write side updates (versions / publish_options / perf log) to state.
    if updates:
        await graph.aupdate_state(config, updates, as_node=_runner._get_as_node(state))

    # Resume the dynamic interrupt() inside review_gate_node with the decision.
    # The node reads this value, writes human_feedback, and sets phase.
    from langgraph.types import Command

    result = await _runner._run_graph_and_persist(
        thread_id,
        graph,
        config,
        Command(resume=decision.model_dump()),
        source="review",
    )

    next_phase = result.get("phase", "unknown") if result else "unknown"

    response_data = {
        "thread_id": thread_id,
        "status": "resumed",
        "decision": decision.decision.value,
        "next_phase": next_phase,
    }

    return success(data=response_data)


@router.get("/versions/{thread_id}")
async def get_version_history(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取内容版本历史 — all revisions for a workflow."""
    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        from backend.api.errors import WorkflowNotFoundError

        raise WorkflowNotFoundError(thread_id)

    versions = state.values.get("content_versions") or []
    current_copy = state.values.get("copy_content") or {}

    return success(
        data={
            "thread_id": thread_id,
            "versions": versions,
            "current": {
                "title": current_copy.get("selected_title", ""),
                "body": current_copy.get("body_text", ""),
                "hashtags": current_copy.get("hashtags", []),
            },
        }
    )


@router.get("/ripple-pending/{thread_id}")
async def get_pending_ripple_decision(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取 Ripple 决策等待状态 — Ripple 结果 + 决策选项"""
    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not _is_at_ripple_gate(state):
        from backend.api.errors import ValidationError

        raise ValidationError(
            "ripple_gate",
            f"Workflow is not awaiting Ripple decision (next: {state.next})",
        )

    values = state.values
    prediction = values.get("ripple_prediction") or {}
    pmf = values.get("ripple_pmf") or {}
    reselect_count = values.get("reselect_count", 0)

    return success(
        data={
            "status": "awaiting_ripple_decision",
            "ripple_prediction": prediction,
            "ripple_pmf": pmf,
            "ripple_reason": values.get("ripple_reason", ""),
            "reselect_count": reselect_count,
            "max_reselect": 2,
            "options": ["accept", "reangle", "retopic"],
        }
    )


@router.post("/ripple-decision/{thread_id}")
async def submit_ripple_decision(
    thread_id: str,
    decision: RippleDecision,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """提交 Ripple 决策 — 用户选择接受/换角度/换话题"""
    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    # Verify workflow is awaiting ripple gate decision
    state = await graph.aget_state(config)
    if not _is_at_ripple_gate(state):
        from backend.api.errors import ValidationError

        raise ValidationError(
            "ripple_gate",
            f"Workflow is not awaiting Ripple decision (next: {state.next})",
        )

    action = decision.action
    if action not in ("accept", "reangle", "retopic"):
        from backend.api.errors import ValidationError

        raise ValidationError(
            "action",
            f"Invalid action: {action}. Must be accept, reangle, or retopic",
        )

    values = state.values or {}
    reselect_count = values.get("reselect_count", 0)

    # Enforce reselect limit
    if action in ("reangle", "retopic") and reselect_count >= 2:
        logger.warning(f"Reselect limit reached for {thread_id}, forcing accept")
        action = "accept"

    # Update state before resuming for reangle/retopic (clear stale data)
    # NOTE: reselect_count increment is owned by ripple_gate_node only —
    # do NOT increment here to avoid double-counting.
    if action in ("reangle", "retopic"):
        updates: dict[str, Any] = {
            "ripple_progress": {},
        }
        if action == "retopic":
            updates.update(
                {
                    "trend_data": {},
                    "content_plan": {},
                    "ripple_prediction": {},
                    "ripple_pmf": {},
                }
            )
        await graph.aupdate_state(config, updates, as_node=_runner._get_as_node(state))

    # Resume the graph with the user's decision
    from langgraph.types import Command

    result = await _runner._run_graph_and_persist(
        thread_id,
        graph,
        config,
        Command(resume={"action": action}),
        source="ripple_gate",
    )

    next_phase = result.get("phase", "unknown") if result else "unknown"

    return success(
        data={
            "thread_id": thread_id,
            "status": "resumed",
            "action": action,
            "next_phase": next_phase,
        }
    )


class CopyUpdateRequest(BaseModel):
    """Partial copy_content update — only provided fields are overwritten."""

    title: str | None = None  # maps to copy_content.selected_title
    body_text: str | None = None
    hashtags: list[str] | None = None


@router.post("/update-copy/{thread_id}")
async def update_copy_content(
    thread_id: str,
    body: CopyUpdateRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """手动覆盖文案 — 部分更新 copy_content，保存后自动重跑 evaluator.

    仅 awaiting_review (review_gate 在 next) 工作流允许编辑。部分覆盖：
    只更新提供的字段，保留 selected_title 之外的字段 (tone/cta 等)。
    保存 copy_content 后用更新后的 state 调 EvaluatorAgent，将
    evaluation_result 写回。evaluator 失败时降级：copy_content 仍保存，
    evaluation_result 为空，返回带 warning。
    """
    if not thread_id or not thread_id.strip():
        from backend.api.errors import ValidationError

        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # 校验 awaiting_review：review_gate 暂停中（动态 interrupt 或 next 兜底）
    if not _is_at_review_gate(state):
        current_phase = (state.values or {}).get("phase", "unknown")
        return success(
            data={
                "thread_id": thread_id,
                "status": "skipped",
                "message": f"仅待审核工作流可编辑文案 (当前: {current_phase})",
                "evaluation_result": {},
            }
        )

    values = state.values or {}
    if values.get("session_id") is None:
        from backend.api.errors import WorkflowNotFoundError

        raise WorkflowNotFoundError(thread_id)

    existing_copy: dict[str, Any] = dict(values.get("copy_content") or {})

    # 部分覆盖：只更新提供的字段
    if body.title is not None:
        existing_copy["selected_title"] = body.title
    if body.body_text is not None:
        existing_copy["body_text"] = body.body_text
    if body.hashtags is not None:
        existing_copy["hashtags"] = body.hashtags

    # 1) 持久化 copy_content（merge：保留未提供字段）
    await graph.aupdate_state(config, {"copy_content": existing_copy})

    # 2) 重跑 evaluator（用更新后的 state 快照）
    evaluation: dict[str, Any] = {}
    warning: str | None = None
    try:
        eval_state = cast("XHSGrowthState", {**values, "copy_content": existing_copy})
        store = getattr(graph, "store", None)
        result = await _evaluator(eval_state, store=store)  # type: ignore[arg-type]
        evaluation = result.get("evaluation_result") or {}

        # 持久化 evaluation_result（不推进工作流）
        await graph.aupdate_state(config, {"evaluation_result": evaluation})
    except Exception as exc:  # noqa: BLE001 — 降级：evaluator 失败不阻断文案保存
        warning = f"evaluator 降级放行：{exc}"
        logger.warning(
            "update_copy: evaluator failed for thread %s, degrading: %s",
            thread_id,
            exc,
        )

    response: dict[str, Any] = {
        "thread_id": thread_id,
        "status": "updated",
        "evaluation_result": evaluation,
    }
    if warning:
        response["warning"] = warning
    return success(data=response)
