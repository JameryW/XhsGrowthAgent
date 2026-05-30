"""Unit tests for ContentStrategistAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_strategist import ContentStrategistAgent
from backend.state.schema import WorkflowPhase


class TestContentStrategistAgent:
    """Tests for ContentStrategistAgent strategy generation."""

    @pytest.fixture
    def agent(self):
        """Create content strategist instance."""
        return ContentStrategistAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_state(self):
        """Standard mock state with trend_data."""
        return {
            "account_id": "test_account",
            "phase": WorkflowPhase.SCOUTING,
            "trend_data": {
                "trending_topics": ["美食探店"],
                "recommendations": ["健康饮食"],
            },
        }

    @pytest.mark.asyncio
    async def test_execute_returns_content_plan(self, agent, mock_state, mock_store):
        """Execute returns content_plan in result."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "selected_topic": "美食探店",
  "content_angle": "探店攻略",
  "target_audience": "美食爱好者",
  "content_type": "图文笔记"
}
```"""

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(mock_state, store=mock_store)

        assert "content_plan" in result
        assert result["phase"] == WorkflowPhase.PLANNING
        assert result["content_plan"]["selected_topic"] == "美食探店"

    @pytest.mark.asyncio
    async def test_execute_recalls_memory(self, agent, mock_state, mock_store):
        """Execute recalls historical performance insights."""
        mock_item = MagicMock()
        mock_item.value = {"insight": "美食话题互动率高"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "test"}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            await agent.execute(mock_state, store=mock_store)

        mock_store.asearch.assert_called()

    @pytest.mark.asyncio
    async def test_ripple_predict_returns_prediction(self, agent, mock_state, mock_store):
        """_ripple_predict returns prediction when topic exists."""
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "美食探店"}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_predict,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
        ):
            mock_predict.return_value = {
                "ripple_job_id": "test-job",
                "ripple_prediction": {"estimated_reach": 5000, "viral_probability": 0.3},
            }
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(mock_state, store=mock_store)

        assert result["content_plan"]["ripple_prediction"]["estimated_reach"] == 5000
        assert result["content_plan"]["ripple_prediction"]["ripple_job_id"] == "test-job"

    @pytest.mark.asyncio
    async def test_ripple_predict_skipped_on_error(self, agent, mock_state, mock_store):
        """Ripple prediction gracefully skipped on error."""
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "美食探店"}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_predict,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
        ):
            mock_predict.side_effect = Exception("Ripple unavailable")
            mock_pmf.side_effect = Exception("Ripple unavailable")

            result = await agent.execute(mock_state, store=mock_store)

        # Should not have ripple_prediction
        assert "ripple_prediction" not in result.get("content_plan", {})

    @pytest.mark.asyncio
    async def test_ripple_predict_skipped_no_topic(self, agent, mock_store):
        """Ripple prediction skipped when no topic."""
        mock_state = {"account_id": "test", "trend_data": {}}
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": ""}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(mock_state, store=mock_store)

        assert result["content_plan"]["selected_topic"] == ""

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "content_strategist"
        assert agent.prompt_file == "content_strategist.yaml"
