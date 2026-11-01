"""The mainline's single execution entry (P3b-2, 票 5bg).

The control plane owns *how* a mainline real publish becomes an effect: the
decision identity is resolved here, before the attempt implementation is
reached, and every in-repo caller (workflow node, publish-retry, free publish)
goes through this function.  The attempt body still lives in
``agents/publisher.py`` as ``_run_publish_attempt`` — a private implementation —
until P4 moves it; what changed is that no caller can reach it without passing
this entry and stating whose decision it executes.

Decision-identity rules (same discipline as P1b/P3b-1):

* a state that already carries ``publish_decision`` (written by the review
  approval, 票 5bc) uses it untouched — this entry does not rewrite approvals;
* a **free** publish is operator-initiated and has no review.  When the caller
  passes ``operator_id``, this entry synthesizes an operator decision with its
  own id, source ``free_publish_operator``, the account and the submitted
  content hash — it does not pretend a review happened, and it does not invent
  an account (no account → no identity);
* anything else proceeds without a decision (legacy retry / deployment publish):
  the attempt then produces no mainline intent, exactly as before.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

__all__ = ["execute_mainline_publish"]

#: ``publish_decision.source`` for an operator-initiated (unreviewed) free publish.
FREE_PUBLISH_OPERATOR_SOURCE = "free_publish_operator"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _operator_decision(state: Mapping[str, Any], operator_id: str) -> dict[str, Any] | None:
    """Synthesize the operator's decision for an unreviewed free publish.

    Returns ``None`` when there is no account to bind the identity to: the
    identity is account-scoped by construction, and inventing an account for it
    is the one thing this codebase never does.
    """
    from backend.services.publish_intent import publish_content_body
    from backend.state.artifacts import content_hash

    options = state.get("publish_options") or {}
    account_id = str(options.get("account_id") or "").strip()
    if not account_id:
        return None
    return {
        "decision_id": f"mainline:operator:{uuid.uuid4().hex}",
        "source": FREE_PUBLISH_OPERATOR_SOURCE,
        "thread_id": str(state.get("session_id") or state.get("thread_id") or ""),
        "account_id": account_id,
        "content_hash": content_hash(publish_content_body(state)),
        "approved_by": operator_id,
        "approved_at": _now_iso(),
    }


async def execute_mainline_publish(
    state: Mapping[str, Any],
    store: Any,
    *,
    agent: Any = None,
    operator_id: str = "",
) -> dict[str, Any]:
    """Execute one mainline real publish through the control-plane entry.

    Returns the same ``{"publish_result", "phase"[ , "publish_options"]}`` shape
    the attempt always returned.  The caller's mapping is not mutated: a
    synthesized operator decision travels on a copy.
    """
    effective: dict[str, Any] = dict(state)
    operator = operator_id.strip()
    if not effective.get("publish_decision") and operator:
        decision = _operator_decision(state, operator)
        if decision is not None:
            effective["publish_decision"] = decision

    from backend.agents.publisher import _run_publish_attempt

    return await _run_publish_attempt(effective, store, agent=agent)
