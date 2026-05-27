"""Unit tests for OrchestratorAgent."""

from unittest.mock import AsyncMock
import pytest

from backend.agents.orchestrator import OrchestratorAgent
from backend.state.schema import XHSGrowthState, WorkflowPhase


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
    async def test_routes_to_engaging_with_pending_actions(self, agent, mock_store):
        """Routes to ENGAGING when pending engagement actions exist."""
        state = {
            "engagement_actions": [{"action": "reply", "comment_id": "123"}],
            "content_plan": {},
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.ENGAGING

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
        """Routes to SCOUTING for default case."""
        state = {
            "engagement_actions": [],
            "analytics": {},
            "error": None,
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.SCOUTING

    @pytest.mark.asyncio
    async def test_prioritizes_engagement_over_analytics(self, agent, mock_store):
        """Engagement actions take priority over analytics."""
        state = {
            "engagement_actions": [{"action": "reply"}],
            "analytics": {"views": 1000},
        }

        result = await agent.execute(state, store=mock_store)

        assert result["phase"] == WorkflowPhase.ENGAGING

    @pytest.mark.asyncio
    async def test_has_content_plan_skips_engagement(self, agent, mock_store):
        """Skip engagement route if content_plan exists."""
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