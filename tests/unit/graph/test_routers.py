"""Unit tests for graph routers."""

from backend.graph.routers import (
    blogger_gate_router,
    choice_outcome,
    content_analyzer_router,
    content_strategist_router,
    copywriter_router,
    draft_gate_router,
    engagement_router,
    evaluator_outcome,
    orchestrator_router,
    review_outcome,
    ripple_gate_router,
    shooting_planner_router,
    should_continue,
    should_plan,
    should_present_choice,
    visual_designer_router,
)
from backend.state.enums import ContentStatus, WorkflowPhase


class TestOrchestratorRouter:
    """Tests for orchestrator_router conditional edge."""

    def test_routes_to_trend_scout_for_scouting(self):
        """SCOUTING phase routes to trend_scout."""
        state = {"phase": WorkflowPhase.SCOUTING}
        result = orchestrator_router(state)
        assert result == "trend_scout"

    def test_routes_to_content_strategist_for_planning(self):
        """PLANNING phase routes to content_strategist."""
        state = {"phase": WorkflowPhase.PLANNING}
        result = orchestrator_router(state)
        assert result == "content_strategist"

    def test_routes_to_analyst_for_analyzing(self):
        """ANALYZING phase routes to analyst."""
        state = {"phase": WorkflowPhase.ANALYZING}
        result = orchestrator_router(state)
        assert result == "analyst"

    def test_routes_to_engagement_for_engaging(self):
        """ENGAGING phase routes to engagement."""
        state = {"phase": WorkflowPhase.ENGAGING}
        result = orchestrator_router(state)
        assert result == "engagement"

    def test_routes_to_end_for_error(self):
        """ERROR phase routes to END."""
        state = {"phase": WorkflowPhase.ERROR}
        result = orchestrator_router(state)
        assert result == "__end__"

    def test_routes_to_end_for_completed(self):
        """COMPLETED phase routes to END."""
        state = {"phase": WorkflowPhase.COMPLETED}
        result = orchestrator_router(state)
        assert result == "__end__"

    def test_routes_to_trend_scout_for_idle(self):
        """IDLE phase routes to trend_scout."""
        state = {"phase": WorkflowPhase.IDLE}
        result = orchestrator_router(state)
        assert result == "trend_scout"

    def test_routes_to_trend_scout_default(self):
        """Unknown phase defaults to trend_scout."""
        state = {"phase": "unknown_phase"}
        result = orchestrator_router(state)
        assert result == "trend_scout"


class TestShouldPlan:
    """Tests for should_plan conditional edge."""

    def test_routes_to_strategist_with_hot_topics(self):
        """Hot topics exist → content_strategist."""
        state = {"trend_data": {"hot_topics": ["美食", "穿搭"]}}
        result = should_plan(state)
        assert result == "content_strategist"

    def test_routes_to_end_without_hot_topics(self):
        """No hot topics → END."""
        state = {"trend_data": {"hot_topics": []}}
        result = should_plan(state)
        assert result == "__end__"

    def test_routes_to_end_with_empty_trend_data(self):
        """Empty trend_data → END."""
        state = {"trend_data": {}}
        result = should_plan(state)
        assert result == "__end__"

    def test_routes_to_end_without_trend_data(self):
        """No trend_data → END."""
        state = {}
        result = should_plan(state)
        assert result == "__end__"

    def test_routes_to_trend_scout_on_retry(self):
        """Error with retry_count < 2 → trend_scout (retry)."""
        state = {"error": "API failed", "retry_count": 0}
        result = should_plan(state)
        assert result == "trend_scout"

    def test_routes_to_end_on_max_retry(self):
        """Error with retry_count >= 2 → END (give up)."""
        state = {"error": "API failed", "retry_count": 2}
        result = should_plan(state)
        assert result == "__end__"

    def test_routes_to_strategist_overrides_error(self):
        """Hot topics present even with error → content_strategist."""
        state = {"trend_data": {"hot_topics": ["美食"]}, "error": "partial fail"}
        result = should_plan(state)
        assert result == "content_strategist"

    def test_error_phase_with_low_retry_retries(self):
        """phase=ERROR with retry_count < 2 → trend_scout (retry, not terminal)."""
        state = {"phase": WorkflowPhase.ERROR, "error": "API failed", "retry_count": 0}
        result = should_plan(state)
        assert result == "trend_scout"

    def test_error_phase_with_max_retry_gives_up(self):
        """phase=ERROR with retry_count >= 2 → __end__ (give up)."""
        state = {"phase": WorkflowPhase.ERROR, "error": "API failed", "retry_count": 2}
        result = should_plan(state)
        assert result == "__end__"

    def test_cancelled_overrides_error_retry(self):
        """phase=CANCELLED with error → __end__ (cancelled is truly terminal)."""
        state = {"phase": WorkflowPhase.CANCELLED, "error": "API failed", "retry_count": 0}
        result = should_plan(state)
        assert result == "__end__"

    def test_paused_overrides_error_retry(self):
        """phase=PAUSED with error → __end__ (paused is terminal)."""
        state = {"phase": WorkflowPhase.PAUSED, "error": "API failed", "retry_count": 0}
        result = should_plan(state)
        assert result == "__end__"


