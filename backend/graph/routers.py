"""Conditional edge routers for the LangGraph workflow."""

from __future__ import annotations

from typing import Any, Literal

from backend.config.settings import Settings
from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.schema import XHSGrowthState


def _check_terminal(state: XHSGrowthState) -> Literal["__end__"] | None:
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
            # Legacy checkpoints may still contain ENGAGING; no interaction
            # node exists anymore, so terminate instead of restarting work.
            WorkflowPhase.ENGAGING: "__end__",
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
            # Legacy checkpoints may still contain ENGAGING; no interaction
            # node exists anymore, so terminate instead of restarting work.
            WorkflowPhase.ENGAGING: "__end__",
            WorkflowPhase.ERROR: "__end__",
            WorkflowPhase.COMPLETED: "__end__",
            WorkflowPhase.IDLE: "trend_scout",
        }

    return routing.get(phase, "trend_scout" if mode != "brief" else "brief_analyzer")


def should_plan(state: XHSGrowthState) -> Literal["content_strategist", "trend_scout", "__end__"]:
    """侦察后判断是否有可操作的趋势 — retry trend_scout on failure before giving up.

    Error with retry_count < 2 overrides _check_terminal for phase=ERROR,
    allowing the workflow to retry before giving up.
    """
    # Check for actionable trends FIRST — if we have data, use it even with errors
    trend_data = state.get("trend_data")
    if trend_data:
        has_topics = bool(
            trend_data.get("hot_topics")
            or trend_data.get("trending_topics")
            or trend_data.get("topics")
        )
        if has_topics:
            return "content_strategist"

    # Error retry takes priority over terminal check — phase=ERROR with
    # retry_count < 2 should retry, not terminate immediately
    has_error = state.get("error")
    retry_count = state.get("retry_count", 0)
    phase = state.get("phase")
    retryable = has_error and retry_count < 2
    if retryable and phase not in (WorkflowPhase.CANCELLED, WorkflowPhase.PAUSED):
        return "trend_scout"

    if terminal := _check_terminal(state):
        return terminal

    return "__end__"


def review_outcome(state: XHSGrowthState) -> Literal["evaluator_gate", "revise_content", "__end__"]:
    """人工审核路由 — 根据审核结果决定下一步.

    approved → evaluator_gate (RQGM agent-as-a-judge 质量关卡，再决定发布/修订).
    The PublisherAgent itself handles dry_run mode, so dry_run=True workflows
    still go through evaluator_gate → publisher.
    """
    if terminal := _check_terminal(state):
        return terminal

    feedback = state.get("human_feedback", {})
    # decision may arrive as a ContentStatus enum or a raw string (from JSON)
    decision: Any = feedback.get("decision", ContentStatus.REJECTED)

    if decision == ContentStatus.APPROVED or decision == "approved":
        return "evaluator_gate"
    if decision == ContentStatus.NEEDS_REVISION or decision == "needs_revision":
        return "revise_content"
    return "__end__"


# Loop-guard caps live in WorkflowSettings (env WORKFLOW_MAX_REVISION_COUNT /
# WORKFLOW_MAX_CYCLE_COUNT). They mirror ripple.max_reselect_count — see
# evaluator_outcome / should_continue below.

# P0-W5: dimensions whose failure is a compliance/policy failure — these can
# NEVER be silently force-published (fail-closed track). Anything else is on
# the quality track, where fail-open at the revision cap remains allowed.
COMPLIANCE_DIMENSIONS = frozenset({"compliance", "policy"})

# P0-W5 (round 2): the reason stamped on the state when this fail-closed gate
# parks the workflow. It is the CONTRACT between the evaluator node (writer)
# and POST /resume (reader): a paused thread carrying it can only continue via
# an explicit human decision (approve / revise), never via the legacy
# whole-pipeline restart. Written by the node from the SAME predicate the router
# uses (`evaluator_requires_human`), so the two can never diverge.
PAUSE_REASON_EVALUATOR_FAIL_CLOSED = "evaluator_fail_closed"


def _evaluation_is_degraded(evaluation: Any) -> bool:
    """Degraded evidence: missing/empty result, degraded flag/status, or a
    missing/None decision (synthesized degraded, LLM timeout, empty content)."""
    if not evaluation or not isinstance(evaluation, dict):
        return True
    if evaluation.get("degraded"):
        return True
    if str(evaluation.get("status") or "").lower() == "degraded":
        return True
    return "decision" not in evaluation or evaluation.get("decision") is None


