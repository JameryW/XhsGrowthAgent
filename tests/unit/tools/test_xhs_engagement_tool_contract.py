"""The two manual engagement tools must not be a second normalisation site.

Spec §1.3 / §8 item 4: a tool that catches everything and returns
``{"success": False}`` makes the Gateway read a transport failure as a
successful call. The tools therefore pass the platform verdict through and let
exceptions travel -- exactly what ``backend/tools/xhs/publisher.py`` already
does for ``xhs.publish``. Since 票 5f the non-``sent`` verdicts travel as
``DomainOutcome`` too (an answer, never retried), so ``ok=True`` through the
Gateway strictly means "sent".
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.runtime.models import DomainOutcome
from backend.tools.xhs.engagement import comment_replier, dm_handler

MODULE = "backend.tools.xhs.engagement"


def _fake_engagement(verdict: Any = None, *, raises: Exception | None = None) -> MagicMock:
    engagement = MagicMock()
    engagement.close = AsyncMock()
    if raises is not None:
        engagement.reply_to_comment = AsyncMock(side_effect=raises)
        engagement.send_dm = AsyncMock(side_effect=raises)
    else:
        engagement.reply_to_comment = AsyncMock(return_value=verdict)
        engagement.send_dm = AsyncMock(return_value=verdict)
    return engagement


def _patched(engagement: MagicMock):
    return (
        patch(f"{MODULE}._get_engagement", return_value=engagement),
        patch(f"{MODULE}._resolve_engagement_cdp_endpoint", AsyncMock(return_value="http://x")),
    )


VERDICT = {
    "success": False,
    "status": "failed",
    "error_code": "send_button_missing",
    "error": "未找到发送按钮：回复未提交",
    "receipt_id": "",
    "receipt_source": "none",
    "correlation_id": "comment_reply-abc123",
    "verified": False,
    "retryable": False,
}


class TestCommentReplierPassesTheVerdictThrough:
    async def test_every_verdict_field_survives_and_the_request_is_echoed(self):
        engagement = _fake_engagement(dict(VERDICT))
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve, pytest.raises(DomainOutcome) as exc:
            await comment_replier.ainvoke(
                {
                    "comment_id": "c-1",
                    "post_id": "p-1",
                    "reply_content": "谢谢",
                    "account_id": "acc-1",
                }
            )

        # The verdict is the answer: everything arrives in the domain payload.
        result = exc.value.payload
        assert result["status"] == "failed"
        assert result["error_code"] == "send_button_missing"
        assert result["receipt_source"] == "none"
        assert result["correlation_id"] == "comment_reply-abc123"
        # Request identity is echoed for the operator, not invented as a receipt.
        assert result["comment_id"] == "c-1"
        assert result["post_id"] == "p-1"
        assert "reply_id" not in result

    async def test_the_session_is_closed_even_when_the_call_fails(self):
        engagement = _fake_engagement(raises=RuntimeError("page crashed"))
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve, pytest.raises(RuntimeError, match="page crashed"):
            await comment_replier.ainvoke(
                {"comment_id": "c-1", "post_id": "p-1", "reply_content": "谢谢"}
            )

        engagement.close.assert_awaited_once()

    async def test_an_exception_is_no_longer_turned_into_a_dict(self):
        """The removal is the point: a dict here is indistinguishable from a call."""
        engagement = _fake_engagement(raises=TimeoutError("submit timeout"))
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve, pytest.raises(TimeoutError):
            await comment_replier.ainvoke(
                {"comment_id": "c-1", "post_id": "p-1", "reply_content": "谢谢"}
            )


class TestDmHandlerPassesTheVerdictThrough:
    async def test_the_inbound_message_id_is_echoed_not_confused_with_a_receipt(self):
        engagement = _fake_engagement(
            {
                "success": True,
                "status": "sent",
                "error_code": "",
                "error": "",
                "receipt_id": "",
                "receipt_source": "none",
                "correlation_id": "dm-def456",
                "verified": False,
                "retryable": False,
            }
        )
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve:
            try:
                result = await dm_handler.ainvoke(
                    {
                        "message_id": "inbound-7",
                        "sender_id": "u-1",
                        "reply_content": "收到",
                        "account_id": "acc-1",
                    }
                )
            except DomainOutcome as exc:
                # Assertion-shaped red (not a crash) if the sent/delivered
                # boundary ever inverts: sent must return its dict.
                pytest.fail(f"status=sent must return its dict, not raise: {exc.reason}")

        assert result["status"] == "sent"
        # ``message_id`` is the one the caller passed in; the outbound receipt is
        # empty because the page echoed nothing.
        assert result["message_id"] == "inbound-7"
        assert result["receipt_id"] == ""
        assert result["verified"] is False
        assert "reply_id" not in result
        # Inbound reply: no per-item approval record, and none is invented.
        assert engagement.send_dm.await_args.kwargs["approval"] is None

    async def test_the_approval_record_is_forwarded_to_the_platform_layer(self):
        """Drop it here and the cold-start gate silently stops existing."""
        engagement = _fake_engagement({"status": "blocked", "success": False})
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve, pytest.raises(DomainOutcome):
            await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-1",
                    "reply_content": "收到",
                    "approved_by": "operator-1",
                    "approved_at": "2026-10-13T00:00:00+00:00",
                    "thread_id": "thread-1",
                }
            )

        approval = engagement.send_dm.await_args.kwargs["approval"]
        assert approval is not None
        assert approval.approved_by == "operator-1"
        assert approval.approved_at == "2026-10-13T00:00:00+00:00"
        assert approval.thread_id == "thread-1"

    async def test_a_partial_approval_record_is_rejected_not_silently_dropped(self):
        """半条审批记录 = 那个自声明 bool 换了个形状，构造时就该炸（§7.2）。"""
        engagement = _fake_engagement({"status": "blocked", "success": False})
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve, pytest.raises(ValueError, match="三件套"):
            await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-1",
                    "reply_content": "收到",
                    "approved_by": "operator-1",
                }
            )

        engagement.send_dm.assert_not_awaited()
