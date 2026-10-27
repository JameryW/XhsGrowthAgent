"""Conditional edge routers for the LangGraph workflow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from backend.config.settings import Settings
from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.modes import OrchestratorDestination, mode_spec
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


def _version_count(state: XHSGrowthState) -> int:
    """Number of live content versions (P1a-S3 routing seam).

    Ref'd threads carry only ``versions_meta`` (the body list lives in the
    Artifact Store and is NOT in router-visible state — routing predicates
    consume RuntimeState only); legacy threads carry the inline list. Reading
    meta first and falling back inline keeps both schemas on one decision.
    """
    meta = state.get("versions_meta")
    if isinstance(meta, list):
        return len(meta)
    return len(state.get("content_versions") or [])


def _has_blogger_notes(state: XHSGrowthState) -> bool:
    """Truthiness of blogger_notes (P1a-S3 routing seam) — same meta-first,
    legacy-inline-fallback contract as :func:`_version_count`."""
    meta = state.get("blogger_notes_meta")
    if isinstance(meta, dict):
        return int(meta.get("count", 0) or 0) > 0
    return bool(state.get("blogger_notes"))


def _has_actionable_trends(state: XHSGrowthState) -> bool:
    """Truthiness of the actionable-topic chain (P1a-S4-1 routing seam).

    trend_data moved to the Artifact Store in S4-1: ref'd threads carry only
    the ``trend_summary`` meta (the body lives behind
    ``artifacts["trend_data"]`` and routers never see the store), while legacy
    threads still carry the inline dict. Meta-first, inline fallback — the
    same contract as :func:`_version_count` / :func:`_has_blogger_notes` —
    keeps both schemas on one decision. The fallback reads the exact alias
    chain ``should_plan`` has always read inline (``hot_topics or
    trending_topics or topics``), and ``trend_summary_of`` derives the meta
    from the same chain, so a ref'd and a legacy thread cannot diverge.
    """
    meta = state.get("trend_summary")
    if isinstance(meta, dict) and meta:
        return bool(meta.get("has_topics"))
    trend_data = state.get("trend_data")
    if not trend_data:
        return False
    return bool(
        trend_data.get("hot_topics")
        or trend_data.get("trending_topics")
        or trend_data.get("topics")
    )


#: Every value :func:`orchestrator_router` can answer with -- imported rather
#: than declared here, because it is the vocabulary of the phase tables that
#: produce it (``backend/state/modes.py``). Re-exported so the name its readers
#: know still resolves; the entry edge's path map is compared against it the way
#: the other seventeen are compared
#: (``tests/unit/graph/test_conditional_edge_wiring.py``).


def orchestrator_router(state: XHSGrowthState) -> OrchestratorDestination:
    """编排器路由 — 根据当前阶段和工作模式决定下一个节点

    The phase tables this reads are the ``phase_routes`` of the mode's spec
    (``backend/state/modes.py``), so this is a lookup -- adding a mode is a
    registry row, not another arm here.

    Every value this can return has to be a key in this edge's path map
    (``backend/graph/wiring.py``). It was not: brief mode's ``phase=creating``
    answer, ``"copywriter"``, had no entry for as long as this signature said
    ``-> str``, so that branch raised ``KeyError`` inside langgraph instead of
    routing (the P1d shape, on a resume path). The annotation and the map are
    now compared in both directions, so the two cannot drift apart again.
    """
    if terminal := _check_terminal(state):
        return terminal

    # The two phase tables this used to hold inline -- one per mode branch --
    # are now each mode's ``phase_routes`` (``backend/state/modes.py``), so that
    # adding a mode is a registry row rather than another arm here. Two checks
    # keep this a lookup rather than a claim: ``plan_registry_complaints``
    # compares every table against the plan template that mode declares, and
    # ``test_the_entry_router_reads_the_mode_spec`` proves this function still
    # consults the registry instead of answering on its own.
    return mode_spec(state).route(state.get("phase", WorkflowPhase.IDLE))


def should_plan(state: XHSGrowthState) -> Literal["content_strategist", "trend_scout", "__end__"]:
    """侦察后判断是否有可操作的趋势 — retry trend_scout on failure before giving up.

    Error with retry_count < 2 overrides _check_terminal for phase=ERROR,
    allowing the workflow to retry before giving up.
    """
    # Check for actionable trends FIRST — if we have data, use it even with
    # errors. Meta-first seam (P1a-S4-1): ref'd threads carry trend_summary
    # (body externalized), legacy threads the inline dict; one decision for
    # both schemas, identical semantics to the pre-S4-1 inline read.
    if _has_actionable_trends(state):
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
# WORKFLOW_MAX_CYCLE_COUNT). max_revision_count budgets human-initiated revise
# cycles; max_cycle_count is enforced in should_continue.

# P0-W5 (round 2): the reason stamped on the state when this fail-closed gate
# parks the workflow. It is the CONTRACT between the evaluator node (writer)
# and POST /resume (reader): a paused thread carrying it can only continue via
# an explicit human decision (approve / revise), never via the legacy
# whole-pipeline restart. Written by the node from the SAME predicate the router
# uses (`evaluator_requires_human`), so the two can never diverge.
PAUSE_REASON_EVALUATOR_FAIL_CLOSED = "evaluator_fail_closed"

# Status stamped by POST /resume when the human chooses revise. Distinguishes a
# human-initiated revise entry (allowed to route into revise_content once) from
# an LLM quality needs_revision/rejected (heavy residual: always human channel).
_HUMAN_REVISION_STATUS = "human_revision_requested"


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


_HUMAN_APPROVED_STATUS = "human_approved"


def _human_requested_revision(evaluation: Mapping[str, Any]) -> bool:
    """True when /resume already chose revise — one-shot entry to revise_content.

    Heavy residual never auto-routes LLM ``needs_revision``/``rejected`` into
    the revise loop; only this resume stamp (or matching ``human_override``)
    may enter ``revise_content`` from ``evaluator_outcome``.
    """
    if str(evaluation.get("status") or "") == _HUMAN_REVISION_STATUS:
        return True
    override = evaluation.get("human_override")
    return isinstance(override, dict) and str(override.get("decision") or "") == "revise"


def _human_approved_override(evaluation: Mapping[str, Any]) -> bool:
    """True when /resume already chose approve — continue toward publish_gate.

    Fail-closed means "requires a human", not "forbidden forever". A stamped
    ``publish_eligibility.allowed=False`` must not re-park after the human
    explicitly approved; publish_gate still demands the irreversible confirm.
    """
    if str(evaluation.get("status") or "") == _HUMAN_APPROVED_STATUS:
        return True
    override = evaluation.get("human_override")
    return isinstance(override, dict) and str(override.get("decision") or "") == "approve"


def _publish_eligibility(state: XHSGrowthState) -> dict[str, Any]:
    """Deterministic publish eligibility audit (never an LLM self-score).

    Prefer the stamped ``evaluation_result.publish_eligibility``; if absent
    (legacy checkpoints), recompute from current state so fail-closed still
    holds.
    """
    evaluation = state.get("evaluation_result") or {}
    if isinstance(evaluation, dict):
        stamped = evaluation.get("publish_eligibility")
        if isinstance(stamped, dict) and "allowed" in stamped:
            return stamped
    from backend.services.compliance.judgers import decide_publish_eligibility

    return decide_publish_eligibility(dict(state)).to_audit_dict()


def _eligibility_blocks(state: XHSGrowthState) -> bool:
    report = _publish_eligibility(state)
    if report.get("allowed") is False:
        return True
    failures = report.get("blocking_failures") or []
    return bool(failures)


def evaluator_requires_human(state: XHSGrowthState) -> bool:
    """Single source of truth: does this run forbid auto-continuing?

    Used by BOTH the evaluator node (to park the workflow in the existing
    paused status) and the evaluator_outcome router (to end the run), so the
    "human channel" decision can never diverge between them.

    Publish permission is owned by deterministic judgers + audit
    (``publish_eligibility``). The LLM panel's ``decision`` never alone grants
    publish, and under heavy residual it also never auto-enters
    ``revise_content`` — revise/approve must come from ``POST /resume``.

    Fail-closed (pause / ``__end__``) when:
    - the panel is degraded / decision-less (P0-W5);
    - quality ``needs_revision`` / ``rejected`` (including at revision cap —
      no force-publish);
    - eligibility blocks when quality already looks "approved" (LLM must not
      self-approve a publish the judgers refuse).

    Exception: a ``/resume`` stamp must NOT re-park —
    - ``human_revision_requested`` → one-shot ``revise_content``;
    - ``human_approved`` → continue toward ``publisher`` / publish_gate even
      when the prior eligibility stamp still says denied (human override).
    """
    evaluation = state.get("evaluation_result")
    if evaluation is None:
        return True

    # Human /resume stamp wins over the evidence that caused the park
    # (degraded flags, quality decision, eligibility stamp). Without this
    # order, a leftover publish_eligibility.allowed=False would re-park
    # approve, and a leftover degraded flag would re-park revise.
    if _human_requested_revision(evaluation) or _human_approved_override(evaluation):
        return False

    if _evaluation_is_degraded(evaluation):
        return True

    decision: Any = evaluation.get("decision")

    # Heavy residual: LLM quality revise/reject always parks for human.
    # Never auto-revise; never force-publish at max_revision_count.
    if decision in (
        ContentStatus.REJECTED,
        ContentStatus.NEEDS_REVISION,
        "rejected",
        "needs_revision",
    ):
        return True

    # Approved / legacy: LLM self-score must not grant publish when judgers block.
    return bool(_eligibility_blocks(state))


def evaluator_outcome(
    state: XHSGrowthState,
) -> Literal["publisher", "revise_content", "__end__"]:
    """创作质量评估路由 — 确定性发布资格 + 人工修订通道（heavy residual）.

    review_gate approved 后进入 evaluator_gate：

    - **能不能发** 只看 ``publish_eligibility``（确定性判定器 + 审计），不看
      LLM 综合自评分。LLM ``approved`` 在判定器失败时不得放行。
    - **要不要改** 不再由 LLM ``needs_revision``/``rejected`` 自动进
      ``revise_content``；质量拒绝一律 ``__end__``（节点 PAUSED），由
      ``POST /resume`` ``human_decision=revise|approve`` 继续。
    - 降级/缺失 → ``__end__``（节点 PAUSED）。
    - 修订上限 **不再** force 进 publisher；上限下的质量拒绝仍走人工通道。
    - 唯一进 ``revise_content`` 的路径：``/resume`` revise 盖章后的一次路由。

    不读 _check_terminal：此处只在人审通过后触发，不会有 cancelled/paused 分支
    （那些在 review_outcome 已拦截）。
    """
    if evaluator_requires_human(state):
        return "__end__"

    evaluation = state.get("evaluation_result") or {}
    # Only human-initiated revise (POST /resume) enters revise_content from here.
    if _human_requested_revision(evaluation):
        return "revise_content"
    # Quality approved and eligibility clear → publish_gate
    return "publisher"


def publish_gate_outcome(state: XHSGrowthState) -> Literal["publisher", "__end__"]:
    """发布确认路由 — 只有明确的确认才放行那次不可逆的发布.

    节点已把人的答复写进 ``publish_confirmation``；这里只读它。**默认拒绝**：
    确认值缺失、拼错、或是来自旧客户端的任何别的词，一律不放行 —— 一个把
    无法识别的值读成"继续"的确认关卡，会把每一次版本错配都变成一次未经
    确认的真实发布。本节点存在的理由就是挡住这个方向，所以它的失败方向
    必须是关。

    取消时节点已把 phase 置为 CANCELLED，故 `_check_terminal` 在这里也返回
    __end__；两条路径通向同一结果是有意的 —— 无论读到哪个键，结论一致。
    """
    if terminal := _check_terminal(state):
        return terminal

    confirmation = state.get("publish_confirmation") or {}
    if str(confirmation.get("decision") or "") == "confirmed":
        return "publisher"
    return "__end__"


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

    if _version_count(state) > 1:
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

    if _version_count(state) > 1:
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

    # A mode whose copy is written from its input rather than from a selected
    # blogger's notes answers before any blogger logic runs (brief mode,
    # historically).
    if not mode_spec(state).runs_blogger_selection:
        return "copywriter"

    selected_blogger = state.get("selected_blogger") or {}
    has_selected_blogger = isinstance(selected_blogger, dict) and bool(
        selected_blogger.get("user_id")
    )
    if has_selected_blogger and _has_blogger_notes(state):
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

    # No blogger-selection loop in this mode: there is nothing to match, so
    # skip viral_matcher and go straight on (brief mode, historically).
    if not mode_spec(state).runs_blogger_selection:
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

    if _version_count(state) > 1:
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
        # One declaration covers all three ripple routers: re-analyze the
        # input, or re-plan the content.
        return mode_spec(state).reanalysis_node
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
        # One declaration covers all three ripple routers: re-analyze the
        # input, or re-plan the content.
        return mode_spec(state).reanalysis_node
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
        # One declaration covers all three ripple routers: re-analyze the
        # input, or re-plan the content.
        return mode_spec(state).reanalysis_node
    if action == "retopic":
        return "trend_scout"

    return "review_gate"
