"""Promotion TTL defaults (票 5z / PRD §9 Q2).

Every registered target namespace defaults to ``None``: promotions never expire
on their own and only leave "current" via supersede. Callers fill
``PromotionCandidate.ttl_seconds`` through ``resolve_promotion_ttl`` and set
``SourceCheck.ttl_expired`` through ``ttl_expired_for``; ``decide_promotion``
stays a pure function of those facts (no clocks inside the protocol).

Plays / materials are intentionally absent from the table — unresolved
namespaces resolve to ``None`` the same way an unknown string does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.memory.promotion import PromotionCandidate

__all__ = [
    "PROMOTION_TTL_SECONDS",
    "resolve_promotion_ttl",
    "ttl_expired_for",
]

#: Explicit per-namespace defaults. Change a value here (and the tests) to give
#: a namespace a real TTL later — do not scatter magic numbers at call sites.
PROMOTION_TTL_SECONDS: dict[str, int | None] = {
    "strategy_notes": None,
    "audience_preferences": None,
    "performance_insights": None,
    "content_history": None,
}


def resolve_promotion_ttl(namespace: str) -> int | None:
    """Return the configured TTL for ``namespace``, or ``None`` if unset/unknown.

    Unknown and undecided namespaces return ``None`` (never raise): the product
    has not chosen a day count for them, and inventing one here would be a
    silent policy decision.
    """
    return PROMOTION_TTL_SECONDS.get(namespace)


def ttl_expired_for(
    candidate: PromotionCandidate,
    *,
    now: datetime,
    observed_at: str | None = None,
) -> bool:
    """Whether ``candidate``'s TTL has elapsed relative to ``now``.

    ``ttl_seconds is None`` ⇒ never expired (supersede-only default). When a
    positive TTL is configured, the clock comparison is against ``observed_at``
    (or ``candidate.observed_at`` when the kwarg is omitted). The protocol does
    not call this; callers do, then pass the boolean into ``SourceCheck``.
    """
    if candidate.ttl_seconds is None:
        return False
    anchor = observed_at if observed_at is not None else candidate.observed_at
    observed = _parse_iso(anchor)
    clock = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return clock >= observed + timedelta(seconds=candidate.ttl_seconds)


def _parse_iso(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
