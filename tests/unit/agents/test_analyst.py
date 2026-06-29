"""Unit tests for AnalystAgent."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.analyst import AnalystAgent
from backend.state.schema import WorkflowPhase


class TestAnalystAgent:
    """Tests for AnalystAgent analytics generation."""

    @pytest.fixture
    def agent(self):
        """Create analyst instance."""
        return AnalystAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        store.aput = AsyncMock()
        return store

    @pytest.fixture
    def mock_state(self):
        """Mock state with publish result."""
        return {
            "account_id": "test_account",
            "phase": WorkflowPhase.PUBLISHING,
            "publish_result": {
                "post_id": "123",
                "views": 1000,
                "likes": 50,
                "engagement_rate": 0.05,
            },
        }

    @pytest.mark.asyncio
    async def test_execute_returns_analytics(self, agent, mock_state, mock_store):
        """Execute returns analytics in result."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "insights": ["美食内容互动率高", "周末发布效果好"],
  "recommendations": ["增加美食内容比例"],
  "metrics": {"engagement_rate": 0.05}
}
```"""

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        assert "analytics" in result
        assert result["phase"] == WorkflowPhase.ANALYZING
        assert "insights" in result["analytics"]

    @pytest.mark.asyncio
    async def test_execute_recalls_content_history(self, agent, mock_state, mock_store):
        """Execute recalls content history."""
        mock_item = MagicMock()
        mock_item.value = {"title": "Past Post", "engagement": 80}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        mock_response = MagicMock()
        mock_response.content = '{"insights": []}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            await agent.execute(mock_state, store=mock_store)

        # Memory recall was called
        mock_store.asearch.assert_called()

    @pytest.mark.asyncio
    async def test_execute_stores_insights(self, agent, mock_state, mock_store):
        """Execute stores insights to memory."""
        mock_response = MagicMock()
        mock_response.content = '{"insights": ["美食效果好"], "recommendations": []}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            await agent.execute(mock_state, store=mock_store)

        # Insights stored
        assert mock_store.aput.called

    @pytest.mark.asyncio
    async def test_ripple_report_returns_report(self, agent, mock_state, mock_store):
        """_ripple_report returns report when job_id exists."""
        state_with_ripple = {
            **mock_state,
            "content_plan": {"ripple_prediction": {"ripple_job_id": "job_123"}},
        }

        with patch("backend.tools.ripple.integration.get_report") as mock_get_report:
            mock_get_report.return_value = {
                "rounds": [{"content": "Report text"}],
            }

            report = await agent._ripple_report(state_with_ripple)

        assert report == "Report text"

    @pytest.mark.asyncio
    async def test_ripple_report_none_when_no_job_id(self, agent):
        """_ripple_report returns None when no job_id."""
        state = {"content_plan": {}}
        result = await agent._ripple_report(state)
        assert result is None

    @pytest.mark.asyncio
    async def test_ripple_report_handles_error(self, agent):
        """_ripple_report handles errors gracefully."""
        state = {"content_plan": {"ripple_prediction": {"ripple_job_id": "job_123"}}}

        with patch("backend.tools.ripple.integration.get_report") as mock_get_report:
            mock_get_report.side_effect = Exception("Ripple error")

            result = await agent._ripple_report(state)

        assert result is None

    def test_compare_prediction_vs_actual(self, agent):
        """_compare_prediction_vs_actual returns comparison dict."""
        prediction = {"estimated_reach": 5000, "viral_probability": 0.3}
        actual = {"engagement_rate": 0.05}

        result = agent._compare_prediction_vs_actual(prediction, actual)

        assert result["predicted_reach"] == 5000
        assert result["predicted_viral_prob"] == 0.3
        assert result["actual_engagement_rate"] == 0.05

    def test_compare_prediction_vs_actual_none_prediction(self, agent):
        """_compare_prediction_vs_actual handles None prediction."""
        result = agent._compare_prediction_vs_actual(None, {"rate": 0.05})
        assert result == {}

    @pytest.mark.asyncio
    async def test_execute_with_ripple_report(self, agent, mock_state, mock_store):
        """Execute includes ripple comparison when report exists."""
        state_with_ripple = {
            **mock_state,
            "content_plan": {
                "ripple_prediction": {"ripple_job_id": "job_123", "estimated_reach": 5000}
            },
        }

        mock_response = MagicMock()
        mock_response.content = '{"insights": [], "recommendations": []}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            with patch.object(agent, "_ripple_report", AsyncMock(return_value="Report")):
                result = await agent.execute(state_with_ripple, store=mock_store)

        assert "ripple_comparison" in result["analytics"]

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "analyst"
        assert agent.prompt_file == "analyst.yaml"

    @pytest.mark.asyncio
    async def test_ripple_report_timeout_returns_none(self, agent):
        """_ripple_report 超时时返回 None"""
        state = {"content_plan": {"ripple_prediction": {"ripple_job_id": "job-timeout"}}}

        # asyncio.wait_for evaluates get_report(job_id) before invoking, so the
        # mock coroutine must be closed to avoid a 'never awaited' leak.
        def _fake_wait_for(coro, timeout, *args, **kwargs):
            coro.close()
            raise TimeoutError()

        with (
            patch("backend.tools.ripple.integration.get_report", new_callable=AsyncMock),
            patch.object(agent, "_ripple_cancel", new_callable=AsyncMock),
            patch("asyncio.wait_for", side_effect=_fake_wait_for),
        ):
            result = await agent._ripple_report(state)

        assert result is None

    @pytest.mark.asyncio
    async def test_ripple_cancel_calls_service(self, agent):
        """_ripple_cancel 调用 RippleService.cancel_simulation"""
        mock_service = MagicMock()
        mock_service.cancel_simulation = AsyncMock(
            return_value={"cancelled": True, "job_id": "job-cancel", "status": "cancelled"}
        )

        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            mock_cls.get_instance.return_value = mock_service
            await agent._ripple_cancel("job-cancel")

        mock_service.cancel_simulation.assert_called_once_with("job-cancel")

    @pytest.mark.asyncio
    async def test_ripple_cancel_handles_empty_job_id(self, agent):
        """_ripple_cancel 对空 job_id 不调用服务"""
        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            await agent._ripple_cancel("")

        mock_cls.get_instance.assert_not_called()

    @pytest.mark.asyncio
    async def test_ripple_cancel_handles_exception(self, agent):
        """_ripple_cancel 对异常做优雅降级（不抛出）"""
        mock_service = MagicMock()
        mock_service.cancel_simulation = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            mock_cls.get_instance.return_value = mock_service
            # 不应抛出异常
            await agent._ripple_cancel("job-err")
