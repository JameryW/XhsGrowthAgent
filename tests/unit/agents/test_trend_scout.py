"""Unit tests for TrendScoutAgent."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.trend_scout import TrendScoutAgent
from backend.state.schema import WorkflowPhase


class TestTrendScoutAgent:
    """Tests for TrendScoutAgent trend discovery."""

    @pytest.fixture
    def agent(self):
        """Create trend scout instance."""
        return TrendScoutAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_state(self):
        """Standard mock state."""
        return {
            "account_id": "test_account",
            "phase": WorkflowPhase.IDLE,
        }

    @pytest.mark.asyncio
    async def test_execute_returns_trend_data(self, agent, mock_state, mock_store):
        """Execute returns trend_data in result."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "trending_topics": ["美食探店", "OOTD穿搭"],
  "opportunities": ["健康饮食", "可持续生活"],
  "recommendations": ["测试话题"]
}
```"""

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=mock_store)

        assert "trend_data" in result
        assert result["phase"] == WorkflowPhase.SCOUTING

    @pytest.mark.asyncio
    async def test_execute_recalls_memory(self, agent, mock_state, mock_store):
        """Execute recalls memory for historical insights."""
        mock_item = MagicMock()
        mock_item.value = {"insight": "美食话题表现好"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=mock_store)

        # Memory was recalled
        mock_store.asearch.assert_called_once()
        assert "trend_data" in result

    @pytest.mark.asyncio
    async def test_execute_handles_invalid_json(self, agent, mock_state, mock_store):
        """Execute handles invalid LLM response."""
        mock_response = MagicMock()
        mock_response.content = "Not valid JSON"

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=mock_store)

        # Should still return trend_data with raw_content
        assert "trend_data" in result
        assert result["trend_data"].get("raw_content") == "Not valid JSON"

    @pytest.mark.asyncio
    async def test_execute_with_account_id(self, agent, mock_store):
        """Execute uses account_id from state."""
        mock_state = {"account_id": "custom_account"}
        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=mock_store)

        assert result["phase"] == WorkflowPhase.SCOUTING

    @pytest.mark.asyncio
    async def test_execute_stores_insight(self, agent, mock_state, mock_store):
        """Execute stores trend insight to memory after scouting."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "trending_topics": [{"topic": "美食探店"}, {"topic": "OOTD穿搭"}],
  "opportunities": ["健康饮食"],
  "recommendations": ["测试话题"]
}
```"""

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=mock_store)

        assert "trend_data" in result
        # aput should have been called to store insight
        mock_store.aput.assert_called_once()
        call_args = mock_store.aput.call_args
        assert call_args.args[0] == ("accounts", "test_account", "performance_insights")

    @pytest.mark.asyncio
    async def test_execute_stores_insight_no_store(self, agent, mock_state):
        """Execute skips insight storage when store is None."""
        mock_response = MagicMock()
        mock_response.content = '{"trending_topics": []}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        result = await agent.execute(mock_state, store=None)

        assert "trend_data" in result

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "trend_scout"
        assert agent.prompt_file == "trend_scout.yaml"
        # SCOUTING task type for trend discovery