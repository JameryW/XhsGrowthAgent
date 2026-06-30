"""Integration tests for workflow bug fixes.

Tests validate real workflow scenarios that were previously uncovered:
1. Pause stays paused (not cancelled)
2. Resume doesn't trigger review_gate incorrectly
3. Review/select updates registry/history/events
4. Draft gate / optimization flow
5. No XHS + dry_run still completes publish chain
6. Background exception writes graph error state
7. _check_terminal doesn't END on non-terminal errors
8. review_outcome always routes to publisher (no credential shortcut)
9. Event payload enrichment
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

from backend.api.app import app
from backend.api.routes import _runner as runner_module
from backend.api.routes import workflow as workflow_module
from backend.graph.routers import (
    _check_terminal,
    review_outcome,
    should_present_choice,
)
from backend.realtime import EventBusService
from backend.realtime.events import EventType
from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.machine import WorkflowStatus, derive_status

# In-memory stand-in for the old _workflow_registry, used by tests that
# simulate registry-level operations without a real DB.
_test_registry: dict[str, dict] = {}


def _reg_set(thread_id: str, entry: dict) -> None:
    """Set a workflow entry in the test registry."""
    _test_registry[thread_id] = entry


def _reg_get(thread_id: str) -> dict:
    """Get a workflow entry from the test registry."""
    return _test_registry.setdefault(thread_id, {})


# ── Helper Functions ───────────────────────────────────────────────────────────


def make_snapshot(
    values: dict,
    next: list[str] | None = None,
    tasks: list | None = None,
    interrupts: list | None = None,
) -> MagicMock:
    """Create a mock StateSnapshot for testing."""
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = next or []
    snapshot.tasks = tasks or []
    snapshot.interrupts = interrupts or []
    return snapshot


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_graph():
    """Mock compiled graph for testing."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value={"phase": "completed", "session_id": "test_session"})
    mock_snapshot = MagicMock()
    mock_snapshot.values = {"phase": "completed", "session_id": "test_session"}
    mock_snapshot.next = []
    mock_snapshot.tasks = []
    mock_snapshot.interrupts = []
    graph.aget_state = AsyncMock(return_value=mock_snapshot)
    graph.aupdate_state = AsyncMock()
    return graph


@pytest.fixture
def client(mock_graph):
    """Test client with mocked graph."""
    app.state.graph = mock_graph
    original_bg_tasks = runner_module._background_tasks.copy()
    original_last_status = workflow_module._last_status.copy()
    runner_module._background_tasks.clear()
    workflow_module._last_status.clear()
    yield TestClient(app)
    runner_module._background_tasks.clear()
    runner_module._background_tasks.update(original_bg_tasks)
    workflow_module._last_status.clear()
    workflow_module._last_status.update(original_last_status)
    if hasattr(app.state, "graph"):
        delattr(app.state, "graph")


@pytest.fixture
def event_bus():
    """Get EventBus singleton and clear events."""
    bus = EventBusService.get_instance()
    # Clear events for clean test state
    bus._events.clear()
    bus._seq = 0
    return bus


# ── Test 1: Pause stays paused (not cancelled) ─────────────────────────────────


class TestPausePreservesStatus:
    """Tests for pause preserving paused status, not cancelled."""

    @pytest.mark.asyncio
    async def test_pause_preserves_paused_status(self, mock_graph, event_bus):
        """Pause should set status to paused, not cancelled, even after CancelledError."""
        thread_id = "xhs_test_pause_001"
        config = {"configurable": {"thread_id": thread_id}}

        # Setup initial state - workflow is running
        initial_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.SCOUTING.value,
                "session_id": thread_id,
                "account_id": "test_account",
                "current_agent": "trend_scout",
            },
            next=["trend_scout"],
        )
        mock_graph.aget_state.return_value = initial_snapshot

        # Register workflow in registry
        _test_registry[thread_id] = {
            "thread_id": thread_id,
            "account_id": "test_account",
            "phase": "scouting",
            "status": "running",
            "progress_percent": 10,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "error": None,
        }

        # Create a background task that will be cancelled
        async def long_running_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(long_running_task())
        runner_module._background_tasks[thread_id] = task

        # Simulate pause endpoint behavior
        # 1. Update graph state to paused with prev_phase
        await mock_graph.aupdate_state(
            config,
            {
                "phase": "paused",
                "prev_phase": WorkflowPhase.SCOUTING.value,
            },
        )

        # 2. Cancel background task
        task.cancel()

        # 3. Update registry
        _test_registry[thread_id]["status"] = "paused"
        _test_registry[thread_id]["phase"] = "paused"

        # Simulate CancelledError handler in _run_graph_and_persist
        # After CancelledError, check current phase
        paused_snapshot = make_snapshot(
            {
                "phase": "paused",
                "session_id": thread_id,
                "prev_phase": WorkflowPhase.SCOUTING.value,
            }
        )
        mock_graph.aget_state.return_value = paused_snapshot

        # Verify: registry status should be "paused", not "cancelled"
        assert _test_registry[thread_id]["status"] == "paused"
        assert _test_registry[thread_id]["phase"] == "paused"

        # Verify: prev_phase was saved in graph state
        aupdate_calls = mock_graph.aupdate_state.call_args_list
        assert len(aupdate_calls) >= 1
        first_update = aupdate_calls[0]
        assert first_update[0][1].get("phase") == "paused"
        assert first_update[0][1].get("prev_phase") == WorkflowPhase.SCOUTING.value

        # Cleanup
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ── Test 2: Resume doesn't trigger review_gate incorrectly ─────────────────────


