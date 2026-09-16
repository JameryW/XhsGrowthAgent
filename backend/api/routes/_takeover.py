"""Automatic takeover of threads whose owner died mid-flight.

S1 recorded who is running a thread and S2 made that record the answer
``/status`` gives, but neither let the record *cause* anything: after a
``kill -9`` the DB row still said "running" forever, and only a person hitting
``/recover`` moved it. This module is the loop that closes that gap -- a scan
that finds a lease whose owner stopped renewing and resumes the thread from
its checkpoint when, and only when, the remaining work is safe to re-run.

Three boundaries, each with a reason:

* **The lease is the gate, not the hint.** The scan calls ``acquire`` and
  resumes only if it is granted. ``_ACQUIRE_SQL`` is the single place the
  "two writers never share a thread" property lives (red line 4): it refuses
  while the incumbent's heartbeat is fresh, so a live owner is never taken
  over. S1 dropped that answer on the floor; this is its first consumer.
* **The pending nodes decide, and only pending nodes.** ``takeover_safety``
  classifies them. Anything but SAFE is refused. That module carries the
  argument for why the pending set is sufficient rather than merely cheap.
* **A refusal is an outcome, not a no-op.** Every decision emits an event, so
  "the scan looked and declined" stays distinguishable from "the scan never
  saw it" -- the same distinction S2 drew for its declared gaps.

Only *newly* expired leases are considered, which is why ``expire_scan`` runs
first: it is the writer that gives ``heartbeat_at`` its meaning and it returns
exactly the rows that just went silent. An expired row that nobody takes over
stays expired, so re-reading "all expired leases" every cycle would re-decide
the same refusal forever and fill the timeline with duplicates. Deciding once
per expiry is also the honest cadence -- nothing changes until a person acts.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from backend.db.execution_leases import acquire, expire_scan
from backend.graph.takeover_safety import TakeoverHazard, takeover_verdict
from backend.state.enums import WorkflowPhase

logger = logging.getLogger("xhs_growth.takeover")

#: Event kind written to workflow_events for every takeover decision.
TAKEOVER_EVENT_KIND = "takeover"

#: Bound on the decision log kept in ``app.state.takeover_status``.
_MAX_LOGGED_DECISIONS = 20


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _status_defaults() -> dict[str, Any]:
    """The exact key set ``_merge_status`` writes, at a fresh process's values.

    A factory rather than a module constant so the ``last_decisions`` list is
    per-caller -- a shared one would make two status buckets the same bucket.
    """
    return {
        "enabled": False,
        "durability": "unknown",
        "interval_seconds": 0.0,
        "status": "disabled",
        "run_count": 0,
        "last_started_at": None,
        "last_finished_at": None,
        "last_source": None,
        "last_newly_expired": 0,
        "last_taken_over": 0,
        "last_refused": 0,
        "last_skipped": 0,
        "last_error": None,
        "last_decisions": [],
    }


def initial_status(*, enabled: bool, durability: str, interval_seconds: float) -> dict[str, Any]:
    """The takeover bucket a fresh process starts with.

    ``status`` distinguishes "the scan is not scheduled" from "it ran and found
    nothing" -- the same distinction P2b ruling 2 asked for about the lease.
    ``durability`` carries the lease backend, because without Postgres there is
    nothing a restart could take over.
    """
    status = _status_defaults()
    status["enabled"] = enabled
    status["durability"] = durability
    status["interval_seconds"] = interval_seconds
    status["status"] = "scheduled" if enabled else "disabled"
    return status


async def _record(thread_id: str, outcome: str, **fields: Any) -> None:
    """Write one durable decision record. Best-effort: telemetry never gates."""
    from backend.db.workflow_events import append_events

    entry = {"kind": TAKEOVER_EVENT_KIND, "outcome": outcome, "ts": _now(), **fields}
    await append_events(thread_id, [entry])


async def _consider(graph: Any, thread_id: str, source: str) -> dict[str, Any]:
    """Decide one thread. Returns a ``{thread_id, outcome, reason}`` record."""
    config = {"configurable": {"thread_id": thread_id}}

    try:
        state = await graph.aget_state(config)
    except Exception as exc:
        logger.warning("takeover: state unreadable for %s: %s", thread_id, exc)
        return {"thread_id": thread_id, "outcome": "skipped", "reason": "state_unreadable"}

    if not state.values:
        # The lease survived but the checkpoint did not. Nothing to resume from;
        # the DB row plus /recover's checkpoint_lost diagnosis is the channel.
        return {"thread_id": thread_id, "outcome": "skipped", "reason": "no_checkpoint"}

    pending = tuple(name for name in (state.next or ()) if name)
    if not pending:
        # A run that finished or errored without a pending node. That is the
        # human /recover path, not an interrupted loop: takeover only ever
        # resumes work LangGraph was still holding a next node for.
        return {"thread_id": thread_id, "outcome": "skipped", "reason": "nothing_pending"}

    may_resume, worst = takeover_verdict(pending)
    if not may_resume:
        hazard = worst.value if worst is not None else TakeoverHazard.NEEDS_HUMAN.value
        logger.info(
            "takeover: refusing %s -- %s pending, worst hazard %s", thread_id, pending, hazard
        )
        await _record(thread_id, "refused", reason=hazard, pending=list(pending), source=source)
        return {"thread_id": thread_id, "outcome": "refused", "reason": hazard}

    # The gate. `acquire` answers False for a live foreign owner *and* for a
    # store that cannot answer at all -- both mean this scan must not proceed,
    # and neither is retried until the row goes silent again.
    if not await acquire(thread_id):
        return {"thread_id": thread_id, "outcome": "skipped", "reason": "lease_refused"}

    from backend.api.routes.workflow import _resume_phase_for_next_nodes, _start_resume_task
    from backend.state.hydration import recover_view

    view = recover_view(state.values)
    phase = _resume_phase_for_next_nodes(pending, view["prev_phase"] or WorkflowPhase.CREATING)

    await _start_resume_task(thread_id, graph, config, phase)

    logger.info("takeover: resuming %s from %s (phase=%s)", thread_id, pending, phase)
    await _record(thread_id, "taken_over", pending=list(pending), phase=str(phase), source=source)
    return {"thread_id": thread_id, "outcome": "taken_over", "reason": None}


async def takeover_scan(app: Any, *, source: str) -> dict[str, Any]:
    """One pass: expire silent leases, then decide each newly-orphaned thread.

    ``source`` is ``"startup"`` or ``"periodic"`` and is recorded on the events
    so an operator can tell a restart recovery from a later sweep.
    """
    report: dict[str, Any] = {
        "source": source,
        "started_at": _now(),
        "finished_at": None,
        "newly_expired": 0,
        "decisions": [],
        "error": None,
    }

    graph = getattr(app.state, "graph", None)
    if graph is None:
        report["error"] = "no_graph"
        report["finished_at"] = _now()
        return report

    try:
        newly_expired = await expire_scan()
        report["newly_expired"] = len(newly_expired)
        for thread_id in newly_expired:
            report["decisions"].append(await _consider(graph, thread_id, source))
    except Exception as exc:  # the scheduler must survive one bad cycle
        logger.exception("takeover scan failed (source=%s)", source)
        report["error"] = f"{type(exc).__name__}: {exc}"

    report["finished_at"] = _now()
    return report


def _merge_status(app: Any, report: dict[str, Any]) -> None:
    """Fold one report into ``app.state.takeover_status`` (single writer)."""
    state = getattr(app.state, "takeover_status", None)
    if not isinstance(state, dict):
        # Created from the same factory the lifespan uses, so a merge onto a
        # fresh bucket cannot invent a key the health surface does not know.
        state = _status_defaults()
        app.state.takeover_status = state

    decisions = report.get("decisions") or []
    counts: dict[str, int] = {}
    for decision in decisions:
        outcome = str(decision.get("outcome"))
        counts[outcome] = counts.get(outcome, 0) + 1

    state["run_count"] = int(state.get("run_count") or 0) + 1
    state["last_started_at"] = report["started_at"]
    state["last_finished_at"] = report["finished_at"]
    state["last_source"] = report["source"]
    state["last_newly_expired"] = report["newly_expired"]
    state["last_taken_over"] = counts.get("taken_over", 0)
    state["last_refused"] = counts.get("refused", 0)
    state["last_skipped"] = counts.get("skipped", 0)
    state["last_error"] = report.get("error")

    log = list(state.get("last_decisions") or [])
    log.extend(decisions)
    state["last_decisions"] = log[-_MAX_LOGGED_DECISIONS:]


async def takeover_scheduler(app: Any, *, interval_seconds: float) -> None:
    """Re-run the scan on a fixed cadence until cancelled.

    Why periodic rather than a single startup pass: a lease only expires once
    its TTL has elapsed, and a process that just restarted still sees the dead
    owner's heartbeat as fresh. The takeover of a thread lost to a crash
    therefore lands one TTL (plus up to one interval) after the restart, on a
    later sweep -- the startup pass catches only what expired while the
    service was down.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        with contextlib.suppress(Exception):
            _merge_status(app, await takeover_scan(app, source="periodic"))


async def startup_takeover_scan(app: Any) -> None:
    """Run the first pass during lifespan startup, swallowing nothing.

    Kept separate from the scheduler so the startup call site can decide
    whether a failure should be fatal. It must not be: a scan that cannot run
    degrades to "no automatic takeover", which is exactly the behaviour the
    service had before S3.
    """
    with contextlib.suppress(Exception):
        _merge_status(app, await takeover_scan(app, source="startup"))


__all__ = [
    "TAKEOVER_EVENT_KIND",
    "initial_status",
    "startup_takeover_scan",
    "takeover_scan",
    "takeover_scheduler",
]
