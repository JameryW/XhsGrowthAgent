"""Wiring of the outgoing reply guard into the two manual engagement tools.

Ledger #59/#94 are contracts; this file is what proves they are *called* before a
message leaves the building, and that the switch being off leaves the tools
byte-identical to before.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.reply_guard import REPLY_GUARD_ENV
from backend.tools.runtime.models import DomainOutcome
from backend.tools.xhs.engagement import comment_replier, dm_handler

MODULE = "backend.tools.xhs.engagement"

SENT: dict[str, Any] = {
    "success": True,
    "status": "sent",
    "error_code": "",
    "error": "",
    "receipt_id": "r-1",
    "receipt_source": "platform",
    "correlation_id": "corr-1",
    "verified": True,
    "retryable": False,
}

CLEAN = "国庆档期还有 3 台车，可以先看下路线再定。"
CLAIM = "已帮您查好 10 月 3 号的档期，还有 2 台车。"
PRESUPPOSITION = "看您上次带老人小孩，这次还选经济型吗？国庆档期还剩 3 台车，随时可以定。"


def _fake_engagement(verdict: dict[str, Any] | None = None) -> MagicMock:
    engagement = MagicMock()
    engagement.close = AsyncMock()
    engagement.reply_to_comment = AsyncMock(return_value=dict(verdict or SENT))
    engagement.send_dm = AsyncMock(return_value=dict(verdict or SENT))
    return engagement


def _patched(engagement: MagicMock):
    return (
        patch(f"{MODULE}._get_engagement", return_value=engagement),
        patch(f"{MODULE}._resolve_engagement_cdp_endpoint", AsyncMock(return_value="http://x")),
    )


class TestSwitchOff:
    async def test_comment_reply_is_untouched(self, monkeypatch) -> None:
        monkeypatch.delenv(REPLY_GUARD_ENV, raising=False)
        engagement = _fake_engagement()
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve:
            result = await comment_replier.ainvoke(
                {"comment_id": "c-1", "post_id": "p-1", "reply_content": CLAIM}
            )
        assert result["reply"] == CLAIM
        assert result["status"] == "sent"
        assert "reply_guard" not in result
        engagement.reply_to_comment.assert_awaited_once()
        assert engagement.reply_to_comment.await_args.kwargs["reply_content"] == CLAIM


class TestSwitchOn:
    async def test_blocked_comment_never_opens_the_browser(self, monkeypatch) -> None:
        monkeypatch.setenv(REPLY_GUARD_ENV, "1")
        engagement = _fake_engagement()
        with (
            patch(f"{MODULE}._get_engagement") as get_engagement,
            patch(
                f"{MODULE}._resolve_engagement_cdp_endpoint",
                AsyncMock(return_value="http://x"),
            ),
            pytest.raises(DomainOutcome) as exc,
        ):
            await comment_replier.ainvoke(
                {"comment_id": "c-1", "post_id": "p-1", "reply_content": CLAIM}
            )
        payload = exc.value.payload
        assert payload["status"] == "blocked"
        assert payload["error_code"] == "reply_guard"
        assert payload["reply_guard"]["blocked"] is True
        assert payload["comment_id"] == "c-1"
        get_engagement.assert_not_called()
        engagement.reply_to_comment.assert_not_awaited()

    async def test_clean_comment_is_sent_verbatim_with_the_report(self, monkeypatch) -> None:
        monkeypatch.setenv(REPLY_GUARD_ENV, "1")
        engagement = _fake_engagement()
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve:
            result = await comment_replier.ainvoke(
                {"comment_id": "c-1", "post_id": "p-1", "reply_content": CLEAN}
            )
        assert result["reply"] == CLEAN
        assert result["reply_guard"]["checked"] is True
        assert result["reply_guard"]["blocked"] is False

    async def test_scrubbed_dm_sends_the_pruned_text(self, monkeypatch) -> None:
        monkeypatch.setenv(REPLY_GUARD_ENV, "1")
        monkeypatch.setattr(
            f"{MODULE}._remember_fan_for_result",
            lambda result, sender_id, **kwargs: result,
        )
        engagement = _fake_engagement()
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve:
            result = await dm_handler.ainvoke(
                {"message_id": "m-1", "sender_id": "u-1", "reply_content": PRESUPPOSITION}
            )
        sent = engagement.send_dm.await_args.kwargs["message"]
        assert result["reply"] == sent
        assert "带老人" not in sent
        assert "国庆档期还剩 3 台车" in sent
        assert result["reply_guard"]["scrubbed"] is True

    async def test_dm_blocks_a_completion_claim_without_receipt(self, monkeypatch) -> None:
        monkeypatch.setenv(REPLY_GUARD_ENV, "1")
        monkeypatch.setattr(
            f"{MODULE}._remember_fan_for_result",
            lambda result, sender_id, **kwargs: result,
        )
        engagement = _fake_engagement()
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve, pytest.raises(DomainOutcome) as exc:
            await dm_handler.ainvoke(
                {"message_id": "m-1", "sender_id": "u-1", "reply_content": CLAIM}
            )
        payload = exc.value.payload
        assert payload["error_code"] == "reply_guard"
        assert payload["sender_id"] == "u-1"
        assert payload["reply_guard"]["missing_receipts"] == ["claim-1"]
        engagement.send_dm.assert_not_awaited()