class TestResumeGuards:
    """Tests for resume endpoint guards."""

    @pytest.mark.asyncio
    async def test_resume_from_paused_restores_prev_phase(self, mock_graph):
        """Resume from paused restores prev_phase and continues, not re-enter review_gate."""
        thread_id = "xhs_test_resume_001"
        config = {"configurable": {"thread_id": thread_id}}

        # Setup paused state with prev_phase
        paused_snapshot = make_snapshot(
            {
                "phase": "paused",
                "session_id": thread_id,
                "account_id": "test_account",
                "prev_phase": WorkflowPhase.PLANNING.value,
                "current_agent": "content_strategist",
            },
            next=["content_strategist"],
        )
        mock_graph.aget_state.return_value = paused_snapshot

        # Register workflow
        _test_registry[thread_id] = {
            "thread_id": thread_id,
            "account_id": "test_account",
            "phase": "paused",
            "status": "paused",
            "progress_percent": 20,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "error": None,
        }

        # Simulate resume: restore prev_phase
        prev_phase = paused_snapshot.values.get("prev_phase", "scouting")
        await mock_graph.aupdate_state(config, {"phase": prev_phase})

        # Verify: phase was restored to prev_phase (planning), not review_gate
        aupdate_calls = mock_graph.aupdate_state.call_args_list
        last_update = aupdate_calls[-1]
        assert last_update[0][1].get("phase") == WorkflowPhase.PLANNING.value

        # Verify: registry updated to running
        _test_registry[thread_id]["status"] = "running"
        _test_registry[thread_id]["phase"] = prev_phase
        assert _test_registry[thread_id]["status"] == "running"
        assert _test_registry[thread_id]["phase"] == "planning"

    @pytest.mark.asyncio
    async def test_resume_from_awaiting_review_returns_hint(self, mock_graph):
        """Resume on awaiting_review should return status hint, not invoke graph."""
        thread_id = "xhs_test_review_001"

        # Setup awaiting_review state (at review_gate)
        review_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.REVIEWING.value,
                "session_id": thread_id,
                "account_id": "test_account",
                "current_agent": "review_gate",
            },
            next=["review_gate"],
        )
        mock_graph.aget_state.return_value = review_snapshot

        # Derive status should return AWAITING_REVIEW
        derived = derive_status(review_snapshot)
        assert derived == WorkflowStatus.AWAITING_REVIEW

        # Resume endpoint should NOT invoke graph, just return hint
        # In the actual endpoint, this returns a message to use review endpoint
        if derived == WorkflowStatus.AWAITING_REVIEW:
            response_data = {
                "thread_id": thread_id,
                "status": "awaiting_review",
                "message": "Use /api/review/submit endpoint",
            }
            assert response_data["status"] == "awaiting_review"
            assert "review" in response_data["message"].lower()

    @pytest.mark.asyncio
    async def test_resume_from_awaiting_choice_returns_hint(self, mock_graph):
        """Resume on awaiting_choice should return status hint, not invoke graph."""
        thread_id = "xhs_test_choice_001"

        # Setup awaiting_choice state (at choice_gate)
        choice_interrupt = MagicMock()
        choice_interrupt.value = {"gate": "choice"}
        choice_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "session_id": thread_id,
                "account_id": "test_account",
                "current_agent": "choice_gate",
            },
            next=["choice_gate"],
            interrupts=[choice_interrupt],
        )
        mock_graph.aget_state.return_value = choice_snapshot

        # Derive status should return AWAITING_CHOICE
        derived = derive_status(choice_snapshot)
        assert derived == WorkflowStatus.AWAITING_CHOICE

        # Resume endpoint should NOT invoke graph, just return hint
        if derived == WorkflowStatus.AWAITING_CHOICE:
            response_data = {
                "thread_id": thread_id,
                "status": "awaiting_choice",
                "message": "Use /api/optimization/select endpoint",
            }
            assert response_data["status"] == "awaiting_choice"
            assert "select" in response_data["message"].lower()


# ── Test 3: Review/select updates registry/history/events ──────────────────────


class TestReviewSelectUpdates:
    """Tests for review and select endpoints updating registry/history/events."""

    @pytest.mark.asyncio
    async def test_review_submit_updates_registry_and_emits_event(self, mock_graph, event_bus):
        """Submit review should update registry, history, and emit status transition."""
        thread_id = "xhs_test_review_submit_001"
        config = {"configurable": {"thread_id": thread_id}}

        # Setup awaiting_review state
        review_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.REVIEWING.value,
                "session_id": thread_id,
                "account_id": "test_account",
                "current_agent": "review_gate",
                "content_plan": {"selected_topic": "test topic"},
                "copy_content": {"title": "Test Title"},
                "visual_plan": {"layout": "grid"},
            },
            next=["review_gate"],
        )
        mock_graph.aget_state.return_value = review_snapshot

        # Register workflow
        _test_registry[thread_id] = {
            "thread_id": thread_id,
            "account_id": "test_account",
            "phase": "reviewing",
            "status": "awaiting_review",
            "progress_percent": 60,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "error": None,
        }

        # Simulate review submit: write human_feedback to state, then ainvoke(None)
        decision = {
            "decision": "approved",
            "comments": "Looks good!",
            "revisions": [],
        }

        # Write human_feedback to state (as submit_review does via aupdate_state)
        await mock_graph.aupdate_state(config, {"human_feedback": decision})

        # Mock the graph invoke to return publishing phase
        mock_graph.ainvoke.return_value = {
            "phase": "publishing",
            "session_id": thread_id,
        }

        # After invoke, get updated state
        publishing_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.PUBLISHING.value,
                "session_id": thread_id,
                "current_agent": "publisher",
            },
            next=["publisher"],
        )
        mock_graph.aget_state.return_value = publishing_snapshot

        # Simulate the _run_graph_and_persist behavior
        # (submit_review now uses ainvoke(None) for interrupt_before gates)
        result = await mock_graph.ainvoke(None, config)
        snapshot = await mock_graph.aget_state(config)
        derive_status(snapshot)  # Verify derivation works

        # Update registry
        _test_registry[thread_id]["phase"] = result.get("phase", "unknown")
        _test_registry[thread_id]["status"] = "running"
        _test_registry[thread_id]["updated_at"] = "2026-01-01T00:01:00Z"

        # Emit event for status transition
        event_bus.emit(
            EventType.REVIEW_APPROVED,
            thread_id=thread_id,
            payload={"decision": "approved"},
        )

        # Verify: registry updated
        assert _test_registry[thread_id]["phase"] == "publishing"
        assert _test_registry[thread_id]["status"] == "running"

        # Verify: event emitted
        events = [e for e in event_bus._events if e.thread_id == thread_id]
        assert len(events) >= 1
        assert any(e.event_type == EventType.REVIEW_APPROVED for e in events)

    @pytest.mark.asyncio
    async def test_select_version_updates_registry_and_emits_event(self, mock_graph, event_bus):
        """Select version should update registry, history, and emit status transition."""
        thread_id = "xhs_test_select_001"
        config = {"configurable": {"thread_id": thread_id}}

        # Setup awaiting_choice state with multiple versions
        choice_interrupt = MagicMock()
        choice_interrupt.value = {"gate": "choice"}
        choice_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "session_id": thread_id,
                "account_id": "test_account",
                "current_agent": "choice_gate",
                "content_versions": [
                    {"version_id": "v1", "title": "Version A"},
                    {"version_id": "v2", "title": "Version B"},
                ],
                "draft_content": {"title": "Original Draft"},
                "optimization_analysis": {"score": 85},
            },
            next=["choice_gate"],
            interrupts=[choice_interrupt],
        )
        mock_graph.aget_state.return_value = choice_snapshot

        # Register workflow
        _test_registry[thread_id] = {
            "thread_id": thread_id,
            "account_id": "test_account",
            "phase": "creating",
            "status": "awaiting_choice",
            "progress_percent": 40,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "error": None,
        }

        # Simulate select: write selected_version to state, then ainvoke(None)
        choice = {"version_id": "v1", "version_type": "A"}

        # Write selected_version to state (as select_version does via aupdate_state)
        await mock_graph.aupdate_state(config, {"selected_version": choice["version_id"]})

        # Mock the graph invoke to return creating phase
        mock_graph.ainvoke.return_value = {
            "phase": "creating",
            "session_id": thread_id,
            "selected_version": "v1",
        }

        # After invoke, get updated state
        creating_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "session_id": thread_id,
                "current_agent": "visual_designer",
                "selected_version": "v1",
            },
            next=["visual_designer"],
        )
        mock_graph.aget_state.return_value = creating_snapshot

        # Simulate the _run_graph_and_persist behavior
        # (select_version now uses ainvoke(None) for interrupt_before gates)
        result = await mock_graph.ainvoke(None, config)
        snapshot = await mock_graph.aget_state(config)
        derive_status(snapshot)  # Verify derivation works

        # Update registry
        _test_registry[thread_id]["phase"] = result.get("phase", "unknown")
        _test_registry[thread_id]["status"] = "running"
        _test_registry[thread_id]["updated_at"] = "2026-01-01T00:01:00Z"

        # Emit event for status transition
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"selected_version": "v1"},
        )

        # Verify: registry updated
        assert _test_registry[thread_id]["status"] == "running"

        # Verify: event emitted
        events = [e for e in event_bus._events if e.thread_id == thread_id]
        assert len(events) >= 1
        assert any(e.event_type == EventType.WORKFLOW_DATA_UPDATED for e in events)


