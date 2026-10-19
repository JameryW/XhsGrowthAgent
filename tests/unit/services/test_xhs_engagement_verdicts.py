"""What an engagement call is allowed to report (spec §8, Phase A).

The four defects these pin are the reason the engagement tools are not in the
Tool Gateway yet: a DM that was never submitted reported success, platform
verdicts were dropped, and receipt ids were clock readings. See
``docs/tool-gateway-engagement-migration.md`` §1.

Each test asserts a *verdict*, not a browser interaction, because the verdict is
what the operator and (later) the Gateway branch on.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.cdp_session_lock import CdpSessionBusyError
from backend.services.xhs_engagement import EngagementRiskError, XHSEngagement
from backend.services.xhs_outreach_policy import (
    OUTREACH_CONFIRMED,
    OUTREACH_NOBODY,
    XhsOutreachPolicy,
)

GATE = "backend.services.xhs_risk_gate"
SENT, BLOCKED, FAILED, UNKNOWN = "sent", "blocked", "failed", "unknown"


@asynccontextmanager
async def _noop_hold(**_kwargs: Any):
    yield "acc-1"


def _engagement(page: Any) -> XHSEngagement:
    """A session whose browser half is ``page`` and whose gates all pass.

    ``_hold_cdp`` is replaced by a no-op because the real one takes a CDP lock
    and sleeps out account cool-downs; neither is what these tests are about.
    """
    engagement = XHSEngagement(
        cdp_endpoint="http://127.0.0.1:9224",
        account_id="acc-1",
        # The real 5s cooldown between browser actions would make this file
        # slow without testing anything it means to test.
        cooldown_seconds=0.0,
    )
    engagement._ensure_page = AsyncMock(return_value=page)
    engagement._hold_cdp = AsyncMock(side_effect=lambda: _noop_hold())
    return engagement


def _page(*query_results: Any) -> MagicMock:
    page = MagicMock(url="https://www.xiaohongshu.com/explore/note-1")
    page.evaluate = AsyncMock(return_value="")  # no risk/login markers
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.query_selector = AsyncMock(side_effect=list(query_results))
    return page


def _element(*, reply_button: Any = None) -> MagicMock:
    """A DOM node whose whole API is awaitable (``MagicMock.fill`` is not)."""
    element = MagicMock()
    element.query_selector = AsyncMock(return_value=reply_button)
    element.fill = AsyncMock()
    element.click = AsyncMock()
    element.inner_text = AsyncMock(return_value="")
    element.get_attribute = AsyncMock(return_value="")
    return element


@pytest.fixture(autouse=True)
def _open_gates(monkeypatch: pytest.MonkeyPatch):
    """Every gate passes, so each test states only the condition it is about."""
    for name in (
        "check_engagement_risk_pause",
        "check_comment_reply_quota",
        "check_dm_quota",
        "check_dm_target_allowed",
        "check_engagement_allowed",
    ):
        monkeypatch.setattr(f"{GATE}.{name}", lambda *a, **k: None)


class TestCommentReplyVerdicts:
    async def test_a_missing_send_button_is_a_failure_not_a_success(self):
        """Defect 1: no click means nothing was submitted, so nothing succeeded."""
        notes: list[str] = []
        page = _page(_element(), _element(), None)  # input, then no button
        engagement = _engagement(page)

        with patch(f"{GATE}.note_comment_reply_sent", lambda *a: notes.append("sent")):
            result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == FAILED
        assert result["success"] is False
        assert result["error_code"] == "send_button_missing"
        # Nothing was submitted, so the daily ceiling must not move.
        assert notes == []
        page.wait_for_function.assert_not_awaited()

    async def test_a_submitted_reply_that_cannot_be_verified_is_unknown(self):
        """The click already happened: calling that a failure invites a double reply."""
        notes: list[str] = []
        page = _page(_element(), _element(), _element())
        page.wait_for_function = AsyncMock(side_effect=TimeoutError("5s"))
        engagement = _engagement(page)

        with patch(f"{GATE}.note_comment_reply_sent", lambda *a: notes.append("sent")):
            result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == UNKNOWN
        assert result["success"] is False
        assert result["error_code"] == "verification_timeout"
        assert result["retryable"] is False
        # A possible send counts against the ceiling: it cannot be taken back.
        assert notes == ["sent"]

    async def test_a_confirmed_reply_is_sent_but_carries_no_receipt(self):
        page = _page(_element(), _element(), _element())
        engagement = _engagement(page)

        with patch(f"{GATE}.note_comment_reply_sent", lambda *a: None):
            result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == SENT
        assert result["success"] is True
        assert result["verified"] is True
        # Defect 4: the id used to be ``reply_<timestamp>`` -- a clock reading.
        assert result["receipt_id"] == ""
        assert result["receipt_source"] == "none"
        assert result["correlation_id"].startswith("comment_reply-")
        assert result["retryable"] is False

    async def test_a_quota_block_is_reported_with_its_own_code(self):
        """Defect 2: the platform's verdict must survive the trip to the caller."""
        page = _page()

        class _Block:
            risk_code = "comment_reply_daily_limit"
            message = "今日评论回复额度已用完"

        engagement = _engagement(page)
        with patch(f"{GATE}.check_comment_reply_quota", lambda *a, **k: _Block()):
            result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == BLOCKED
        assert result["error_code"] == "comment_reply_daily_limit"
        assert result["retryable"] is False
        page.goto.assert_not_awaited()


