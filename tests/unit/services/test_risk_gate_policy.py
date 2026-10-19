"""Per-account cool-down policy overrides."""

from __future__ import annotations

import pytest

from backend.services.xhs_risk_gate import (
    browser_action_cooldown_seconds,
    check_browser_action_allowed,
    check_comment_reply_quota,
    check_dm_quota,
    clear_cooldown_policy,
    comment_reply_daily_limit,
    dm_daily_limit,
    get_cooldown_policy,
    note_browser_action,
    note_comment_reply_sent,
    note_dm_sent,
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


class TestDailyLimitOverridesAreReachable:
    """The readers asked ``_policies`` for these keys all along.

    Until the whitelist, the writer and the API accepted the request, the
    answer always came from the global env — a per-account ceiling nobody
    could actually set.  These pin each surface that had to change.
    """

    def test_an_override_reaches_the_reader(self):
        assert dm_daily_limit("a1") == 20
        assert comment_reply_daily_limit("a1") == 50
        set_cooldown_policy("a1", dm_daily_limit=3, comment_reply_daily_limit=4)
        assert dm_daily_limit("a1") == 3
        assert comment_reply_daily_limit("a1") == 4
        # Other accounts stay global.
        assert dm_daily_limit("a2") == 20
        assert comment_reply_daily_limit("a2") == 50

    def test_an_override_actually_bounds_the_quota_gate(self):
        """The whole point: the quota gate must answer per account."""
        set_cooldown_policy("a1", dm_daily_limit=1)
        set_cooldown_policy("a2", dm_daily_limit=2)
        assert check_dm_quota("a1") is None
        assert check_dm_quota("a2") is None
        note_dm_sent("a1")
        note_dm_sent("a2")
        assert check_dm_quota("a1") is not None  # a1's 1 is spent
        assert check_dm_quota("a2") is None  # a2 still has one

    def test_zero_is_zero(self):
        """0 means "nothing today", not "fall back to the default"."""
        set_cooldown_policy("a1", dm_daily_limit=0, comment_reply_daily_limit=0)
        assert dm_daily_limit("a1") == 0
        assert check_dm_quota("a1") is not None
        assert check_comment_reply_quota("a1") is not None

    def test_replace_wipes_the_limits_like_every_other_field(self):
        set_cooldown_policy("a1", dm_daily_limit=3, browser_action_seconds=8)
        set_cooldown_policy("a1", browser_action_seconds=5, replace=True)
        overrides = get_cooldown_policy("a1")["overrides"]
        assert overrides.get("dm_daily_limit") is None
        assert overrides.get("browser_action_seconds") == 5
        assert dm_daily_limit("a1") == 20

    def test_the_effective_surface_shows_the_whole_policy(self):
        """``get_cooldown_policy`` is the operator's window; a key it cannot
        show is a key nobody knows is set.

        Lookups go through ``.get`` on purpose: a missing key must fail the
        assertion, not blow up with a KeyError that could pass for a harness
        crash (see the mutation self-check rule "the red must be an assert").
        """
        set_cooldown_policy("a1", dm_daily_limit=3)
        policy = get_cooldown_policy("a1")
        assert policy["defaults"].get("dm_daily_limit") == 20
        assert policy["defaults"].get("comment_reply_daily_limit") == 50
        assert policy["overrides"].get("dm_daily_limit") == 3
        assert policy["effective"].get("dm_daily_limit") == 3
        assert policy["effective"].get("comment_reply_daily_limit") == 50

    def test_comment_reply_counting_is_bounded_by_the_override(self):
        set_cooldown_policy("a1", comment_reply_daily_limit=1)
        assert check_comment_reply_quota("a1") is None
        note_comment_reply_sent("a1")
        assert check_comment_reply_quota("a1") is not None


def test_min_risk_pressure_floor():
    from backend.services.xhs_risk_gate import account_min_risk_pressure

    assert account_min_risk_pressure("a1") in (0, 1)  # global SAFE_MODE may be on
    set_cooldown_policy("a1", min_risk_pressure=2)
    assert account_min_risk_pressure("a1") == 2
    set_cooldown_policy("a1", min_risk_pressure=0, replace=True)
    # replace with only 0 still stores override 0
    assert account_min_risk_pressure("a1") == 0
