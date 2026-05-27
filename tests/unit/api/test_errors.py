import pytest
from backend.api.errors import (
    ErrorCode, APIError,
    WorkflowNotFoundError, ValidationError, ReviewNotPendingError
)

def test_error_code_enum():
    assert ErrorCode.WORKFLOW_NOT_FOUND.value == "ERROR_WORKFLOW_NOT_FOUND"
    assert ErrorCode.VALIDATION_ERROR.value == "ERROR_VALIDATION"

def test_workflow_not_found_error():
    exc = WorkflowNotFoundError("test123")
    assert exc.code == ErrorCode.WORKFLOW_NOT_FOUND
    assert exc.status_code == 404
    assert "test123" in exc.message
    assert exc.details["thread_id"] == "test123"

def test_validation_error():
    exc = ValidationError("account_id", "is required")
    assert exc.code == ErrorCode.VALIDATION_ERROR
    assert exc.status_code == 400
    assert exc.details["field"] == "account_id"

def test_api_error_to_response():
    exc = WorkflowNotFoundError("test123")
    response = exc.to_response("req001")
    assert response.success is False
    assert response.request_id == "req001"
    assert response.error.code == ErrorCode.WORKFLOW_NOT_FOUND.value

def test_review_not_pending_error():
    """Test ReviewNotPendingError has correct attributes."""
    exc = ReviewNotPendingError("thread-abc", "creating")
    assert exc.code == ErrorCode.REVIEW_NOT_PENDING
    assert exc.status_code == 400
    assert "thread-abc" in exc.details["thread_id"]
    assert exc.details["current_phase"] == "creating"
    assert exc.message == "No pending review for this workflow"