class TestDirectMessageVerdicts:
    async def test_a_missing_send_button_no_longer_reports_success(self):
        """Defect 1 (the severe one): no DM went out, no quota may be spent."""
        notes: list[str] = []
        # query_selector order on the DM page: search input, textarea, send button.
        page = _page(None, _element(), None)
        engagement = _engagement(page)

        with patch(
            f"{GATE}.note_dm_sent",
            lambda *a, **k: notes.append({"args": a, "proactive": k.get("proactive")}),
        ):
            result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == FAILED
        assert result["success"] is False
        assert result["error_code"] == "send_button_missing"
        assert notes == []

    async def test_a_clicked_send_is_sent_but_unverified(self):
        page = _page(None, _element(), _element())
        notes: list[str] = []
        engagement = _engagement(page)

        with patch(
            f"{GATE}.note_dm_sent",
            lambda *a, **k: notes.append({"args": a, "proactive": k.get("proactive")}),
        ):
            result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == SENT
        assert result["success"] is True
        # No read-back exists yet, so the click must not be dressed as delivery.
        assert result["verified"] is False
        assert result["receipt_id"] == ""
        # "user-9" is nobody's inbound peer here, so the send is cold outreach
        # and the note must say so — otherwise the proactive budget counts
        # replies and stops bounding cold sends.
        assert notes == [{"args": ("acc-1",), "proactive": True}]

    async def test_a_cold_target_without_confirmation_never_reaches_the_browser(self):
        """§8 item 5: the gate is checked before any browser action, not after."""
        page = _page()
        engagement = _engagement(page)

        class _Block:
            risk_code = "dm_target_not_inbound"
            message = "冷启动私信需要人工确认"

        with patch(f"{GATE}.check_dm_target_allowed", lambda *a, **k: _Block()):
            result = await engagement.send_dm("cold-user", "你好", human_confirmed=False)

        assert result["status"] == BLOCKED
        assert result["error_code"] == "dm_target_not_inbound"
        engagement._ensure_page.assert_not_awaited()
        page.goto.assert_not_awaited()


