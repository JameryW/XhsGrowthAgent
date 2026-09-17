"""Publisher node implementation."""

import logging
from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.agents.publisher import PublisherAgent
from backend.realtime import EventBusService, EventType
from backend.services.publish_identity import normalize_platform_post_id
from backend.state.schema import XHSGrowthState

_publisher = PublisherAgent()

logger = logging.getLogger("xhs_growth.graph.nodes")


async def _record_publish_identity(state: XHSGrowthState, result: dict[str, Any]) -> None:
    """Persist the workflow-to-platform identity onto this thread's evaluator sample.

    The published platform id only ever existed in ``publish_result`` (and in
    the checkpoint) — the analytics routes re-derived the same link per request
    and discarded it.  Writing it here, at the one place that holds both the
    thread and the published id, is what turns that link from a projection into
    a stored fact the sync-time weak-label backfill can join on.

    Best-effort: a database outage must never affect a publish that already
    happened, and a dry run / failed publish normalizes to an empty id and
    writes nothing.
    """
    thread_id = str(state.get("session_id") or state.get("thread_id") or "").strip()
    publish_result = result.get("publish_result") or {}
    platform_post_id = normalize_platform_post_id(publish_result.get("platform_post_id"))
    if not thread_id or not platform_post_id:
        return
    try:
        from backend.db.evaluator_config import record_publish_identity
        from backend.db.pool import is_pool_ready

        if not is_pool_ready():
            return
        await record_publish_identity(thread_id, platform_post_id)
    except Exception:
        logger.warning("publish identity record failed (non-blocking)", exc_info=True)


async def publisher_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute publisher agent — does NOT emit WORKFLOW_COMPLETED here.

    The completed event is emitted by _runner._emit_status_transition when
    derive_status returns COMPLETED, which happens only after the graph has
    fully finished (including any manually resumed analyst step). Emitting it
    here would prematurely close SSE streams and skip downstream nodes.
    """
    _check_cancelled(state)
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "publisher"},
    )

    result = await _publisher(state, store=store)

    # Durable side effect of a real publish: the evaluator gate ran before this
    # node, so the sample this identity belongs to is already in the table.
    await _record_publish_identity(state, result)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={
            "agent": "publisher",
            "status": result.get("publish_result", {}).get("status", "unknown"),
        },
    )

    return NodeResult(result, "publisher").to_dict()
