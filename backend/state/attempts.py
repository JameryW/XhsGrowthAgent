"""Attempt identity for node-internal LLM retries (票 5w / agent-os matrix row 2).

``_llm_structured`` walks a strongest-first chain of structured-output levels and
retries within a level. Until this ticket those attempts were implicit: a log
line, no id, no event. The five-entity model (Task / Run / Step / Attempt /
Effect) needs an *Attempt* entity that is addressable on its own — an attempt is
not an effect (nothing external happened) and not a step (the node did not
finish).

Design constraints, all load-bearing:

* **pure**: id derivation and entry building do no I/O, read no clock, and never
  raise on a well-formed call;
* **data-minimising**: an entry carries the attempt's shape, never its content —
  no prompt, no model output, no exception message (only the class name). The
  bodies belong behind an explicit, sanitised export;
* **best-effort emission**: callers append entries to the existing perf
  contextvar; ``emit_events`` is already best-effort, so telemetry can never
  fail the call it describes;
* **closed vocabulary**: the four outcomes are the four ways an attempt can end,
  and the two rejection kinds stay distinct — a malformed payload can never
  become a result, while a well-formed payload a validator refuses can (when the
  check is advisory).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from backend.state.events import ATTEMPT_EVENT_KIND

__all__ = [
    "ATTEMPT_EVENT_KIND",
    "AttemptOutcome",
    "attempt_entry",
    "attempt_id",
]

#: Reservation: an entry may never grow beyond these keys. A new field is a
#: schema decision that needs its own review (and a docs update), not a quiet
#: append at a call site.
_ENTRY_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "attempt_id",
        "agent",
        "task_type",
        "level",
        "attempt_no",
        "outcome",
        "duration_ms",
        "started_at",
        "error_class",
    }
)


class AttemptOutcome(StrEnum):
    """How one attempt ended. Closed on purpose — a reader enumerates it."""

    SUCCEEDED = "succeeded"
    """The payload validated and the semantic check (if any) accepted it."""

    PAYLOAD_REJECTED = "payload_rejected"
    """Schema-invalid payload. Never eligible to become a result."""

    SEMANTIC_REJECTED = "semantic_rejected"
    """Well-formed payload a ``validator`` refused; may be advisory."""

    UNREACHABLE = "unreachable"
    """The level itself could not be called; nothing was answered."""


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"attempt.{name} must be a non-empty string")
    return value


def attempt_id(
    agent: str,
    *,
    level: str,
    attempt_no: int,
    started_at: str,
) -> str:
    """Deterministic id for one attempt.

    ``attempt_no`` is part of the derivation: without it, the second attempt at
    the same level would reuse the first one's id and an append-only reader could
    not tell a retry from a duplicate write.
    """
    import hashlib

    agent = _require_text("agent", agent)
    level = _require_text("level", level)
    started_at = _require_text("started_at", started_at)
    if not isinstance(attempt_no, int) or isinstance(attempt_no, bool) or attempt_no < 1:
        raise ValueError("attempt.attempt_no must be an int >= 1")
    digest = hashlib.sha256(
        f"{agent}\x1f{level}\x1f{attempt_no}\x1f{started_at}".encode()
    ).hexdigest()
    return f"att_{digest[:16]}"


def attempt_entry(
    *,
    agent: str,
    task_type: str,
    level: str,
    attempt_no: int,
    outcome: AttemptOutcome,
    duration_ms: float,
    started_at: str,
    error_class: str = "",
) -> dict[str, Any]:
    """Build one perf-entry-shaped attempt event (no content, deterministic id).

    ``duration_ms`` is wall-clock of the single attempt; it is rounded to
    milliseconds so the entry is stable enough to diff. ``error_class`` is an
    exception class name or empty — never a message.
    """
    import math

    agent = _require_text("agent", agent)
    task_type = _require_text("task_type", task_type)
    level = _require_text("level", level)
    started_at = _require_text("started_at", started_at)
    if not isinstance(outcome, AttemptOutcome):
        raise ValueError("attempt.outcome must be an AttemptOutcome member")
    if not isinstance(attempt_no, int) or isinstance(attempt_no, bool) or attempt_no < 1:
        raise ValueError("attempt.attempt_no must be an int >= 1")
    if (
        not isinstance(duration_ms, (int, float))
        or isinstance(duration_ms, bool)
        or not math.isfinite(float(duration_ms))
        or duration_ms < 0
    ):
        raise ValueError("attempt.duration_ms must be a finite number >= 0")
    if not isinstance(error_class, str):
        raise ValueError("attempt.error_class must be a string")

    entry: dict[str, Any] = {
        "kind": ATTEMPT_EVENT_KIND,
        "attempt_id": attempt_id(agent, level=level, attempt_no=attempt_no, started_at=started_at),
        "agent": agent,
        "task_type": task_type,
        "level": level,
        "attempt_no": attempt_no,
        "outcome": outcome.value,
        "duration_ms": round(float(duration_ms), 3),
        "started_at": started_at,
        "error_class": error_class,
    }
    if set(entry) != _ENTRY_KEYS:  # pragma: no cover - protects the reservation
        raise AssertionError("attempt entry grew past its reserved key set")
    return entry