class TestReviewOutcome:
    """Tests for review_outcome conditional edge.

    approved → evaluator_gate (RQGM agent-as-a-judge panel runs before publish).
    """

    def test_routes_to_evaluator_gate_for_approved_enum(self):
        """APPROVED enum → evaluator_gate (AI quality gate before publisher)."""
        state = {"human_feedback": {"decision": ContentStatus.APPROVED}}
        result = review_outcome(state)
        assert result == "evaluator_gate"

    def test_routes_to_evaluator_gate_for_approved_string(self):
        """approved string → evaluator_gate."""
        state = {"human_feedback": {"decision": "approved"}}
        result = review_outcome(state)
        assert result == "evaluator_gate"

    def test_routes_to_evaluator_gate_for_approved_without_xhs(self):
        """APPROVED → evaluator_gate even without XHS config (dry_run handled by PublisherAgent)."""
        state = {"human_feedback": {"decision": ContentStatus.APPROVED}}
        result = review_outcome(state)
        assert result == "evaluator_gate"

    def test_routes_to_revise_for_needs_revision(self):
        """NEEDS_REVISION → revise_content."""
        state = {"human_feedback": {"decision": ContentStatus.NEEDS_REVISION}}
        result = review_outcome(state)
        assert result == "revise_content"

    def test_routes_to_end_for_rejected(self):
        """REJECTED → __end__ (end workflow, no revision loop)."""
        state = {"human_feedback": {"decision": ContentStatus.REJECTED}}
        result = review_outcome(state)
        assert result == "__end__"

    def test_routes_to_end_for_no_feedback(self):
        """No feedback defaults to REJECTED → __end__."""
        state = {}
        result = review_outcome(state)
        assert result == "__end__"

    def test_routes_to_revise_for_needs_revision_string(self):
        """Raw string decision (JSON resume value) → revise_content."""
        state = {"human_feedback": {"decision": "needs_revision"}}
        result = review_outcome(state)
        assert result == "revise_content"

    def test_routes_to_end_for_rejected_string(self):
        """Raw string rejected → __end__."""
        state = {"human_feedback": {"decision": "rejected"}}
        result = review_outcome(state)
        assert result == "__end__"

    def test_terminal_phase_overrides_approved(self):
        """phase=CANCELLED wins over an approved decision → __end__."""
        state = {
            "phase": WorkflowPhase.CANCELLED,
            "human_feedback": {"decision": ContentStatus.APPROVED},
        }
        result = review_outcome(state)
        assert result == "__end__"


