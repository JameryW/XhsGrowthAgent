"""Ledger #62: the publish gate refuses an incomplete note before anyone is asked.

``publish_preflight`` decides whether the note's coupling and realization edges
exist; this file pins the *seam* — that the gate consults it only when the
opt-in switch is on, that a broken note is refused without waking a human, and
that the refusal is the same kind of durable telemetry a human refusal is.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.nodes.publish_gate import (
    PUBLISH_CANCELLED,
    PUBLISH_CONFIRMED,
    REFUSAL_INTERLOCK,
    SOURCE_AUTO_PUBLISH,
    SOURCE_PREFLIGHT,
    publish_gate_node,
)
from backend.services import publish_preflight
from backend.state.enums import WorkflowPhase

INTERRUPT = "backend.agents.nodes.publish_gate.interrupt"
EMIT = "backend.state.events.emit_events"

#: A note whose body promises a second card the visual plan never drew.
BROKEN_COPY = {"selected_title": "川西自驾 7 天", "body_text": "实测对比表见图 2。"}
BROKEN_VISUAL = {"image_prompts": ["封面：折多山垭口"]}

HEALTHY_COPY = {"selected_title": "川西自驾 7 天", "body_text": "路线和花费都写在下面。"}
HEALTHY_VISUAL = {"image_prompts": ["封面", "路线表", "清单"]}


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "thread-123",
        "phase": WorkflowPhase.REVIEWING,
        "copy_content": dict(HEALTHY_COPY),
        "visual_plan": dict(HEALTHY_VISUAL),
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(publish_preflight.PREFLIGHT_ENV, raising=False)


@pytest.fixture
def switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(publish_preflight.PREFLIGHT_ENV, "1")


class TestSwitchOff:
    """Default deployment: the node result and payload keep their old shape."""

    @pytest.mark.asyncio
    async def test_result_carries_no_preflight_key(self) -> None:
        state = _state(auto_publish=True, copy_content=dict(BROKEN_COPY))
        with patch(INTERRUPT) as mock_int:
            result = await publish_gate_node(state, store=MagicMock())

        mock_int.assert_not_called()
        assert result["phase"] == WorkflowPhase.PUBLISHING
        assert result["publish_confirmation"]["decision"] == PUBLISH_CONFIRMED
        assert "publish_preflight" not in result

    @pytest.mark.asyncio
    async def test_interrupt_payload_keeps_its_exact_keys(self) -> None:
        with patch(INTERRUPT, return_value={"decision": PUBLISH_CONFIRMED}) as mock_int:
            await publish_gate_node(_state(), store=MagicMock())

        summary = mock_int.call_args[0][0]["publish_summary"]
        assert "interlock" not in summary


class TestSwitchOn:
    """Opted-in deployment: an incomplete note never reaches a human."""

    @pytest.mark.asyncio
    async def test_broken_card_reference_is_refused_before_the_human(self, switch_on: None) -> None:
        state = _state(
            auto_publish=True,
            copy_content=dict(BROKEN_COPY),
            visual_plan=dict(BROKEN_VISUAL),
            publish_options={"account_id": "acct-9"},
        )
        with (
            patch(INTERRUPT) as mock_int,
            patch(EMIT, new_callable=AsyncMock) as emit,
        ):
            result = await publish_gate_node(state, store=MagicMock())

        mock_int.assert_not_called()
        confirmation = result["publish_confirmation"]
        assert result["phase"] == WorkflowPhase.CANCELLED
        assert confirmation["decision"] == PUBLISH_CANCELLED
        assert confirmation["source"] == SOURCE_PREFLIGHT
        assert confirmation["error_code"] == REFUSAL_INTERLOCK
        assert "coupling:body->carousel[2]" in confirmation["comments"]
        assert result["is_blocking"] is True
        assert result["publish_preflight"]["checked"] is True
        assert result["publish_preflight"]["blocked"] is True

        _thread_id, entries = emit.await_args[0]
        (entry,) = entries
        assert entry["reason"] == REFUSAL_INTERLOCK
        assert entry["gate"] == "publish"
        assert entry["account_id"] == "acct-9"

    @pytest.mark.asyncio
    async def test_healthy_note_is_confirmed_and_reports_the_check(self, switch_on: None) -> None:
        state = _state(auto_publish=True)
        with patch(INTERRUPT) as mock_int:
            result = await publish_gate_node(state, store=MagicMock())

        mock_int.assert_not_called()
        assert result["phase"] == WorkflowPhase.PUBLISHING
        assert result["publish_confirmation"]["source"] == SOURCE_AUTO_PUBLISH
        assert result["publish_preflight"] == {
            "checked": True,
            "blocked": False,
            "issues": [],
            "effects": [],
        }

    @pytest.mark.asyncio
    async def test_human_payload_carries_the_interlock_summary(self, switch_on: None) -> None:
        with patch(INTERRUPT, return_value={"decision": PUBLISH_CONFIRMED}) as mock_int:
            result = await publish_gate_node(_state(), store=MagicMock())

        summary = mock_int.call_args[0][0]["publish_summary"]
        assert summary["interlock"]["checked"] is True
        assert summary["interlock"]["blocked"] is False
        assert result["publish_preflight"]["checked"] is True

    @pytest.mark.asyncio
    async def test_missing_effect_blocks_even_though_the_cards_exist(self, switch_on: None) -> None:
        state = _state(auto_publish=True, copy_content={"body_text": "置顶评论领路书。"})
        with patch(INTERRUPT):
            result = await publish_gate_node(state, store=MagicMock())

        reasons = [issue["reason"] for issue in result["publish_preflight"]["issues"]]
        assert reasons == ["pinned_comment_not_scheduled"]
        assert result["phase"] == WorkflowPhase.CANCELLED
