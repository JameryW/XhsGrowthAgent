"""Unified error handling for XHS Growth Agent."""

from typing import Any, Literal

from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

# ── Error taxonomy (P0-W3) ──
# Which recovery track a failure belongs to. Recorded on state (`error_class`)
# so downstream retry/recovery logic can distinguish them. Routing semantics
# are UNCHANGED in P0: unknown errors classify as "transient", which keeps
# the pre-existing retry behavior identical. A unified retry engine consuming
# these classes is P1/P2 scope.
ErrorClass = Literal[
    "transient",
    "semantic",
    "side_effect_unknown",
    "policy_violation",
    "auth_expired",
]

ERROR_CLASS_TRANSIENT: ErrorClass = "transient"  # 网络/429/timeout — 可自动重试
ERROR_CLASS_SEMANTIC: ErrorClass = "semantic"  # 输出非法/无结果 — 需修复或重规划
ERROR_CLASS_SIDE_EFFECT_UNKNOWN: ErrorClass = "side_effect_unknown"  # 外部动作结果不明
ERROR_CLASS_POLICY_VIOLATION: ErrorClass = "policy_violation"  # 需人工，fail-closed
ERROR_CLASS_AUTH_EXPIRED: ErrorClass = "auth_expired"  # 需人工（重新登录），fail-closed

# Substring signals — intentionally small and cheap; anything unrecognized
# falls back to "transient" (old behavior: every error used the retry path).
_SEMANTIC_MARKERS = (
    "json",
    "parse",
    "invalid output",
    "no result",
    "未返回",
    "无法解析",
    "解析失败",
    "schema",
)
_POLICY_MARKERS = (
    "违规",
    "policy",
    "content_violation",
    "sensitive word",
)
_AUTH_MARKERS = (
    "auth",
    "401",
    "403",
    "cookie",
    "凭证",
    "登录",
    "token invalid",
    "expired",
)


def classify_error(error: Exception) -> ErrorClass:
    """Classify an exception into the shared error taxonomy (P0-W3).

    Deterministic and conservative: timeout/connection/rate-limit style
    failures are `transient` (safe to retry), malformed-output style failures
    are `semantic`, authentication failures are `auth_expired`. Anything else
    defaults to `transient` so routing behavior stays exactly what it was
    before the taxonomy existed.
    """
    if isinstance(error, TimeoutError | ConnectionError | OSError):
        return ERROR_CLASS_TRANSIENT
    if type(error).__name__ in ("TimeoutError", "APITimeoutError", "ConnectTimeout"):
        return ERROR_CLASS_TRANSIENT
    name = type(error).__name__.lower()
    msg = str(error).lower()
    if "timeout" in name or "timeout" in msg:
        return ERROR_CLASS_TRANSIENT
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return ERROR_CLASS_TRANSIENT
    if "auth" in name.lower():
        return ERROR_CLASS_AUTH_EXPIRED
    for marker in _AUTH_MARKERS:
        if marker in msg:
            return ERROR_CLASS_AUTH_EXPIRED
    for marker in _POLICY_MARKERS:
        if marker in msg:
            return ERROR_CLASS_POLICY_VIOLATION
    for marker in _SEMANTIC_MARKERS:
        if marker in msg:
            return ERROR_CLASS_SEMANTIC
    return ERROR_CLASS_TRANSIENT


class AgentError(Exception):
    """Agent execution error — should be caught by LangGraph retry."""

    def __init__(self, agent_name: str, cause: Exception, phase: str | None = None):
        # Backward compat: old code passed (agent_name, phase_str, original_error)
        # Detect old convention: if cause is a string, it's actually the phase
        if isinstance(cause, str) and phase is not None and isinstance(phase, Exception):
            # Old calling convention: (agent_name, phase, original_error)
            actual_phase = cause
            actual_cause = phase
            cause = actual_cause
            phase = actual_phase

        self.agent_name = agent_name
        self.cause = cause
        self.phase = phase
        # Backward compat alias
        self.original_error = cause
        super().__init__(f"Agent {agent_name} failed: {cause}")


class WorkflowCancelledError(Exception):
    """Workflow was cancelled — nodes should stop execution."""

    pass


def handle_agent_error(
    error: Exception, state: XHSGrowthState, *, agent_name: str = ""
) -> dict[str, Any]:
    """统一错误处理，返回状态更新。

    Called from BaseAgent.__call__ except block (stateful retry path).
    Returns a state update dict — NOT raising — so LangGraph merges it into
    state and downstream routers (should_plan/orchestrator) can read
    retry_count to decide stateful retry vs termination.

    See prd ADR-lite: trading LangGraph RetryPolicy (framework-level, only
    triggers on exceptions) for stateful cross-super-step retry (business
    routers reading retry_count).

    P0-W3: the failure is also classified into the error taxonomy and recorded
    in the (new, additive) `error_class` state field so it reaches checkpoints
    and observers. No router reads it yet — default `transient` preserves the
    pre-existing routing behavior exactly.
    """
    return {
        "phase": WorkflowPhase.ERROR,
        "error": str(error),
        "error_class": classify_error(error),
        "retry_count": state.get("retry_count", 0) + 1,
        "current_agent": agent_name,
    }
