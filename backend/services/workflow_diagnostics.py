"""Durable failure diagnostics for workflow executions.

The event tier already records per-node LLM/tool telemetry, but a failed graph
run only wrote a free-form ``error`` string to the workflow row.  Operators had
to read stack traces to tell a session/auth failure from a transient model
timeout, and there was no per-note cost attached to the failure.

This module turns one failure into a bounded, redaction-safe event payload:
a stable root-cause bucket plus the token/USD cost of the run's telemetry so
far.  Emission is best-effort by contract -- failure reporting must never mask
or replace the original exception.
"""

from __future__ import annotations

import contextlib
from typing import Any

from backend.services.content_launch import classify_root_cause, estimate_note_cost
from backend.state.events import emit_events, load_perf_log

FAILURE_EVENT_KIND = "run"


async def record_workflow_failure(
    thread_id: str,
    exc: BaseException,
    *,
    phase: str = "",
    source: str = "run",
) -> dict[str, Any]:
    """Emit one diagnostic event and return the payload (also on storage errors).

    ``load_perf_log`` is best-effort and may return an empty list; the cost
    report then carries zeros rather than dropping the diagnostic entirely.
    """

    error_code = type(exc).__name__
    message = str(exc)
    root_cause = classify_root_cause(
        error_code=error_code,
        message=message,
        phase=phase,
    )
    try:
        events = await load_perf_log(thread_id)
    except Exception:  # pragma: no cover - load_perf_log already swallows
        events = []
    cost = estimate_note_cost(events)
    payload: dict[str, Any] = {
        "kind": FAILURE_EVENT_KIND,
        "event": "workflow_failure",
        "source": source,
        "phase": phase,
        "root_cause": root_cause,
        "token_cost": cost,
        "error_code": error_code,
        "message": message[:500],
    }
    with contextlib.suppress(Exception):  # pragma: no cover - emit_events swallows too
        await emit_events(thread_id, [payload])
    return payload


__all__ = ["FAILURE_EVENT_KIND", "record_workflow_failure"]
