"""Unified enum definitions - synced with OpenAPI specification."""

from enum import StrEnum


class WorkflowPhase(StrEnum):
    """Workflow execution phase."""

    IDLE = "idle"
    BRIEFING = "briefing"  # Brief mode: parsing/analyzing brief
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


class ExecutionMode(StrEnum):
    """Workflow execution mode."""

    SINGLE = "single"  # One content cycle, then completed
    CONTINUOUS = "continuous"  # Loop back to orchestrator after each cycle


class WorkflowMode(StrEnum):
    """Workflow input mode — determines starting node and pipeline path."""

    TREND = "trend"  # Trend discovery mode (existing flow: trend_scout → ...)
    BRIEF = "brief"  # Brief-based mode (brief_analyzer → shooting_planner → ...)
