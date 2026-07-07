"""Tests for visual_designer_node error-state handling.

After prd 07-07-remove-handle-agent-error-dead-code, BaseAgent.__call__
returns an error state (phase=ERROR, error, retry_count) instead of raising
on failure. The visual_designer_node previously unconditionally set
``result["phase"] = "reviewing"`` after the agent call, which masked the
error phase — the workflow would continue to review_gate with broken
visual_plan data instead of terminating.

These tests lock in the fix: when the agent fails (no visual_plan key in
result), the node must NOT overwrite phase and must propagate the error
state as-is.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agents.nodes.visual_designer import visual_designer_node
from backend.state.enums import WorkflowPhase


class TestVisualDesignerNodeErrorState:
    """Verify visual_designer_node preserves error state on agent failure."""

    @pytest.mark.asyncio
    async def test_failure_preserves_error_phase(self):
        """When the visual_designer agent fails, the node must NOT overwrite
        phase=ERROR with "reviewing". The error state from __call__ must
        propagate as-is so _check_terminal catches it and the graph terminates.
        """
        state = {
            "session_id": "test-vd-error",
            "phase": WorkflowPhase.CREATING,
            "current_agent": "copywriter",
            "retry_count": 0,
        }

        # Patch the agent's execute to raise → __call__ catches and returns
        # handle_agent_error dict (phase=ERROR, error, retry_count, ...).
        from backend.agents.nodes.visual_designer import _visual_designer

        async def _failing_execute(self, state, store):
            raise RuntimeError("visual designer LLM failed")

        with patch.object(type(_visual_designer), "execute", _failing_execute):
            result = await visual_designer_node(state, store=None)

        # The error phase must be preserved — NOT overwritten to "reviewing"
        assert result.get("phase") == WorkflowPhase.ERROR, (
            "visual_designer_node must not mask phase=ERROR on agent failure; "
            f"got phase={result.get('phase')}"
        )
        assert "visual designer LLM failed" in result.get("error", "")
        assert result.get("retry_count") == 1
        assert result.get("current_agent") == "visual_designer"

    @pytest.mark.asyncio
    async def test_success_sets_reviewing_phase(self):
        """When the visual_designer agent succeeds, the node sets phase=reviewing
        as before (no regression on the happy path)."""
        state = {
            "session_id": "test-vd-success",
            "phase": WorkflowPhase.CREATING,
            "current_agent": "copywriter",
            "retry_count": 0,
        }

        from backend.agents.nodes.visual_designer import _visual_designer

        async def _success_execute(self, state, store):
            return {
                "visual_plan": {"cover_prompt": "test cover", "layout_type": "grid"},
                "phase": WorkflowPhase.CREATING,
            }

        with patch.object(type(_visual_designer), "execute", _success_execute):
            result = await visual_designer_node(state, store=None)

        # Success path: phase advanced to reviewing
        assert result.get("phase") == "reviewing"
        assert "visual_plan" in result
