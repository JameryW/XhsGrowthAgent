"""Thin projections from Action / artifact shapes onto judger state.

Both the creator-agent Action path and the workflow graph must call
:func:`backend.services.compliance.judgers.decide_publish_eligibility` on a
state-like mapping.  This module is the only place that builds that mapping
from Action plan context or a publish artifact body — it does **not**
duplicate rule tables.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "project_action_plan_state",
    "project_artifact_body_for_judgers",
]


def _as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def project_action_plan_state(
    *,
    account_id: str = "",
    niche: str = "",
    auto_publish: bool = False,
    is_commercial: bool = False,
    publish_eligibility: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Minimal state for plan-time judgers (no artifact body).

    Account-level failure modes (``dual_auto``, ``high_risk_auto`` when niche
    is known) are answerable here.  Callers must pass
    ``judgers=PLAN_TIME_JUDGERS`` into ``decide_publish_eligibility`` — body
    judgers (lexicon / disclosure) belong at execute after the hash match.
    """
    state: dict[str, Any] = {
        "account_id": _as_text(account_id),
        "niche": _as_text(niche),
        "auto_publish": bool(auto_publish),
        "is_commercial": bool(is_commercial),
        "copy_content": {"selected_title": "", "body_text": ""},
    }
    if niche:
        state["content_plan"] = {"niche": _as_text(niche)}
    if publish_eligibility is not None:
        state["evaluation_result"] = {
            "publish_eligibility": dict(publish_eligibility),
        }
    if extra:
        for key, value in extra.items():
            state[key] = value
    return state


def project_artifact_body_for_judgers(
    body: Mapping[str, Any] | None,
    *,
    account_id: str = "",
    title: str = "",
    text: str = "",
    niche: str = "",
    auto_publish: bool = False,
    is_commercial: bool | None = None,
    disclosure_confirmed: bool | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a publish artifact (plus known account flags) for full judgers.

    Prefer explicit ``title`` / ``text`` when the caller already parsed a
    :class:`~backend.creator_agent.execution.PublishContent`; otherwise read
    them from ``body``.  Optional commercial / niche keys on the artifact are
    honoured when the caller did not override them.
    """
    payload = body if isinstance(body, Mapping) else {}
    selected_title = _as_text(title) or _as_text(payload.get("title"))
    body_text = _as_text(text) or _as_text(payload.get("body"))
    resolved_niche = (
        _as_text(niche) or _as_text(payload.get("niche")) or _as_text(payload.get("category"))
    )
    if is_commercial is None:
        raw_commercial = payload.get("is_commercial")
        commercial = bool(raw_commercial) if raw_commercial is not None else False
    else:
        commercial = bool(is_commercial)

    state: dict[str, Any] = {
        "account_id": _as_text(account_id),
        "niche": resolved_niche,
        "auto_publish": bool(auto_publish),
        "is_commercial": commercial,
        "copy_content": {
            "selected_title": selected_title,
            "body_text": body_text,
        },
    }
    if resolved_niche:
        state["content_plan"] = {"niche": resolved_niche}
    if disclosure_confirmed is not None:
        state["disclosure_confirmed"] = bool(disclosure_confirmed)
        state["publish_options"] = {"disclosure_confirmed": bool(disclosure_confirmed)}
    if extra:
        for key, value in extra.items():
            state[key] = value
    return state
