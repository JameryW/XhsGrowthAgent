"""Conditional edge routers for the LangGraph workflow."""

from __future__ import annotations

from typing import Literal

from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.schema import XHSGrowthState


def _check_terminal(state: XHSGrowthState) -> str | None:
    """Return '__end__' if workflow is in terminal state, else None.

    Terminal states: cancelled, paused, error, completed.
    Note: state.get("error") alone is NOT terminal — the workflow may retry
    or have next nodes that can recover. Only phase=ERROR is terminal.
    """
    phase = state.get("phase")
    if phase in (
        WorkflowPhase.CANCELLED,
        WorkflowPhase.PAUSED,
        WorkflowPhase.ERROR,
        WorkflowPhase.COMPLETED,
    ):
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

    # Check for actionable trends — normalize across field aliases:
    # hot_topics (canonical), trending_topics (LLM output), topics (fallback)
    if trend_data:
        has_topics = bool(
            trend_data.get("hot_topics")
            or trend_data.get("trending_topics")
            or trend_data.get("topics")
        )
        if has_topics:
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


def should_optimize(
    state: XHSGrowthState,
) -> Literal["content_analyzer", "visual_designer", "__end__"]:
    """判断是否进入优化流程 — always optimize unless explicitly skipped."""
    if terminal := _check_terminal(state):
        return terminal

    if state.get("skip_optimization"):
        return "visual_designer"

    return "content_analyzer"


def content_analyzer_router(
    state: XHSGrowthState,
) -> Literal["choice_gate", "version_generator", "__end__"]:
    """Route after content_analyzer — if copywriter already generated style
    variants (content_versions with length > 1), go directly to choice_gate
    for style selection; otherwise go to version_generator for A/B/C generation.
    """
    if terminal := _check_terminal(state):
        return terminal

    versions = state.get("content_versions", [])
    if len(versions) > 1:
        return "choice_gate"

    return "version_generator"


def choice_outcome(state: XHSGrowthState) -> Literal["visual_designer", "version_generator"]:
    """Style selection → version_generator (A/B/C), version selection → visual_designer.

    After the FIRST choice_gate (style selection), route to version_generator
    so it can generate A/B/C variants based on the selected style.
    After the SECOND choice_gate (version selection), route to visual_designer.
    """
    # If a style was just selected (style_selected=True), generate A/B/C variants
    if state.get("style_selected"):
        return "version_generator"

    return "visual_designer"


def should_present_choice(
    state: XHSGrowthState,
) -> Literal["choice_gate", "visual_designer", "__end__"]:
    """Route after version generation — only enter choice_gate if multiple versions exist.

    When there is a single version or no versions, auto-select and skip
    directly to visual_designer. This avoids an unnecessary interrupt when
    there is nothing for the user to choose.
    """
    if terminal := _check_terminal(state):
        return terminal

    versions = state.get("content_versions", [])
    if len(versions) > 1:
        return "choice_gate"
    # Single or no versions — auto-select and skip to visual_designer
    return "visual_designer"


def shooting_planner_router(
    state: XHSGrowthState,
) -> Literal["content_analyzer", "visual_designer", "__end__"]:
    """Route after shooting_planner — both modes go to content_analyzer
    for optimization (content analysis -> version generation -> choice -> visual).
    Falls back to visual_designer if skip_optimization, or __end__ for terminal state.
    """
    if terminal := _check_terminal(state):
        return terminal

    return should_optimize(state)


def should_brief_or_optimize(
    state: XHSGrowthState,
) -> Literal["shooting_planner", "__end__"]:
    """Route after viral_matcher — both modes go to shooting_planner."""
    if terminal := _check_terminal(state):
        return terminal

    return "shooting_planner"


def blogger_gate_router(
    state: XHSGrowthState,
) -> Literal["copywriter", "draft_gate", "__end__"]:
    """Route after blogger_gate — brief mode goes to copywriter, trend mode to draft_gate.

    Brief mode: blogger_gate → copywriter (AI generates copy from brief + blogger notes)
    Trend mode: blogger_gate → draft_gate (user writes draft manually)
    """
    if terminal := _check_terminal(state):
        return terminal

    mode = state.get("workflow_mode", "trend")
    if mode == "brief":
        return "copywriter"

    return "draft_gate"


def draft_gate_router(
    state: XHSGrowthState,
) -> Literal["viral_matcher", "shooting_planner"]:
    """Route after draft_gate — based on which path entered draft_gate.

    From copywriter (trend mode, no selected_blogger) → viral_matcher
    From blogger_gate (selected_blogger present) → shooting_planner
    From blogger_gate (blogger skipped/no candidates) → shooting_planner
    From copywriter (brief mode) → shooting_planner (skip blogger selection)

    Brief mode and blogger-skipped both avoid the viral_matcher →
    blogger_scout → blogger_gate loop, going directly to shooting_planner.
    """
    selected_blogger = state.get("selected_blogger")
    if selected_blogger and isinstance(selected_blogger, dict) and selected_blogger.get("user_id"):
        return "shooting_planner"

    # Blogger was skipped or no candidates → go to shooting_planner, not viral_matcher
    if state.get("blogger_skipped"):
        return "shooting_planner"

    # Brief mode: skip blogger selection loop
    mode = state.get("workflow_mode", "trend")
    if mode == "brief":
        return "shooting_planner"

    return "viral_matcher"


def copywriter_router(
    state: XHSGrowthState,
) -> Literal["draft_gate", "__end__"]:
    """Route after copywriter — both modes go to draft_gate for review.
    Returns __end__ for terminal states.
    """
    if terminal := _check_terminal(state):
        return terminal

    return "draft_gate"


def visual_designer_router(
    state: XHSGrowthState,
) -> Literal["review_gate", "__end__"]:
    """Route after visual_designer — both modes go to review_gate.
    Returns __end__ only for terminal states (paused/cancelled/error).
    """
    if _check_terminal(state):
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
