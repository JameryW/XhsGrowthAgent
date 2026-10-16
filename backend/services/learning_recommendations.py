"""P2-1: topic recommendations from recent performing posts (outcome-learning loop).

Uses imported ``creator_note_stats`` only — never invents engagement metrics.
Empty state when the account lacks enough performing samples.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.services.creator_stats.types import NoteStats

DEFAULT_RECOMMENDATION_LIMIT = 5
# Need at least one note with real engagement signal before recommending.
MIN_PERFORMING_SAMPLES = 1
OUTCOME_LEARNING_DOC = "docs/outcome-learning.md"


@dataclass(frozen=True)
class TopicRecommendation:
    """One Start-page topic suggestion grounded in a performing note."""

    topic: str
    related_note_id: str
    note_title: str
    engagement_rate: float
    views: int
    evidence_doc: str = OUTCOME_LEARNING_DOC
    evidence_href: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = "creator_note_stats"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _has_performance(note: NoteStats) -> bool:
    """True when the note carries a real platform signal (not a zero stub)."""
    if note.engagement_rate > 0:
        return True
    return (note.likes + note.comments + note.collects + note.shares) > 0


def _topic_from_note(note: NoteStats) -> str:
    """Derive a topic label from tags or title — never a fabricated keyword."""
    for tag in note.tags:
        cleaned = str(tag).strip().lstrip("#")
        if cleaned:
            return cleaned
    title = (note.title or "").strip()
    if title:
        # Keep the title short enough for a Start form chip.
        return title if len(title) <= 40 else f"{title[:37]}…"
    return ""


def build_topic_recommendations(
    notes: list[NoteStats],
    *,
    account_id: str = "",
    limit: int = DEFAULT_RECOMMENDATION_LIMIT,
) -> dict[str, Any]:
    """Rank performing notes and emit topic recommendations (or an empty state).

    Returns a payload shaped for ``GET /analytics/.../learning-recommendations``.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_RECOMMENDATION_LIMIT
    limit = max(1, min(limit, 20))

    performing = [n for n in notes if _has_performance(n) and _topic_from_note(n)]
    performing.sort(
        key=lambda n: (n.engagement_rate, n.views, n.likes),
        reverse=True,
    )
    top = performing[:limit]

    if len(top) < MIN_PERFORMING_SAMPLES:
        return {
            "account_id": account_id,
            "limit": limit,
            "min_samples": MIN_PERFORMING_SAMPLES,
            "sample_count": 0,
            "empty": True,
            "empty_reason": "insufficient_performing_samples",
            "recommendations": [],
            "outcome_learning_doc": OUTCOME_LEARNING_DOC,
        }

    recommendations: list[TopicRecommendation] = []
    for note in top:
        topic = _topic_from_note(note)
        href = f"/analytics?account={account_id}" if account_id else "/analytics"
        if note.note_id:
            sep = "&" if "?" in href else "?"
            href = f"{href}{sep}note={note.note_id}"
        recommendations.append(
            TopicRecommendation(
                topic=topic,
                related_note_id=note.note_id,
                note_title=(note.title or "").strip(),
                engagement_rate=float(note.engagement_rate or 0.0),
                views=int(note.views or 0),
                evidence_doc=OUTCOME_LEARNING_DOC,
                evidence_href=href,
                tags=[str(t) for t in (note.tags or []) if str(t).strip()],
            )
        )

    return {
        "account_id": account_id,
        "limit": limit,
        "min_samples": MIN_PERFORMING_SAMPLES,
        "sample_count": len(recommendations),
        "empty": False,
        "empty_reason": None,
        "recommendations": [r.to_dict() for r in recommendations],
        "outcome_learning_doc": OUTCOME_LEARNING_DOC,
    }


async def get_learning_recommendations(
    account_id: str,
    *,
    limit: int = DEFAULT_RECOMMENDATION_LIMIT,
) -> dict[str, Any]:
    """Load imported note stats and build Start-page learning recommendations."""
    account_id = (account_id or "").strip()
    if not account_id:
        return build_topic_recommendations([], account_id="", limit=limit)

    from backend.db import creator_stats as stats_db

    # Fetch a wider window then rank — list_note_stats already orders by engagement.
    fetch_limit = max(limit * 2, 20)
    notes = await stats_db.list_note_stats(account_id, limit=fetch_limit, order_by="engagement")
    return build_topic_recommendations(notes, account_id=account_id, limit=limit)


__all__ = [
    "DEFAULT_RECOMMENDATION_LIMIT",
    "MIN_PERFORMING_SAMPLES",
    "OUTCOME_LEARNING_DOC",
    "TopicRecommendation",
    "build_topic_recommendations",
    "get_learning_recommendations",
]
