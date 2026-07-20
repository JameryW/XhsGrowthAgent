"""Unit tests for brief_gate_node interrupt/resume paths.

Status-derivation coverage for brief_gate lives in test_brief_mode_status.py;
this file covers the node's own decision handling (skip / answer merge),
which previously had no node-level tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agents.nodes.brief_gate import brief_gate_node
from backend.state.schema import WorkflowPhase


def _state(**overrides):
    base = {
        "session_id": "thread-123",
        "phase": WorkflowPhase.BRIEFING,
    }
    base.update(overrides)
    return base


class TestBriefGateNode:
    @pytest.mark.asyncio
    async def test_no_clarification_proceeds(self):
        """No clarification in state → proceed without interrupt."""
        with patch("backend.agents.nodes.brief_gate.interrupt") as mock_int:
            result = await brief_gate_node(_state(), store=MagicMock())
        mock_int.assert_not_called()
        assert result["phase"] == WorkflowPhase.BRIEFING

    @pytest.mark.asyncio
    async def test_resolved_clarification_proceeds(self):
        """resolved=True → proceed without interrupt."""
        state = _state(brief_clarification={"questions": [], "resolved": True})
        with patch("backend.agents.nodes.brief_gate.interrupt") as mock_int:
            result = await brief_gate_node(state, store=MagicMock())
        mock_int.assert_not_called()
        assert result["phase"] == WorkflowPhase.BRIEFING

    @pytest.mark.asyncio
    async def test_unresolved_interrupts_with_questions(self):
        """Unresolved clarification → interrupt carrying the questions."""
        questions = [{"id": "q1", "question": "目标人群?"}]
        state = _state(brief_clarification={"questions": questions, "resolved": False})
        with patch(
            "backend.agents.nodes.brief_gate.interrupt",
            return_value={"action": "skip"},
        ) as mock_int:
            result = await brief_gate_node(state, store=MagicMock())
        mock_int.assert_called_once()
        payload = mock_int.call_args[0][0]
        assert payload["gate"] == "brief_clarification"
        assert payload["questions"] == questions
        # Skip → clarification marked resolved, brief_content untouched
        assert result["brief_clarification"] == {"questions": [], "resolved": True}
        assert "brief_content" not in result

    @pytest.mark.asyncio
    async def test_answer_merges_into_brief_content(self):
        """Answers merge into brief_content; empty/None values dropped."""
        state = _state(
            brief_clarification={"questions": [{"id": "q1"}], "resolved": False},
            brief_content={"brand_name": "ACME"},
        )
        with patch(
            "backend.agents.nodes.brief_gate.interrupt",
            return_value={
                "action": "answer",
                "answers": {"product_name": "Widget", "content_direction": "", "tone": None},
            },
        ):
            result = await brief_gate_node(state, store=MagicMock())
        assert result["brief_clarification"] == {"questions": [], "resolved": True}
        merged = result["brief_content"]
        assert merged["brand_name"] == "ACME"  # preserved
        assert merged["product_name"] == "Widget"  # added
        assert "content_direction" not in merged  # empty string dropped
        assert "tone" not in merged  # None dropped
