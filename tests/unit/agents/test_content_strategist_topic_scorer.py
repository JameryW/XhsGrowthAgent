"""Tests for ContentStrategistAgent topic_scorer integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_strategist import ContentStrategistAgent
from backend.state.schema import WorkflowPhase


class TestContentStrategistTopicScorer:
    """topic_scorer 死代码修复：strategist 生成前对候选话题打分。"""

    @pytest.fixture
    def agent(self):
        return ContentStrategistAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_scores_injected_into_prompt(self, agent, mock_store):
        """trend_data 含 hot_topics 时，topic_scorer 被调用且评分进入 system prompt。"""
        mock_state = {
            "account_id": "test_account",
            "niche": "美食",
            "trend_data": {"hot_topics": [{"topic": "探店"}]},
        }

        captured_prompts: list[str] = []

        async def fake_ainvoke(messages):
            captured_prompts.append(messages[0].content)
            resp = MagicMock()
            resp.content = '{"selected_topic": "探店"}'
            return resp

        mock_model = MagicMock()
        mock_model.ainvoke = fake_ainvoke
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(
            return_value={
                "heat_score": 82,
                "growth_trend": "爆发期",
                "competition_level": "中等",
                "recommendation": "强烈推荐",
            }
        )

        with (
            patch("backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock) as mp,
            patch("backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock) as mpmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mp.return_value = {"ripple_prediction": None}
            mpmf.return_value = {"ripple_pmf": None}
            await agent.execute(mock_state, store=mock_store)

        scorer.ainvoke.assert_awaited()
        assert any("话题热度评分" in p for p in captured_prompts)
        assert any("82" in p for p in captured_prompts)

    @pytest.mark.asyncio
    async def test_scorer_failure_does_not_block(self, agent, mock_store):
        """topic_scorer 抛异常时不阻断主流程。"""
        mock_state = {
            "account_id": "test_account",
            "niche": "美食",
            "trend_data": {"hot_topics": [{"topic": "探店"}]},
        }

        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "探店"}'
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(side_effect=RuntimeError("XHS down"))

        with (
            patch("backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock) as mp,
            patch("backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock) as mpmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mp.return_value = {"ripple_prediction": None}
            mpmf.return_value = {"ripple_pmf": None}
            result = await agent.execute(mock_state, store=mock_store)

        assert result["phase"] == WorkflowPhase.PLANNING
        assert result["content_plan"]["selected_topic"] == "探店"

    @pytest.mark.asyncio
    async def test_empty_trend_data_skips_scoring(self, agent, mock_store):
        """无 trend_data 时跳过 topic_scorer 调用。"""
        mock_state = {"account_id": "test_account", "niche": "美食", "trend_data": {}}

        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "x"}'
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch("backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock) as mp,
            patch("backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock) as mpmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mp.return_value = {"ripple_prediction": None}
            mpmf.return_value = {"ripple_pmf": None}
            await agent.execute(mock_state, store=mock_store)

        scorer.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_drift_triggers_regeneration(self, agent, mock_store):
        """selected_topic 偏离候选集时触发一次重生成，最终落回候选集。"""
        mock_state = {
            "account_id": "test_account",
            "niche": "美食",
            "trend_data": {"hot_topics": [{"topic": "探店"}]},
        }

        # 第一次输出偏离话题，第二次落回候选集
        responses = [
            MagicMock(content='{"selected_topic": "随便编的"}'),
            MagicMock(content='{"selected_topic": "探店"}'),
        ]
        call_count = {"n": 0}

        async def fake_ainvoke(messages):
            r = responses[min(call_count["n"], len(responses) - 1)]
            call_count["n"] += 1
            return r

        mock_model = MagicMock()
        mock_model.ainvoke = fake_ainvoke
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch("backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock) as mp,
            patch("backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock) as mpmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mp.return_value = {"ripple_prediction": None}
            mpmf.return_value = {"ripple_pmf": None}
            result = await agent.execute(mock_state, store=mock_store)

        assert call_count["n"] == 2  # 初版 + 重生成
        assert result["content_plan"]["selected_topic"] == "探店"
        assert result["content_plan"].get("topic_revised") is True
