"""Conditional edge routers for the LangGraph workflow."""

from __future__ import annotations

import os
from typing import Literal

from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.schema import XHSGrowthState


def _xhs_configured() -> bool:
    """Check if XHS platform credentials are available."""
    return bool(os.environ.get("XHS_COOKIE") and os.environ.get("XHS_USER_ID"))


def _check_terminal(state: XHSGrowthState) -> str | None:
    """Return '__end__' if workflow is in terminal state, else None.

    Terminal states: cancelled, paused, error
    """
    phase = state.get("phase")
    if phase == WorkflowPhase.CANCELLED:
        return "__end__"
    if phase == WorkflowPhase.PAUSED:
        return "__end__"
    if state.get("error"):
        return "__end__"
    return None


def orchestrator_router(state: XHSGrowthState) -> str:
    """编排器路由 — 根据当前阶段决定下一个节点"""
    if terminal := _check_terminal(state):
        return terminal

    phase = state.get("phase", WorkflowPhase.IDLE)

    routing = {
        WorkflowPhase.SCOUTING: "trend_scout",
        WorkflowPhase.PLANNING: "content_strategist",
        WorkflowPhase.ANALYZING: "analyst",
        WorkflowPhase.ENGAGING: "engagement",
        WorkflowPhase.ERROR: "__end__",
        WorkflowPhase.COMPLETED: "__end__",
        WorkflowPhase.IDLE: "trend_scout",
    }

    return routing.get(phase, "trend_scout")


def should_plan(state: XHSGrowthState) -> Literal["content_strategist", "trend_scout", "__end__"]:
    """侦察后判断是否有可操作的趋势 — retry trend_scout on failure before giving up."""
<<<<<<< HEAD
    trend_data = state.get("trend_data")

    # trend_data present with results → proceed to content_strategist
    if trend_data and trend_data.get("hot_topics"):
        return "content_strategist"

    # No trend_data: check if we should retry
=======
    if terminal := _check_terminal(state):
        return terminal

    trend_data = state.get("trend_data")

    if trend_data and trend_data.get("hot_topics"):
        return "content_strategist"

>>>>>>> worktree-agent-ad3563fd65e05dd25
    has_error = state.get("error")
    retry_count = state.get("retry_count", 0)

    if has_error and retry_count < 2:
        return "trend_scout"

    return "__end__"


def review_outcome(state: XHSGrowthState) -> Literal["publisher", "revise_content", "__end__"]:
    """人工审核路由 — 根据审核结果决定下一步"""
    if terminal := _check_terminal(state):
        return terminal

    feedback = state.get("human_feedback", {})
    decision = feedback.get("decision", ContentStatus.REJECTED)

    if decision == ContentStatus.APPROVED or decision == "approved":
        if not _xhs_configured():
            return "__end__"
        return "publisher"
    if decision == ContentStatus.NEEDS_REVISION or decision == "needs_revision":
        return "revise_content"
    return "__end__"


def should_continue(state: XHSGrowthState) -> Literal["orchestrator", "engagement", "__end__"]:
    """分析后决定是否继续下一个周期"""
    if terminal := _check_terminal(state):
        return terminal

    phase = state.get("phase", WorkflowPhase.IDLE)

    if phase == WorkflowPhase.ANALYZING:
        mode = state.get("execution_mode", "single")
        if mode == "continuous":
            return "orchestrator"
        return "engagement"

    return "__end__"


def should_optimize(state: XHSGrowthState) -> Literal["content_analyzer", "visual_designer"]:
    """判断是否进入优化流程."""
    if state.get("error"):
        return "visual_designer"

    if state.get("skip_optimization"):
        return "visual_designer"

    viral_posts = state.get("viral_posts", [])
    if viral_posts and len(viral_posts) > 0:
        return "content_analyzer"

    return "visual_designer"


def choice_outcome(state: XHSGrowthState) -> Literal["visual_designer"]:
    """版本选择后路由 — 统一进入视觉设计."""
    return "visual_designer"
