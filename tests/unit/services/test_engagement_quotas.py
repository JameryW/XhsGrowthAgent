"""P0-3 engagement quota / inbound whitelist / risk pause + §9.5 policy gates."""

from __future__ import annotations

import pytest

from backend.services import xhs_risk_gate as rg
from backend.services.xhs_effect_ledger import EngagementApproval
from backend.services.xhs_outreach_policy import (
    OUTREACH_CONFIRMED,
    OUTREACH_NOBODY,
    XhsOutreachPolicy,
)

#: §7.2 审批记录的测试替身（取代旧的 approval=APPROVAL 自声明）。
APPROVAL = EngagementApproval(
    thread_id="thread-1",
    approved_by="operator-1",
    approved_at="2026-10-13T00:00:00+00:00",
)


@pytest.fixture(autouse=True)
def _reset_gates():
    rg.reset_gates_for_tests()
    yield
    rg.reset_gates_for_tests()


def test_dm_requires_inbound_peer() -> None:
    """The safe default (``policy=None``) reaches nobody new."""
    block = rg.check_dm_target_allowed("acc-1", "user-x")
    assert block is not None
    assert block.risk_code == "dm_target_not_inbound"


def test_dm_allows_inbound_peer() -> None:
    rg.note_inbound_peers("acc-1", ["user-x"])
    assert rg.check_dm_target_allowed("acc-1", "user-x") is None


def test_dm_outbound_needs_policy_and_confirm() -> None:
    """The account's *policy* opens cold outreach — and only with a per-call confirm.

    Replaces the old env-switch test: ``XHS_ALLOW_OUTBOUND_DM`` no longer
    reaches this gate directly (it is a deployment default consumed by
    ``load_outreach_policy``, see test_xhs_outreach_policy).
    """
    policy = XhsOutreachPolicy(account_id="acc-1", mode=OUTREACH_CONFIRMED, daily_proactive_cap=5)
    unconfirmed = rg.check_dm_target_allowed("acc-1", "cold", approval=None, policy=policy)
    assert unconfirmed is not None
    assert unconfirmed.risk_code == "dm_unconfirmed"
    assert rg.check_dm_target_allowed("acc-1", "cold", approval=APPROVAL, policy=policy) is None


def test_the_gate_is_policy_driven_not_env_driven(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolved policy is the only thing that opens cold outreach here.

    Mutating the gate to re-read a global env switch must turn this red: the
    signature's ``policy`` argument is the answer, not the environment.
    """
    monkeypatch.setenv("XHS_ALLOW_OUTBOUND_DM", "1")
    monkeypatch.setenv("XHS_OUTREACH_MODE", OUTREACH_CONFIRMED)
    block = rg.check_dm_target_allowed("acc-1", "cold", approval=APPROVAL)
    assert block is not None
    assert block.risk_code == "dm_target_not_inbound"


def test_nobody_policy_closes_even_replies() -> None:
    """``nobody`` is an account-level sentence: no touches at all, replies included."""
    rg.note_inbound_peers("acc-1", ["friend"])
    policy = XhsOutreachPolicy(account_id="acc-1", mode=OUTREACH_NOBODY)
    block = rg.check_dm_target_allowed("acc-1", "friend", policy=policy)
    assert block is not None
    assert block.risk_code == "outreach_suspended"


def test_proactive_budget_stops_at_the_cap() -> None:
    """The cap counts cold sends only; a reply never spends it."""
    policy = XhsOutreachPolicy(account_id="acc-1", mode=OUTREACH_CONFIRMED, daily_proactive_cap=2)
    rg.note_inbound_peers("acc-1", ["friend"])
    rg.note_dm_sent("acc-1", proactive=False)
    assert rg.check_dm_target_allowed("acc-1", "cold-1", approval=APPROVAL, policy=policy) is None
    rg.note_dm_sent("acc-1", proactive=True)
    assert rg.check_dm_target_allowed("acc-1", "cold-2", approval=APPROVAL, policy=policy) is None
    rg.note_dm_sent("acc-1", proactive=True)
    block = rg.check_dm_target_allowed("acc-1", "cold-3", approval=APPROVAL, policy=policy)
    assert block is not None
    assert block.risk_code == "proactive_dm_daily_limit"
    # The reply half is untouched by the spent outreach budget.
    assert rg.check_dm_target_allowed("acc-1", "friend", policy=policy) is None


def test_zero_cap_is_zero_budget() -> None:
    """``confirmed_anyone`` with cap 0 still says no — 0 of something is none of it."""
    policy = XhsOutreachPolicy(account_id="acc-1", mode=OUTREACH_CONFIRMED, daily_proactive_cap=0)
    block = rg.check_dm_target_allowed("acc-1", "cold", approval=APPROVAL, policy=policy)
    assert block is not None
    assert block.risk_code == "dm_target_not_inbound"


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
