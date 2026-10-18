"""Retry-loop stall signal — the Progress Detector's first production consumer."""

from __future__ import annotations

from backend.agents.base import _retry_stall_signal


def test_single_failure_is_not_a_stall():
    signal = _retry_stall_signal([("json", "missing field: title")])
    assert signal.stalled is False


def test_two_identical_corrections_stall():
    failures = [("json", "missing field: title"), ("json", "missing field: title")]
    signal = _retry_stall_signal(failures)
    assert signal.stalled is True
    assert signal.reason == "same_error_repeated"


def test_two_different_corrections_are_converging():
    failures = [("json", "missing field: title"), ("json", "bad value: urgency")]
    assert _retry_stall_signal(failures).stalled is False


def test_window_defaults_to_two_for_the_two_attempt_budget():
    # attempts_per_level defaults to 2; a third identical failure must also
    # register (the detector looks at the trailing window, not exactly two).
    failures = [("json", "x")] * 3
    signal = _retry_stall_signal(failures)
    assert signal.stalled is True
    assert signal.evidence["count"] == 2
