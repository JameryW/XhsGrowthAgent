"""Tests for Ripple wave limit defaults."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.ripple_service import RippleService


@pytest.mark.asyncio
async def test_predict_spread_defaults_to_three_waves(monkeypatch):
    monkeypatch.delenv("RIPPLE_MAX_WAVES", raising=False)
    monkeypatch.delenv("RIPPLE_SIMULATION_HORIZON", raising=False)
    monkeypatch.delenv("RIPPLE_ENSEMBLE_RUNS", raising=False)
    service = object.__new__(RippleService)
    service._get_config = MagicMock(return_value={"enabled": True})  # type: ignore[method-assign]
    service.is_healthy = MagicMock(return_value=True)  # type: ignore[method-assign]
    service.submit_and_wait = AsyncMock(return_value={"job_id": "job_1"})  # type: ignore[method-assign]
    service._parse_spread_result = MagicMock(return_value={"ripple_prediction": {}})  # type: ignore[method-assign]

    await service.predict_spread(topic="测试")

    request_body = service.submit_and_wait.await_args.args[0]
    assert request_body["max_waves"] == 3
    assert request_body["simulation_horizon"] == "12h"
    assert request_body["ensemble_runs"] == 1


@pytest.mark.asyncio
async def test_validate_pmf_defaults_to_three_waves(monkeypatch):
    monkeypatch.delenv("RIPPLE_MAX_WAVES", raising=False)
    monkeypatch.delenv("RIPPLE_SIMULATION_HORIZON", raising=False)
    monkeypatch.delenv("RIPPLE_ENSEMBLE_RUNS", raising=False)
    service = object.__new__(RippleService)
    service._get_config = MagicMock(return_value={"enabled": True})  # type: ignore[method-assign]
    service.is_healthy = MagicMock(return_value=True)  # type: ignore[method-assign]
    service.submit_and_wait = AsyncMock(return_value={"job_id": "job_1"})  # type: ignore[method-assign]
    service._parse_pmf_result = MagicMock(return_value={"ripple_pmf": {}})  # type: ignore[method-assign]

    await service.validate_pmf(product_name="产品", category="note", description="角度")

    request_body = service.submit_and_wait.await_args.args[0]
    assert request_body["max_waves"] == 3
    assert request_body["simulation_horizon"] == "12h"
    assert request_body["ensemble_runs"] == 1


@pytest.mark.asyncio
async def test_submit_and_wait_caps_progress_total_waves():
    service = object.__new__(RippleService)
    service.submit_simulation = AsyncMock(return_value={"job_id": "job_1"})  # type: ignore[method-assign]
    service.wait_for_completion = AsyncMock()  # type: ignore[method-assign]
    service.get_result = AsyncMock(return_value={"output": {}})  # type: ignore[method-assign]

    await service.submit_and_wait({"max_waves": 3}, thread_id="thread_1")

    service.wait_for_completion.assert_awaited_once()
    assert service.wait_for_completion.await_args.kwargs["total_waves_limit"] == 3
