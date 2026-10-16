"""P1-1 account health panel payload."""

from __future__ import annotations

import pytest

from backend.services.xhs_risk_gate import (
    get_account_health,
    note_engagement_risk_pause,
    note_qr_risk_block,
    reset_gates_for_tests,
    set_cooldown_policy,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("XHS_QR_RISK_BLOCK_SECONDS", "3600")
    monkeypatch.setenv("XHS_ENGAGEMENT_RISK_PAUSE_SECONDS", "7200")
    monkeypatch.setenv("CREATOR_STATS_SAFE_MODE", "1")
    reset_gates_for_tests()
    yield
    reset_gates_for_tests()


def test_account_health_includes_policy_safe_mode_last_hit_and_ban():
    set_cooldown_policy("acc-h", browser_action_seconds=33.0, min_risk_pressure=1.0)
    note_qr_risk_block("acc-h", reason="300012")
    note_engagement_risk_pause("acc-h", reason="risk_control")

    health = get_account_health("acc-h")
    assert health["account_id"] == "acc-h"
    assert health["policy"]["effective"]["browser_action_seconds"] == 33.0
    assert health["safe_mode"]["env_enabled"] is True
    assert health["safe_mode"]["active"] is True
    assert health["last_risk_hit"] is not None
    assert health["last_risk_hit"]["reason"] in {"risk_control", "300012"}
    assert health["remaining_ban_seconds"] > 0
    assert health["engagement_pause"]["paused"] is True
    assert isinstance(health["active"], list)
    assert len(health["active"]) >= 1
