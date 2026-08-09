"""Contract tests for the score-band and dimension-weight response config."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.api.routes import evaluation
from backend.db.evaluator_config import EvaluatorWeights


@pytest.mark.asyncio
async def test_score_config_falls_back_to_bias_free_defaults_when_pool_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evaluation, "is_pool_ready", lambda: False)

    thresholds, weights = await evaluation._score_config("acct-1")

    assert thresholds == {"pass": 70.0, "warn": 50.0}
    assert weights["copywriting"] == 0.18
    assert weights["altruism"] == 0.09
    assert "bias_check" not in weights


@pytest.mark.asyncio
async def test_score_config_returns_effective_account_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = EvaluatorWeights(
        dimension_weights={"copywriting": 0.25, "altruism": 0.09},
        pass_threshold=82.0,
        reject_threshold=58.0,
    )
    load_weights = AsyncMock(return_value=resolved)
    monkeypatch.setattr(evaluation, "is_pool_ready", lambda: True)
    monkeypatch.setattr("backend.db.evaluator_config.load_weights", load_weights)

    thresholds, weights = await evaluation._score_config("acct-1")

    assert thresholds == {"pass": 82.0, "warn": 58.0}
    assert weights == {"copywriting": 0.25, "altruism": 0.09}
    load_weights.assert_awaited_once_with("acct-1")
