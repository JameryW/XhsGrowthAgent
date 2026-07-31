"""Durable risk-gate cool-down hydrate / export."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from backend.db.risk_gates import reset_risk_gate_memory_for_tests
from backend.services.xhs_risk_gate import (
    check_browser_action_allowed,
    check_publish_allowed,
    check_sync_auth_cooldown,
    export_risk_gate_state,
    hydrate_risk_gates,
    note_browser_action,
    note_publish,
    note_sync_auth_failure,
    reset_gates_for_tests,
    snapshot_risk_gates,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", "60")
    monkeypatch.setenv("XHS_PUBLISH_COOLDOWN_SECONDS", "120")
    monkeypatch.setenv("CREATOR_STATS_AUTH_FAIL_COOLDOWN_MINUTES", "30")
    reset_gates_for_tests()
    reset_risk_gate_memory_for_tests()
    yield
    reset_gates_for_tests()
    reset_risk_gate_memory_for_tests()


@pytest.mark.asyncio
async def test_export_and_hydrate_roundtrip(monkeypatch):
    note_browser_action(account_id="acc-1", owner="publisher")
    note_publish(account_id="acc-1")
    note_sync_auth_failure("acc-1", reason="AUTH_EXPIRED")
    exported = export_risk_gate_state()
    assert "account:acc-1" in exported["browser_action"]
    assert "account:acc-1" in exported["publish"]
    assert "acc-1" in exported["sync_auth"]

    reset_gates_for_tests()
    assert check_browser_action_allowed(account_id="acc-1", owner="stats") is None

    monkeypatch.setattr(
        "backend.db.risk_gates.load_risk_gate_state",
        AsyncMock(return_value=exported),
    )
    await hydrate_risk_gates()
    assert check_browser_action_allowed(account_id="acc-1", owner="stats") is not None
    assert check_publish_allowed(account_id="acc-1") is not None
    assert check_sync_auth_cooldown("acc-1") is not None
    snap = snapshot_risk_gates()
    assert snap["durable"] is True


@pytest.mark.asyncio
async def test_hydrate_ignores_expired_auth_blocks(monkeypatch):
    past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    payload = {
        "browser_action": {},
        "publish": {},
        "engagement": {},
        "sync_auth": {"acc-x": {"until": past, "reason": "AUTH_EXPIRED"}},
        "qr_risk": {},
        "qr_last_attempt": {},
    }
    monkeypatch.setattr(
        "backend.db.risk_gates.load_risk_gate_state",
        AsyncMock(return_value=payload),
    )
    await hydrate_risk_gates()
    assert check_sync_auth_cooldown("acc-x") is None
