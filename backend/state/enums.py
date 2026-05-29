"""Unified enum definitions - synced with OpenAPI specification."""
from enum import Enum

class WorkflowPhase(str, Enum):
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

class ContentStatus(str, Enum):
    """Content review status."""
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    FAILED = "failed"

class ContentType(str, Enum):
    """Content type."""
    NOTE = "note"
    VIDEO = "video"
    CAROUSEL = "carousel"

class Urgency(str, Enum):
    """Content urgency level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    TRENDING = "trending"