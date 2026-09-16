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
    CREATOR_NOTE_NOT_FOUND = "ERROR_CREATOR_NOTE_NOT_FOUND"
    CREATOR_MODEL_NOT_FOUND = "ERROR_CREATOR_MODEL_NOT_FOUND"
    CREATOR_MODEL_REVISION_CONFLICT = "ERROR_CREATOR_MODEL_REVISION_CONFLICT"
    CREATOR_MODEL_REVISION_NOT_FOUND = "ERROR_CREATOR_MODEL_REVISION_NOT_FOUND"
    CREATOR_DECISION_NOT_FOUND = "ERROR_CREATOR_DECISION_NOT_FOUND"
    CREATOR_FEEDBACK_AUDIENCE_MISMATCH = "ERROR_CREATOR_FEEDBACK_AUDIENCE_MISMATCH"
    CREATOR_LEARNING_SIGNAL_NOT_FOUND = "ERROR_CREATOR_LEARNING_SIGNAL_NOT_FOUND"
    CREATOR_LEARNING_SIGNAL_CONFLICT = "ERROR_CREATOR_LEARNING_SIGNAL_CONFLICT"
    CREATOR_EVIDENCE_NOT_FOUND = "ERROR_CREATOR_EVIDENCE_NOT_FOUND"
    CREATOR_ACTION_NOT_FOUND = "ERROR_CREATOR_ACTION_NOT_FOUND"
    CREATOR_ACTION_CONFLICT = "ERROR_CREATOR_ACTION_CONFLICT"
    CREATOR_ACTION_EXECUTION_NOT_FOUND = "ERROR_CREATOR_ACTION_EXECUTION_NOT_FOUND"
    CREATOR_ACTION_EXECUTION_NOT_ALLOWED = "ERROR_CREATOR_ACTION_EXECUTION_NOT_ALLOWED"
    CREATOR_ACTION_CAPABILITY_NOT_WIRED = "ERROR_CREATOR_ACTION_CAPABILITY_NOT_WIRED"
    CREATOR_ACTION_POLICY_DENIED = "ERROR_CREATOR_ACTION_POLICY_DENIED"
    CREATOR_ACTION_PUBLISH_CONTENT_UNAVAILABLE = "ERROR_CREATOR_ACTION_PUBLISH_CONTENT_UNAVAILABLE"
    CREATOR_ACTION_CREDENTIAL_UNAVAILABLE = "ERROR_CREATOR_ACTION_CREDENTIAL_UNAVAILABLE"
    ACCOUNT_AUTH_FAILED = "ERROR_ACCOUNT_AUTH_FAILED"
    CONSOLE_USER_NOT_FOUND = "ERROR_CONSOLE_USER_NOT_FOUND"
    CONSOLE_USER_DUPLICATE = "ERROR_CONSOLE_USER_DUPLICATE"
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

    def to_response(self, request_id: str | None = None) -> ApiResponse[Any]:
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


class CreatorNoteNotFoundError(APIError):
    """Imported Creator Center note not found for an account."""

    def __init__(self, account_id: str, note_id: str):
        super().__init__(
            code=ErrorCode.CREATOR_NOTE_NOT_FOUND,
            message=f"Creator note '{note_id}' not found for account '{account_id}'",
            details={"account_id": account_id, "note_id": note_id},
            status_code=404,
        )


class CreatorModelNotFoundError(APIError):
    """No Creator Model has been initialized for an account."""

    def __init__(self, account_id: str):
        super().__init__(
            code=ErrorCode.CREATOR_MODEL_NOT_FOUND,
            message=f"Creator Model not found for account '{account_id}'",
            details={"account_id": account_id},
            status_code=404,
        )


class CreatorModelRevisionConflictError(APIError):
    """The caller attempted to overwrite a newer Creator Model revision."""

    def __init__(self, expected: int, actual: int):
        super().__init__(
            code=ErrorCode.CREATOR_MODEL_REVISION_CONFLICT,
            message="Creator Model revision is stale",
            details={"expected_revision": expected, "actual_revision": actual},
            status_code=409,
        )


class CreatorModelRevisionNotFoundError(APIError):
    """No immutable Model Revision snapshot exists for the requested revision.

    Foreign accounts and genuinely absent revisions are intentionally
    indistinguishable so history cannot be probed across accounts.
    """

    def __init__(self, account_id: str, revision: int):
        super().__init__(
            code=ErrorCode.CREATOR_MODEL_REVISION_NOT_FOUND,
            message=f"Creator Model revision {revision} not found",
            details={"account_id": account_id, "revision": revision},
            status_code=404,
        )


