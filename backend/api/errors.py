"""Standardized error codes and exception classes."""

from enum import StrEnum
from typing import Any

from backend.api.responses import ApiResponse, error


class ErrorCode(StrEnum):
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
    # Authentication errors
    AUTH_TOKEN_MISSING = "ERROR_AUTH_TOKEN_MISSING"
    AUTH_TOKEN_INVALID = "ERROR_AUTH_TOKEN_INVALID"
    AUTH_TOKEN_EXPIRED = "ERROR_AUTH_TOKEN_EXPIRED"
    AUTH_LOGIN_FAILED = "ERROR_AUTH_LOGIN_FAILED"


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


class ChoiceNotPendingError(APIError):
    """No pending version selection exception."""

    def __init__(self, thread_id: str, current_phase: str):
        super().__init__(
            code=ErrorCode.REVIEW_NOT_PENDING,
            message="Workflow is not awaiting version selection",
            details={"thread_id": thread_id, "current_phase": current_phase},
            status_code=400,
        )


class ValidationError(APIError):
    """Validation error exception."""

    def __init__(self, field: str, reason: str):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=reason,
            details={"field": field, "reason": reason},
            status_code=400,
        )


# Authentication exceptions
class AuthenticationError(APIError):
    """Base authentication exception."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(code=code, message=message, details=details, status_code=401)


class TokenMissingError(AuthenticationError):
    """Token missing in request."""

    def __init__(self):
        super().__init__(
            code=ErrorCode.AUTH_TOKEN_MISSING,
            message="Authorization token required",
            details={"hint": "Include Authorization: Bearer <token> header"},
        )


class TokenInvalidError(AuthenticationError):
    """Token invalid or expired."""

    def __init__(self, reason: str = "invalid"):
        super().__init__(
            code=ErrorCode.AUTH_TOKEN_INVALID,
            message=f"Token {reason}",
            details={"reason": reason},
        )


class LoginFailedError(AuthenticationError):
    """Login failed."""

    def __init__(self, reason: str = "Invalid credentials"):
        super().__init__(
            code=ErrorCode.AUTH_LOGIN_FAILED,
            message="Login failed",
            details={"reason": reason},
        )


# ── Publish error classification ──


class PublishErrorType(StrEnum):
    """Structured publish error types for actionable recovery."""

    AUTH_EXPIRED = "auth_expired"
    RATE_LIMITED = "rate_limited"
    CONTENT_VIOLATION = "content_violation"
    IMAGE_MISSING = "image_missing"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


_PUBLISH_ERROR_PATTERNS: list[tuple[str, PublishErrorType]] = [
    ("cookie", PublishErrorType.AUTH_EXPIRED),
    ("login", PublishErrorType.AUTH_EXPIRED),
    ("token", PublishErrorType.AUTH_EXPIRED),
    ("auth", PublishErrorType.AUTH_EXPIRED),
    ("401", PublishErrorType.AUTH_EXPIRED),
    ("403", PublishErrorType.AUTH_EXPIRED),
    ("rate limit", PublishErrorType.RATE_LIMITED),
    ("429", PublishErrorType.RATE_LIMITED),
    ("too many", PublishErrorType.RATE_LIMITED),
    ("throttl", PublishErrorType.RATE_LIMITED),
    ("违规", PublishErrorType.CONTENT_VIOLATION),
    ("violation", PublishErrorType.CONTENT_VIOLATION),
    ("审核", PublishErrorType.CONTENT_VIOLATION),
    ("sensitive", PublishErrorType.CONTENT_VIOLATION),
    ("image", PublishErrorType.IMAGE_MISSING),
    ("图片", PublishErrorType.IMAGE_MISSING),
    ("photo", PublishErrorType.IMAGE_MISSING),
    ("upload", PublishErrorType.IMAGE_MISSING),
    ("network", PublishErrorType.NETWORK_ERROR),
    ("timeout", PublishErrorType.NETWORK_ERROR),
    ("connection", PublishErrorType.NETWORK_ERROR),
    ("ECONNREFUSED", PublishErrorType.NETWORK_ERROR),
    ("fetch", PublishErrorType.NETWORK_ERROR),
]

_PUBLISH_RECOVERY_ACTIONS: dict[PublishErrorType, dict] = {
    PublishErrorType.AUTH_EXPIRED: {
        "message": "登录凭证已失效，请重新配置 XHS_COOKIE",
        "action": "reconfigure",
        "action_label": "重新配置",
        "hint": "在 .env 文件中更新 XHS_COOKIE 后重启服务",
    },
    PublishErrorType.RATE_LIMITED: {
        "message": "发布频率过高，请稍后再试",
        "action": "retry_later",
        "action_label": "稍后重试",
        "hint": "建议等待 10-30 分钟后重试",
    },
    PublishErrorType.CONTENT_VIOLATION: {
        "message": "内容可能违反平台规则，请修改后重试",
        "action": "revise_content",
        "action_label": "修改内容",
        "hint": "检查标题、正文是否包含敏感词或违规内容",
    },
    PublishErrorType.IMAGE_MISSING: {
        "message": "图片缺失或上传失败",
        "action": "provide_images",
        "action_label": "补充图片",
        "hint": "确保图片文件存在且格式正确（JPG/PNG）",
    },
    PublishErrorType.NETWORK_ERROR: {
        "message": "网络连接失败，请检查网络后重试",
        "action": "retry",
        "action_label": "重试",
        "hint": "检查网络连接是否正常",
    },
    PublishErrorType.UNKNOWN: {
        "message": "发布遇到未知错误",
        "action": "retry",
        "action_label": "重试",
        "hint": "如持续出现请联系管理员",
    },
}


def classify_publish_error(error_msg: str) -> tuple[PublishErrorType, dict]:
    """Classify a publish error message into a structured type with recovery action."""
    lower = error_msg.lower()
    for pattern, error_type in _PUBLISH_ERROR_PATTERNS:
        if pattern.lower() in lower:
            return error_type, _PUBLISH_RECOVERY_ACTIONS[error_type]
    return PublishErrorType.UNKNOWN, _PUBLISH_RECOVERY_ACTIONS[PublishErrorType.UNKNOWN]
