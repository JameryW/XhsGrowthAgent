"""P0-3 engagement quota / inbound whitelist / risk pause."""

from __future__ import annotations

import pytest

from backend.services import xhs_risk_gate as rg


@pytest.fixture(autouse=True)
def _reset_gates():
    rg.reset_gates_for_tests()
    yield
    rg.reset_gates_for_tests()


def test_dm_requires_inbound_peer() -> None:
    block = rg.check_dm_target_allowed("acc-1", "user-x")
    assert block is not None
    assert block.risk_code == "dm_target_not_inbound"


def test_dm_allows_inbound_peer() -> None:
    rg.note_inbound_peers("acc-1", ["user-x"])
    assert rg.check_dm_target_allowed("acc-1", "user-x") is None


def test_dm_outbound_needs_flag_and_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")
    assert rg.check_dm_target_allowed("acc-1", "cold", human_confirmed=False) is not None
    assert rg.check_dm_target_allowed("acc-1", "cold", human_confirmed=True) is None


def test_dm_daily_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_DM_DAILY_LIMIT", "2")
    rg.note_inbound_peers("acc-1", ["u1"])
    assert rg.check_dm_quota("acc-1") is None
    rg.note_dm_sent("acc-1")
    rg.note_dm_sent("acc-1")
    block = rg.check_dm_quota("acc-1")
    assert block is not None
    assert block.risk_code == "dm_daily_limit"


def test_engagement_risk_pause_visible() -> None:
    rg.note_engagement_risk_pause("acc-1", reason="risk_control")
    status = rg.get_engagement_pause_status("acc-1")
    assert status["paused"] is True
    assert status["reason"] == "risk_control"
    assert status["retry_after_seconds"] > 0
    active = rg.list_active_cooldowns(account_id="acc-1")
    assert any(r["kind"] == "engagement_risk_pause" for r in active)
