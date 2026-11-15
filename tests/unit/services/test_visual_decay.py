"""Exponential time-decay tests for visual scene recommendations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.services.visual_analysis import (
    VISUAL_DECAY_HALF_LIFE_DAYS,
    _parse_observed_at,
    decay_weight,
    weighted_distribution,
)


def test_half_life_cuts_weight_in_half() -> None:
    now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    fresh = decay_weight(now, now=now)
    one_half_life = decay_weight(now - timedelta(days=VISUAL_DECAY_HALF_LIFE_DAYS), now=now)
    assert fresh == 1.0
    assert one_half_life == pytest.approx(0.5, rel=1e-6)


def test_missing_timestamp_is_neutral() -> None:
    assert decay_weight(None) == 1.0
    assert decay_weight("") == 1.0
    assert decay_weight("not-a-date") == 1.0


def test_future_timestamp_is_clamped() -> None:
    now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    assert decay_weight(now + timedelta(days=3), now=now) == 1.0


def test_parse_epoch_seconds_and_milliseconds() -> None:
    expected = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)
    seconds = expected.timestamp()
    assert _parse_observed_at(seconds) == expected
    assert _parse_observed_at(seconds * 1000) == expected


def test_weighted_distribution_normalises_and_ignores_negative() -> None:
    distribution = weighted_distribution({"a": 2.0, "b": 1.0, "c": -1.0, "d": 0.0})
    assert distribution == {"a": 2.0 / 3.0, "b": 1.0 / 3.0}
    assert sum(distribution.values()) == pytest.approx(1.0)


def test_weighted_distribution_empty() -> None:
    assert weighted_distribution({}) == {}
    assert weighted_distribution({"a": 0.0}) == {}