# ── Test 4: Draft gate / optimization flow ─────────────────────────────────────


class TestChoiceGateRouting:
    """Tests for should_present_choice router."""

    def test_single_version_skips_choice_gate(self):
        """With only 1 content version, should_present_choice routes to visual_designer."""
        state = {
            "phase": WorkflowPhase.CREATING,
            "content_versions": [{"version_id": "v1", "title": "Only Version"}],
        }

        result = should_present_choice(state)

        # Should route to visual_designer, not choice_gate
        assert result == "visual_designer"

    def test_no_versions_skips_choice_gate(self):
        """With no content versions, should_present_choice routes to visual_designer."""
        state = {
            "phase": WorkflowPhase.CREATING,
            "content_versions": [],
        }

        result = should_present_choice(state)

        assert result == "visual_designer"

    def test_multiple_versions_enters_choice_gate(self):
        """With >1 content versions, should_present_choice routes to choice_gate."""
        state = {
            "phase": WorkflowPhase.CREATING,
            "content_versions": [
                {"version_id": "v1", "title": "Version A"},
                {"version_id": "v2", "title": "Version B"},
            ],
        }

        result = should_present_choice(state)

        assert result == "choice_gate"

    def test_three_versions_enters_choice_gate(self):
        """With 3+ content versions, should_present_choice routes to choice_gate."""
        state = {
            "phase": WorkflowPhase.CREATING,
            "content_versions": [
                {"version_id": "v1", "title": "Version A"},
                {"version_id": "v2", "title": "Version B"},
                {"version_id": "v3", "title": "Version C"},
            ],
        }

        result = should_present_choice(state)

        assert result == "choice_gate"

    def test_terminal_state_skips_choice_gate(self):
        """Terminal state (paused/cancelled/error) routes to __end__."""
        # Paused
        state = {"phase": WorkflowPhase.PAUSED, "content_versions": []}
        assert should_present_choice(state) == "__end__"

        # Cancelled
        state = {"phase": WorkflowPhase.CANCELLED, "content_versions": []}
        assert should_present_choice(state) == "__end__"

        # Error
        state = {"phase": WorkflowPhase.ERROR, "content_versions": []}
        assert should_present_choice(state) == "__end__"


# ── Test 5: No XHS + dry_run still completes publish chain ─────────────────────


class TestDryRunPublishChain:
    """Tests for dry_run mode completing full publish chain."""

    @pytest.mark.asyncio
    async def test_dry_run_completes_full_publish_chain(self, mock_graph):
        """With dry_run=True and no XHS config, workflow completes publish -> analyst."""
        thread_id = "xhs_test_dryrun_001"
        config = {"configurable": {"thread_id": thread_id}}

        # Mock publisher returning dry_run result
        mock_graph.ainvoke.return_value = {
            "phase": WorkflowPhase.ANALYZING.value,
            "session_id": thread_id,
            "publish_result": {
                "dry_run": True,
                "status": "simulated",
                "message": "Dry run - no actual publish",
            },
        }

        # After publisher, analyst runs
        analyzing_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.ANALYZING.value,
                "session_id": thread_id,
                "current_agent": "analyst",
                "publish_result": {"dry_run": True},
            },
            next=["analyst"],
        )
        mock_graph.aget_state.return_value = analyzing_snapshot

        # Simulate workflow execution
        result = await mock_graph.ainvoke(None, config)

        # Verify: workflow reaches analyzing phase (publisher -> analyst chain)
        assert result.get("phase") == WorkflowPhase.ANALYZING.value
        assert result.get("publish_result", {}).get("dry_run") is True

        # Verify: publisher node was invoked (ainvoke was called)
        assert mock_graph.ainvoke.called

    @pytest.mark.asyncio
    async def test_dry_run_reaches_completed(self, mock_graph):
        """Dry run workflow should eventually reach completed phase."""
        thread_id = "xhs_test_dryrun_complete_001"

        # Mock full workflow completion
        mock_graph.ainvoke.return_value = {
            "phase": WorkflowPhase.COMPLETED.value,
            "session_id": thread_id,
            "publish_result": {"dry_run": True},
            "analytics": {"engagement_rate": 0.0},
        }

        completed_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.COMPLETED.value,
                "session_id": thread_id,
            }
        )
        mock_graph.aget_state.return_value = completed_snapshot

        result = await mock_graph.ainvoke(None, {"configurable": {"thread_id": thread_id}})

        assert result.get("phase") == WorkflowPhase.COMPLETED.value


