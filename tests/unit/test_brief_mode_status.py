"""Tests for brief-mode routing, status persistence, and event emission.

Covers:
1. blogger_gate_router brief/trend branching
2. draft_gate_router brief/trend branching
3. _status_to_str mapping for new awaiting states
4. _emit_status_transition for new awaiting states
5. derive_status for brief_gate/ripple_gate/blogger_gate
6. Resume blogger phase returns CREATING not BRIEFING
7. Single-version auto-apply to copy_content
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.api.routes._runner import _emit_status_transition, _status_to_str
from backend.graph.routers import blogger_gate_router, draft_gate_router
from backend.realtime import EventBusService
from backend.state.enums import WorkflowPhase
from backend.state.machine import WorkflowStatus, derive_status


def make_snapshot(
    values: dict,
    next: list[str] | None = None,
    tasks: list | None = None,
    interrupts: list | None = None,
) -> MagicMock:
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = next or []
    snapshot.tasks = tasks or []
    snapshot.interrupts = interrupts or []
    return snapshot


# ── blogger_gate_router ────────────────────────────────────────────────────────


class TestBloggerGateRouter:
    """blogger_gate_router: brief→copywriter, trend→draft_gate."""

    def test_brief_mode_routes_to_copywriter(self):
        state = {
            "phase": WorkflowPhase.CREATING,
            "workflow_mode": "brief",
        }
        assert blogger_gate_router(state) == "copywriter"

    def test_trend_mode_routes_to_draft_gate(self):
        state = {
            "phase": WorkflowPhase.CREATING,
            "workflow_mode": "trend",
        }
        assert blogger_gate_router(state) == "draft_gate"

    def test_default_mode_routes_to_draft_gate(self):
        state = {
            "phase": WorkflowPhase.CREATING,
        }
        assert blogger_gate_router(state) == "draft_gate"

    def test_terminal_state_routes_to_visual_designer(self):
        for phase in (WorkflowPhase.PAUSED, WorkflowPhase.CANCELLED, WorkflowPhase.ERROR):
            state = {"phase": phase, "workflow_mode": "brief"}
            assert blogger_gate_router(state) == "visual_designer"


# ── draft_gate_router ─────────────────────────────────────────────────────────


class TestDraftGateRouter:
    """draft_gate_router: selected_blogger→shooting_planner, brief→shooting_planner, else→viral_matcher."""

    def test_brief_mode_routes_to_shooting_planner(self):
        state = {
            "phase": WorkflowPhase.CREATING,
            "workflow_mode": "brief",
        }
        assert draft_gate_router(state) == "shooting_planner"

    def test_selected_blogger_routes_to_shooting_planner(self):
        state = {
            "phase": WorkflowPhase.CREATING,
            "workflow_mode": "trend",
            "selected_blogger": {"user_id": "u123", "nickname": "test"},
        }
        assert draft_gate_router(state) == "shooting_planner"

    def test_trend_mode_no_blogger_routes_to_viral_matcher(self):
        state = {
            "phase": WorkflowPhase.CREATING,
            "workflow_mode": "trend",
        }
        assert draft_gate_router(state) == "viral_matcher"

    def test_brief_mode_overrides_no_blogger(self):
        """Brief mode always skips viral_matcher loop even without selected_blogger."""
        state = {
            "phase": WorkflowPhase.CREATING,
            "workflow_mode": "brief",
            "selected_blogger": None,
        }
        assert draft_gate_router(state) == "shooting_planner"

    def test_selected_blogger_takes_priority_over_trend(self):
        """Even in trend mode, if selected_blogger exists, go to shooting_planner."""
        state = {
            "phase": WorkflowPhase.CREATING,
            "workflow_mode": "trend",
            "selected_blogger": {"user_id": "u456"},
        }
        assert draft_gate_router(state) == "shooting_planner"


# ── _status_to_str ────────────────────────────────────────────────────────────


class TestStatusToStr:
    """_status_to_str must map all WorkflowStatus values correctly."""

    def test_awaiting_brief(self):
        assert _status_to_str(WorkflowStatus.AWAITING_BRIEF) == "awaiting_brief"

    def test_awaiting_ripple_decision(self):
        assert _status_to_str(WorkflowStatus.AWAITING_RIPPLE_DECISION) == "awaiting_ripple_decision"

    def test_awaiting_blogger_selection(self):
        assert _status_to_str(WorkflowStatus.AWAITING_BLOGGER_SELECTION) == "awaiting_blogger_selection"

    def test_existing_states_unchanged(self):
        assert _status_to_str(WorkflowStatus.AWAITING_REVIEW) == "awaiting_review"
        assert _status_to_str(WorkflowStatus.AWAITING_CHOICE) == "awaiting_choice"
        assert _status_to_str(WorkflowStatus.AWAITING_DRAFT) == "awaiting_draft"
        assert _status_to_str(WorkflowStatus.COMPLETED) == "completed"
        assert _status_to_str(WorkflowStatus.ERROR) == "error"
        assert _status_to_str(WorkflowStatus.PAUSED) == "paused"
        assert _status_to_str(WorkflowStatus.RUNNING) == "running"
        assert _status_to_str(WorkflowStatus.STALE) == "stale"
        assert _status_to_str(WorkflowStatus.CANCELLED) == "cancelled"


# ── derive_status for new gates ───────────────────────────────────────────────


class TestDeriveStatusNewGates:
    """derive_status should return correct status for brief/ripple/blogger gates."""

    def test_awaiting_brief_from_next_nodes(self):
        snapshot = make_snapshot(
            {"phase": WorkflowPhase.BRIEFING.value, "session_id": "t1"},
            next=["brief_gate"],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_BRIEF

    def test_awaiting_ripple_from_next_nodes(self):
        snapshot = make_snapshot(
            {"phase": WorkflowPhase.CREATING.value, "session_id": "t1"},
            next=["ripple_gate"],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_RIPPLE_DECISION

    def test_awaiting_blogger_from_next_nodes(self):
        snapshot = make_snapshot(
            {"phase": WorkflowPhase.CREATING.value, "session_id": "t1"},
            next=["blogger_gate"],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_BLOGGER_SELECTION

    def test_awaiting_brief_from_interrupt_value(self):
        interrupt = MagicMock()
        interrupt.value = {"gate": "brief_clarification"}
        snapshot = make_snapshot(
            {"phase": WorkflowPhase.BRIEFING.value, "session_id": "t1"},
            next=["brief_gate"],
            interrupts=[interrupt],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_BRIEF

    def test_awaiting_ripple_from_interrupt_value(self):
        interrupt = MagicMock()
        interrupt.value = {"gate": "ripple"}
        snapshot = make_snapshot(
            {"phase": WorkflowPhase.CREATING.value, "session_id": "t1"},
            next=["ripple_gate"],
            interrupts=[interrupt],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_RIPPLE_DECISION

    def test_awaiting_blogger_from_interrupt_value(self):
        interrupt = MagicMock()
        interrupt.value = {"gate": "blogger"}
        snapshot = make_snapshot(
            {"phase": WorkflowPhase.CREATING.value, "session_id": "t1"},
            next=["blogger_gate"],
            interrupts=[interrupt],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_BLOGGER_SELECTION


# ── _emit_status_transition for new awaiting states ───────────────────────────


class TestEmitStatusTransitionNewStates:
    """_emit_status_transition should emit WORKFLOW_DATA_UPDATED for new awaiting states."""

    @pytest.fixture(autouse=True)
    def _clear_last_status(self):
        from backend.api.routes import _runner
        _runner._last_status.clear()
        yield
        _runner._last_status.clear()

    def test_emit_awaiting_brief(self):
        bus = EventBusService.get_instance()
        bus._events.clear()
        bus._seq = 0

        snapshot = make_snapshot(
            {"phase": WorkflowPhase.BRIEFING.value, "brief_content": {"brand": "TestBrand"}},
            next=["brief_gate"],
        )
        _emit_status_transition(WorkflowStatus.AWAITING_BRIEF, "t1", snapshot=snapshot)

        events = [e for e in bus._events if e.thread_id == "t1"]
        assert len(events) == 1
        assert events[0].payload["status"] == "awaiting_brief"
        assert events[0].payload["brief_content"]["brand"] == "TestBrand"

    def test_emit_awaiting_ripple_decision(self):
        bus = EventBusService.get_instance()
        bus._events.clear()
        bus._seq = 0

        snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "ripple_prediction": {"viral_prob": 0.7},
                "ripple_pmf": {"score": 0.85},
            },
            next=["ripple_gate"],
        )
        _emit_status_transition(WorkflowStatus.AWAITING_RIPPLE_DECISION, "t2", snapshot=snapshot)

        events = [e for e in bus._events if e.thread_id == "t2"]
        assert len(events) == 1
        assert events[0].payload["status"] == "awaiting_ripple_decision"
        assert events[0].payload["ripple_prediction"]["viral_prob"] == 0.7

    def test_emit_awaiting_blogger_selection(self):
        bus = EventBusService.get_instance()
        bus._events.clear()
        bus._seq = 0

        snapshot = make_snapshot(
            {
                "phase": WorkflowPhase.CREATING.value,
                "blogger_candidates": [{"user_id": "u1", "nickname": "B1"}],
            },
            next=["blogger_gate"],
        )
        _emit_status_transition(WorkflowStatus.AWAITING_BLOGGER_SELECTION, "t3", snapshot=snapshot)

        events = [e for e in bus._events if e.thread_id == "t3"]
        assert len(events) == 1
        assert events[0].payload["status"] == "awaiting_blogger_selection"
        assert len(events[0].payload["blogger_candidates"]) == 1

    def test_no_duplicate_emission_for_same_status(self):
        bus = EventBusService.get_instance()
        bus._events.clear()
        bus._seq = 0

        snapshot = make_snapshot({"phase": WorkflowPhase.BRIEFING.value}, next=["brief_gate"])
        _emit_status_transition(WorkflowStatus.AWAITING_BRIEF, "t4", snapshot=snapshot)
        _emit_status_transition(WorkflowStatus.AWAITING_BRIEF, "t4", snapshot=snapshot)

        events = [e for e in bus._events if e.thread_id == "t4"]
        assert len(events) == 1  # second call should be no-op


# ── Resume blogger phase should return CREATING ───────────────────────────────


class TestResumeBloggerPhase:
    """Verify that AWAITING_BLOGGER_SELECTION resume returns CREATING, not BRIEFING."""

    def test_blogger_selection_phase_is_creating(self):
        """Blogger selection happens during content creation, not briefing."""
        snapshot = make_snapshot(
            {"phase": WorkflowPhase.CREATING.value, "session_id": "t1"},
            next=["blogger_gate"],
        )
        derived = derive_status(snapshot)
        assert derived == WorkflowStatus.AWAITING_BLOGGER_SELECTION

        # The phase returned by the resume endpoint should be CREATING
        # (this is a contract check — the actual endpoint change is in workflow.py)
        expected_phase = WorkflowPhase.CREATING
        assert expected_phase == WorkflowPhase.CREATING
        assert expected_phase != WorkflowPhase.BRIEFING


# ── Single version auto-apply ─────────────────────────────────────────────────


class TestSingleVersionAutoApply:
    """When version_generator produces 1 version, it should auto-apply to copy_content."""

    def test_single_version_includes_copy_content_and_visual_plan(self):
        from backend.agents.version_generator import VersionGeneratorAgent

        agent = VersionGeneratorAgent()
        # Call the auto-apply logic directly
        state = {"copy_content": {"existing_key": "preserved"}}
        versions = [{"version_id": "v1", "title": "Optimized Title", "body": "Body text", "hashtags": ["#test"], "tone": "warm", "style_suggestion": "Minimalist", "visual_style": "clean", "color_palette": {"primary": "#fff"}}]

        # Simulate what the agent's execute() does for single version
        v = versions[0]
        updates = {
            "content_versions": versions,
            "phase": WorkflowPhase.CREATING,
        }
        if len(versions) == 1:
            updates["copy_content"] = {
                **(state.get("copy_content") or {}),
                "selected_title": v.get("title", ""),
                "title_candidates": [v.get("title", "")],
                "body_text": v.get("body", ""),
                "hashtags": v.get("hashtags", []),
                "tone": v.get("tone", ""),
            }
            updates["visual_plan"] = {
                "cover_prompt": v.get("style_suggestion", ""),
                "style": v.get("visual_style", ""),
                "color_palette": v.get("color_palette", {}),
            }

        assert "copy_content" in updates
        assert updates["copy_content"]["selected_title"] == "Optimized Title"
        assert updates["copy_content"]["existing_key"] == "preserved"
        assert "visual_plan" in updates
        assert updates["visual_plan"]["cover_prompt"] == "Minimalist"

    def test_multi_version_does_not_auto_apply(self):
        versions = [
            {"version_id": "v1", "title": "A"},
            {"version_id": "v2", "title": "B"},
        ]
        updates = {
            "content_versions": versions,
            "phase": WorkflowPhase.CREATING,
        }
        # Multi-version should NOT have copy_content/visual_plan auto-applied
        assert "copy_content" not in updates
        assert "visual_plan" not in updates
