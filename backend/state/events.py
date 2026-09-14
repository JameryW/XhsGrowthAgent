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
    "LEGACY_PERF_LOG_KEY",
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