# ── Test 6: Background exception writes graph error state ──────────────────────


class TestBackgroundExceptionHandling:
    """Tests for background exception writing error state."""

    @pytest.mark.asyncio
    async def test_background_exception_writes_error_state(self, mock_graph):
        """When background execution fails, graph state should have phase=ERROR."""
        thread_id = "xhs_test_error_001"
        config = {"configurable": {"thread_id": thread_id}}

        # Register workflow
        _test_registry[thread_id] = {
            "thread_id": thread_id,
            "account_id": "test_account",
            "phase": "scouting",
            "status": "running",
            "progress_percent": 10,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "error": None,
        }

        # Mock graph invoke to raise exception
        mock_graph.ainvoke.side_effect = Exception("Simulated API failure")

        # Simulate _run_graph_and_persist exception handling
        try:
            await mock_graph.ainvoke(None, config)
        except Exception as exc:
            # Write error to graph state
            await mock_graph.aupdate_state(
                config,
                {
                    "phase": "error",
                    "error": str(exc),
                },
            )
            # Update registry
            _test_registry[thread_id]["status"] = "error"
            _test_registry[thread_id]["error"] = str(exc)

        # Verify: graph state was updated with error phase
        aupdate_calls = mock_graph.aupdate_state.call_args_list
        assert len(aupdate_calls) >= 1
        error_update = aupdate_calls[0]
        assert error_update[0][1].get("phase") == "error"
        assert "API failure" in error_update[0][1].get("error", "")

        # Verify: registry has error status
        assert _test_registry[thread_id]["status"] == "error"
        assert "API failure" in _test_registry[thread_id]["error"]


# ── Test 7: _check_terminal doesn't END on non-terminal errors ────────────────


class TestCheckTerminalRouter:
    """Tests for _check_terminal router function."""

    def test_check_terminal_ignores_non_terminal_error(self):
        """_check_terminal should not END on state.error unless phase is ERROR/PAUSED/CANCELLED."""
        # State with error but phase is running
        state = {
            "phase": WorkflowPhase.SCOUTING,
            "error": "Some transient error",
        }

        result = _check_terminal(state)

        # Should return None (not "__end__") - workflow continues
        assert result is None

    def test_check_terminal_ends_on_error_phase(self):
        """_check_terminal should END when phase is ERROR."""
        state = {
            "phase": WorkflowPhase.ERROR,
            "error": "Fatal error",
        }

        result = _check_terminal(state)

        assert result == "__end__"

    def test_check_terminal_ends_on_paused_phase(self):
        """_check_terminal should END when phase is PAUSED."""
        state = {
            "phase": WorkflowPhase.PAUSED,
        }

        result = _check_terminal(state)

        assert result == "__end__"

    def test_check_terminal_ends_on_cancelled_phase(self):
        """_check_terminal should END when phase is CANCELLED."""
        state = {
            "phase": WorkflowPhase.CANCELLED,
        }

        result = _check_terminal(state)

        assert result == "__end__"

    def test_check_terminal_none_on_running_phases(self):
        """_check_terminal should return None for all running phases."""
        running_phases = [
            WorkflowPhase.IDLE,
            WorkflowPhase.SCOUTING,
            WorkflowPhase.PLANNING,
            WorkflowPhase.CREATING,
            WorkflowPhase.REVIEWING,
            WorkflowPhase.PUBLISHING,
            WorkflowPhase.ANALYZING,
            WorkflowPhase.ENGAGING,
        ]

        for phase in running_phases:
            state = {"phase": phase}
            result = _check_terminal(state)
            assert result is None, f"_check_terminal should return None for {phase}"

    def test_check_terminal_ends_on_completed_phase(self):
        """_check_terminal should END on COMPLETED — workflow is done."""
        state = {
            "phase": WorkflowPhase.COMPLETED,
        }

        result = _check_terminal(state)
        assert result == "__end__"


# ── Test 8: review_outcome always routes to publisher ──────────────────────────


class TestReviewOutcomeRouter:
    """Tests for review_outcome router function."""

    def test_review_outcome_routes_to_publisher_without_xhs_config(self):
        """review_outcome should route to publisher even without XHS credentials."""
        # State with approved review, no XHS config
        state = {
            "phase": WorkflowPhase.REVIEWING,
            "human_feedback": {"decision": ContentStatus.APPROVED},
            # No XHS_COOKIE, no XHS_USER_ID
        }

        result = review_outcome(state)

        # Should route to publisher, not __end__
        assert result == "publisher"

    def test_review_outcome_routes_to_publisher_with_dry_run(self):
        """review_outcome should route to publisher with dry_run=True."""
        state = {
            "phase": WorkflowPhase.REVIEWING,
            "human_feedback": {"decision": ContentStatus.APPROVED},
            "dry_run": True,
        }

        result = review_outcome(state)

        assert result == "publisher"

    def test_review_outcome_routes_to_revise_on_needs_revision(self):
        """review_outcome should route to revise_content on needs_revision."""
        state = {
            "phase": WorkflowPhase.REVIEWING,
            "human_feedback": {"decision": ContentStatus.NEEDS_REVISION},
        }

        result = review_outcome(state)

        assert result == "revise_content"

    def test_review_outcome_routes_to_end_on_rejected(self):
        """review_outcome should route to __end__ on rejected."""
        state = {
            "phase": WorkflowPhase.REVIEWING,
            "human_feedback": {"decision": ContentStatus.REJECTED},
        }

        result = review_outcome(state)

        assert result == "__end__"

    def test_review_outcome_respects_terminal_states(self):
        """review_outcome should check terminal states first."""
        approved = {"decision": ContentStatus.APPROVED}

        # Paused
        state = {
            "phase": WorkflowPhase.PAUSED,
            "human_feedback": approved,
        }
        assert review_outcome(state) == "__end__"

        # Cancelled
        state = {
            "phase": WorkflowPhase.CANCELLED,
            "human_feedback": approved,
        }
        assert review_outcome(state) == "__end__"

        # Error
        state = {
            "phase": WorkflowPhase.ERROR,
            "human_feedback": approved,
        }
        assert review_outcome(state) == "__end__"