class CreatorDecisionNotFoundError(APIError):
    """Decision record is missing or not visible to the account owner."""

    def __init__(self, decision_id: str):
        super().__init__(
            code=ErrorCode.CREATOR_DECISION_NOT_FOUND,
            message=f"Creator decision '{decision_id}' not found",
            details={"decision_id": decision_id},
            status_code=404,
        )


class CreatorFeedbackAudienceMismatchError(APIError):
    """Feedback cannot be attached to another audience member's decision."""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.CREATOR_FEEDBACK_AUDIENCE_MISMATCH,
            message="Feedback audience does not match the decision audience",
            status_code=400,
        )


class CreatorLearningSignalNotFoundError(APIError):
    """Learning signal is missing or not visible to the account owner."""

    def __init__(self, signal_id: str):
        super().__init__(
            code=ErrorCode.CREATOR_LEARNING_SIGNAL_NOT_FOUND,
            message=f"Creator learning signal '{signal_id}' not found",
            details={"signal_id": signal_id},
            status_code=404,
        )


class CreatorLearningSignalConflictError(APIError):
    """A reviewed signal cannot be assigned a different disposition."""

    def __init__(self, signal_id: str, status: str):
        super().__init__(
            code=ErrorCode.CREATOR_LEARNING_SIGNAL_CONFLICT,
            message="Creator learning signal has already been reviewed",
            details={"signal_id": signal_id, "status": status},
            status_code=409,
        )


class CreatorEvidenceNotFoundError(APIError):
    """Evidence is missing or not visible to the account owner."""

    def __init__(self, evidence_id: str):
        super().__init__(
            code=ErrorCode.CREATOR_EVIDENCE_NOT_FOUND,
            message=f"Creator evidence '{evidence_id}' not found",
            details={"evidence_id": evidence_id},
            status_code=404,
        )


class CreatorActionNotFoundError(APIError):
    """Action intent is missing or not visible to the account owner."""

    def __init__(self, action_id: str):
        super().__init__(
            code=ErrorCode.CREATOR_ACTION_NOT_FOUND,
            message=f"Creator action '{action_id}' not found",
            details={"action_id": action_id},
            status_code=404,
        )


class CreatorActionConflictError(APIError):
    """A resolved action cannot be assigned a different disposition."""

    def __init__(self, action_id: str, status: str):
        super().__init__(
            code=ErrorCode.CREATOR_ACTION_CONFLICT,
            message="Creator action has already been resolved",
            details={"action_id": action_id, "status": status},
            status_code=409,
        )


class CreatorActionExecutionNotFoundError(APIError):
    """Execution receipt is missing or not visible to the account owner."""

    def __init__(self, action_id: str):
        super().__init__(
            code=ErrorCode.CREATOR_ACTION_EXECUTION_NOT_FOUND,
            message=f"Creator action execution for '{action_id}' not found",
            details={"action_id": action_id},
            status_code=404,
        )


class CreatorActionExecutionNotAllowedError(APIError):
    """Action Intent has not been confirmed and cannot be executed."""

    def __init__(self, action_id: str, status: str):
        super().__init__(
            code=ErrorCode.CREATOR_ACTION_EXECUTION_NOT_ALLOWED,
            message="Creator action must be confirmed before execution",
            details={"action_id": action_id, "status": status},
            status_code=409,
        )


class CreatorActionCapabilityNotWiredError(APIError):
    """The action kind has a durable intent but no executor wired yet."""

    def __init__(self, action_id: str, action_kind: str):
        super().__init__(
            code=ErrorCode.CREATOR_ACTION_CAPABILITY_NOT_WIRED,
            message=f"Creator action kind '{action_kind}' has no executor yet",
            details={"action_id": action_id, "action_kind": action_kind},
            status_code=501,
        )


class CreatorActionPolicyDeniedError(APIError):
    """Deterministic policy refused the action before an intent was created.

    403 rather than 409: the request is well-formed and the caller is allowed to
    make it -- the account's current state is what makes it refuse.  ``policy_id``
    is the stable handle for that state, and ``retry_after_seconds`` (when
    present) tells the caller when asking again could succeed.
    """

    def __init__(
        self,
        *,
        policy_id: str,
        reason: str,
        account_id: str,
        retry_after_seconds: int | None = None,
    ):
        details: dict[str, Any] = {"policy_id": policy_id, "account_id": account_id}
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds
        super().__init__(
            code=ErrorCode.CREATOR_ACTION_POLICY_DENIED,
            message=reason or "Creator action refused by policy",
            details=details,
            status_code=403,
        )


