"""Unit tests for graph routers."""

import pytest

from backend.graph.routers import (
    orchestrator_router,
    should_plan,
    review_outcome,
    should_continue,
)
from backend.state.enums import WorkflowPhase, ContentStatus
from backend.state.schema import XHSGrowthState


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


class TestReviewOutcome:
    """Tests for review_outcome conditional edge."""

    def test_routes_to_publisher_for_approved_enum(self):
        """APPROVED enum → publisher."""
        state = {"human_feedback": {"decision": ContentStatus.APPROVED}}
        result = review_outcome(state)
        assert result == "publisher"

    def test_routes_to_publisher_for_approved_string(self):
        """approved string → publisher."""
        state = {"human_feedback": {"decision": "approved"}}
        result = review_outcome(state)
        assert result == "publisher"

    def test_routes_to_revise_for_needs_revision(self):
        """NEEDS_REVISION → revise_content."""
        state = {"human_feedback": {"decision": ContentStatus.NEEDS_REVISION}}
        result = review_outcome(state)
        assert result == "revise_content"

    def test_routes_to_revise_for_rejected(self):
        """REJECTED → revise_content."""
        state = {"human_feedback": {"decision": ContentStatus.REJECTED}}
        result = review_outcome(state)
        assert result == "revise_content"

    def test_routes_to_revise_default(self):
        """No feedback → revise_content (safe default)."""
        state = {}
        result = review_outcome(state)
        assert result == "revise_content"


class TestShouldContinue:
    """Tests for should_continue conditional edge."""

    def test_routes_to_end_with_error(self):
        """Error exists → END."""
        state = {"error": "Something failed"}
        result = should_continue(state)
        assert result == "__end__"

    def test_routes_to_orchestrator_after_analyzing(self):
        """ANALYZING phase → orchestrator (new cycle)."""
        state = {"phase": WorkflowPhase.ANALYZING, "error": None}
        result = should_continue(state)
        assert result == "orchestrator"

    def test_routes_to_end_default(self):
        """Default phase → END."""
        state = {"phase": WorkflowPhase.IDLE}
        result = should_continue(state)
        assert result == "__end__"

    def test_error_takes_priority(self):
        """Error takes priority over phase."""
        state = {"phase": WorkflowPhase.ANALYZING, "error": "Failed"}
        result = should_continue(state)
        assert result == "__end__"