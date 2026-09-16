"""Unit tests for publish_gate_node — the human authorisation a real publish needs.

The node has one question to answer (does this run need a fresh yes?) and one
rule for reading the answer (only a literal ``"confirmed"`` is a yes).  Both are
pinned here, along with the reason the refusal path parks the run at
``phase=CANCELLED``: the publisher is skipped on refusal, so a phase left at
PUBLISHING would leave the run with no next node and ``derive_status`` would
report *completed* for a note that was never posted.

Whether the gate is wired into the compiled graph, and what ``AWAITING_PUBLISH``
derives from its interrupt, is covered separately (tests/unit/graph/ and the
status-machine tests).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.agents.nodes.publish_gate import (
    PUBLISH_CANCELLED,
    PUBLISH_CONFIRMED,
    SOURCE_AUTO_PUBLISH,
    SOURCE_DRY_RUN,
    SOURCE_HUMAN,
    publish_gate_node,
    publish_needs_confirmation,
)
from backend.core.error_handling import WorkflowCancelledError
from backend.state.enums import WorkflowPhase

#: Patch the name the node resolves at call time, not langgraph's own symbol.
INTERRUPT = "backend.agents.nodes.publish_gate.interrupt"


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "thread-123",
        "phase": WorkflowPhase.REVIEWING,
        "copy_content": {"selected_title": "标题"},
        "visual_plan": {"image_paths": ["a.jpg"]},
    }
    base.update(overrides)
    return base


class TestStandingAuthorisationSkipsTheGate:
    """``auto_publish`` / ``dry_run`` are explicit prior statements, so no yes is asked."""

    @pytest.mark.asyncio
    async def test_auto_publish_at_workflow_level_does_not_interrupt(self):
        with patch(INTERRUPT) as mock_int:
            result = await publish_gate_node(_state(auto_publish=True), store=MagicMock())
        mock_int.assert_not_called()
        assert result["phase"] == WorkflowPhase.PUBLISHING
        assert result["publish_confirmation"] == {
            "decision": PUBLISH_CONFIRMED,
            "source": SOURCE_AUTO_PUBLISH,
        }

    @pytest.mark.asyncio
    async def test_auto_publish_in_publish_options_does_not_interrupt(self):
        """The approve decision's publish_options carry a standing authorisation too."""
        state = _state(publish_options={"auto_publish": True})
        with patch(INTERRUPT) as mock_int:
            result = await publish_gate_node(state, store=MagicMock())
        mock_int.assert_not_called()
        assert result["publish_confirmation"]["source"] == SOURCE_AUTO_PUBLISH

    @pytest.mark.asyncio
    async def test_dry_run_at_workflow_level_does_not_interrupt(self):
        with patch(INTERRUPT) as mock_int:
            result = await publish_gate_node(_state(dry_run=True), store=MagicMock())
        mock_int.assert_not_called()
        assert result["phase"] == WorkflowPhase.PUBLISHING
        assert result["publish_confirmation"] == {
            "decision": PUBLISH_CONFIRMED,
            "source": SOURCE_DRY_RUN,
        }

    @pytest.mark.asyncio
    async def test_dry_run_in_publish_options_does_not_interrupt(self):
        state = _state(publish_options={"dry_run": True})
        with patch(INTERRUPT) as mock_int:
            result = await publish_gate_node(state, store=MagicMock())
        mock_int.assert_not_called()
        assert result["publish_confirmation"]["source"] == SOURCE_DRY_RUN


@pytest.mark.parametrize(
    ("state", "needs"),
    [
        ({}, True),
        ({"auto_publish": False}, True),
        ({"auto_publish": True}, False),
        ({"publish_options": {"auto_publish": True}}, False),
        # `is True`, not truthiness: a stand-in value is not a statement anyone
        # actually made, so the gate stays shut rather than assuming consent.
        ({"auto_publish": "true"}, True),
        ({"auto_publish": 1}, True),
        ({"publish_options": {"auto_publish": 1}}, True),
        ({"dry_run": False}, True),
        ({"dry_run": True}, False),
        ({"publish_options": {"dry_run": True}}, False),
        # The workflow-level flag is the stronger of the two: a thread started
        # as a rehearsal must stay one even when the approving decision asks for
        # a real publish.  Reading only publish_options would let it flip.
        ({"dry_run": True, "publish_options": {"dry_run": False}}, False),
        # dry_run is deliberately truthiness-based *because it is the same
        # function the publisher picks its mock path with* — gate and publisher
        # cannot disagree about whether anything actually leaves the machine.
        # auto_publish has no such twin, hence the strict comparison above.
        ({"dry_run": "yes"}, False),
    ],
)
def test_publish_needs_confirmation_truth_table(state: dict[str, Any], needs: bool):
    assert publish_needs_confirmation(state) is needs


