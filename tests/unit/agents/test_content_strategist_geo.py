"""ContentStrategistAgent × GEO-CiteScore (ledger #37) prompt wiring.

The agent must surface the GEO blank-ness only when ``topic_scorer`` returned
it (i.e. ``XHS_GEO_SCORING`` is on), and it must only ever break ties: a topic
with a better collect forecast still outranks a blanker one, because
collect-first remains the objective.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_strategist import ContentStrategistAgent

SCORER = "backend.tools.analysis.topic_scorer.topic_scorer"
RIPPLE_PREDICT = "backend.tools.ripple.integration.predict_spread"
RIPPLE_PMF = "backend.tools.ripple.integration.validate_pmf"


class TestContentStrategistGeo:
    @pytest.fixture
    def agent(self):
        return ContentStrategistAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    async def _run(
        self,
        agent,
        mock_store,
        state: dict[str, Any],
        scorer_result,
    ) -> list[str]:
        captured: list[str] = []

        async def fake_ainvoke(messages):
            captured.append(messages[0].content)
            return MagicMock(content='{"selected_topic": "探店"}')

        model = MagicMock()
        model.ainvoke = fake_ainvoke
        agent._model = model

        scorer = AsyncMock()
        if callable(scorer_result):
            scorer.ainvoke = scorer_result
        else:
            scorer.ainvoke = AsyncMock(return_value=scorer_result)

        with (
            patch(RIPPLE_PREDICT, new_callable=AsyncMock) as predict,
            patch(RIPPLE_PMF, new_callable=AsyncMock) as pmf,
            patch(SCORER, scorer),
        ):
            predict.return_value = {"ripple_prediction": None}
            pmf.return_value = {"ripple_pmf": None}
            await agent.execute(state, store=mock_store)
        return captured

    @pytest.mark.asyncio
    async def test_geo_note_is_surfaced_with_its_keyword(
        self, agent, mock_store, xhs_read_grant
    ) -> None:
        state = {
            "account_id": "test_account",
            "niche": "美食",
            "trend_data": {"hot_topics": [{"topic": "探店"}]},
        }
        prompts = await self._run(
            agent,
            mock_store,
            state,
            {
                "heat_score": 70,
                "geo": {
                    "best_keyword": "探店人均多少钱",
                    "best_score": 0.812345,
                    "recommendation": "空白明显",
                },
            },
        )

        prompt = next(p for p in prompts if "话题热度评分" in p)
        assert "GEO空白 0.81（探店人均多少钱）" in prompt

    @pytest.mark.asyncio
    async def test_no_geo_block_keeps_the_prompt_unchanged(
        self, agent, mock_store, xhs_read_grant
    ) -> None:
        state = {
            "account_id": "test_account",
            "niche": "美食",
            "trend_data": {"hot_topics": [{"topic": "探店"}]},
        }
        prompts = await self._run(
            agent, mock_store, state, {"heat_score": 70, "recommendation": "推荐"}
        )

        prompt = next(p for p in prompts if "话题热度评分" in p)
        assert "GEO空白" not in prompt
        assert "探店: 热度 70" in prompt

    @pytest.mark.asyncio
    async def test_geo_only_breaks_ties_between_equal_candidates(
        self, agent, mock_store, xhs_read_grant
    ) -> None:
        state = {
            "account_id": "test_account",
            "niche": "美食",
            "trend_data": {"hot_topics": [{"topic": "低空白"}, {"topic": "高空白"}]},
        }

        async def fake_scorer(payload):
            blank = payload["topic"] == "高空白"
            return {
                "heat_score": 70,
                "predicted_collect": 40,
                "geo": {"best_keyword": payload["topic"], "best_score": 0.9 if blank else 0.2},
            }

        prompts = await self._run(agent, mock_store, state, fake_scorer)

        prompt = next(p for p in prompts if "话题热度评分" in p)
        assert prompt.index("高空白") < prompt.index("低空白")
        assert "【主推】高空白" in prompt

    @pytest.mark.asyncio
    async def test_collect_forecast_still_outranks_a_blanker_topic(
        self, agent, mock_store, xhs_read_grant
    ) -> None:
        state = {
            "account_id": "test_account",
            "niche": "美食",
            "trend_data": {"hot_topics": [{"topic": "高收藏低空白"}, {"topic": "低收藏高空白"}]},
        }

        async def fake_scorer(payload):
            high_collect = payload["topic"] == "高收藏低空白"
            return {
                "heat_score": 70,
                "predicted_collect": 120 if high_collect else 3,
                "geo": {
                    "best_keyword": payload["topic"],
                    "best_score": 0.1 if high_collect else 0.9,
                },
            }

        prompts = await self._run(agent, mock_store, state, fake_scorer)

        prompt = next(p for p in prompts if "话题热度评分" in p)
        assert "【主推】高收藏低空白" in prompt
        assert prompt.index("高收藏低空白") < prompt.index("低收藏高空白")

    @pytest.mark.asyncio
    async def test_malformed_geo_block_is_ignored(self, agent, mock_store, xhs_read_grant) -> None:
        state = {
            "account_id": "test_account",
            "niche": "美食",
            "trend_data": {"hot_topics": [{"topic": "探店"}]},
        }
        prompts = await self._run(
            agent,
            mock_store,
            state,
            {"heat_score": 70, "geo": {"best_keyword": "", "best_score": "n/a"}},
        )

        prompt = next(p for p in prompts if "话题热度评分" in p)
        assert "GEO空白" not in prompt