class CreatorActionPublishContentUnavailableError(APIError):
    """A confirmed publish intent has no payload the executor can act on.

    409, not 501: nothing is missing *in the wiring* -- the capability is
    executable -- the intent itself is not actionable (no thread to resolve its
    artifact under, or an unreadable/misshaped body).  Refusing here is also
    what keeps the failure free of side effects: the Gateway is never reached,
    so no receipt is minted and nothing is posted.
    """

    def __init__(self, *, action_id: str, reason: str):
        super().__init__(
            code=ErrorCode.CREATOR_ACTION_PUBLISH_CONTENT_UNAVAILABLE,
            message=reason or "Creator action has no publishable content",
            details={"action_id": action_id},
            status_code=409,
        )


class CreatorActionCredentialUnavailableError(APIError):
    """The account holds no credential for the capability being executed.

    409, like the content refusal above and for the same reason: nothing is
    missing in the wiring -- the capability is executable and the caller is
    allowed to ask -- the *account* cannot act, because no usable credential
    was resolved for it.  403 stays reserved for the policy engine, which is a
    rule saying no rather than a precondition that is not met.

    ``required_scopes`` names what the capability declares it needs, so a
    caller can tell which grant to provision without reading the catalog.
    """

    def __init__(self, *, account_id: str, required_scopes: tuple[str, ...], reason: str):
        super().__init__(
            code=ErrorCode.CREATOR_ACTION_CREDENTIAL_UNAVAILABLE,
            message=reason or "Creator action account has no usable credential",
            details={"account_id": account_id, "required_scopes": list(required_scopes)},
            status_code=409,
        )


class AccountNotFoundError(APIError):
    """Account missing or not visible to the current console user."""

    def __init__(self, account_id: str):
        super().__init__(
            code=ErrorCode.ACCOUNT_NOT_FOUND,
            message=f"Account '{account_id}' not found",
            details={"account_id": account_id},
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

    def __init__(self) -> None:
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
    ACCOUNT_UNVERIFIED = "account_unverified"
    RATE_LIMITED = "rate_limited"
    CONTENT_VIOLATION = "content_violation"
    IMAGE_MISSING = "image_missing"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


_PUBLISH_ERROR_PATTERNS: list[tuple[str, PublishErrorType]] = [
    ("cookie", PublishErrorType.AUTH_EXPIRED),
    ("login", PublishErrorType.AUTH_EXPIRED),
    ("登录", PublishErrorType.AUTH_EXPIRED),
    ("凭证", PublishErrorType.AUTH_EXPIRED),
    ("token", PublishErrorType.AUTH_EXPIRED),
    ("auth", PublishErrorType.AUTH_EXPIRED),
    ("401", PublishErrorType.AUTH_EXPIRED),
    ("403", PublishErrorType.AUTH_EXPIRED),
    ("未绑定手机号", PublishErrorType.ACCOUNT_UNVERIFIED),
    ("绑定手机号", PublishErrorType.ACCOUNT_UNVERIFIED),
    ("手机号", PublishErrorType.ACCOUNT_UNVERIFIED),
    ("实名", PublishErrorType.ACCOUNT_UNVERIFIED),
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

_PUBLISH_RECOVERY_ACTIONS: dict[PublishErrorType, dict[str, Any]] = {
    PublishErrorType.AUTH_EXPIRED: {
        "message": "小红书登录态已失效，请重新扫码登录",
        "action": "reconfigure",
        "action_label": "去设置",
        "hint": "请在设置页启动该账号浏览器并重新扫码登录",
    },
    PublishErrorType.ACCOUNT_UNVERIFIED: {
        "message": "小红书账号未完成平台要求的手机号/实名校验",
        "action": "verify_account",
        "action_label": "绑定手机号",
        "hint": "请在当前小红书账号中绑定手机号或完成账号安全校验后重试发布",
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


def classify_publish_error(error_msg: str) -> tuple[PublishErrorType, dict[str, Any]]:
    """Classify a publish error message into a structured type with recovery action."""
    lower = error_msg.lower()
    for pattern, error_type in _PUBLISH_ERROR_PATTERNS:
        if pattern.lower() in lower:
            return error_type, _PUBLISH_RECOVERY_ACTIONS[error_type]
    return PublishErrorType.UNKNOWN, _PUBLISH_RECOVERY_ACTIONS[PublishErrorType.UNKNOWN]
