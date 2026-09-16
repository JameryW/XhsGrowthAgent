"""Publish gate node — the human authorisation a real publish always needs.

The evaluator's "publisher" verdict answers a *quality* question: is this
content good enough to post?  It is not the authorisation to post it.  Those
were the same event until P2a-S4b, which meant an AI quality gate could decide
on its own to perform an irreversible external action.  This node splits them:
after the AI gate, the run stops and waits for an explicit human yes.

The gate is skippable, but only by an *explicit* prior statement, never by the
absence of one (see :func:`publish_needs_confirmation`).
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")

#: The only two decisions this gate accepts.  Anything else — a missing key, a
#: client that predates the endpoint, a typo — is read as a refusal.  A
#: confirmation gate that treats an unrecognised value as "go ahead" turns
#: every version skew into an unconfirmed publish, which is the exact failure
#: this node exists to prevent.
PUBLISH_CONFIRMED = "confirmed"
PUBLISH_CANCELLED = "cancelled"

#: The ``source`` stamped on the confirmation record, mirroring
#: ``human_feedback.source`` at review_gate (which uses "auto_low_risk").
SOURCE_HUMAN = "human"
SOURCE_AUTO_PUBLISH = "auto_publish"
SOURCE_DRY_RUN = "dry_run"


def publish_needs_confirmation(state: XHSGrowthState | dict[str, Any]) -> bool:
    """Does this run need a fresh human yes before it may publish?

    Two things make the confirmation unnecessary, and each is an explicit
    statement someone already made:

    * ``auto_publish`` — the flag ``POST /start`` and ``POST /api/review/submit``
      have advertised as "审核通过后自动发布" since before this slice, and which
      nothing ever read.  It arrives from either place (workflow level, or the
      approve decision's ``publish_options``); the two are OR-ed, because a
      standing authorisation given in one place is not revoked by omission in
      the other.  Honouring it is what makes this gate a change to the default
      path only — a workflow that already asked not to be asked again still
      publishes straight through.
    * a dry run (:func:`publish_is_dry_run`) — nothing leaves the machine, so
      there is no irreversible act to authorise.

    Everything else — including every unknown/missing value — needs the yes.
    """
    from backend.agents.publisher import publish_is_dry_run

    options = state.get("publish_options") or {}
    if options.get("auto_publish") is True or state.get("auto_publish") is True:
        return False
    return not publish_is_dry_run(state)


def _skip_reason(state: XHSGrowthState | dict[str, Any]) -> str:
    """Which standing authorisation let this run through (for the record)."""
    options = state.get("publish_options") or {}
    if options.get("auto_publish") is True or state.get("auto_publish") is True:
        return SOURCE_AUTO_PUBLISH
    return SOURCE_DRY_RUN


async def publish_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Stop before the irreversible publish and wait for a human decision.

    Flow:
    1. A standing authorisation is already in state (auto_publish, or a dry
       run) → no interrupt; record the confirmation with its source and keep
       phase=PUBLISHING so ``publish_gate_outcome`` routes to the publisher.
    2. Otherwise ``interrupt()`` with ``gate="publish"`` — the same dynamic
       interrupt pattern as review_gate / ripple_gate, which is what makes
       ``Command(resume=...)`` the resuming channel (an ``interrupt_before``
       entry could not be resumed that way, and would also need a second
       entry point in the compiled graph).

    Decision format (from ``Command(resume=decision)``):
      {"decision": "confirmed"} → PUBLISHING → publisher
      {"decision": "cancelled"} → CANCELLED  → END (nothing is published)

    A refusal sets ``phase=CANCELLED``, not ``ERROR``: a human saying "not this
    one" is a decision, not a fault.  Leaving the phase at PUBLISHING was the
    other candidate and is worse — with the publisher skipped, the run would
    have no next nodes and ``derive_status`` would report *completed* for a
    note that was never posted.
    """
    _check_cancelled(state)

    if not publish_needs_confirmation(state):
        reason = _skip_reason(state)
        logger.info("publish gate: standing authorisation present (%s), not interrupting", reason)
        return NodeResult(
            {
                "publish_confirmation": {"decision": PUBLISH_CONFIRMED, "source": reason},
                "phase": WorkflowPhase.PUBLISHING,
            },
            "publish_gate",
        ).to_dict()

    copy = state.get("copy_content") or {}
    options = state.get("publish_options") or {}

    # ``gate="publish"`` is the contract with derive_status: an interrupt whose
    # payload carries it derives AWAITING_PUBLISH rather than falling through to
    # a generic awaiting state.
    decision = interrupt(
        {
            "gate": "publish",
            "publish_summary": {
                "title": (copy.get("selected_title") or ""),
                "has_images": bool((state.get("visual_plan") or {}).get("image_paths")),
                "account_id": options.get("account_id") or state.get("account_id", ""),
            },
        }
    )

    raw: Any = PUBLISH_CANCELLED
    comments = ""
    if isinstance(decision, dict):
        raw = decision.get("decision", PUBLISH_CANCELLED)
        comments = str(decision.get("comments") or "")

    confirmed = raw == PUBLISH_CONFIRMED
    if not confirmed and raw != PUBLISH_CANCELLED:
        # Not silence: an unrecognised value is worth a line, because it means a
        # caller is speaking a dialect this gate does not know.
        logger.warning("publish gate: unrecognised decision %r — refusing the publish", raw)

    logger.info("publish gate: %s", "confirmed" if confirmed else "cancelled")

    return NodeResult(
        {
            "publish_confirmation": {
                "decision": PUBLISH_CONFIRMED if confirmed else PUBLISH_CANCELLED,
                "source": SOURCE_HUMAN,
                "comments": comments,
            },
            "phase": WorkflowPhase.PUBLISHING if confirmed else WorkflowPhase.CANCELLED,
        },
        "publish_gate",
    ).to_dict()
