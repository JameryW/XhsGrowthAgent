"""Wiring of the DM quota uplift allocator into ``dm_handler`` (ledger #44).

The contract lives in ``backend/services/dm_uplift.py``; this file proves the
manual DM tool consults it *before* the browser is opened and that the switch
being off leaves the tool byte-identical.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.dm_uplift import DM_UPLIFT_ENV
from backend.tools.runtime.models import DomainOutcome
from backend.tools.xhs.engagement import dm_handler

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
EAGER = "多少钱？押金怎么定"
BLAND = "你好呀"
HOSTILE = "骗子，我要举报你们"


def _fake_engagement(verdict: dict[str, Any] | None = None) -> MagicMock:
    engagement = MagicMock()
    engagement.close = AsyncMock()
    engagement.send_dm = AsyncMock(return_value=dict(verdict or SENT))
    return engagement


def _patched(engagement: MagicMock):
    return (
        patch(f"{MODULE}._get_engagement", return_value=engagement),
        patch(f"{MODULE}._resolve_engagement_cdp_endpoint", AsyncMock(return_value="http://x")),
        patch(
            f"{MODULE}._remember_fan_for_result",
            lambda result, sender_id, **kwargs: result,
        ),
    )


class TestSwitchOff:
    async def test_dm_is_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(DM_UPLIFT_ENV, raising=False)
        engagement = _fake_engagement()
        with _patched(engagement)[0], _patched(engagement)[1], _patched(engagement)[2]:
            result = await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-1",
                    "reply_content": CLEAN,
                    "inbound_message": BLAND,
                }
            )
        assert result["status"] == "sent"
        assert "dm_uplift" not in result
        engagement.send_dm.assert_awaited_once()


class TestSwitchOn:
    async def test_persuadable_dm_is_sent_with_the_report(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DM_UPLIFT_ENV, "1")
        engagement = _fake_engagement()
        with _patched(engagement)[0], _patched(engagement)[1], _patched(engagement)[2]:
            result = await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-1",
                    "reply_content": CLEAN,
                    "inbound_message": EAGER,
                }
            )
        assert result["status"] == "sent"
        report = result["dm_uplift"]
        assert report["priors"] == "fixed"
        assert report["stratum"] == "persuadables"
        assert report["action"] == "full_fsm"
        assert report["may_send"] is True
        engagement.send_dm.assert_awaited_once()

    async def test_lost_cause_defers_without_opening_the_browser(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DM_UPLIFT_ENV, "1")
        engagement = _fake_engagement()
        with (
            patch(f"{MODULE}._get_engagement") as get_engagement,
            patch(
                f"{MODULE}._resolve_engagement_cdp_endpoint",
                AsyncMock(return_value="http://x"),
            ),
            pytest.raises(DomainOutcome) as exc,
        ):
            await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-1",
                    "reply_content": CLEAN,
                    "inbound_message": BLAND,
                }
            )
        payload = exc.value.payload
        assert payload["status"] == "blocked"
        assert payload["error_code"] == "dm_quota_preserved"
        assert payload["hint"] == "public_reply_only"
        assert payload["dm_uplift"]["stratum"] == "lost_causes"
        get_engagement.assert_not_called()
        engagement.send_dm.assert_not_awaited()

    async def test_hostile_dm_gets_the_uplift_block_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DM_UPLIFT_ENV, "1")
        with (
            patch(f"{MODULE}._get_engagement") as get_engagement,
            patch(
                f"{MODULE}._resolve_engagement_cdp_endpoint",
                AsyncMock(return_value="http://x"),
            ),
            pytest.raises(DomainOutcome) as exc,
        ):
            await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-1",
                    "reply_content": CLEAN,
                    "inbound_message": HOSTILE,
                }
            )
        payload = exc.value.payload
        assert payload["error_code"] == "dm_uplift_blocked"
        assert payload["hint"] == "silent_block"
        assert payload["dm_uplift"]["stratum"] == "sleeping_dogs"
        get_engagement.assert_not_called()

    async def test_thin_evidence_sends_instead_of_blocking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DM_UPLIFT_ENV, "1")
        engagement = _fake_engagement()
        with _patched(engagement)[0], _patched(engagement)[1], _patched(engagement)[2]:
            result = await dm_handler.ainvoke(
                {"message_id": "m-1", "sender_id": "u-1", "reply_content": CLEAN}
            )
        assert result["status"] == "sent"
        assert result["dm_uplift"]["evidence_sufficient"] is False
        engagement.send_dm.assert_awaited_once()

    async def test_qualification_slots_flow_into_the_assessment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DM_UPLIFT_ENV, "1")
        with (
            patch(f"{MODULE}._get_engagement") as get_engagement,
            patch(
                f"{MODULE}._resolve_engagement_cdp_endpoint",
                AsyncMock(return_value="http://x"),
            ),
            pytest.raises(DomainOutcome) as exc,
        ):
            await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-1",
                    "reply_content": CLEAN,
                    "qualification_state": {
                        "slots": {
                            "date": "10-01",
                            "item_tier": "SUV",
                            "pickup_region": "成都东站",
                        }
                    },
                }
            )
        payload = exc.value.payload
        assert payload["dm_uplift"]["signals"]["qualified_slots"] == 3
        assert payload["dm_uplift"]["evidence_sufficient"] is True
        get_engagement.assert_not_called()
