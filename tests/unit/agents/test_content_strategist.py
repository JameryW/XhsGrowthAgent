"""Unit tests for ContentStrategistAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_strategist import ContentStrategistAgent
from backend.services.ripple_service import RippleTimeoutError
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
        """Ripple prediction gracefully skipped on error — uses fallback data."""
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

        # Should have fallback ripple_prediction with zeros
        assert result["content_plan"]["ripple_prediction"]["estimated_reach"] == 0
        assert result["content_plan"]["ripple_prediction"]["viral_probability"] == 0.0
        # Generic error (not timeout) sets ripple_reason to "unreachable"
        assert result.get("ripple_reason") == "unreachable"

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

    @pytest.mark.asyncio
    async def test_ripple_timeout_saves_job_id(self, agent, mock_state, mock_store):
        """RippleTimeoutError 时保存 job_id 到结果"""
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "美食探店"}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        async def _raise_timeout(*args, **kwargs):
            raise RippleTimeoutError("job-timeout-123", 900.0)

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch.object(agent, "_ripple_cancel", new_callable=AsyncMock) as mock_cancel,
        ):
            # predict_spread raises RippleTimeoutError which propagates through _ripple_predict
            # We need to make _ripple_predict raise RippleTimeoutError
            mock_pred.side_effect = _raise_timeout
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(mock_state, store=mock_store)

        # job_id 应被保存
        assert result.get("ripple_job_id") == "job-timeout-123"
        assert result.get("ripple_reason") == "timeout"
        # cancel 应被调用
        mock_cancel.assert_called_once_with("job-timeout-123")

    @pytest.mark.asyncio
    async def test_ripple_cancel_called_on_timeout(self, agent):
        """_ripple_cancel 调用 RippleService.cancel_simulation"""
        mock_service = MagicMock()
        mock_service.cancel_simulation = AsyncMock(
            return_value={"cancelled": True, "job_id": "job-cancel-456", "status": "cancelled"}
        )

        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            mock_cls.get_instance.return_value = mock_service
            result = await agent._ripple_cancel("job-cancel-456")

        assert result["cancelled"] is True
        mock_service.cancel_simulation.assert_called_once_with("job-cancel-456")

    @pytest.mark.asyncio
    async def test_ripple_cancel_handles_empty_job_id(self, agent):
        """_ripple_cancel 对空 job_id 返回 None"""
        result = await agent._ripple_cancel("")
        assert result is None

    @pytest.mark.asyncio
    async def test_ripple_cancel_handles_exception(self, agent):
        """_ripple_cancel 对异常做优雅降级"""
        mock_service = MagicMock()
        mock_service.cancel_simulation = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            mock_cls.get_instance.return_value = mock_service
            result = await agent._ripple_cancel("job-err")

        assert result is None
