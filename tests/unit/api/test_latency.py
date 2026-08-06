"""Tests for env-gated HTTP latency instrumentation (backend/api/latency.py).

XHS_LATENCY_LOG defaults off → zero overhead (should_sample short-circuits).
When on, sampled requests emit one structured JSON line per call. Sampling
bounds /status log volume. Instrumentation never raises into the request.
"""

from __future__ import annotations

import json
import logging

import pytest

from backend.api import latency as latency_mod
from backend.api.latency import LatencyTimer


@pytest.fixture
def enabled(monkeypatch):
    """Force the env-gated flag on for the test process."""
    monkeypatch.setattr(latency_mod, "_ENABLED", True)
    yield


def test_should_sample_false_when_disabled(monkeypatch):
    monkeypatch.setattr(latency_mod, "_ENABLED", False)
    assert LatencyTimer.should_sample("/status") is False
    assert LatencyTimer.should_sample("/list") is False


def test_should_sample_true_for_unsampled_endpoints(enabled):
    # /list has no sampling denominator → always sampled when enabled
    assert LatencyTimer.should_sample("/list") is True
    assert LatencyTimer.should_sample("/account-totals") is True
    assert LatencyTimer.should_sample("/evaluation/result") is True


def test_status_sampling_is_bounded(enabled):
    # /status samples 1-in-N; across many calls most must be False, at least
    # one True (not all-False, not all-True). Bounding volume, not uniformity.
    samples = [LatencyTimer.should_sample("/status") for _ in range(200)]
    true_count = sum(samples)
    assert 0 < true_count < 200  # sampled, not 100%, not 0%


def test_emit_writes_structured_json_line(enabled, caplog):
    caplog.set_level(logging.INFO, logger="xhs_growth.api.latency")
    timer = LatencyTimer("/list", "acct-1")
    with timer.segment("db"):
        pass
    with timer.segment("serialize"):
        pass
    timer.emit(phase="ok")

    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "http_latency"
    assert payload["endpoint"] == "/list"
    assert payload["thread_id"] == "acct-1"
    assert payload["phase"] == "ok"
    assert "total_ms" in payload
    assert "db_ms" in payload
    assert "serialize_ms" in payload


def test_emit_never_raises_on_bad_payload(enabled, caplog):
    # A timer whose internals are corrupted must not raise into the caller.
    caplog.set_level(logging.DEBUG, logger="xhs_growth.api.latency")
    timer = LatencyTimer("/status", None)
    timer._segments = None  # type: ignore[assignment]  # corrupt on purpose
    timer.emit(phase="ok")  # must not raise
    # Falled through to the debug-swallow branch.


def test_segment_exception_not_suppressed(enabled):
    # The context manager must NOT swallow exceptions raised inside it.
    timer = LatencyTimer("/list", "t1")
    with pytest.raises(ValueError, match="boom"), timer.segment("db"):  # noqa: SIM117
        raise ValueError("boom")
