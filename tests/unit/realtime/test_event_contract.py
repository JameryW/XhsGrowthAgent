"""Tests for realtime event payload contracts."""

from backend.realtime.events import Event, EventType


class TestEventContract:
    """Verify event payloads match frontend expectations."""

    def test_workflow_phase_changed_has_required_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_PHASE_CHANGED,
            thread_id="test_123",
            payload={
                "old_phase": "scouting",
                "new_phase": "planning",
                "current_agent": "orchestrator",
            },
            timestamp="2026-05-30T00:00:00Z",
            seq=0,
        )
        d = event.to_dict()
        assert d["event_type"] == "workflow.phase_changed"
        assert d["thread_id"] == "test_123"
        assert "old_phase" in d["payload"]
        assert "new_phase" in d["payload"]
        assert "current_agent" in d["payload"]

    def test_workflow_data_updated_has_required_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_DATA_UPDATED,
            thread_id="test_123",
            payload={"data_type": "trend_data", "data": {"hot_topics": []}},
            timestamp="2026-05-30T00:00:00Z",
            seq=1,
        )
        d = event.to_dict()
        assert d["event_type"] == "workflow.data_updated"
        assert "data_type" in d["payload"]
        assert "data" in d["payload"]

    def test_review_pending_has_required_fields(self):
        event = Event(
            event_type=EventType.REVIEW_PENDING,
            thread_id="test_123",
            payload={
                "content_plan": {"selected_topic": "test"},
                "copy_content": {"selected_title": "title"},
                "visual_plan": {"layout_style": "grid"},
            },
            timestamp="2026-05-30T00:00:00Z",
            seq=2,
        )
        d = event.to_dict()
        assert d["event_type"] == "review.pending"
        assert "content_plan" in d["payload"]
        assert "copy_content" in d["payload"]
        assert "visual_plan" in d["payload"]

    def test_workflow_started_has_required_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_STARTED,
            thread_id="test_123",
            payload={
                "phase": "scouting",
                "account_id": "default",
                "dry_run": True,
            },
            timestamp="2026-05-30T00:00:00Z",
            seq=3,
        )
        d = event.to_dict()
        assert d["event_type"] == "workflow.started"
        assert "phase" in d["payload"]
        assert "dry_run" in d["payload"]

    def test_workflow_agent_started_has_required_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_AGENT_STARTED,
            thread_id="test_123",
            payload={"agent": "trend_scout"},
            timestamp="2026-05-30T00:00:00Z",
            seq=4,
        )
        d = event.to_dict()
        assert d["event_type"] == "workflow.agent_started"
        assert "agent" in d["payload"]

    def test_workflow_agent_completed_has_required_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_AGENT_COMPLETED,
            thread_id="test_123",
            payload={"agent": "publisher", "status": "success"},
            timestamp="2026-05-30T00:00:00Z",
            seq=5,
        )
        d = event.to_dict()
        assert d["event_type"] == "workflow.agent_completed"
        assert "agent" in d["payload"]
        assert "status" in d["payload"]

    def test_workflow_completed_has_required_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_COMPLETED,
            thread_id="test_123",
            payload={"publish_result": {"status": "published", "post_id": "abc"}},
            timestamp="2026-05-30T00:00:00Z",
            seq=6,
        )
        d = event.to_dict()
        assert d["event_type"] == "workflow.completed"
        assert "publish_result" in d["payload"]

    def test_event_serialization_preserves_all_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_PHASE_CHANGED,
            thread_id="thread_456",
            payload={
                "old_phase": "planning",
                "new_phase": "creating",
                "current_agent": "content_strategist",
            },
            timestamp="2026-05-30T12:00:00Z",
            seq=42,
        )
        d = event.to_dict()
        assert d["thread_id"] == "thread_456"
        assert d["timestamp"] == "2026-05-30T12:00:00Z"
        assert d["seq"] == 42