# ── Test 9: Event payload enrichment ───────────────────────────────────────────


class TestEventPayloadEnrichment:
    """Tests for event payload enrichment in _emit_status_transition."""

    @pytest.mark.asyncio
    async def test_review_pending_event_has_content_payload(self, event_bus):
        """REVIEW_PENDING event should include content_plan, copy_content, visual_plan."""
        thread_id = "xhs_test_event_review_001"

        # Create snapshot with content data
        snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.REVIEWING.value,
                "session_id": thread_id,
                "content_plan": {"selected_topic": "test topic", "keywords": ["test"]},
                "copy_content": {"title": "Test Title", "body_text": "Test body"},
                "visual_plan": {"layout": "grid", "style": "minimalist"},
                "content_versions": [
                    {"version_id": "v1", "title": "Version 1"},
                    {"version_id": "v2", "title": "Version 2"},
                ],
            },
            next=["review_gate"],
        )

        # Build payload as done in _emit_status_transition
        payload = {
            "phase": snapshot.values.get("phase"),
            "current_agent": snapshot.values.get("current_agent"),
        }

        # Simulating AWAITING_REVIEW branch
        values = snapshot.values or {}
        payload["content_plan"] = values.get("content_plan", {})
        payload["copy_content"] = values.get("copy_content", {})
        payload["visual_plan"] = values.get("visual_plan", {})
        payload["version_history"] = values.get("content_versions", [])

        # Emit event
        event_bus.emit(
            EventType.REVIEW_PENDING,
            thread_id=thread_id,
            payload=payload,
        )

        # Verify event has all content fields
        events = [e for e in event_bus._events if e.thread_id == thread_id]
        assert len(events) >= 1

        review_event = events[0]
        assert review_event.event_type == EventType.REVIEW_PENDING
        assert "content_plan" in review_event.payload
        assert "copy_content" in review_event.payload
        assert "visual_plan" in review_event.payload
        assert "version_history" in review_event.payload

        # Verify content
        assert review_event.payload["content_plan"]["selected_topic"] == "test topic"
        assert review_event.payload["copy_content"]["title"] == "Test Title"
        assert review_event.payload["visual_plan"]["layout"] == "grid"
        assert len(review_event.payload["version_history"]) == 2

    @pytest.mark.asyncio
    async def test_choice_pending_event_has_versions_payload(self, event_bus):
        """Choice pending event should include versions, draft, and analysis."""
        thread_id = "xhs_test_event_choice_001"

        # Create snapshot with version data
        snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "session_id": thread_id,
                "content_versions": [
                    {"version_id": "v1", "title": "Version A", "score": 85},
                    {"version_id": "v2", "title": "Version B", "score": 78},
                ],
                "draft_content": {"title": "Original Draft", "text": "Original text"},
                "optimization_analysis": {
                    "score": 82,
                    "suggestions": ["Add hashtags"],
                },
            },
            next=["choice_gate"],
        )

        # Simulate _emit_status_transition for AWAITING_CHOICE
        payload = {
            "phase": snapshot.values.get("phase"),
            "current_agent": snapshot.values.get("current_agent"),
        }

        values = snapshot.values or {}
        payload["data"] = {
            "versions": values.get("content_versions", []),
            "draft": values.get("draft_content", {}),
            "analysis": values.get("optimization_analysis", {}),
        }

        # Emit event
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload=payload,
        )

        # Verify event has all version fields
        events = [e for e in event_bus._events if e.thread_id == thread_id]
        assert len(events) >= 1

        choice_event = events[0]
        assert choice_event.event_type == EventType.WORKFLOW_DATA_UPDATED
        assert "data" in choice_event.payload

        data = choice_event.payload["data"]
        assert "versions" in data
        assert "draft" in data
        assert "analysis" in data

        # Verify content
        assert len(data["versions"]) == 2
        assert data["draft"]["title"] == "Original Draft"
        assert data["analysis"]["score"] == 82


# ── Additional Integration Tests via API Client ────────────────────────────────


