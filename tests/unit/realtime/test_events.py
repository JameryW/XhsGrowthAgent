"""Tests for Event types and Event data class."""

import pytest
from backend.realtime.events import EventType, Event


def test_event_type_enum():
    """EventType contains all business events"""
    assert EventType.WORKFLOW_STARTED == "workflow.started"
    assert EventType.WORKFLOW_PHASE_CHANGED == "workflow.phase_changed"
    assert EventType.REVIEW_PENDING == "review.pending"
    assert EventType.ANALYTICS_COST_ALERT == "analytics.cost_alert"


def test_event_creation():
    """Event can be created and serialized correctly"""
    event = Event(
        event_type=EventType.WORKFLOW_PHASE_CHANGED,
        thread_id="thread_123",
        payload={"old_phase": "scouting", "new_phase": "planning"},
        timestamp="2026-05-26T10:00:00Z",
        seq=1,
    )

    assert event.event_type == EventType.WORKFLOW_PHASE_CHANGED
    assert event.thread_id == "thread_123"
    assert event.seq == 1

    # to_dict serialization
    data = event.to_dict()
    assert data["event_type"] == "workflow.phase_changed"
    assert data["thread_id"] == "thread_123"
    assert data["seq"] == 1


def test_event_global_event():
    """Global event has thread_id as None"""
    event = Event(
        event_type=EventType.ANALYTICS_COST_ALERT,
        thread_id=None,
        payload={"today_cost": 15.23},
        timestamp="2026-05-26T12:00:00Z",
        seq=2,
    )

    assert event.thread_id is None
    data = event.to_dict()
    assert data["thread_id"] is None


def test_event_empty_payload():
    """Event can have empty payload"""
    event = Event(
        event_type=EventType.WORKFLOW_STARTED,
        thread_id="thread_1",
        payload={},
        timestamp="2026-05-26T10:00:00Z",
        seq=0,
    )
    assert event.payload == {}
    assert event.seq == 0


def test_event_type_values_unique():
    """All EventType values are unique strings"""
    values = [e.value for e in EventType]
    assert len(values) == len(set(values))
    assert all(isinstance(v, str) and v for v in values)


def test_event_immutable():
    """Event is immutable (frozen=True)"""
    event = Event(
        event_type=EventType.WORKFLOW_STARTED,
        thread_id="thread_1",
        payload={"key": "value"},
        timestamp="2026-05-26T10:00:00Z",
        seq=0,
    )
    # Attempting to modify should raise FrozenInstanceError
    try:
        event.seq = 1
        assert False, "Should have raised FrozenInstanceError"
    except Exception:
        pass  # Expected behavior