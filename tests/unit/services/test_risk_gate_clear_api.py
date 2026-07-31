"""Active cool-down listing and clear helpers."""

from __future__ import annotations

import pytest

from backend.services.xhs_risk_gate import (
    clear_account_cooldowns,
    list_active_cooldowns,
    note_browser_action,
    note_publish,
    note_sync_auth_failure,
    reset_gates_for_tests,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", "60")
    monkeypatch.setenv("XHS_PUBLISH_COOLDOWN_SECONDS", "90")
    monkeypatch.setenv("CREATOR_STATS_AUTH_FAIL_COOLDOWN_MINUTES", "30")
    reset_gates_for_tests()
    yield
    reset_gates_for_tests()


def test_list_active_cooldowns_has_remaining():
    note_browser_action(account_id="a1", owner="publisher")
    note_publish(account_id="a1")
    note_sync_auth_failure("a1")
    rows = list_active_cooldowns(account_id="a1")
    kinds = {r["kind"] for r in rows}
    assert "browser_action" in kinds
    assert "publish" in kinds
    assert "sync_auth" in kinds
    assert all(int(r["retry_after_seconds"]) > 0 for r in rows)


def test_clear_account_cooldowns_scoped():
    note_browser_action(account_id="a1", owner="publisher")
    note_browser_action(account_id="a2", owner="engagement")
    note_sync_auth_failure("a1")
    result = clear_account_cooldowns("a1")
    assert result["total"] >= 2
    assert list_active_cooldowns(account_id="a1") == []
    # a2 still has browser cool-down
    assert any(r["kind"] == "browser_action" for r in list_active_cooldowns(account_id="a2"))


def test_clear_kinds_filter():
    note_publish(account_id="a1")
    note_sync_auth_failure("a1")
    result = clear_account_cooldowns("a1", kinds=["publish"])
    assert result["cleared"].get("publish", 0) >= 1
    kinds = {r["kind"] for r in list_active_cooldowns(account_id="a1")}
    assert "publish" not in kinds
    assert "sync_auth" in kinds
