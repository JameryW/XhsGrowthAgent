"""Fan-relation memory is updated only after a successful DM."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.runtime.models import DomainOutcome
from backend.tools.xhs.engagement import dm_handler, reset_fan_relation_store, suggest_icebreaker

MODULE = "backend.tools.xhs.engagement"


def _sent_verdict() -> dict[str, Any]:
    return {
        "success": True,
        "status": "sent",
        "error_code": "",
        "error": "",
        "receipt_id": "",
        "receipt_source": "none",
        "correlation_id": "dm-fan-1",
        "verified": False,
        "retryable": False,
    }


def _fake_engagement(verdict: dict[str, Any]) -> MagicMock:
    engagement = MagicMock()
    engagement.close = AsyncMock()
    engagement.send_dm = AsyncMock(return_value=verdict)
    return engagement


def _patched(engagement: MagicMock):
    return (
        patch(f"{MODULE}._get_engagement", return_value=engagement),
        patch(f"{MODULE}._resolve_engagement_cdp_endpoint", AsyncMock(return_value="http://x")),
    )


@pytest.fixture(autouse=True)
def _fan_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XHS_FAN_RELATION_PATH", str(tmp_path / "fan_relations.json"))
    reset_fan_relation_store()
    yield
    reset_fan_relation_store()


class TestDmHandlerFanMemory:
    async def test_successful_dm_records_a_fan_and_returns_an_icebreaker(self):
        engagement = _fake_engagement(_sent_verdict())
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve:
            result = await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-1",
                    "reply_content": "收到",
                    "sender_nickname": "小鹿",
                    "fan_interests": ["通勤穿搭"],
                    "fan_topic": "通勤穿搭",
                }
            )

        assert result["fan_profile"]["user_id"] == "u-1"
        assert result["fan_profile"]["nickname"] == "小鹿"
        assert result["fan_profile"]["interaction_count"] == 1
        assert "小鹿" in result["icebreaker"]
        assert "通勤穿搭" in suggest_icebreaker("u-1", "通勤穿搭")

    async def test_repeated_dm_increments_the_existing_profile(self):
        engagement = _fake_engagement(_sent_verdict())
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve:
            await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-1",
                    "reply_content": "收到",
                    "sender_nickname": "小鹿",
                }
            )
            result = await dm_handler.ainvoke(
                {
                    "message_id": "m-2",
                    "sender_id": "u-1",
                    "reply_content": "再次收到",
                    "fan_interests": ["半身裙"],
                }
            )

        assert result["fan_profile"]["interaction_count"] == 2
        assert "半身裙" in result["fan_profile"]["interests"]

    async def test_blocked_dm_does_not_create_a_fan_record(self):
        engagement = _fake_engagement({"status": "blocked", "success": False})
        get_engagement, resolve = _patched(engagement)
        with get_engagement, resolve, pytest.raises(DomainOutcome):
            await dm_handler.ainvoke(
                {
                    "message_id": "m-1",
                    "sender_id": "u-blocked",
                    "reply_content": "收到",
                    "sender_nickname": "未发送",
                }
            )

        assert suggest_icebreaker("u-blocked") == ""
