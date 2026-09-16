"""EventStore façade — the read/write seam for workflow telemetry (P1a-S2).

Before S2, telemetry lived in the LangGraph checkpoint as ``performance_log``
and was serialized on every superstep. It now lives in the Event store
(:mod:`backend.db.workflow_events`); this module is the only place agents and
routes touch it, so a future backend swap (or an artifact-style ref tier)
lands in one file.

Legacy threads keep their inline ``performance_log`` (decision D1: no
checkpoint rewrite). :func:`load_perf_log` is therefore the *only* correct way
to read a thread's telemetry: it returns the inline list when the checkpoint
carries one and the stored events otherwise, and concatenates both for a
legacy thread that was resumed after the migration.

Best-effort by contract: emitting is telemetry. Nothing in a workflow node may
fail because an event could not be stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "ACTION_EVENT_KIND",
    "ACTION_POLICY_DENIED",
    "ACTION_PUBLISH_REFUSED",
    "LEGACY_PERF_LOG_KEY",
    "action_perf_entry",
    "emit_events",
    "has_inline_perf_log",
    "inline_perf_log",
    "load_perf_log",
    "reset_memory_store",
    "resolve_thread_id",
]

# Checkpoint key telemetry used to occupy. Its *presence* (not its value) is
# what marks a thread as legacy: post-S2 runs never write it into state.
LEGACY_PERF_LOG_KEY = "performance_log"

#: Telemetry kind for a *refusal* — an action that was asked for and denied.
#: Declared in ``backend.db.workflow_events.EVENT_KINDS`` since P1a as part of
#: the forward-looking set; P2a-S5b is its first emitter (pinned by a test, so
#: the declaration and the emitter cannot drift apart again).
ACTION_EVENT_KIND = "action"

#: The refusal vocabulary, in one place: a reader enumerates what a timeline
#: may contain instead of discovering it per call site.
ACTION_POLICY_DENIED = "policy_denied"
ACTION_PUBLISH_REFUSED = "publish_refused"


def action_perf_entry(
    action: str,
    *,
    account_id: str = "",
    timestamp: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build one ``kind:"action"`` entry recording a refused action.

    Refusals are decisions, and until P2a-S5b the two that matter lived only in
    an HTTP status and in workflow state: the policy engine denying an intent,
    and a human answering "not this one" at the publish gate.  An operator
    asking "why was nothing posted?" had to infer the answer from a log line or
    from a thread's final phase.  The Event store already carries the rest of a
    run's timeline (``node`` / ``llm`` / ``human_wait`` / ``tool``), so a
    refusal belongs in the same place.

    ``action`` is one of :data:`ACTION_POLICY_DENIED` /
    :data:`ACTION_PUBLISH_REFUSED`; ``fields`` carries the machine-readable
    specifics (``policy_id``, ``gate``, ``reason``).  Free text is deliberately
    **not** a parameter: the same rule as the Gateway's trace sink — an event
    says what happened, the bodies belong behind an explicit, sanitised export.
    A human's comment therefore stays on the confirmation record, never here.

    Reserved keys are written last so ``fields`` cannot spoof them.  The caller
    writes the entry with :func:`emit_events`, which is best-effort: telemetry
    must never fail the thing it is describing.
    """
    from datetime import UTC, datetime

    entry: dict[str, Any] = dict(fields)
    entry["kind"] = ACTION_EVENT_KIND
    entry["action"] = action
    entry["account_id"] = account_id
    entry["timestamp"] = timestamp or datetime.now(UTC).isoformat()
    return entry


def resolve_thread_id(state: Mapping[str, Any] | None) -> str:
    """Best-effort thread identity for an event write.

    ``thread_id`` is the canonical key, but the CLI's initial state only carries
    ``session_id`` — and every writer sets the two to the same value, so the
    fallback keeps CLI runs from silently dropping their telemetry.
    """
    if not state:
        return ""
    return str(state.get("thread_id") or state.get("session_id") or "")


def inline_perf_log(values: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The legacy inline ``performance_log`` carried by a checkpoint."""
    if not values:
        return []
    raw = values.get(LEGACY_PERF_LOG_KEY) or []
    return [entry for entry in raw if isinstance(entry, dict)]


def has_inline_perf_log(values: Mapping[str, Any] | None) -> bool:
    return values is not None and LEGACY_PERF_LOG_KEY in values


async def emit_events(thread_id: str, entries: list[dict[str, Any]], /) -> int:
    """Append perf-log-shaped entries to the Event store. Best-effort."""
    if not thread_id or not entries:
        return 0
    from backend.db.workflow_events import append_events

    try:
        return await append_events(thread_id, entries)
    except Exception:  # pragma: no cover - append_events already swallows
        return 0


async def load_perf_log(
    thread_id: str,
    values: Mapping[str, Any] | None = None,
    /,
) -> list[dict[str, Any]]:
    """A thread's complete telemetry, legacy or new, in chronological order.

    Legacy checkpoints carry the entries inline; post-S2 threads have them in
    the Event store. A legacy thread resumed after the migration has both, and
    the inline entries are the older ones — so they come first.
    """
    inline = inline_perf_log(values)
    if not thread_id:
        return inline
    from backend.db.workflow_events import list_events

    try:
        stored = await list_events(thread_id)
    except Exception:
        return inline
    if not stored:
        return inline
    if not inline:
        return stored
    return inline + stored


def reset_memory_store() -> None:
    """Test-only reset of the no-Postgres fallback."""
    from backend.db.workflow_events import _reset_memory_store

    _reset_memory_store()
