"""Unit tests for async creative memory calibrator — retry, payload building, scheduling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.memory.calibrator import (
    build_calibration_payload,
    calibrate_creative_memory,
    schedule_calibration,
)
from backend.memory.types import CalibrationPayload


def _sample_state() -> dict:
    return {
        "account_id": "test_acct",
        "niche": "母婴",
        "content_plan": {"style_id": "style_heal"},
        "copy_content": {"play_id": "play1", "used_material_ids": ["m1"]},
        "publish_result": {"post_id": "post123"},
    }


class TestBuildCalibrationPayload:
    def test_builds_from_state(self):
        state = _sample_state()
        payload = build_calibration_payload(
            state, actual_engagement_rate=0.05, actual_save_rate=0.03
        )
        assert payload["account_id"] == "test_acct"
        assert payload["niche"] == "母婴"
        assert payload["style_id"] == "style_heal"
        assert payload["play_id"] == "play1"
        assert payload["post_id"] == "post123"
        assert payload["actual_engagement_rate"] == 0.05
        assert payload["actual_save_rate"] == 0.03
        assert payload["play_success"] is True  # 0.05 >= 0.03

    def test_play_success_false_for_low_engagement(self):
        state = _sample_state()
        payload = build_calibration_payload(
            state, actual_engagement_rate=0.01, actual_save_rate=0.005
        )
        assert payload["play_success"] is False

    def test_defaults_for_missing_fields(self):
        state = {}
        payload = build_calibration_payload(state, actual_engagement_rate=0.0, actual_save_rate=0.0)
        assert payload["account_id"] == "default"
        assert payload["niche"] == ""
        assert payload["style_id"] == ""
        assert payload["play_id"] == ""


class TestCalibrateCreativeMemory:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        store.aput = AsyncMock()

        payload = CalibrationPayload(
            account_id="test_acct",
            niche="母婴",
            style_id="",
            actual_engagement_rate=0.05,
            actual_save_rate=0.03,
        )
        result = await calibrate_creative_memory(store, payload)
        assert result is True

    @pytest.mark.asyncio
    async def test_retries_on_unexpected_failure(self):
        """calibrate_creative_memory retries when CreativeMemory.calibrate raises unexpectedly."""
        call_count = 0

        async def failing_calibrate(payload):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient error")

        with patch("backend.memory.calibrator.CreativeMemory") as mock_cm:
            instance = MagicMock()
            instance.calibrate = failing_calibrate
            mock_cm.return_value = instance

            store = AsyncMock()
            payload = CalibrationPayload(
                account_id="test_acct",
                niche="母婴",
                style_id="",
                actual_engagement_rate=0.05,
                actual_save_rate=0.03,
            )
            with patch("backend.memory.calibrator.RETRY_DELAY", 0.01):
                result = await calibrate_creative_memory(store, payload, max_retries=3)
            assert result is True
            assert call_count >= 2

    @pytest.mark.asyncio
    async def test_returns_false_after_max_retries(self):
        """Returns False when all retries are exhausted."""
        with patch("backend.memory.calibrator.CreativeMemory") as mock_cm:
            instance = MagicMock()
            instance.calibrate = AsyncMock(side_effect=RuntimeError("permanent error"))
            mock_cm.return_value = instance

            store = AsyncMock()
            payload = CalibrationPayload(
                account_id="test_acct",
                niche="母婴",
                style_id="",
                actual_engagement_rate=0.05,
                actual_save_rate=0.03,
            )
            with patch("backend.memory.calibrator.RETRY_DELAY", 0.01):
                result = await calibrate_creative_memory(store, payload, max_retries=2)
            assert result is False


class TestScheduleCalibration:
    @pytest.mark.asyncio
    async def test_returns_asyncio_task(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        store.aput = AsyncMock()

        payload = CalibrationPayload(
            account_id="test_acct",
            niche="母婴",
            style_id="",
            actual_engagement_rate=0.05,
            actual_save_rate=0.03,
        )
        task = await schedule_calibration(store, payload)
        assert task is not None
        # Wait for task to complete
        await task
        assert task.done()