class TestEvaluatorOutcome:
    """Tests for evaluator_outcome conditional edge (RQGM agent-as-a-judge)."""

    def test_approved_routes_to_publisher(self):
        """Evaluation approved → publisher."""
        state = {"evaluation_result": {"decision": ContentStatus.APPROVED}}
        assert evaluator_outcome(state) == "publisher"

    def test_approved_string_routes_to_publisher(self):
        state = {"evaluation_result": {"decision": "approved"}}
        assert evaluator_outcome(state) == "publisher"

    def test_needs_revision_routes_to_revise(self):
        state = {"evaluation_result": {"decision": ContentStatus.NEEDS_REVISION}}
        assert evaluator_outcome(state) == "revise_content"

    def test_rejected_routes_to_revise(self):
        """REJECTED also routes to revise (not __end__) — let writer try to fix."""
        state = {"evaluation_result": {"decision": ContentStatus.REJECTED}}
        assert evaluator_outcome(state) == "revise_content"

    def test_no_evaluation_defaults_to_publisher(self):
        """No evaluation_result → degrade to publisher (don't block on missing eval)."""
        state = {}
        assert evaluator_outcome(state) == "publisher"

    def test_needs_revision_force_approves_at_limit(self):
        """revision_count >= MAX → force publisher (prevent infinite loop)."""
        state = {
            "evaluation_result": {"decision": ContentStatus.NEEDS_REVISION},
            "revision_count": 2,
        }
        assert evaluator_outcome(state) == "publisher"

    def test_rejected_force_approves_at_limit(self):
        """REJECTED at revision limit → publisher (not infinite loop)."""
        state = {
            "evaluation_result": {"decision": ContentStatus.REJECTED},
            "revision_count": 2,
        }
        assert evaluator_outcome(state) == "publisher"

    def test_needs_revision_still_revises_below_limit(self):
        """revision_count < MAX → still routes to revise_content."""
        state = {
            "evaluation_result": {"decision": ContentStatus.NEEDS_REVISION},
            "revision_count": 1,
        }
        assert evaluator_outcome(state) == "revise_content"

    def test_needs_revision_revises_at_zero(self):
        """revision_count=0 (first cycle) → still routes to revise_content."""
        state = {
            "evaluation_result": {"decision": ContentStatus.NEEDS_REVISION},
            "revision_count": 0,
        }
        assert evaluator_outcome(state) == "revise_content"

    def test_approved_ignores_revision_count(self):
        """APPROVED always routes to publisher — guard must not interfere.

        The revision_count guard only applies to needs_revision/rejected.
        An approved decision at revision_count >= MAX must still go to
        publisher (not get stuck or re-route to revise_content).
        """
        state = {
            "evaluation_result": {"decision": ContentStatus.APPROVED},
            "revision_count": 99,
        }
        assert evaluator_outcome(state) == "publisher"

    def test_above_limit_force_approves(self):
        """revision_count > MAX (not just ==) → force publisher."""
        state = {
            "evaluation_result": {"decision": ContentStatus.NEEDS_REVISION},
            "revision_count": 5,
        }
        assert evaluator_outcome(state) == "publisher"


class TestShouldContinue:
    """Tests for should_continue conditional edge."""

    def test_routes_to_end_with_error_phase(self):
        """ERROR phase → END."""
        state = {"phase": WorkflowPhase.ERROR}
        result = should_continue(state)
        assert result == "__end__"

    def test_continues_on_non_terminal_error(self):
        """Error string with active phase should not terminate — may retry."""
        state = {"phase": WorkflowPhase.ANALYZING, "error": "Something failed"}
        result = should_continue(state)
        assert result != "__end__"

    def test_routes_to_engagement_after_analyzing_single(self):
        """ANALYZING phase with single mode → engagement."""
        state = {"phase": WorkflowPhase.ANALYZING, "error": None}
        result = should_continue(state)
        assert result == "engagement"

    def test_routes_to_orchestrator_after_analyzing_continuous(self):
        """ANALYZING phase with continuous mode → orchestrator (new cycle)."""
        state = {"phase": WorkflowPhase.ANALYZING, "error": None, "execution_mode": "continuous"}
        result = should_continue(state)
        assert result == "orchestrator"

    def test_continuous_mode_caps_at_max_cycle_count(self):
        """ANALYZING + continuous + cycle_count >= _MAX_CYCLE_COUNT → END.

        Prevents an unbounded analyst→orchestrator→analyst loop in continuous
        mode when the orchestrator keeps routing back to analyst.
        """
        from backend.graph.routers import _MAX_CYCLE_COUNT

        state = {
            "phase": WorkflowPhase.ANALYZING,
            "error": None,
            "execution_mode": "continuous",
            "cycle_count": _MAX_CYCLE_COUNT,
        }
        result = should_continue(state)
        assert result == "__end__"

    def test_continuous_mode_below_cap_still_loops(self):
        """ANALYZING + continuous + cycle_count < _MAX_CYCLE_COUNT → orchestrator."""
        state = {
            "phase": WorkflowPhase.ANALYZING,
            "error": None,
            "execution_mode": "continuous",
            "cycle_count": 2,
        }
        result = should_continue(state)
        assert result == "orchestrator"

    def test_routes_to_end_default(self):
        """Default phase → END."""
        state = {"phase": WorkflowPhase.IDLE}
        result = should_continue(state)
        assert result == "__end__"

    def test_error_phase_takes_priority(self):
        """ERROR phase takes priority over active phase."""
        state = {"phase": WorkflowPhase.ERROR, "error": "Failed"}
        result = should_continue(state)
        assert result == "__end__"


