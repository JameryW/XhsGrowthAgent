"""Recovery policy (P2) — not every failure deserves another model call.

``backend/models/retry.py`` answers one question: retry or raise. The design
note asks a finer one — *what kind of recovery* fits this failure:

- a transient infrastructure error wants the **same** call again, no model
  change and no extra reasoning budget;
- a schema/argument error wants a cheaper, structured-output-friendly model,
  not a stronger one (a bigger model does not fix a malformed request);
- a repeated logic failure is the one case where stronger reasoning earns its
  cost;
- a permission or policy refusal wants **no retry at all** — asking again is
  how a system gets talked into a bypass.

This module classifies; it does not execute the switch. The tier wiring
(which model a DEGRADE/ESCALATE resolves to) is a configuration decision with
its own evidence bar, so the retry wrapper only records the classification
today — a decision log, not a behavior change.

Kept deliberately independent of ``retry._is_retryable``'s private helpers but
aligned with it by a test: any exception that layer considers retryable must
classify as ``RETRY_SAME`` here. Two rule tables that disagree are worse than
one.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "RecoveryAction",
    "classify_recovery",
]


class RecoveryAction(StrEnum):
    """What kind of recovery fits a failure."""

    RETRY_SAME = "retry_same"
    """Transient (429 / 5xx / network): same call, exponential backoff."""

    DEGRADE_MODEL = "degrade_model"
    """Bad arguments / schema / unparsable output: a cheaper structured model."""

    ESCALATE_MODEL = "escalate_model"
    """Repeated identical failure: stronger reasoning is the only lever left."""

    STOP_AND_REPORT = "stop_and_report"
    """Auth, permission, content policy: retrying is how bypasses happen."""


#: Status codes that mean "you are not allowed to do this" — never retried.
_DENIED_STATUSES = frozenset({401, 403})
#: Status codes that mean "the request itself is wrong" — a model switch may
#: help only if it produces a well-formed request; the caller decides.
_BAD_ARGUMENT_STATUSES = frozenset({400, 404, 409, 422})
#: Status codes that mean "try again later".
_TRANSIENT_STATUSES = frozenset({408, 425, 429})

_DENIED_NAME_HINTS = ("authentication", "permissiondenied", "forbidden", "unauthorized")
_POLICY_NAME_HINTS = ("contentpolicy", "content_filter", "moderation", "safety")
_BAD_ARGUMENT_NAME_HINTS = (
    "badrequest",
    "validation",
    "jsondecode",
    "structuredoutput",
    "unprocessable",
)
_TRANSIENT_NAME_HINTS = (
    "ratelimit",
    "connection",
    "timeout",
    "transport",
    "internalserver",
    "serviceunavailable",
)


def _status_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "statusCode"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _name_of(exc: BaseException) -> str:
    return type(exc).__name__.lower()


def classify_recovery(
    exc: BaseException,
    *,
    attempt: int = 1,
    max_attempts: int = 3,
    stalled: bool = False,
    action_available: bool = True,
) -> RecoveryAction:
    """Classify one failure into a recovery action.

    Precedence is the safety order, not the likelihood order:

    1. **Denial wins.** 401/403 and policy/moderation refusals stop, even when
       the exception also looks transient. Retrying a refusal is the bypass
       path the design note warns about.
    2. Bad request / unparsable structured output degrades the model.
    3. Transient errors retry the same call until the attempt budget runs out;
       past the budget they stop and report (a network that never came back is
       an infrastructure incident, not a reasoning problem).
    4. An explicit ``stalled`` signal (repeated identical failure, see
       ``backend.state.progress``) escalates — that is the one case where more
       reasoning budget can pay off.
    5. ``action_available=False`` downgrades ESCALATE to RETRY_SAME: without a
       stronger model configured, "escalate" would be a lie.
    """
    status = _status_of(exc)
    name = _name_of(exc)

    if status in _DENIED_STATUSES or any(h in name for h in _DENIED_NAME_HINTS):
        return RecoveryAction.STOP_AND_REPORT
    if any(h in name for h in _POLICY_NAME_HINTS):
        return RecoveryAction.STOP_AND_REPORT

    if status in _BAD_ARGUMENT_STATUSES or any(h in name for h in _BAD_ARGUMENT_NAME_HINTS):
        return RecoveryAction.DEGRADE_MODEL

    transient = (
        status in _TRANSIENT_STATUSES
        or (status is not None and status >= 500)
        or any(h in name for h in _TRANSIENT_NAME_HINTS)
    )
    if transient:
        if attempt >= max_attempts:
            return RecoveryAction.STOP_AND_REPORT
        return RecoveryAction.RETRY_SAME

    if stalled:
        return RecoveryAction.ESCALATE_MODEL if action_available else RecoveryAction.RETRY_SAME

    # Unknown failure: one cheap retry, then let the caller decide.
    return RecoveryAction.RETRY_SAME if attempt < max_attempts else RecoveryAction.STOP_AND_REPORT
