"""Tests for orchestrator_node event emission — dry_run default correctness.

The WORKFLOW_STARTED event payload includes ``dry_run``. The default was
``True`` (state.get("dry_run", True)), which is wrong: the API default is
``False`` (WorkflowStartRequest.dry_run = Field(default=False)), and a
missing ``dry_run`` key should not imply a dry run. This would mislead
consumers (frontend, OMP) into thinking a live workflow is a dry run.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.nodes.orchestrator import orchestrator_node
from backend.realtime.events import EventType
from backend.state.schema import WorkflowPhase


class TestOrchestratorNodeDryRunDefault:
    """Verify the dry_run default in WORKFLOW_STARTED is False, not True."""

    @pytest.mark.asyncio
    async def test_dry_run_defaults_false_when_missing(self):
        """When state has no dry_run key, the event reports dry_run=False.

        Previously defaulted to True (bug), misleading consumers into
        thinking a live workflow is a dry run.
        """
        state: dict = {
            "session_id": "thread-123",
            "phase": WorkflowPhase.SCOUTING,
            "account_id": "test_account",
            # dry_run intentionally absent — must default to False
        }

        emitted: list[dict] = []
        mock_bus = MagicMock()
        mock_bus.emit = MagicMock(
            side_effect=lambda etype, thread_id, payload: emitted.append(
                {"type": etype, "thread_id": thread_id, "payload": payload}
            )
        )

        with (
            patch(
                "backend.agents.nodes.orchestrator._orchestrator",
                new=AsyncMock(return_value={"phase": WorkflowPhase.SCOUTING}),
            ),
            patch(
                "backend.agents.nodes.orchestrator.EventBusService.get_instance",
                return_value=mock_bus,
            ),
        ):
            await orchestrator_node(state, store=MagicMock())

        # Compare against the EventType enum directly — robust across Python
        # versions. str(StrEnum) returns the value ("workflow.started"), not
        # the member name, so substring matching on "WORKFLOW_STARTED" fails
        # silently on Python 3.11+.
        started_events = [e for e in emitted if e["type"] == EventType.WORKFLOW_STARTED]
        assert len(started_events) == 1
        assert started_events[0]["payload"]["dry_run"] is False

    @pytest.mark.asyncio
    async def test_dry_run_preserved_when_true(self):
        """When state.dry_run=True, the event reports dry_run=True."""
        state: dict = {
            "session_id": "thread-456",
            "phase": WorkflowPhase.SCOUTING,
            "account_id": "test_account",
            "dry_run": True,
        }

        emitted: list[dict] = []
        mock_bus = MagicMock()
        mock_bus.emit = MagicMock(
            side_effect=lambda etype, thread_id, payload: emitted.append(
                {"type": etype, "thread_id": thread_id, "payload": payload}
            )
        )

        with (
            patch(
                "backend.agents.nodes.orchestrator._orchestrator",
                new=AsyncMock(return_value={"phase": WorkflowPhase.SCOUTING}),
            ),
            patch(
                "backend.agents.nodes.orchestrator.EventBusService.get_instance",
                return_value=mock_bus,
            ),
        ):
            await orchestrator_node(state, store=MagicMock())

        started_events = [e for e in emitted if e["type"] == EventType.WORKFLOW_STARTED]
        assert len(started_events) == 1
        assert started_events[0]["payload"]["dry_run"] is True

    @pytest.mark.asyncio
    async def test_dry_run_preserved_when_false(self):
        """When state.dry_run=False, the event reports dry_run=False."""
        state: dict = {
            "session_id": "thread-789",
            "phase": WorkflowPhase.SCOUTING,
            "account_id": "test_account",
            "dry_run": False,
        }

        emitted: list[dict] = []
        mock_bus = MagicMock()
        mock_bus.emit = MagicMock(
            side_effect=lambda etype, thread_id, payload: emitted.append(
                {"type": etype, "thread_id": thread_id, "payload": payload}
            )
        )

        with (
            patch(
                "backend.agents.nodes.orchestrator._orchestrator",
                new=AsyncMock(return_value={"phase": WorkflowPhase.SCOUTING}),
            ),
            patch(
                "backend.agents.nodes.orchestrator.EventBusService.get_instance",
                return_value=mock_bus,
            ),
        ):
            await orchestrator_node(state, store=MagicMock())

        started_events = [e for e in emitted if e["type"] == EventType.WORKFLOW_STARTED]
        assert len(started_events) == 1
        assert started_events[0]["payload"]["dry_run"] is False
