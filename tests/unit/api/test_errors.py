from backend.api.errors import (
    ErrorCode,
    PublishErrorType,
    ReviewNotPendingError,
    ValidationError,
    WorkflowNotFoundError,
    classify_publish_error,
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


# ── classify_publish_error — publish-failure recovery classification ──


def test_classify_auth_expired():
    """Cookie/login/token/auth/401/403 → AUTH_EXPIRED with reconfigure action."""
    msgs = [
        "cookie expired", "需要重新登录", "invalid token",
        "auth failed", "401 Unauthorized", "403 Forbidden",
    ]
    for msg in msgs:
        et, recovery = classify_publish_error(msg)
        assert et is PublishErrorType.AUTH_EXPIRED, msg
        assert recovery["action"] == "reconfigure"


def test_classify_rate_limited():
    """rate limit / 429 / too many / throttl → RATE_LIMITED."""
    for msg in ["rate limit exceeded", "429 Too Many Requests", "too many requests", "throttled"]:
        et, _ = classify_publish_error(msg)
        assert et is PublishErrorType.RATE_LIMITED, msg


def test_classify_content_violation():
    """违规/violation/审核/sensitive → CONTENT_VIOLATION."""
    for msg in ["内容违规", "content violation", "审核未通过", "sensitive content"]:
        et, _ = classify_publish_error(msg)
        assert et is PublishErrorType.CONTENT_VIOLATION, msg


def test_classify_image_missing():
    """image/图片/photo/upload → IMAGE_MISSING."""
    for msg in ["image upload failed", "图片缺失", "photo too large", "upload error"]:
        et, _ = classify_publish_error(msg)
        assert et is PublishErrorType.IMAGE_MISSING, msg


def test_classify_network_error():
    """network/timeout/connection/ECONNREFUSED/fetch → NETWORK_ERROR."""
    msgs = [
        "network unreachable", "Timeout 30000ms exceeded",
        "connection reset", "ECONNREFUSED", "fetch failed",
    ]
    for msg in msgs:
        et, _ = classify_publish_error(msg)
        assert et is PublishErrorType.NETWORK_ERROR, msg


def test_classify_case_insensitive():
    """Pattern matching is case-insensitive."""
    et, _ = classify_publish_error("RATE LIMIT")
    assert et is PublishErrorType.RATE_LIMITED


def test_classify_unknown_fallback():
    """Unrecognized message → UNKNOWN with retry action."""
    et, recovery = classify_publish_error("something totally unexpected happened")
    assert et is PublishErrorType.UNKNOWN
    assert recovery["action"] == "retry"
    # recovery dict always has the fields the frontend renders
    assert {"message", "action", "action_label", "hint"} <= set(recovery)


def test_classify_recovery_dict_shape():
    """Every error type's recovery dict has the full action contract."""
    from backend.api.errors import _PUBLISH_RECOVERY_ACTIONS

    for et in PublishErrorType:
        rec = _PUBLISH_RECOVERY_ACTIONS[et]
        assert {"message", "action", "action_label", "hint"} <= set(rec), et
