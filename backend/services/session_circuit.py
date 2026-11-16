"""Process-wide account session circuit breakers.

The breaker contract lives in :mod:`backend.services.content_launch`; this
module gives it one process-wide instance per account and the small API the
browser-facing publisher uses.  A hard login/signature failure trips the
breaker immediately; repeated transient errors degrade it.  Calls for an open
account fail closed without touching the browser.

This is intentionally process-local: it prevents a hot loop from hammering a
broken browser profile in one worker, while the durable execution ledger and
the platform-side risk gate remain the cross-worker truth.
"""

from __future__ import annotations

from datetime import datetime

from backend.services.content_launch import (
    AccountSessionCircuitBreaker,
    SessionCircuitSnapshot,
)

_BREAKERS: dict[str, AccountSessionCircuitBreaker] = {}


class SessionCircuitOpenError(RuntimeError):
    """Raised when an account's session circuit is open (or cooling down)."""

    def __init__(self, snapshot: SessionCircuitSnapshot) -> None:
        self.snapshot = snapshot
        super().__init__(
            f"session circuit open for {snapshot.account_id!r}: {snapshot.reason or 'cooldown'}"
        )


def breaker_for(
    account_id: str,
    *,
    cooldown_seconds: float = 1800.0,
    degraded_threshold: int = 3,
) -> AccountSessionCircuitBreaker:
    key = (account_id or "").strip()
    breaker = _BREAKERS.get(key)
    if breaker is None:
        breaker = AccountSessionCircuitBreaker(
            key,
            cooldown_seconds=cooldown_seconds,
            degraded_threshold=degraded_threshold,
        )
        _BREAKERS[key] = breaker
    return breaker


def check_session_allowed(
    account_id: str,
    *,
    now: datetime | None = None,
) -> SessionCircuitSnapshot:
    """Return the current snapshot or raise when the account must not call out."""

    breaker = breaker_for(account_id)
    if not breaker.allow_attempt(now):
        raise SessionCircuitOpenError(breaker.snapshot(now))
    return breaker.snapshot(now)


def record_success(account_id: str, *, now: datetime | None = None) -> SessionCircuitSnapshot:
    return breaker_for(account_id).record_success(now)


def record_failure(
    account_id: str,
    *,
    error_code: str = "",
    message: str = "",
    now: datetime | None = None,
) -> SessionCircuitSnapshot:
    return breaker_for(account_id).record_failure(error_code, message, now=now)


def reset_session_circuits() -> None:
    """Test/operator hook: forget every process-local breaker."""

    _BREAKERS.clear()


__all__ = [
    "SessionCircuitOpenError",
    "breaker_for",
    "check_session_allowed",
    "record_failure",
    "record_success",
    "reset_session_circuits",
]
