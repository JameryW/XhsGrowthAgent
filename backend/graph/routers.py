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
    """编排器路由 — 根据当前阶段和工作模式决定下一个节点"""
    if terminal := _check_terminal(state):
        return terminal

    phase = state.get("phase", WorkflowPhase.IDLE)
    mode = state.get("workflow_mode", "trend")

    # Brief mode: route to brief_analyzer instead of trend_scout
    if mode == "brief":
        routing = {
            WorkflowPhase.BRIEFING: "brief_analyzer",
            WorkflowPhase.PLANNING: "content_strategist",
            WorkflowPhase.CREATING: "copywriter",
            WorkflowPhase.ANALYZING: "analyst",
            WorkflowPhase.ENGAGING: "engagement",
            WorkflowPhase.ERROR: "__end__",
            WorkflowPhase.COMPLETED: "__end__",
            WorkflowPhase.IDLE: "brief_analyzer",
        }
    else:
        # Trend mode (existing flow)
        routing = {
            WorkflowPhase.SCOUTING: "trend_scout",
            WorkflowPhase.PLANNING: "content_strategist",
            WorkflowPhase.ANALYZING: "analyst",
            WorkflowPhase.ENGAGING: "engagement",
            WorkflowPhase.ERROR: "__end__",
            WorkflowPhase.COMPLETED: "__end__",
            WorkflowPhase.IDLE: "trend_scout",
        }

    return routing.get(phase, "trend_scout" if mode != "brief" else "brief_analyzer")


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


def should_brief_or_optimize(
    state: XHSGrowthState,
) -> Literal["shooting_planner", "content_analyzer", "visual_designer"]:
    """Route after viral_matcher — brief mode goes to shooting_planner,
    trend mode goes to content_analyzer or visual_designer.
    """
    if _check_terminal(state):
        return "visual_designer"

    mode = state.get("workflow_mode", "trend")
    if mode == "brief":
        return "shooting_planner"

    # Trend mode: existing optimization flow
    return should_optimize(state)


def blogger_gate_router(
    state: XHSGrowthState,
) -> Literal["shooting_planner", "content_analyzer", "visual_designer"]:
    """Route after blogger_gate — brief mode goes to shooting_planner,
    trend mode goes to content_analyzer or visual_designer.

    Same routing logic as should_brief_or_optimize, applied after
    blogger selection is complete.
    """
    if _check_terminal(state):
        return "visual_designer"

    mode = state.get("workflow_mode", "trend")
    if mode == "brief":
        return "shooting_planner"

    return should_optimize(state)


def copywriter_router(
    state: XHSGrowthState,
) -> Literal["draft_gate", "visual_designer"]:
    """Route after copywriter — brief mode skips draft_gate, trend mode goes to draft_gate."""
    if _check_terminal(state):
        return "visual_designer"

    mode = state.get("workflow_mode", "trend")
    if mode == "brief":
        # Brief mode: skip draft_gate, go directly to visual_designer
        return "visual_designer"

    return "draft_gate"


def visual_designer_router(
    state: XHSGrowthState,
) -> Literal["review_gate", "__end__"]:
    """Route after visual_designer — brief mode ends (no review/publish),
    trend mode goes to review_gate.
    """
    if _check_terminal(state):
        return "__end__"

    mode = state.get("workflow_mode", "trend")
    if mode == "brief":
        # Brief mode: done after visual design + Ripple analysis
        return "__end__"

    return "review_gate"


def ripple_gate_router(
    state: XHSGrowthState,
) -> Literal["copywriter", "content_strategist", "brief_analyzer", "trend_scout", "__end__"]:
    """Route after ripple_gate — based on user's reselect decision.

    Trend mode:
      accept   → copywriter (normal flow)
      reangle  → content_strategist (re-plan with same trend data)
      retopic  → trend_scout (go back and find new trends)

    Brief mode:
      accept   → copywriter (normal flow)
      reangle  → brief_analyzer (re-analyze brief with new direction)
      retopic  → trend_scout (switch to trend mode entirely)
    """
    if terminal := _check_terminal(state):
        return terminal

    decision = state.get("ripple_decision") or {}
    action = decision.get("action", "accept")

    if action == "reangle":
        mode = state.get("workflow_mode", "trend")
        return "brief_analyzer" if mode == "brief" else "content_strategist"
    if action == "retopic":
        return "trend_scout"

    # Default: accept → continue to copywriter
    return "copywriter"