class TestEngagementRouter:
    """Tests for engagement_router conditional edge."""

    def test_single_mode_routes_to_end(self):
        """Single execution mode → END (no infinite loop)."""
        state = {"execution_mode": "single", "phase": WorkflowPhase.ENGAGING}
        assert engagement_router(state) == "__end__"

    def test_continuous_mode_routes_to_orchestrator(self):
        """Continuous execution mode → orchestrator (next cycle)."""
        state = {"execution_mode": "continuous", "phase": WorkflowPhase.ENGAGING}
        assert engagement_router(state) == "orchestrator"

    def test_continuous_mode_caps_at_max_cycle_count(self):
        """Continuous + cycle_count >= _MAX_CYCLE_COUNT → END.

        Prevents an unbounded engagement→orchestrator→engagement loop.
        """
        from backend.graph.routers import _MAX_CYCLE_COUNT

        state = {
            "execution_mode": "continuous",
            "phase": WorkflowPhase.ENGAGING,
            "cycle_count": _MAX_CYCLE_COUNT,
        }
        assert engagement_router(state) == "__end__"

    def test_continuous_mode_below_cap_still_loops(self):
        """Continuous + cycle_count < _MAX_CYCLE_COUNT → orchestrator."""
        state = {
            "execution_mode": "continuous",
            "phase": WorkflowPhase.ENGAGING,
            "cycle_count": 1,
        }
        assert engagement_router(state) == "orchestrator"

    def test_cancelled_routes_to_end(self):
        """CANCELLED phase → END even in continuous mode."""
        state = {"execution_mode": "continuous", "phase": WorkflowPhase.CANCELLED}
        assert engagement_router(state) == "__end__"

    def test_default_is_single(self):
        """No execution_mode specified defaults to single → END."""
        state = {"phase": WorkflowPhase.ENGAGING}
        assert engagement_router(state) == "__end__"

    def test_error_phase_routes_to_end(self):
        """ERROR phase → END even in continuous mode."""
        state = {"execution_mode": "continuous", "phase": WorkflowPhase.ERROR}
        assert engagement_router(state) == "__end__"

    def test_paused_routes_to_end(self):
        """PAUSED phase → END even in continuous mode."""
        state = {"execution_mode": "continuous", "phase": WorkflowPhase.PAUSED}
        assert engagement_router(state) == "__end__"

    def test_error_field_with_active_phase_not_terminal(self):
        """Error field with ENGAGING phase is not terminal — _check_terminal only checks phase."""
        state = {"execution_mode": "continuous", "phase": WorkflowPhase.ENGAGING, "error": "boom"}
        # ENGAGING in continuous mode → orchestrator (error field alone is not terminal)
        assert engagement_router(state) == "orchestrator"


class TestShouldPresentChoice:
    """Tests for should_present_choice conditional edge."""

    def test_single_version_skips_choice_gate(self):
        """Single version → visual_designer (skip choice_gate)."""
        state = {"content_versions": [{"version_id": "v1"}]}
        assert should_present_choice(state) == "visual_designer"

    def test_no_versions_skips_choice_gate(self):
        """No versions → visual_designer (skip choice_gate)."""
        state = {"content_versions": []}
        assert should_present_choice(state) == "visual_designer"

    def test_multiple_versions_enters_choice_gate(self):
        """Multiple versions → choice_gate."""
        state = {"content_versions": [{"version_id": "v1"}, {"version_id": "v2"}]}
        assert should_present_choice(state) == "choice_gate"

    def test_terminal_state_routes_to_end(self):
        """Terminal state → __end__ (not visual_designer)."""
        state = {
            "phase": WorkflowPhase.CANCELLED,
            "content_versions": [{"version_id": "v1"}, {"version_id": "v2"}],
        }
        assert should_present_choice(state) == "__end__"