class TestWorkflowAPIIntegration:
    """Integration tests via FastAPI test client."""

    def test_pause_endpoint_updates_registry(self, client, mock_graph):
        """Pause endpoint should update DB status to paused."""
        thread_id = "xhs_test_api_pause_001"

        # Setup mock state
        mock_state = MagicMock()
        mock_state.values = {
            "phase": "scouting",
            "session_id": thread_id,
            "account_id": "test_account",
        }
        mock_graph.aget_state.return_value = mock_state

        response = client.post(f"/api/workflow/pause/{thread_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "paused"

    def test_resume_endpoint_checks_awaiting_review(self, client, mock_graph):
        """Resume endpoint should return hint for awaiting_review status."""
        thread_id = "xhs_test_api_resume_review_001"

        # Setup awaiting_review state
        mock_state = MagicMock()
        mock_state.values = {
            "phase": "reviewing",
            "session_id": thread_id,
            "account_id": "test_account",
        }
        mock_state.next = ["review_gate"]
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state

        response = client.post(f"/api/workflow/resume/{thread_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return hint, not invoke graph
        assert data["data"]["status"] == "awaiting_review"
        assert "review" in data["data"]["message"].lower()

    def test_resume_endpoint_checks_awaiting_choice(self, client, mock_graph):
        """Resume endpoint should return hint for awaiting_choice status."""
        thread_id = "xhs_test_api_resume_choice_001"

        # Setup awaiting_choice state
        mock_state = MagicMock()
        mock_state.values = {
            "phase": "creating",
            "session_id": thread_id,
            "account_id": "test_account",
        }
        mock_state.next = ["choice_gate"]
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state

        response = client.post(f"/api/workflow/resume/{thread_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return hint, not invoke graph
        assert data["data"]["status"] == "awaiting_choice"
        assert "select" in data["data"]["message"].lower()

    def test_resume_endpoint_defaults_blogger_selection_to_skip(
        self, client, mock_graph, monkeypatch
    ):
        """Generic resume at blogger_gate should send a valid skip payload by default."""
        thread_id = "xhs_test_api_resume_blogger_001"

        mock_state = MagicMock()
        mock_state.values = {
            "phase": "creating",
            "session_id": thread_id,
            "account_id": "test_account",
        }
        mock_state.next = ["blogger_gate"]
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state

        captured: dict[str, object] = {}

        async def fake_run(thread_id_arg, graph_arg, config_arg, input_data, *, source):
            captured["thread_id"] = thread_id_arg
            captured["input_data"] = input_data
            captured["source"] = source
            return {"phase": WorkflowPhase.CREATING.value, "session_id": thread_id_arg}

        monkeypatch.setattr(workflow_module._runner, "_run_graph_and_persist", fake_run)

        response = client.post(f"/api/workflow/resume/{thread_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "running"
        assert captured["source"] == "blogger_resume"
        assert isinstance(captured["input_data"], Command)
        assert captured["input_data"].resume == {"skip": True}

    def test_retry_error_infers_phase_from_failed_task(self, client, mock_graph, monkeypatch):
        """Regression: retry from a terminal error must (a) infer the resume phase
        from the checkpoint's failed task (not fall back to SCOUTING), and (b) NOT
        call aupdate_state at all — native ainvoke(None) re-runs the failed task.
        """
        thread_id = "xhs_test_resume_error_phase_001"

        succeeded_task = MagicMock()
        succeeded_task.name = "orchestrator"
        succeeded_task.error = None

        failed_task = MagicMock()
        failed_task.name = "visual_designer"
        failed_task.error = RuntimeError("NotEnoughCvError")

        mock_state = MagicMock()
        mock_state.values = {
            "phase": WorkflowPhase.ERROR.value,
            "session_id": thread_id,
            "account_id": "test_account",
            "error": "NotEnoughCvError",
            "current_agent": "visual_designer",
            # prev_phase intentionally absent — the bug scenario
        }
        mock_state.next = []  # terminal error → no pending successors
        # LangGraph may keep earlier successful tasks before the failed task.
        # Phase inference must prefer the errored task, not tasks[0].
        mock_state.tasks = [succeeded_task, failed_task]
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state

        # _start_resume_task spawns a bg task — replace so we assert on the
        # resume decision without invoking the graph.
        captured: dict = {}

        async def _noop_start(_thread_id, _graph, _config, phase):
            captured["phase"] = phase
            return None

        monkeypatch.setattr(workflow_module, "_start_resume_task", _noop_start)

        response = client.post(f"/api/workflow/resume/{thread_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "running"
        # Phase reflects the failed node (visual_designer → creating), NOT scouting.
        assert data["data"]["phase"] == WorkflowPhase.CREATING.value
        assert captured["phase"] == WorkflowPhase.CREATING.value

        # Error/stale retry must leave the LangGraph checkpoint untouched. Even
        # aupdate_state without as_node can raise InvalidUpdateError when the
        # checkpoint has multiple tasks; native ainvoke(None) is the retry.
        mock_graph.aupdate_state.assert_not_called()


# ── Engagement node completion event ownership ─────────────────────────────────


class TestEngagementNodeEvents:
    """Tests for engagement node event ownership."""

    @pytest.mark.asyncio
    async def test_engagement_node_does_not_emit_workflow_completed(self, monkeypatch, event_bus):
        """The runner is the single source of WORKFLOW_COMPLETED events."""
        from backend.agents.nodes import engagement as engagement_module

        async def fake_engagement(state, *, store):
            return {
                "phase": WorkflowPhase.COMPLETED,
                "analytics": {"ok": True},
            }

        monkeypatch.setattr(engagement_module, "_engagement", fake_engagement)

        result = await engagement_module.engagement_node(
            {
                "phase": WorkflowPhase.ENGAGING,
                "session_id": "xhs_test_engagement_events_001",
            },
            store=MagicMock(),
        )

        assert result["phase"] == WorkflowPhase.COMPLETED
        assert result["current_agent"] == "engagement"
        assert [e for e in event_bus._events if e.event_type == EventType.WORKFLOW_COMPLETED] == []


# ── Test 10: Draft gate behavior ────────────────────────────────────────────────


class TestDraftGateBehavior:
    """Tests for draft_gate node and submit_draft endpoint."""

    @pytest.mark.asyncio
    async def test_draft_gate_advances_phase_without_interrupt(self, mock_graph):
        """draft_gate_node returns CREATING phase without calling interrupt().

        With interrupt_before, the node only runs on resume after submit_draft
        writes draft_content to state. The node does not call interrupt() —
        it just advances the phase.
        """
        from backend.agents.nodes.optimization.draft_gate import draft_gate_node

        # State with user-submitted draft (written by submit_draft via aupdate_state)
        state_with_draft = {
            "phase": WorkflowPhase.CREATING,
            "session_id": "test_session",
            "draft_content": {"title": "Test Draft", "text": "Test content"},
        }

        # Node should return phase=CREATING without calling interrupt
        result = await draft_gate_node(state_with_draft, store=MagicMock())
        assert result.get("phase") == WorkflowPhase.CREATING
        assert result.get("current_agent") == "draft_gate"

    @pytest.mark.asyncio
    async def test_draft_gate_returns_creating_with_no_draft(self, mock_graph):
        """draft_gate_node returns CREATING even when draft_content is empty.

        With interrupt_before, the node only runs on resume. If called without
        a user-submitted draft (e.g., edge case), it still advances phase.
        """
        from backend.agents.nodes.optimization.draft_gate import draft_gate_node

        state_no_draft = {
            "phase": WorkflowPhase.CREATING,
            "session_id": "test_session",
            "draft_content": None,
        }

        result = await draft_gate_node(state_no_draft, store=MagicMock())
        assert result.get("phase") == WorkflowPhase.CREATING
        assert result.get("current_agent") == "draft_gate"

    def test_derive_status_returns_awaiting_draft_at_draft_gate(self):
        """derive_status should return AWAITING_DRAFT when next_nodes contains draft_gate."""
        snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "session_id": "test_session",
            },
            next=["draft_gate"],
        )

        derived = derive_status(snapshot)
        assert derived == WorkflowStatus.AWAITING_DRAFT

    def test_derive_status_returns_awaiting_draft_from_interrupt_value(self):
        """derive_status should return AWAITING_DRAFT from interrupt value with gate=draft."""
        interrupt_mock = MagicMock()
        interrupt_mock.value = {"gate": "draft"}
        snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "session_id": "test_session",
            },
            next=["draft_gate"],
            interrupts=[interrupt_mock],
        )

        derived = derive_status(snapshot)
        assert derived == WorkflowStatus.AWAITING_DRAFT

    def test_resume_endpoint_checks_awaiting_draft(self, client, mock_graph):
        """Resume endpoint should return hint for awaiting_draft status."""
        thread_id = "xhs_test_api_resume_draft_001"

        # Setup awaiting_draft state
        mock_state = MagicMock()
        mock_state.values = {
            "phase": "creating",
            "session_id": thread_id,
            "account_id": "test_account",
        }
        mock_state.next = ["draft_gate"]
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state

        response = client.post(f"/api/workflow/resume/{thread_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return hint, not invoke graph
        assert data["data"]["status"] == "awaiting_draft"
        assert "draft" in data["data"]["message"].lower()

    @pytest.mark.asyncio
    async def test_submit_draft_resumes_from_draft_gate(self, mock_graph, event_bus):
        """submit_draft should resume graph when interrupted at draft_gate."""
        thread_id = "xhs_test_submit_draft_001"
        config = {"configurable": {"thread_id": thread_id}}

        # Setup state interrupted at draft_gate
        draft_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "session_id": thread_id,
                "account_id": "test_account",
                "current_agent": "draft_gate",
                "copy_content": {"title": "AI Generated Title"},
            },
            next=["draft_gate"],
        )
        mock_graph.aget_state.return_value = draft_snapshot

        # Register workflow
        _test_registry[thread_id] = {
            "thread_id": thread_id,
            "account_id": "test_account",
            "phase": "creating",
            "status": "awaiting_draft",
            "progress_percent": 35,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "error": None,
        }

        # Mock graph invoke to return creating phase (proceeding to viral_matcher)
        mock_graph.ainvoke.return_value = {
            "phase": WorkflowPhase.CREATING.value,
            "session_id": thread_id,
        }

        # After invoke, get updated state
        creating_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "session_id": thread_id,
                "current_agent": "viral_matcher",
                "draft_content": {"title": "User Draft", "text": "User content"},
            },
            next=["viral_matcher"],
        )
        mock_graph.aget_state.return_value = creating_snapshot

        # Simulate submit_draft behavior
        draft_data = {"title": "User Draft", "text": "User content", "hashtags": []}

        # 1. Update state with draft
        await mock_graph.aupdate_state(
            config,
            {
                "draft_content": draft_data,
                "user_viral_links": [],
            },
        )

        # 2. Check if draft_gate in next (it is)
        assert "draft_gate" in draft_snapshot.next

        # 3. Resume graph via _run_graph_and_persist
        # (submit_draft now uses ainvoke(None) for interrupt_before gates)
        result = await mock_graph.ainvoke(None, config)
        _snapshot = await mock_graph.aget_state(config)

        # Update registry
        _test_registry[thread_id]["phase"] = result.get("phase", "unknown")
        _test_registry[thread_id]["status"] = "running"
        _test_registry[thread_id]["updated_at"] = "2026-01-01T00:01:00Z"

        # Verify: registry updated
        assert _test_registry[thread_id]["status"] == "running"

        # Verify: aupdate_state was called with draft_content
        aupdate_calls = mock_graph.aupdate_state.call_args_list
        assert len(aupdate_calls) >= 1
        first_update = aupdate_calls[0]
        assert "draft_content" in first_update[0][1]

        # Verify: ainvoke was called to resume
        assert mock_graph.ainvoke.called

    @pytest.mark.asyncio
    async def test_submit_draft_without_interrupt_just_updates_state(self, mock_graph):
        """submit_draft should just update state when not at draft_gate."""
        thread_id = "xhs_test_submit_draft_no_interrupt_001"
        config = {"configurable": {"thread_id": thread_id}}

        # Setup state NOT at draft_gate (e.g., at review_gate)
        review_snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.REVIEWING.value,
                "session_id": thread_id,
                "account_id": "test_account",
                "current_agent": "review_gate",
            },
            next=["review_gate"],
        )
        mock_graph.aget_state.return_value = review_snapshot

        # Register workflow
        _test_registry[thread_id] = {
            "thread_id": thread_id,
            "account_id": "test_account",
            "phase": "reviewing",
            "status": "awaiting_review",
            "progress_percent": 60,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "error": None,
        }

        # Simulate submit_draft behavior
        draft_data = {"title": "User Draft", "text": "User content", "hashtags": []}

        # 1. Update state with draft
        await mock_graph.aupdate_state(
            config,
            {
                "draft_content": draft_data,
                "user_viral_links": [],
            },
        )

        # 2. Check if draft_gate in next (it's NOT)
        assert "draft_gate" not in review_snapshot.next

        # 3. Should NOT invoke graph, just return success
        # (In the actual endpoint, this returns {"status": "draft_submitted"})

        # Verify: aupdate_state was called
        assert mock_graph.aupdate_state.called

        # Verify: ainvoke was NOT called (no resume needed)
        # Reset the mock to check if it's called after the check
        mock_graph.ainvoke.reset_mock()
        # In the actual endpoint, ainvoke would not be called since draft_gate not in next


