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


async def _learn_port_edits(
    state: XHSGrowthState,
    human_feedback: dict[str, Any],
    store: BaseStore,
) -> None:
    """Learn spans only from an explicit human edit at the review gate."""
    edited_body = str(human_feedback.get("edited_body") or "")
    current = state.get("copy_content") or {}
    old_body = str(current.get("body_text") or "") if isinstance(current, dict) else ""
    if not edited_body or not old_body or edited_body == old_body:
        return
    try:
        from backend.services.port import (
            load_port_memory,
            merge_port_memory,
            mine_span_revisions,
            save_port_memory,
        )

        spans = mine_span_revisions(old_body, edited_body)
        if not spans:
            return
        learned = merge_port_memory(
            await load_port_memory(store, str(state.get("account_id") or "")),
            spans,
        )
        await save_port_memory(store, str(state.get("account_id") or ""), learned)
        human_feedback["port_spans"] = [span.as_dict() for span in spans]
    except Exception as exc:  # noqa: BLE001 - learning never blocks a revision
        logger.debug("PORT learning skipped: %s", exc)


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

    Increments revision_count on each cycle. Entry is human-initiated
    (POST /resume revise); the max_revision_count budget bounds that loop —
    evaluator_outcome never force-publishes at the cap (heavy residual).

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

    await _learn_port_edits(state, human_feedback, store)

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