def _rejection_is_compliance_driven(evaluation: dict[str, Any]) -> bool:
    """True when a REJECTED decision was driven by compliance/policy evidence.

    Primary marker: the additive ``failed_dimensions`` list (P0-W5) intersected
    with the compliance dimensions. Back-compat for legacy results without the
    marker: any dimension flagged ``is_blocking`` (the same evidence that made
    _compute_decision reject). Missing marker + no blocking dims ⇒ quality
    (the PRD's backward-compatible default).
    """
    failed_dims = evaluation.get("failed_dimensions")
    dims = evaluation.get("dimensions") or []
    blocking = {
        str(d.get("dimension")) for d in dims if isinstance(d, dict) and d.get("is_blocking")
    }
    if failed_dims is not None:
        if set(failed_dims) & set(COMPLIANCE_DIMENSIONS):
            return True
        # A blocking dimension on ANY track is a hard policy signal.
        return bool(set(failed_dims) & blocking)
    return bool(blocking)


def evaluator_requires_human(state: XHSGrowthState) -> bool:
    """P0-W5 single source of truth: does this evaluation forbid auto-publish?

    Used by BOTH the evaluator node (to park the workflow in the existing
    paused status) and the evaluator_outcome router (to end the run), so the
    "human channel" decision can never diverge between them.
    """
    evaluation = state.get("evaluation_result")
    if _evaluation_is_degraded(evaluation):
        return True
    decision: Any = evaluation.get("decision")
    if decision in (ContentStatus.REJECTED, "rejected"):
        revision_count = state.get("revision_count", 0)
        if (
            revision_count >= Settings().workflow.max_revision_count
            and _rejection_is_compliance_driven(evaluation)
        ):
            return True
    return False


def evaluator_outcome(
    state: XHSGrowthState,
) -> Literal["publisher", "revise_content", "__end__"]:
    """创作质量评估路由 — RQGM agent-as-a-judge 面板判定（P0-W5 fail-closed）.

    review_gate approved 后进入 evaluator_gate。读取 evaluation_result.decision：
    - approved → publisher
    - needs_revision / rejected（质量轨）→ revise_content（revision_hints 随
      evaluation_result 携带）
    - 降级/缺失/decision=None、以及 compliance/政策维度的拒绝 → __end__：
      质量门失败时禁止静默放行发布（compliance fail-closed）。evaluator 节点已
      把 phase 置为既有 PAUSED 语义并写入 PAUSE_REASON_EVALUATOR_FAIL_CLOSED，
      人工通过 POST /resume/{thread_id} {"human_decision": "approve"|"revise"}
      继续（compliance 阻断按设计可被人工推翻——fail-closed 是"必须有人决定"，
      不是"禁止发布"）。路由本身不写状态。

    循环防护（仅质量轨）：revision_count >= Settings().workflow.max_revision_count
    （默认 2）时，只有全部 REJECTED 证据都来自质量维度才放行 publisher（保持
    旧行为锚定）；compliance/阻塞维度参与的拒绝走与上面相同的人工通道。

    不读 _check_terminal：此处只在人审通过后触发，不会有 cancelled/paused 分支
    （那些在 review_outcome 已拦截）。
    """
    if evaluator_requires_human(state):
        return "__end__"

    evaluation = state.get("evaluation_result") or {}
    decision: Any = evaluation.get("decision")

    if decision in (
        ContentStatus.NEEDS_REVISION,
        ContentStatus.REJECTED,
        "needs_revision",
        "rejected",
    ):
        # Force-approve if revision limit reached — prevent infinite loop
        # (quality track only; compliance rejections were caught above).
        revision_count = state.get("revision_count", 0)
        if revision_count >= Settings().workflow.max_revision_count:
            return "publisher"
        return "revise_content"
    # approved（及显式未知 decision 的 legacy 结果）→ 放行发布
    return "publisher"


