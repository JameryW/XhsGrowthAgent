"""Run identity for one execution lifetime within a Task (票 5x / agent-os row 2).

A ``thread_id`` is a Task. Until this ticket, resume (continue the same
execution after a pause / gate / error) and rerun (terminal restart that pulls
phase back to SCOUTING on the same thread) could not be told apart from any
id — both reused the thread. The five-entity model needs a *Run* entity that
is addressable on its own: a Run is not an Attempt (nothing node-internal) and
not an Effect (nothing external was claimed).

Design constraints, all load-bearing:

* **pure**: id derivation and entry building do no I/O, read no clock, and never
  raise on a well-formed call;
* **data-minimising**: an entry carries the run's shape, never its content —
  no goal, brief, or agent output;
* **best-effort emission**: callers emit via ``emit_events`` (already
  best-effort), so telemetry can never fail the call it describes;
* **closed vocabulary**: the four causes name how a run boundary was crossed —
  ``start`` / ``rerun`` mint a new id; ``resume`` / ``recover`` reuse one.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from backend.state.events import RUN_EVENT_KIND

__all__ = [
    "RUN_EVENT_KIND",
    "RunCause",
    "mint_run_stamp",
    "next_run_seq",
    "run_entry",
    "run_id",
    "run_identity_view",
]

#: Reservation: an entry may never grow beyond these keys. A new field is a
#: schema decision that needs its own review (and a docs update), not a quiet
#: append at a call site.
_ENTRY_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "run_id",
        "thread_id",
        "run_seq",
        "cause",
        "started_at",
    }
)


class RunCause(StrEnum):
    """How a run boundary was crossed. Closed on purpose — a reader enumerates it."""

    START = "start"
    """``POST /start`` minted the first run on a new thread."""

    RESUME = "resume"
    """Continue the same run after pause / gate / error-stale retry."""

    RERUN = "rerun"
    """Terminal restart on the same thread (completed/cancelled → SCOUTING)."""

    RECOVER = "recover"
    """``/recover`` strategy continuing the same failed execution."""


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"run.{name} must be a non-empty string")
    return value


def next_run_seq(current: Any) -> int:
    """The next monotonic seq for a thread.

    Missing / non-positive / non-int values mean "no prior run stamped" → 1.
    """
    if isinstance(current, bool) or not isinstance(current, int) or current < 1:
        return 1
    return current + 1


def run_identity_view(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Additive ``run_id`` / ``run_seq`` / ``run_cause`` for API responses.

    Legacy checkpoints (no stamp) and malformed values surface as ``None`` —
    never invent a run on read.
    """
    values = values or {}
    rid = values.get("run_id")
    run_id_out: str | None = rid if isinstance(rid, str) and rid.strip() else None
    seq = values.get("run_seq")
    run_seq_out: int | None = (
        seq if isinstance(seq, int) and not isinstance(seq, bool) and seq >= 1 else None
    )
    cause = values.get("run_cause")
    run_cause_out: str | None = cause if isinstance(cause, str) and cause.strip() else None
    return {
        "run_id": run_id_out,
        "run_seq": run_seq_out,
        "run_cause": run_cause_out,
    }


def run_id(
    thread_id: str,
    *,
    run_seq: int,
    started_at: str,
) -> str:
    """Deterministic id for one run.

    ``run_seq`` is part of the derivation: without it, a terminal restart on
    the same thread at the same timestamp would collide with the previous run.
    """
    import hashlib

    thread_id = _require_text("thread_id", thread_id)
    started_at = _require_text("started_at", started_at)
    if not isinstance(run_seq, int) or isinstance(run_seq, bool) or run_seq < 1:
        raise ValueError("run.run_seq must be an int >= 1")
    digest = hashlib.sha256(f"{thread_id}\x1f{run_seq}\x1f{started_at}".encode()).hexdigest()
    return f"run_{digest[:16]}"


def run_entry(
    *,
    thread_id: str,
    run_seq: int,
    cause: RunCause,
    started_at: str,
) -> dict[str, Any]:
    """Build one event-store entry for a minted run (no content, deterministic id)."""
    thread_id = _require_text("thread_id", thread_id)
    started_at = _require_text("started_at", started_at)
    if not isinstance(cause, RunCause):
        raise ValueError("run.cause must be a RunCause member")
    if not isinstance(run_seq, int) or isinstance(run_seq, bool) or run_seq < 1:
        raise ValueError("run.run_seq must be an int >= 1")
    if cause not in (RunCause.START, RunCause.RERUN):
        # Minting events are only for boundaries that create a new id. Reuse
        # causes stay off the wire so a reader never mistakes "continue" for
        # "new open".
        raise ValueError("run.cause for a minted entry must be start or rerun")

    entry: dict[str, Any] = {
        "kind": RUN_EVENT_KIND,
        "run_id": run_id(thread_id, run_seq=run_seq, started_at=started_at),
        "thread_id": thread_id,
        "run_seq": run_seq,
        "cause": cause.value,
        "started_at": started_at,
    }
    if set(entry) != _ENTRY_KEYS:  # pragma: no cover - protects the reservation
        raise AssertionError("run entry grew past its reserved key set")
    return entry


def mint_run_stamp(
    thread_id: str,
    *,
    cause: RunCause,
    started_at: str,
    prior_seq: Any = None,
) -> dict[str, Any]:
    """State patch + event entry for a newly minted run.

    Returns ``{"state": {...}, "entry": {...}}``. ``prior_seq`` is the value
    currently in checkpoint (may be missing on legacy threads).
    """
    if cause not in (RunCause.START, RunCause.RERUN):
        raise ValueError("mint_run_stamp only mints start or rerun")
    seq = 1 if cause is RunCause.START else next_run_seq(prior_seq)
    rid = run_id(thread_id, run_seq=seq, started_at=started_at)
    return {
        "state": {
            "run_id": rid,
            "run_seq": seq,
            "run_cause": cause.value,
        },
        "entry": run_entry(
            thread_id=thread_id,
            run_seq=seq,
            cause=cause,
            started_at=started_at,
        ),
    }
