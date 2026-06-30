"""Event types and Event data class for real-time updates."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    """All business event types enumeration."""

    # Workflow events
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_PHASE_CHANGED = "workflow.phase_changed"
    WORKFLOW_AGENT_STARTED = "workflow.agent_started"
    WORKFLOW_AGENT_COMPLETED = "workflow.agent_completed"
    WORKFLOW_DATA_UPDATED = "workflow.data_updated"
    WORKFLOW_PAUSED = "workflow.paused"
    WORKFLOW_RESUMED = "workflow.resumed"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_ERROR = "workflow.error"

    # Review events
    REVIEW_PENDING = "review.pending"
    REVIEW_SUBMITTED = "review.submitted"
    REVIEW_APPROVED = "review.approved"
    REVIEW_REJECTED = "review.rejected"
    REVIEW_NEEDS_REVISION = "review.needs_revision"

    # Ripple CAS engine events
    RIPPLE_PROGRESS = "ripple.progress"

    # Analytics events
    ANALYTICS_REPORT_UPDATED = "analytics.report_updated"
    ANALYTICS_COST_ALERT = "analytics.cost_alert"
    ANALYTICS_PERFORMANCE_NEW = "analytics.performance_new"


@dataclass(frozen=True)
class Event:
    """Single event data structure (immutable)."""

    event_type: EventType
    thread_id: str | None
    payload: dict[str, Any]
    timestamp: str
    seq: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize to WebSocket message format."""
        return {
            "event_type": self.event_type.value,
            "thread_id": self.thread_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "seq": self.seq,
        }
