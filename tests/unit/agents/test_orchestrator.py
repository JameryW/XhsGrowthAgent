"""Unit tests for OrchestratorAgent."""

from unittest.mock import AsyncMock

import pytest

from backend.agents.orchestrator import OrchestratorAgent
from backend.state.schema import WorkflowPhase


class TestOrchestratorAgent:
    """Tests for OrchestratorAgent routing logic."""

    @pytest.fixture
    def agent(self):
        """Create orchestrator instance."""
        return OrchestratorAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_ignores_legacy_pending_actions(self, agent, mock_store):
        """Historical engagement actions must not activate automation."""
        state = {
            "engagement_actions": [{"action": "reply", "comment_id": "123"}],
            "content_plan": {},
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.SCOUTING

    @pytest.mark.asyncio
    async def test_routes_to_analyzing_with_empty_insights(self, agent, mock_store):
        """Routes to ANALYZING when analytics exist without insights."""
        state = {
            "analytics": {"views": 1000, "engagement": 50},
            "engagement_actions": [],
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.ANALYZING

    @pytest.mark.asyncio
    async def test_routes_to_error_after_max_retries(self, agent, mock_store):
        """Routes to ERROR after 3 retries."""
        state = {
            "error": "Something failed",
            "retry_count": 3,
            "engagement_actions": [],
            "analytics": {},
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.ERROR

    @pytest.mark.asyncio
    async def test_routes_to_scouting_on_error_below_max_retries(self, agent, mock_store):
        """Clears error and routes to SCOUTING below max retries."""
        state = {
            "error": "Something failed",
            "retry_count": 1,
            "engagement_actions": [],
            "analytics": {},
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.SCOUTING
        assert result["error"] is None
        assert result["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_routes_to_scouting_by_default(self, agent, mock_store):
        """Routes to SCOUTING for default case (trend mode)."""
        state = {
            "engagement_actions": [],
            "analytics": {},
            "error": None,
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.SCOUTING

    @pytest.mark.asyncio
    async def test_routes_to_briefing_in_brief_mode(self, agent, mock_store):
        """Routes to BRIEFING when workflow_mode is 'brief'."""
        state = {
            "engagement_actions": [],
            "analytics": {},
            "error": None,
            "workflow_mode": "brief",
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.BRIEFING

    @pytest.mark.asyncio
    async def test_analytics_still_takes_priority_over_legacy_actions(self, agent, mock_store):
        """Historical interaction actions do not override analytics routing."""
        state = {
            "engagement_actions": [{"action": "reply"}],
            "analytics": {"views": 1000},
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.ANALYZING

    @pytest.mark.asyncio
    async def test_content_plan_keeps_legacy_actions_inert(self, agent, mock_store):
        """A content plan must not activate a removed engagement route."""
        state = {
            "engagement_actions": [{"action": "reply"}],
            "content_plan": {"selected_topic": "test"},
        }

        result = await agent.execute(state, store=mock_store)

        # Should not be engaging, go to default scouting
        assert result["phase"] == WorkflowPhase.SCOUTING

    @pytest.mark.asyncio
    async def test_analytics_with_insights_skips_analyzing(self, agent, mock_store):
        """Skip analyzing route if insights already exist."""
        state = {
            "analytics": {"views": 1000, "insights": ["insight1"]},
            "engagement_actions": [],
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.SCOUTING

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "orchestrator"
        assert agent.prompt_file == "orchestrator.yaml"
        # ROUTING task type for orchestration decisions
