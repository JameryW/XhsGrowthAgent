"""Unit tests for the revise node's stall signal (P0-A, second consumer).

The node has one job (reset the draft and carry the verdict forward) and one
observer bolted on (record the round, emit a signal when the loop is cycling).
These tests pin both, and pin the boundary between them: the signal must never
change the outcome of the node — no routing key, no early exit, no budget
adjustment. The round cap remains the only decider.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.nodes.revise_content import revise_content_node
from backend.state.enums import WorkflowPhase
from backend.state.events import ACTION_EVENT_KIND
from backend.state.progress import (
    PROGRESS_EVENT_KIND,
    REVISION_SAME_HINTS,
)

#: The emitter is imported when the node runs, so patching the origin module is
#: what actually intercepts it (same reason as the publish_gate tests).
EMIT = "backend.state.events.emit_events"


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "thread-123",
        "account_id": "acct-1",
        "phase": WorkflowPhase.REVIEWING,
        "revision_count": 0,
        "human_feedback": {"comment": "keep me"},
    }
    base.update(overrides)
    return base


def _evaluation(*hints: str, score: float | None = 60.0) -> dict[str, Any]:
    return {
        "overall_score": score,
        "revision_hints": list(hints),
        "decision": "needs_revision",
    }


@pytest.mark.asyncio
class TestRevisionRecordIsWritten:
    async def test_first_round_records_one_verdict(self):
        state = _state(evaluation_result=_evaluation("标题缺具体收益", score=58.0))
        result = await revise_content_node(state, store=MagicMock())

        history = result["revision_history"]
        assert len(history) == 1
        assert history[0]["round"] == 1
        assert history[0]["score"] == 58.0
        assert history[0]["hints_digest"]

    async def test_no_verdict_records_nothing(self):
        # The human "needs_revision" path can reach this node without a panel
        # verdict; a fabricated record would look like "no change" next round.
        with patch(EMIT, new=AsyncMock(return_value=0)) as emit:
            result = await revise_content_node(_state(), store=MagicMock())
        assert "revision_history" not in result
        emit.assert_not_awaited()

    async def test_history_is_appended_not_replaced(self):
        prior = [
            {"round": 1, "score": 58.0, "hints_digest": "abc", "decision": "", "degraded": False}
        ]
        state = _state(
            revision_count=1,
            revision_history=prior,
            evaluation_result=_evaluation("标题缺具体收益", score=70.0),
        )
        result = await revise_content_node(state, store=MagicMock())

        # The node returns the delta; LangGraph's append_list reducer composes.
        assert result["revision_history"][0]["round"] == 2
        assert len(result["revision_history"]) == 1

    async def test_existing_behaviour_is_unchanged(self):
        state = _state(
            revision_count=1,
            copy_content={"selected_title": "旧标题"},
            visual_plan={"image_paths": ["a.jpg"]},
            evaluation_result=_evaluation("标题缺具体收益"),
        )
        result = await revise_content_node(state, store=MagicMock())

        assert result["revision_count"] == 2
        assert result["copy_content"] == {}
        assert result["visual_plan"] == {}
        assert result["phase"] == WorkflowPhase.CREATING
        assert result["human_feedback"]["revisions"] == ["标题缺具体收益"]
        assert result["human_feedback"]["comment"] == "keep me"


@pytest.mark.asyncio
class TestStallSignalIsEmitted:
    async def test_same_complaint_twice_emits_a_signal(self):
        # Round 1 goes through the node so both digests are derived the same way.
        first = await revise_content_node(
            _state(evaluation_result=_evaluation("标题缺具体收益", score=58.0)),
            store=MagicMock(),
        )
        state = _state(
            revision_count=1,
            revision_history=first["revision_history"],
            evaluation_result=_evaluation("标题缺具体收益", score=59.0),
        )

        with patch(EMIT, new=AsyncMock(return_value=1)) as emit:
            result = await revise_content_node(state, store=MagicMock())

        assert result["revision_count"] == 2
        emit.assert_awaited_once()
        thread_id, entries = emit.await_args.args
        assert thread_id == "thread-123"
        entry = entries[0]
        assert entry["kind"] == PROGRESS_EVENT_KIND
        assert entry["reason"] == REVISION_SAME_HINTS
        assert entry["account_id"] == "acct-1"
        assert entry["thread_id"] == "thread-123"

    async def test_progress_does_not_emit(self):
        first = await revise_content_node(
            _state(evaluation_result=_evaluation("标题缺具体收益", score=58.0)),
            store=MagicMock(),
        )
        state = _state(
            revision_count=1,
            revision_history=first["revision_history"],
            evaluation_result=_evaluation("正文第二段太虚", score=72.0),
        )
        with patch(EMIT, new=AsyncMock(return_value=0)) as emit:
            await revise_content_node(state, store=MagicMock())
        emit.assert_not_awaited()

    async def test_signal_never_changes_the_verdict(self):
        # Even when stalled, the node returns exactly the same keys as a healthy
        # round: no routing hint, no early phase change, no budget bump.
        first = await revise_content_node(
            _state(evaluation_result=_evaluation("标题缺具体收益", score=58.0)),
            store=MagicMock(),
        )
        healthy = await revise_content_node(
            _state(evaluation_result=_evaluation("正文第二段太虚", score=72.0)),
            store=MagicMock(),
        )
        state = _state(
            revision_count=1,
            revision_history=first["revision_history"],
            evaluation_result=_evaluation("标题缺具体收益", score=58.0),
        )
        with patch(EMIT, new=AsyncMock(return_value=1)):
            stalled = await revise_content_node(state, store=MagicMock())

        assert set(stalled) - {"revision_history"} == set(healthy) - {"revision_history"}

    async def test_missing_thread_id_does_not_break_the_node(self):
        # emit_events returns 0 for an empty thread id; the node must still
        # return its update (telemetry is never allowed to fail the run).
        first = await revise_content_node(
            _state(evaluation_result=_evaluation("标题缺具体收益", score=58.0)),
            store=MagicMock(),
        )
        state = {
            "phase": WorkflowPhase.REVIEWING,
            "revision_count": 1,
            "revision_history": first["revision_history"],
            "evaluation_result": _evaluation("标题缺具体收益", score=58.0),
        }
        result = await revise_content_node(state, store=MagicMock())
        assert result["revision_count"] == 2

    async def test_the_signal_is_not_an_action_refusal(self):
        # Two vocabularies share the timeline: progress is observation, action
        # is a refusal. Filing a stall under "action" would read as "denied".
        first = await revise_content_node(
            _state(evaluation_result=_evaluation("标题缺具体收益", score=58.0)),
            store=MagicMock(),
        )
        state = _state(
            revision_count=1,
            revision_history=first["revision_history"],
            evaluation_result=_evaluation("标题缺具体收益", score=58.0),
        )
        with patch(EMIT, new=AsyncMock(return_value=1)) as emit:
            await revise_content_node(state, store=MagicMock())
        entry = emit.await_args.args[1][0]
        assert entry["kind"] != ACTION_EVENT_KIND