class TestContentStrategistRouter:
    """Tests for content_strategist_router conditional edge.

    Regression: without the _check_terminal guard, phase=ERROR falls through
    to ripple_gate, which auto-accepts when Ripple data is absent (viral_prob/
    pmf default to 1.0) and overwrites the error phase with `creating` —
    silently swallowing the strategist failure.
    """

    def test_error_routes_to_end(self):
        """phase=ERROR → __end__ (do NOT reach ripple_gate)."""
        state = {"phase": WorkflowPhase.ERROR}
        assert content_strategist_router(state) == "__end__"

    def test_cancelled_routes_to_end(self):
        """CANCELLED → __end__."""
        state = {"phase": WorkflowPhase.CANCELLED}
        assert content_strategist_router(state) == "__end__"

    def test_blocking_mode_routes_to_ripple_gate(self):
        """No ripple_pending (blocking mode) → ripple_gate."""
        state = {}
        assert content_strategist_router(state) == "ripple_gate"

    def test_background_mode_routes_to_ripple_finalize(self):
        """ripple_pending=True → ripple_finalize."""
        state = {"ripple_pending": True}
        assert content_strategist_router(state) == "ripple_finalize"

    def test_error_overrides_ripple_pending(self):
        """phase=ERROR takes priority over ripple_pending (terminal guard first)."""
        state = {"phase": WorkflowPhase.ERROR, "ripple_pending": True}
        assert content_strategist_router(state) == "__end__"


class TestRippleGateRouter:
    """Tests for ripple_gate_router conditional edge."""

    def test_accept_routes_to_copywriter(self):
        """Accept decision → copywriter."""
        state = {"ripple_decision": {"action": "accept"}}
        assert ripple_gate_router(state) == "copywriter"

    def test_reangle_trend_routes_to_strategist(self):
        """Reangle in trend mode → content_strategist."""
        state = {"ripple_decision": {"action": "reangle"}, "workflow_mode": "trend"}
        assert ripple_gate_router(state) == "content_strategist"

    def test_reangle_brief_routes_to_brief_analyzer(self):
        """Reangle in brief mode → brief_analyzer."""
        state = {"ripple_decision": {"action": "reangle"}, "workflow_mode": "brief"}
        assert ripple_gate_router(state) == "brief_analyzer"

    def test_retopic_routes_to_trend_scout(self):
        """Retopic → trend_scout (both modes)."""
        state = {"ripple_decision": {"action": "retopic"}}
        assert ripple_gate_router(state) == "trend_scout"

    def test_default_accept(self):
        """No decision → default accept → copywriter."""
        state = {}
        assert ripple_gate_router(state) == "copywriter"

    def test_cancelled_routes_to_end(self):
        """CANCELLED → __end__."""
        state = {"phase": WorkflowPhase.CANCELLED}
        assert ripple_gate_router(state) == "__end__"


class TestBloggerGateRouter:
    """Tests for blogger_gate_router conditional edge."""

    def test_brief_mode_routes_to_copywriter(self):
        """Brief mode → copywriter."""
        state = {"workflow_mode": "brief"}
        assert blogger_gate_router(state) == "copywriter"

    def test_trend_mode_without_blogger_notes_routes_to_draft_gate(self):
        """Trend mode without selected blogger notes → draft_gate."""
        state = {"workflow_mode": "trend"}
        assert blogger_gate_router(state) == "draft_gate"

    def test_trend_mode_with_selected_blogger_notes_routes_to_copywriter(self):
        """Trend mode selected blogger notes → copywriter for style candidates."""
        state = {
            "workflow_mode": "trend",
            "selected_blogger": {"user_id": "u1"},
            "blogger_notes": [{"title": "note"}],
        }
        assert blogger_gate_router(state) == "copywriter"

    def test_default_is_trend(self):
        """No workflow_mode → draft_gate (trend default)."""
        state = {}
        assert blogger_gate_router(state) == "draft_gate"

    def test_cancelled_routes_to_end(self):
        """CANCELLED → __end__."""
        state = {"phase": WorkflowPhase.CANCELLED}
        assert blogger_gate_router(state) == "__end__"


