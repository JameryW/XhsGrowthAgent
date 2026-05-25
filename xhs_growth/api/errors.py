"""Standardized error codes and exception classes."""
from typing import Any
from enum import Enum
from xhs_growth.api.responses import error, ApiResponse

class ErrorCode(str, Enum):
    """Standard error codes."""
    WORKFLOW_NOT_FOUND = "ERROR_WORKFLOW_NOT_FOUND"
    WORKFLOW_ALREADY_RUNNING = "ERROR_WORKFLOW_ALREADY_RUNNING"
    WORKFLOW_PHASE_INVALID = "ERROR_WORKFLOW_PHASE_INVALID"
    WORKFLOW_STATE_CORRUPT = "ERROR_WORKFLOW_STATE_CORRUPT"
    REVIEW_NOT_PENDING = "ERROR_REVIEW_NOT_PENDING"
    REVIEW_DECISION_INVALID = "ERROR_REVIEW_DECISION_INVALID"
    ACCOUNT_NOT_FOUND = "ERROR_ACCOUNT_NOT_FOUND"
    ACCOUNT_AUTH_FAILED = "ERROR_ACCOUNT_AUTH_FAILED"
    AGENT_EXECUTION_FAILED = "ERROR_AGENT_EXECUTION_FAILED"
    AGENT_TIMEOUT = "ERROR_AGENT_TIMEOUT"
    SERVICE_UNAVAILABLE = "ERROR_SERVICE_UNAVAILABLE"
    XHS_API_ERROR = "ERROR_XHS_API_ERROR"
    INTERNAL_ERROR = "ERROR_INTERNAL"
    VALIDATION_ERROR = "ERROR_VALIDATION"
    RATE_LIMIT_EXCEEDED = "ERROR_RATE_LIMIT"

class APIError(Exception):
    """Base API exception."""
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        status_code: int = 400,
    ):
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code
        super().__init__(message)

    def to_response(self, request_id: str | None = None) -> ApiResponse:
        """Convert to API response."""
        return error(
            code=self.code.value,
            message=self.message,
            details=self.details,
            request_id=request_id,
        )

class WorkflowNotFoundError(APIError):
    """Workflow not found exception."""
    def __init__(self, thread_id: str):
        super().__init__(
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            message=f"Workflow '{thread_id}' not found",
            details={"thread_id": thread_id},
            status_code=404,
        )

class ReviewNotPendingError(APIError):
    """No pending review exception."""
    def __init__(self, thread_id: str, current_phase: str):
        super().__init__(
            code=ErrorCode.REVIEW_NOT_PENDING,
            message="No pending review for this workflow",
            details={"thread_id": thread_id, "current_phase": current_phase},
            status_code=400,
        )

class ValidationError(APIError):
    """Validation error exception."""
    def __init__(self, field: str, reason: str):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Validation failed: {field}",
            details={"field": field, "reason": reason},
            status_code=400,
        )