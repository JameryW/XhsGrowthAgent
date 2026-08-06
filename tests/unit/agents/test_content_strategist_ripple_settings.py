"""Verify RippleSettings values flow through to predict_spread/validate_pmf calls.

The strategist previously hardcoded max_waves=3, simulation_horizon="12h",
ensemble_runs=1, so RIPPLE_MAX_WAVES / RIPPLE_SIMULATION_HORIZON /
RIPPLE_ENSEMBLE_RUNS env vars had no effect. These tests pin the wiring so a
user lowering RIPPLE_MAX_WAVES actually speeds up the sims.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_strategist import ContentStrategistAgent
from backend.state.schema import WorkflowPhase


class TestRippleSettingsFlowThrough:
    """RippleSettings defaults reach the ripple integration calls."""

    @pytest.fixture
    def agent(self):
        return ContentStrategistAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def content_plan_state(self):
        return {
            "account_id": "test_account",
            "phase": WorkflowPhase.SCOUTING,
            "trend_data": {"trending_topics": ["美食探店"]},
        }

    def _wire_model(self, agent, topic: str = "美食探店") -> MagicMock:
        mock_response = MagicMock()
        mock_response.content = f'{{"selected_topic": "{topic}"}}'
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model
        return mock_model

    def _scorer(self) -> MagicMock:
        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})
        return scorer

    @pytest.mark.asyncio
    async def test_predict_spread_uses_settings_max_waves_and_horizon(
        self, agent, content_plan_state, mock_store
    ):
        """predict_spread receives max_waves / horizon from RippleSettings."""
        self._wire_model(agent)

        scorer = self._scorer()
        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
            patch("backend.agents.content_strategist.Settings") as mock_settings,
        ):
            mock_settings.return_value.ripple.default_max_waves = 5
            mock_settings.return_value.ripple.default_simulation_horizon = "24h"
            mock_settings.return_value.ripple.default_ensemble_runs = 1
            mock_settings.return_value.ripple.background = False
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            await agent.execute(content_plan_state, store=mock_store)

        _, kwargs = mock_pred.call_args
        assert kwargs["max_waves"] == 5
        assert kwargs["simulation_horizon"] == "24h"

    @pytest.mark.asyncio
    async def test_validate_pmf_uses_settings_max_waves_horizon_ensemble(
        self, agent, content_plan_state, mock_store
    ):
        """validate_pmf receives max_waves / horizon / ensemble_runs from RippleSettings."""
        self._wire_model(agent)

        scorer = self._scorer()
        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
            patch("backend.agents.content_strategist.Settings") as mock_settings,
        ):
            mock_settings.return_value.ripple.default_max_waves = 2
            mock_settings.return_value.ripple.default_simulation_horizon = "6h"
            mock_settings.return_value.ripple.default_ensemble_runs = 3
            mock_settings.return_value.ripple.background = False
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            await agent.execute(content_plan_state, store=mock_store)

        _, kwargs = mock_pmf.call_args
        assert kwargs["max_waves"] == 2
        assert kwargs["simulation_horizon"] == "6h"
        assert kwargs["ensemble_runs"] == 3

    @pytest.mark.asyncio
    async def test_defaults_match_documented_values(self, agent, content_plan_state, mock_store):
        """When Settings is unpatched (real defaults), the calls still get 3 / '12h' / 1 —
        behavior identical to the old hardcoded literals."""
        self._wire_model(agent)

        scorer = self._scorer()
        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            await agent.execute(content_plan_state, store=mock_store)

        _, pred_kwargs = mock_pred.call_args
        _, pmf_kwargs = mock_pmf.call_args
        assert pred_kwargs["max_waves"] == 3
        assert pred_kwargs["simulation_horizon"] == "12h"
        assert pmf_kwargs["max_waves"] == 3
        assert pmf_kwargs["simulation_horizon"] == "12h"
        assert pmf_kwargs["ensemble_runs"] == 1

    @pytest.mark.asyncio
    async def test_low_viral_threshold_read_from_settings(
        self, agent, content_plan_state, mock_store
    ):
        """Raising low_viral_threshold via Settings makes a viral_probability=0.3
        prediction trigger the Ripple-insight regen branch (ripple_revised=True).

        Pins the wiring extracted from the old hardcoded ``< 0.3`` gate: with the
        threshold raised to 0.5, 0.3 < 0.5 fires the regen. Non-vacuous — reverts
        to the hardcoded ``< 0.3`` literal (0.3 is not < 0.3) and this fails.
        """
        self._wire_model(agent)
        scorer = self._scorer()

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
            patch("backend.agents.content_strategist.Settings") as mock_settings,
        ):
            mock_settings.return_value.ripple.low_viral_threshold = 0.5
            mock_settings.return_value.ripple.background = False
            mock_pred.return_value = {
                "ripple_prediction": {"estimated_reach": 5000, "viral_probability": 0.3},
            }
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(content_plan_state, store=mock_store)

        # ripple_revised is set ONLY in the low-viral-probability regen branch.
        assert result["content_plan"].get("ripple_revised") is True
