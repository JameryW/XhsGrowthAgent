"""Tests for the process-local account session breaker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.services import session_circuit


@pytest.fixture(autouse=True)
def _clean_breakers():
    session_circuit.reset_session_circuits()
    yield
    session_circuit.reset_session_circuits()


def test_hard_auth_failure_trips_and_blocks_attempts():
    session_circuit.record_failure(
        "acc-1",
        error_code="signature_unavailable",
        message="browser login expired",
    )

    with pytest.raises(session_circuit.SessionCircuitOpenError) as excinfo:
        session_circuit.check_session_allowed("acc-1")

    assert excinfo.value.snapshot.account_id == "acc-1"
    assert "signature_unavailable" in excinfo.value.snapshot.reason


def test_transient_failures_degrade_only_after_the_threshold():
    now = datetime(2026, 11, 16, tzinfo=UTC)
    breaker = session_circuit.breaker_for("acc-2", degraded_threshold=3)

    for _ in range(2):
        snapshot = breaker.record_failure("timeout", "network jitter", now=now)
        assert snapshot.state.value == "healthy"

    snapshot = breaker.record_failure("timeout", "network jitter", now=now)
    assert snapshot.state.value == "degraded"


def test_cooldown_reopens_and_success_resets():
    now = datetime(2026, 11, 16, tzinfo=UTC)
    session_circuit.record_failure("acc-3", error_code="login_required", now=now)

    with pytest.raises(session_circuit.SessionCircuitOpenError):
        session_circuit.check_session_allowed("acc-3", now=now)

    reopened = session_circuit.check_session_allowed(
        "acc-3",
        now=now + timedelta(minutes=31),
    )
    assert reopened.state.value == "healthy"

    session_circuit.record_failure("acc-3", error_code="login_required", now=now)
    assert session_circuit.record_success("acc-3", now=now).state.value == "healthy"
