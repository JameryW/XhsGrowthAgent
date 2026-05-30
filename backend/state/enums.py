"""Unified enum definitions - synced with OpenAPI specification."""
from enum import StrEnum


class WorkflowPhase(StrEnum):
    """Workflow execution phase."""
    IDLE = "idle"
    SCOUTING = "scouting"
    PLANNING = "planning"
    CREATING = "creating"
    REVIEWING = "reviewing"
    PUBLISHING = "publishing"
    ANALYZING = "analyzing"
    ENGAGING = "engaging"
    COMPLETED = "completed"
    ERROR = "error"
    PAUSED = "paused"
    CANCELLED = "cancelled"

class ContentStatus(StrEnum):
    """Content review status."""
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    FAILED = "failed"

class ContentType(StrEnum):
    """Content type."""
    NOTE = "note"
    VIDEO = "video"
    CAROUSEL = "carousel"

class Urgency(StrEnum):
    """Content urgency level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    TRENDING = "trending"