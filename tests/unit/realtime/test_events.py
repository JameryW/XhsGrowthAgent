"""Tests for Event types and Event data class."""

import pytest
from xhs_growth.realtime.events import EventType, Event


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