class TestTheOutreachPolicyIsTheEntryRule:
    """§9.5 wiring at the engagement layer: who may be touched at all."""

    async def test_nobody_mode_blocks_a_comment_reply_before_any_browser_action(self):
        """``nobody`` closes the reply path too — a reply still touches a person."""
        engagement = _engagement(_page())
        policy = XhsOutreachPolicy(account_id="acc-1", mode=OUTREACH_NOBODY)

        with patch(
            "backend.services.xhs_outreach_policy.load_outreach_policy",
            AsyncMock(return_value=policy),
        ):
            result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == BLOCKED
        assert result["error_code"] == "outreach_suspended"
        engagement._ensure_page.assert_not_awaited()

    async def test_nobody_mode_blocks_a_dm_before_any_browser_action(self):
        engagement = _engagement(_page())
        policy = XhsOutreachPolicy(account_id="acc-1", mode=OUTREACH_NOBODY)

        with patch(
            "backend.services.xhs_outreach_policy.load_outreach_policy",
            AsyncMock(return_value=policy),
        ):
            result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == BLOCKED
        assert result["error_code"] == "outreach_suspended"
        engagement._ensure_page.assert_not_awaited()

    async def test_the_resolved_policy_is_what_the_target_gate_is_given(self):
        """The gate must see the account's policy — not its own safe default.

        If ``send_dm`` drops the argument, a ``confirmed_anyone`` account
        silently degrades to ``inbound_only`` and cold outreach never opens.
        """
        seen: dict[str, Any] = {}
        policy = XhsOutreachPolicy(
            account_id="acc-1", mode=OUTREACH_CONFIRMED, daily_proactive_cap=7
        )

        def _record_gate(account_id: str, target: str, **kwargs: Any) -> None:
            seen["account_id"] = account_id
            seen["target"] = target
            seen["policy"] = kwargs.get("policy")
            seen["human_confirmed"] = kwargs.get("human_confirmed")
            return None

        # query_selector slots on a cold confirmed DM: 新建私信 / 搜索框 /
        # 输入框 / 发送按钮.  The search slot is empty on purpose — this test
        # pins the gate wiring, not the search flow.
        page = _page(None, None, _element(), _element())
        engagement = _engagement(page)

        with (
            patch(
                "backend.services.xhs_outreach_policy.load_outreach_policy",
                AsyncMock(return_value=policy),
            ),
            patch(f"{GATE}.check_dm_target_allowed", _record_gate),
            patch(f"{GATE}.note_dm_sent", lambda *a, **k: None),
        ):
            result = await engagement.send_dm("cold-user", "你好", human_confirmed=True)

        assert result["status"] == SENT
        assert seen["policy"] is policy
        assert seen["human_confirmed"] is True

    async def test_a_reply_to_an_inbound_peer_never_spends_the_outreach_budget(self):
        """The note's ``proactive`` flag follows the inbound whitelist, not the caller."""
        notes: list[dict[str, Any]] = []
        page = _page(None, _element(), _element())
        engagement = _engagement(page)

        with (
            patch(f"{GATE}.is_inbound_peer", lambda *a, **k: True),
            patch(
                f"{GATE}.note_dm_sent",
                lambda *a, **k: notes.append({"proactive": k.get("proactive")}),
            ),
        ):
            result = await engagement.send_dm("friend", "你好")

        assert result["status"] == SENT
        assert notes == [{"proactive": False}]


class TestRetryabilityIsDerivedOnce:
    async def test_a_busy_cdp_session_is_retryable(self):
        """Transient by nature: the same call succeeds once the lock frees up."""
        engagement = _engagement(_page())
        engagement._hold_cdp = AsyncMock(side_effect=CdpSessionBusyError("acc-1", "stats"))

        result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == BLOCKED
        assert result["error_code"] == "cdp_busy"
        assert result["retryable"] is True

    async def test_every_unknown_code_defaults_to_not_retryable(self):
        """A write whose code we cannot explain must not be repeated automatically."""
        engagement = _engagement(_page())
        engagement._hold_cdp = AsyncMock(
            side_effect=EngagementRiskError("session_expired", "登录态已失效")
        )

        result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == BLOCKED
        assert result["retryable"] is False