class TestInterruptPayload:
    """The interrupt carries the ``gate="publish"`` contract derive_status reads."""

    @pytest.mark.asyncio
    async def test_payload_reports_what_is_about_to_be_posted(self):
        state = _state(
            copy_content={"selected_title": "露营装备清单"},
            visual_plan={"image_paths": ["a.jpg", "b.jpg"]},
            publish_options={"account_id": "acct-9"},
        )
        with patch(INTERRUPT, return_value={"decision": PUBLISH_CONFIRMED}) as mock_int:
            await publish_gate_node(state, store=MagicMock())

        payload = mock_int.call_args[0][0]
        assert payload["gate"] == "publish"
        assert payload["publish_summary"] == {
            "title": "露营装备清单",
            "has_images": True,
            "account_id": "acct-9",
        }

    @pytest.mark.asyncio
    async def test_payload_survives_an_empty_run(self):
        state = _state(copy_content={}, visual_plan={})
        with patch(INTERRUPT, return_value=None) as mock_int:
            await publish_gate_node(state, store=MagicMock())

        payload = mock_int.call_args[0][0]
        assert payload["publish_summary"] == {"title": "", "has_images": False, "account_id": ""}

    @pytest.mark.asyncio
    async def test_payload_falls_back_to_the_workflow_account(self):
        state = _state(account_id="acct-from-state")
        with patch(INTERRUPT, return_value=None) as mock_int:
            await publish_gate_node(state, store=MagicMock())

        assert mock_int.call_args[0][0]["publish_summary"]["account_id"] == "acct-from-state"


class TestDecisionHandling:
    @pytest.mark.asyncio
    async def test_confirmed_authorises_the_publish(self):
        with patch(INTERRUPT, return_value={"decision": PUBLISH_CONFIRMED}):
            result = await publish_gate_node(_state(), store=MagicMock())

        assert result["phase"] == WorkflowPhase.PUBLISHING
        assert result["current_agent"] == "publish_gate"
        assert result["publish_confirmation"] == {
            "decision": PUBLISH_CONFIRMED,
            "source": SOURCE_HUMAN,
            "comments": "",
        }

    @pytest.mark.asyncio
    async def test_cancelled_is_a_decision_not_a_fault(self):
        """A human saying "not this one" ends the run, it does not error it."""
        decision = {"decision": PUBLISH_CANCELLED, "comments": "标题不合适"}
        with patch(INTERRUPT, return_value=decision):
            result = await publish_gate_node(_state(), store=MagicMock())

        assert result["phase"] == WorkflowPhase.CANCELLED
        assert result["phase"] != WorkflowPhase.ERROR
        assert result["publish_confirmation"] == {
            "decision": PUBLISH_CANCELLED,
            "source": SOURCE_HUMAN,
            "comments": "标题不合适",
        }

    @pytest.mark.asyncio
    async def test_the_gate_writes_its_own_key(self):
        """It must not overwrite human_feedback — review_outcome routes on that."""
        state = _state(human_feedback={"decision": "approved"})
        with patch(INTERRUPT, return_value={"decision": PUBLISH_CANCELLED}):
            result = await publish_gate_node(state, store=MagicMock())

        assert "human_feedback" not in result
        assert result["publish_confirmation"]["decision"] == PUBLISH_CANCELLED

    @pytest.mark.parametrize(
        "resume_value",
        [
            None,  # resumed with no decision at all
            {},  # an empty object
            {"decision": None},
            {"decision": ""},
            {"decision": "yes"},
            {"decision": "Confirmed"},  # case matters
            {"decision": "CONFIRMED"},
            {"decision": "confirmed "},  # a trailing space is not a yes
            {"decision": True},
            {"decision": 1},
            "confirmed",  # a bare string is not this gate's contract
            {"approved": True},  # the review_gate dialect, not this one
        ],
    )
    @pytest.mark.asyncio
    async def test_everything_but_confirmed_refuses(self, resume_value: Any):
        """The failure direction is closed — version skew must not read as consent.

        A confirmation gate that treats an unrecognised value as "go ahead" turns
        every version skew into an unconfirmed real publish, which is the exact
        failure this node exists to prevent.
        """
        with patch(INTERRUPT, return_value=resume_value):
            result = await publish_gate_node(_state(), store=MagicMock())

        assert result["phase"] == WorkflowPhase.CANCELLED
        assert result["publish_confirmation"]["decision"] == PUBLISH_CANCELLED


class TestAlreadyTerminalRunIsNotAsked:
    @pytest.mark.asyncio
    async def test_cancelled_phase_raises_before_the_gate(self):
        with patch(INTERRUPT) as mock_int, pytest.raises(WorkflowCancelledError):
            await publish_gate_node(_state(phase=WorkflowPhase.CANCELLED), store=MagicMock())
        mock_int.assert_not_called()

    @pytest.mark.asyncio
    async def test_paused_phase_raises_before_the_gate(self):
        with patch(INTERRUPT) as mock_int, pytest.raises(WorkflowCancelledError):
            await publish_gate_node(_state(phase=WorkflowPhase.PAUSED), store=MagicMock())
        mock_int.assert_not_called()
