"""Unified browser/publish/engagement cool-downs."""

from __future__ import annotations

import pytest

from backend.services.xhs_risk_gate import (
    check_browser_action_allowed,
    check_engagement_allowed,
    check_publish_allowed,
    note_browser_action,
    note_engagement,
    note_publish,
    reset_gates_for_tests,
    snapshot_risk_gates,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_gates_for_tests()
    yield
    reset_gates_for_tests()


def test_browser_action_cooldown_blocks_feature_switch(monkeypatch):
    monkeypatch.setenv("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", "30")
    note_browser_action(account_id="a1", owner="publisher")
    block = check_browser_action_allowed(account_id="a1", owner="creator_stats")
    assert block is not None
    assert block.reason == "browser_action_cooldown"
    assert block.retry_after_seconds > 0


def test_browser_action_same_owner_shorter_gap(monkeypatch):
    monkeypatch.setenv("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", "30")
    note_browser_action(account_id="a1", owner="engagement")
    block = check_browser_action_allowed(account_id="a1", owner="engagement")
    assert block is not None
    # 0.4 × 30 = 12s max remaining
    assert block.retry_after_seconds <= 12


def test_publish_and_engagement_cooldowns(monkeypatch):
    monkeypatch.setenv("XHS_PUBLISH_COOLDOWN_SECONDS", "60")
    monkeypatch.setenv("XHS_ENGAGEMENT_ACCOUNT_COOLDOWN_SECONDS", "40")
    note_publish(account_id="a1")
    assert check_publish_allowed(account_id="a1") is not None
    note_engagement(account_id="a1")
    assert check_engagement_allowed(account_id="a1") is not None


def test_snapshot_risk_gates_shape(monkeypatch):
    monkeypatch.setenv("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", "30")
    note_browser_action(account_id="a1", owner="publisher")
    snap = snapshot_risk_gates()
    assert "active_browser_cooldowns" in snap
    assert snap["active_browser_cooldowns"] >= 1