def should_continue(state: XHSGrowthState) -> Literal["orchestrator", "__end__"]:
    """分析后决定是否继续下一个周期

    Continuous-mode loop guard: cycle_count >= Settings().workflow.max_cycle_count
    （默认 5）forces __end__, preventing an unbounded analyst→orchestrator→analyst
    loop when the orchestrator keeps routing back to analyst (phase stays ANALYZING).
    Mirrors the revision_count / reselect_count caps on the other loops.
    """
    if terminal := _check_terminal(state):
        return terminal

    phase = state.get("phase", WorkflowPhase.IDLE)

    if phase == WorkflowPhase.ANALYZING:
        mode = state.get("execution_mode", "single")
        if mode == "continuous":
            # Cap continuous-mode cycles — no infinite orchestrator loop
            if state.get("cycle_count", 0) >= Settings().workflow.max_cycle_count:
                return "__end__"
            return "orchestrator"
        return "__end__"

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
    """Route after blogger_gate.

    Brief mode: blogger_gate → copywriter (AI generates copy from brief + blogger notes)
    Trend mode with selected blogger notes: blogger_gate → copywriter so it can
    generate multi-style candidates from the selected blogger's notes.
    Trend mode without a selected blogger: blogger_gate → draft_gate.
    """
    if terminal := _check_terminal(state):
        return terminal

    mode = state.get("workflow_mode", "trend")
    if mode == "brief":
        return "copywriter"

    blogger_notes = state.get("blogger_notes") or []
    selected_blogger = state.get("selected_blogger") or {}
    has_selected_blogger = isinstance(selected_blogger, dict) and bool(
        selected_blogger.get("user_id")
    )
    if has_selected_blogger and blogger_notes:
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
) -> Literal["choice_gate", "draft_gate", "__end__"]:
    """Route after copywriter.

    If copywriter generated multi-style variants from blogger notes, pause at
    choice_gate for style selection. Otherwise go to draft_gate for review.
    Returns __end__ for terminal states.
    """
    if terminal := _check_terminal(state):
        return terminal

    versions = state.get("content_versions", [])
    if len(versions) > 1:
        return "choice_gate"

    return "draft_gate"


def visual_designer_router(
    state: XHSGrowthState,
) -> Literal["review_gate", "ripple_late_recheck", "__end__"]:
    """Route after visual_designer.

    Background mode with a still-pending Ripple result (ripple_pending=True):
    go to ripple_late_recheck, which bounded-polls the store for the
    late-arriving prediction and may interrupt for a suboptimal result.
    Blocking mode (or background result already consumed by ripple_finalize):
    ripple_pending is False → go straight to review_gate.

    review_gate uses dynamic interrupt() (like ripple_gate): low-risk drafts
    with auto_approve_low_risk enabled auto-pass inside the node (writing the
    auto_low_risk audit trace); all others interrupt for human review. The
    router never bypasses review_gate, so the audit trace is always written.

    Returns __end__ only for terminal states (paused/cancelled/error).
    """
    if _check_terminal(state):
        return "__end__"

    if state.get("ripple_pending"):
        return "ripple_late_recheck"

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


def content_strategist_router(
    state: XHSGrowthState,
) -> Literal["ripple_finalize", "ripple_gate", "__end__"]:
    """Route after content_strategist based on Ripple mode.

    Background mode (ripple_pending=True): skip ripple_gate, go to
    ripple_finalize which reads the store-written background result.
    Blocking mode: go to ripple_gate (existing behavior).
    """
    # Terminal guard: if content_strategist errored (phase=ERROR), do NOT
    # fall through to ripple_gate — ripple_gate auto-accepts when Ripple data
    # is absent (viral_prob/pmf default to 1.0), which would overwrite the
    # error phase with `creating` and silently swallow the failure. End here.
    if terminal := _check_terminal(state):
        return terminal
    if state.get("ripple_pending"):
        return "ripple_finalize"
    return "ripple_gate"


def ripple_finalize_router(
    state: XHSGrowthState,
) -> Literal["copywriter", "content_strategist", "brief_analyzer", "trend_scout", "__end__"]:
    """Route after ripple_finalize — mirrors ripple_gate_router."""
    if terminal := _check_terminal(state):
        return terminal

    decision = state.get("ripple_decision") or {}
    action = decision.get("action", "accept")

    if action == "reangle":
        mode = state.get("workflow_mode", "trend")
        return "brief_analyzer" if mode == "brief" else "content_strategist"
    if action == "retopic":
        return "trend_scout"

    return "copywriter"


def ripple_late_recheck_router(
    state: XHSGrowthState,
) -> Literal["review_gate", "content_strategist", "brief_analyzer", "trend_scout", "__end__"]:
    """Route after ripple_late_recheck.

    accept (or no interrupt — result acceptable / poll timeout fail-open) → review_gate.
    reangle → content_strategist (trend) / brief_analyzer (brief).
    retopic → trend_scout.
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

    return "review_gate"