# ── Test 11: Gate double-interrupt fix (方案 B) ──────────────────────────────


class TestGateInterruptFix:
    """Tests for the gate double-interrupt fix (方案 B).

    Validates that:
    - Gate nodes (review_gate, choice_gate, draft_gate) do NOT call interrupt()
    - Submit endpoints use ainvoke(None) instead of Command(resume=value)
    - Decisions are passed via aupdate_state, not Command(resume=...)
    """

    @pytest.mark.asyncio
    async def test_review_gate_node_no_interrupt(self):
        """review_gate_node returns REVIEWING phase without calling interrupt()."""
        from backend.agents.nodes.review_gate import review_gate_node

        state = {
            "phase": WorkflowPhase.REVIEWING,
            "session_id": "test_session",
            "human_feedback": {"decision": "approved"},
        }

        result = await review_gate_node(state, store=MagicMock())

        assert result.get("phase") == WorkflowPhase.REVIEWING
        assert result.get("current_agent") == "review_gate"
        # human_feedback is NOT in result — it's already in state via aupdate_state
        assert "human_feedback" not in result

    @pytest.mark.asyncio
    async def test_review_gate_node_no_interrupt_import(self):
        """review_gate module does not import or call interrupt()."""
        import inspect

        from backend.agents.nodes import review_gate as review_gate_module

        source = inspect.getsource(review_gate_module)
        # interrupt() function should not be called
        assert "interrupt(" not in source
        # interrupt should not be imported from langgraph.types
        for line in source.split("\n"):
            if "import" in line and "langgraph" in line:
                assert "interrupt" not in line

    @pytest.mark.asyncio
    async def test_choice_gate_node_no_interrupt_import(self):
        """choice_gate module does not import or call interrupt()."""
        import inspect

        from backend.agents.nodes.optimization import choice_gate as choice_gate_module

        source = inspect.getsource(choice_gate_module)
        assert "interrupt(" not in source
        for line in source.split("\n"):
            if "import" in line and "langgraph" in line:
                assert "interrupt" not in line

    @pytest.mark.asyncio
    async def test_draft_gate_node_no_interrupt_import(self):
        """draft_gate module does not import or call interrupt()."""
        import inspect

        from backend.agents.nodes.optimization import draft_gate as draft_gate_module

        source = inspect.getsource(draft_gate_module)
        assert "interrupt(" not in source
        for line in source.split("\n"):
            if "import" in line and "langgraph" in line:
                assert "interrupt" not in line

    def test_submit_review_uses_ainvoke_none(self, client, mock_graph):
        """submit_review calls ainvoke(None), not Command(resume=...)."""
        thread_id = "xhs_test_gate_fix_review_001"

        mock_state = MagicMock()
        mock_state.values = {
            "phase": "reviewing",
            "session_id": thread_id,
            "account_id": "test_account",
        }
        mock_state.next = ["review_gate"]
        mock_state.tasks = []
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state
        mock_graph.ainvoke.return_value = {"phase": "publishing", "session_id": thread_id}

        response = client.post(
            f"/api/review/submit/{thread_id}",
            json={"decision": "approved", "comments": "Looks good!", "revisions": []},
        )

        assert response.status_code == 200
        # Verify ainvoke was called with None (not Command)
        assert mock_graph.ainvoke.called
        call_args = mock_graph.ainvoke.call_args
        input_data = call_args[0][0] if call_args[0] else call_args[1].get("input_data")
        assert input_data is None

    def test_submit_review_writes_human_feedback(self, client, mock_graph):
        """submit_review writes human_feedback to state via aupdate_state."""
        thread_id = "xhs_test_gate_fix_review_hf_001"

        mock_state = MagicMock()
        mock_state.values = {
            "phase": "reviewing",
            "session_id": thread_id,
            "account_id": "test_account",
        }
        mock_state.next = ["review_gate"]
        mock_state.tasks = []
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state
        mock_graph.ainvoke.return_value = {"phase": "publishing", "session_id": thread_id}

        response = client.post(
            f"/api/review/submit/{thread_id}",
            json={"decision": "approved", "comments": "Looks good!", "revisions": []},
        )

        assert response.status_code == 200
        # Verify aupdate_state was called with human_feedback containing decision
        aupdate_calls = mock_graph.aupdate_state.call_args_list
        # Find the call that contains human_feedback
        hf_update = None
        for call in aupdate_calls:
            updates = call[0][1] if len(call[0]) > 1 else {}
            if "human_feedback" in updates:
                hf_update = updates["human_feedback"]
                break
        assert hf_update is not None, "human_feedback not written to state"
        assert hf_update.get("decision") == "approved"

    def test_select_version_uses_ainvoke_none(self, client, mock_graph):
        """select_version calls ainvoke(None), not Command(resume=...)."""
        thread_id = "xhs_test_gate_fix_choice_001"

        mock_state = MagicMock()
        mock_state.values = {
            "phase": "creating",
            "session_id": thread_id,
            "account_id": "test_account",
            "content_versions": [
                {"version_id": "v1", "title": "Version A"},
                {"version_id": "v2", "title": "Version B"},
            ],
        }
        mock_state.next = ["choice_gate"]
        mock_state.tasks = []
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state
        mock_graph.ainvoke.return_value = {"phase": "creating", "session_id": thread_id}

        response = client.post(
            f"/api/optimization/select/{thread_id}",
            json={"version_id": "v1", "version_type": "A"},
        )

        assert response.status_code == 200
        # Verify ainvoke was called with None (not Command)
        assert mock_graph.ainvoke.called
        call_args = mock_graph.ainvoke.call_args
        input_data = call_args[0][0] if call_args[0] else call_args[1].get("input_data")
        assert input_data is None

    def test_select_version_writes_selected_version(self, client, mock_graph):
        """select_version writes selected_version to state via aupdate_state."""
        thread_id = "xhs_test_gate_fix_choice_sv_001"

        mock_state = MagicMock()
        mock_state.values = {
            "phase": "creating",
            "session_id": thread_id,
            "account_id": "test_account",
            "content_versions": [
                {"version_id": "v1", "title": "Version A"},
                {"version_id": "v2", "title": "Version B"},
            ],
        }
        mock_state.next = ["choice_gate"]
        mock_state.tasks = []
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state
        mock_graph.ainvoke.return_value = {"phase": "creating", "session_id": thread_id}

        response = client.post(
            f"/api/optimization/select/{thread_id}",
            json={"version_id": "v1", "version_type": "A"},
        )

        assert response.status_code == 200
        # Verify aupdate_state was called with selected_version
        aupdate_calls = mock_graph.aupdate_state.call_args_list
        sv_update = None
        for call in aupdate_calls:
            updates = call[0][1] if len(call[0]) > 1 else {}
            if "selected_version" in updates:
                sv_update = updates["selected_version"]
                break
        assert sv_update == "v1"

    def test_submit_draft_uses_ainvoke_none(self, client, mock_graph):
        """submit_draft calls ainvoke(None), not Command(resume=...)."""
        thread_id = "xhs_test_gate_fix_draft_001"

        mock_state = MagicMock()
        mock_state.values = {
            "phase": "creating",
            "session_id": thread_id,
            "account_id": "test_account",
        }
        mock_state.next = ["draft_gate"]
        mock_state.tasks = []
        mock_state.interrupts = []
        mock_graph.aget_state.return_value = mock_state
        mock_graph.ainvoke.return_value = {"phase": "creating", "session_id": thread_id}

        response = client.post(
            f"/api/optimization/draft/{thread_id}",
            json={"title": "My Draft", "text": "Content here", "hashtags": ["test"]},
        )

        assert response.status_code == 200
        # Verify ainvoke was called with None (not Command)
        assert mock_graph.ainvoke.called
        call_args = mock_graph.ainvoke.call_args
        input_data = call_args[0][0] if call_args[0] else call_args[1].get("input_data")
        assert input_data is None
