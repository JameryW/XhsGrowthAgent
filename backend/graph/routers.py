"""Conditional edge routers for the LangGraph workflow."""

from __future__ import annotations

from typing import Literal

from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.schema import XHSGrowthState


def _check_terminal(state: XHSGrowthState) -> str | None:
    """Return '__end__' if workflow is in terminal state, else None.

    Terminal states: cancelled, paused, error phase.
    Note: state.get("error") alone is NOT terminal — the workflow may retry
    or have next nodes that can recover. Only phase=ERROR is terminal.
    """
    phase = state.get("phase")
    if phase == WorkflowPhase.CANCELLED:
        return "__end__"
    if phase == WorkflowPhase.PAUSED:
        return "__end__"
    if phase == WorkflowPhase.ERROR:
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
    if terminal := _check_terminal(state):
        return terminal

    trend_data = state.get("trend_data")

    if trend_data and trend_data.get("hot_topics"):
        return "content_strategist"

    has_error = state.get("error")
    retry_count = state.get("retry_count", 0)

    if has_error and retry_count < 2:
        return "trend_scout"

    return "__end__"


def review_outcome(state: XHSGrowthState) -> Literal["publisher", "revise_content", "__end__"]:
    """人工审核路由 — 根据审核结果决定下一步.

    Always routes to publisher when approved — the PublisherAgent itself
    handles dry_run mode, so dry_run=True workflows still go through the
    full publish -> analyst chain.
    """
    if terminal := _check_terminal(state):
        return terminal

    feedback = state.get("human_feedback", {})
    decision = feedback.get("decision", ContentStatus.REJECTED)

    if decision == ContentStatus.APPROVED or decision == "approved":
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


def engagement_router(state: XHSGrowthState) -> Literal["orchestrator", "__end__"]:
    """Engagement completion router — loop back or end based on execution mode.

    In single-execution mode (default), engagement is the final node → END.
    In continuous mode, engagement feeds back to orchestrator for the next cycle.
    """
    if terminal := _check_terminal(state):
        return terminal

    mode = state.get("execution_mode", "single")
    if mode == "continuous":
        return "orchestrator"
    return "__end__"


def should_optimize(state: XHSGrowthState) -> Literal["content_analyzer", "visual_designer"]:
    """判断是否进入优化流程."""
    if state.get("error") and state.get("phase") == WorkflowPhase.ERROR:
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


def should_present_choice(state: XHSGrowthState) -> Literal["choice_gate", "visual_designer"]:
    """Route after version generation — only enter choice_gate if multiple versions exist.

    When there is a single version or no versions, auto-select and skip
    directly to visual_designer. This avoids an unnecessary interrupt when
    there is nothing for the user to choose.
    """
    if _check_terminal(state):
        # Terminal state — route to visual_designer which will eventually
        # end via its own downstream routers
        return "visual_designer"

    versions = state.get("content_versions", [])
    if len(versions) > 1:
        return "choice_gate"
    # Single or no versions — auto-select and skip to visual_designer
    return "visual_designer"
