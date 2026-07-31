"""Per-account cool-down policy overrides."""

from __future__ import annotations

import pytest

from backend.services.xhs_risk_gate import (
    browser_action_cooldown_seconds,
    check_browser_action_allowed,
    clear_cooldown_policy,
    get_cooldown_policy,
    note_browser_action,
    publish_cooldown_seconds,
    reset_gates_for_tests,
    set_cooldown_policy,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", "20")
    monkeypatch.setenv("XHS_PUBLISH_COOLDOWN_SECONDS", "90")
    reset_gates_for_tests()
    yield
    reset_gates_for_tests()


def test_set_policy_overrides_effective_seconds():
    assert browser_action_cooldown_seconds("a1") == 20
    set_cooldown_policy("a1", browser_action_seconds=5, publish_seconds=10)
    assert browser_action_cooldown_seconds("a1") == 5
    assert publish_cooldown_seconds("a1") == 10
    # other accounts stay global
    assert browser_action_cooldown_seconds("a2") == 20
    policy = get_cooldown_policy("a1")
    assert policy["overrides"]["browser_action_seconds"] == 5
    assert policy["effective"]["publish_seconds"] == 10


def test_policy_affects_remaining_cooldown():
    set_cooldown_policy("a1", browser_action_seconds=40)
    note_browser_action(account_id="a1", owner="publisher")
    block = check_browser_action_allowed(account_id="a1", owner="stats")
    assert block is not None
    assert block.retry_after_seconds > 20


def test_clear_policy_restores_defaults():
    set_cooldown_policy("a1", browser_action_seconds=3)
    clear_cooldown_policy("a1")
    assert browser_action_cooldown_seconds("a1") == 20
    assert get_cooldown_policy("a1")["overrides"] == {}


def test_replace_policy_wipes_unspecified_fields():
    set_cooldown_policy("a1", browser_action_seconds=3, publish_seconds=4)
    set_cooldown_policy("a1", browser_action_seconds=8, replace=True)
    overrides = get_cooldown_policy("a1")["overrides"]
    assert overrides == {"browser_action_seconds": 8}