class TestDraftGateRouter:
    """Tests for draft_gate_router conditional edge."""

    def test_selected_blogger_routes_to_shooting_planner(self):
        """Selected blogger → shooting_planner."""
        state = {"selected_blogger": {"user_id": "u1"}}
        assert draft_gate_router(state) == "shooting_planner"

    def test_blogger_skipped_routes_to_shooting_planner(self):
        """Blogger skipped → shooting_planner."""
        state = {"blogger_skipped": True}
        assert draft_gate_router(state) == "shooting_planner"

    def test_brief_mode_routes_to_shooting_planner(self):
        """Brief mode → shooting_planner (skip blogger loop)."""
        state = {"workflow_mode": "brief"}
        assert draft_gate_router(state) == "shooting_planner"

    def test_trend_no_blogger_routes_to_viral_matcher(self):
        """Trend mode without blogger → viral_matcher."""
        state = {"workflow_mode": "trend"}
        assert draft_gate_router(state) == "viral_matcher"

    def test_default_routes_to_viral_matcher(self):
        """Default → viral_matcher."""
        state = {}
        assert draft_gate_router(state) == "viral_matcher"


class TestCopywriterRouter:
    """Tests for copywriter_router."""

    def test_routes_to_draft_gate(self):
        """Normal → draft_gate."""
        state = {"phase": WorkflowPhase.CREATING}
        assert copywriter_router(state) == "draft_gate"

    def test_routes_to_choice_gate_with_multi_style_versions(self):
        """Multi-style variants → choice_gate for style selection."""
        state = {
            "phase": WorkflowPhase.CREATING,
            "content_versions": [{"version_id": "style_a"}, {"version_id": "style_b"}],
        }
        assert copywriter_router(state) == "choice_gate"

    def test_cancelled_routes_to_end(self):
        """CANCELLED → __end__."""
        state = {"phase": WorkflowPhase.CANCELLED}
        assert copywriter_router(state) == "__end__"


class TestVisualDesignerRouter:
    """Tests for visual_designer_router."""

    def test_routes_to_review_gate(self):
        """Normal → review_gate."""
        state = {"phase": WorkflowPhase.CREATING}
        assert visual_designer_router(state) == "review_gate"

    def test_cancelled_routes_to_end(self):
        """CANCELLED → __end__."""
        state = {"phase": WorkflowPhase.CANCELLED}
        assert visual_designer_router(state) == "__end__"


class TestContentAnalyzerRouter:
    """Tests for content_analyzer_router."""

    def test_multiple_versions_routes_to_choice_gate(self):
        """Multiple versions → choice_gate (style selection)."""
        state = {"content_versions": [{"id": "v1"}, {"id": "v2"}]}
        assert content_analyzer_router(state) == "choice_gate"

    def test_single_version_routes_to_version_generator(self):
        """Single version → version_generator."""
        state = {"content_versions": [{"id": "v1"}]}
        assert content_analyzer_router(state) == "version_generator"

    def test_no_versions_routes_to_version_generator(self):
        """No versions → version_generator."""
        state = {"content_versions": []}
        assert content_analyzer_router(state) == "version_generator"

    def test_cancelled_routes_to_end(self):
        """CANCELLED → __end__."""
        state = {"phase": WorkflowPhase.CANCELLED}
        assert content_analyzer_router(state) == "__end__"


class TestChoiceOutcome:
    """Tests for choice_outcome router."""

    def test_style_selected_routes_to_version_generator(self):
        """Style just selected → version_generator (A/B/C generation)."""
        state = {"style_selected": True}
        assert choice_outcome(state) == "version_generator"

    def test_no_style_selected_routes_to_visual_designer(self):
        """No style_selected → visual_designer (version was selected)."""
        state = {}
        assert choice_outcome(state) == "visual_designer"


class TestShootingPlannerRouter:
    """Tests for shooting_planner_router."""

    def test_default_routes_to_content_analyzer(self):
        """Default → content_analyzer (optimization)."""
        state = {}
        assert shooting_planner_router(state) == "content_analyzer"

    def test_skip_optimization_routes_to_visual_designer(self):
        """skip_optimization → visual_designer."""
        state = {"skip_optimization": True}
        assert shooting_planner_router(state) == "visual_designer"

    def test_cancelled_routes_to_end(self):
        """CANCELLED → __end__."""
        state = {"phase": WorkflowPhase.CANCELLED}
        assert shooting_planner_router(state) == "__end__"
