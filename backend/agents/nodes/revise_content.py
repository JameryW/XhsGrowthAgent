"""Revise content node implementation - resets content for revision."""

import logging
from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.progress import (
    ProgressSignal,
    detect_revision_stall,
    progress_event,
    revision_record,
)
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def _emit_stall(state: XHSGrowthState, signal: ProgressSignal) -> None:
    """Publish a stall signal to the event timeline. Best-effort by contract.

    Same rule as every other telemetry write: a run must never fail because its
    observer could not store a row. The signal is emitted, never routed on —
    ``max_revision_count`` still decides how many rounds this loop gets.
    """
    from backend.state.events import emit_events, resolve_thread_id

    thread_id = resolve_thread_id(state)
    entry = progress_event(
        signal,
        account_id=str(state.get("account_id") or ""),
        thread_id=thread_id,
    )
    await emit_events(thread_id, [entry])


async def revise_content_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Revise content - inject feedback for copy rewrite.

    Preserves evaluation_result.revision_hints into human_feedback.revisions so
    the copywriter can act on the evaluator's panel verdict (RQGM co-evolution:
    evaluator feedback feeds back into the writer).

    Increments revision_count on each cycle; evaluator_outcome force-approves
    after Settings().workflow.max_revision_count to prevent infinite revision loops.

    P0-A (observe-only): each cycle also appends a compact verdict record and
    runs the Progress Detector over the loop's history. Two rounds asking for
    the same fix, or two rounds without score movement, produce a
    ``kind:"progress"`` event and a warning log. Nothing here changes the
    routing or the budget — the round cap remains the only decider.
    """
    _check_cancelled(state)
    # Carry evaluator revision hints into human_feedback for the copywriter
    evaluation = state.get("evaluation_result") or {}
    revision_hints: list[str] = evaluation.get("revision_hints") or []
    existing_feedback = state.get("human_feedback") or {}
    human_feedback = dict(existing_feedback)
    if revision_hints:
        human_feedback["revisions"] = list(revision_hints)

    # Clear previous copy content to trigger rewrite
    result: dict[str, Any] = {
        "copy_content": {},  # Clear, triggers rewrite
        "visual_plan": {},  # Clear, triggers redesign
        "phase": WorkflowPhase.CREATING,
        # Increment revision counter — evaluator_outcome reads this to cap loops
        "revision_count": state.get("revision_count", 0) + 1,
    }
    if human_feedback:
        result["human_feedback"] = human_feedback

    record = revision_record(result["revision_count"], evaluation)
    if record is not None:
        history = [
            entry for entry in (state.get("revision_history") or []) if isinstance(entry, dict)
        ]
        result["revision_history"] = [record]
        signal = detect_revision_stall([*history, record])
        if signal.stalled:
            logger.warning(
                "Revision loop stalled after round %s: %s evidence=%s",
                record["round"],
                signal.reason,
                signal.evidence,
            )
            await _emit_stall(state, signal)

    return NodeResult(result, "revise_content").to_dict()
