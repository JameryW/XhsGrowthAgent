"""Creative Memory adapter for the Creator Agent observation seam.

Lives on the content-production side so ``backend/creator_agent`` never imports
this storage.  It enumerates the durable Creative Memory rows for one account
and maps them onto ``ContentObservation`` values.

Deliberately **not** built on ``CreativeMemory.recall_style`` and friends: those
are relevance APIs with small default limits, and ``recall_style`` falls back to
synthetic cold-start styles (``default_*``) when an account has none.  A proposal
must never present invented content as something the creator measurably did.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.creator_agent.models import ContentObservation, ContentObservationKind

logger = logging.getLogger(__name__)

_COLD_START_PREFIX = "default_"


def _text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return str(value).strip() if value is not None else ""


def _rate(row: dict[str, Any], key: str) -> float | None:
    """Return a usable 0..1 measured rate, or ``None`` to drop the row."""
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(max(float(value), 0.0), 1.0)


def _count(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(int(value), 0)


def _style_observation(row: dict[str, Any]) -> ContentObservation | None:
    style_id = _text(row, "style_id")
    if not style_id or style_id.startswith(_COLD_START_PREFIX):
        return None
    parts = [
        part
        for part in (_text(row, "tone"), _text(row, "visual_style"))
        if part and not part.startswith(_COLD_START_PREFIX)
    ]
    measured = _rate(row, "engagement_rate")
    if measured is None or not parts:
        return None
    return ContentObservation(
        kind=ContentObservationKind.STYLE,
        source_id=style_id,
        description="/".join(parts)[:300],
        measured_rate=measured,
        sample_count=_count(row, "sample_count"),
        observed_at=_text(row, "last_used"),
    )


def _play_observation(row: dict[str, Any]) -> ContentObservation | None:
    play_id = _text(row, "play_id")
    if not play_id or play_id.startswith(_COLD_START_PREFIX):
        return None
    description = _text(row, "trigger_condition") or _text(row, "title_formula")
    measured = _rate(row, "avg_engagement_rate")
    if measured is None or not description:
        return None
    return ContentObservation(
        kind=ContentObservationKind.PLAY,
        source_id=play_id,
        description=description[:300],
        measured_rate=measured,
        sample_count=_count(row, "proven_count"),
        observed_at=_text(row, "last_proven"),
    )


def _material_observation(row: dict[str, Any]) -> ContentObservation | None:
    material_id = _text(row, "material_id")
    if not material_id or material_id.startswith(_COLD_START_PREFIX):
        return None
    description = _text(row, "category")
    measured = _rate(row, "effectiveness")
    if measured is None or not description:
        return None
    return ContentObservation(
        kind=ContentObservationKind.MATERIAL,
        source_id=material_id,
        description=description[:300],
        measured_rate=measured,
        sample_count=_count(row, "reuse_count"),
        observed_at=_text(row, "created_at"),
    )


class CreativeMemoryObservationSource:
    """Reads durable Style DNA, Conversion Plays, and Materials for one account."""

    async def observations(self, account_id: str, *, limit: int) -> list[ContentObservation]:
        from backend.db import creative_memory as creative_memory_db

        account_id = (account_id or "").strip()
        if not account_id:
            return []

        rows = await creative_memory_db.list_styles(account_id, limit=limit)
        styles = [
            item
            for item in (_style_observation(row) for row in rows if isinstance(row, dict))
            if item is not None
        ]
        rows = await creative_memory_db.list_plays(account_id, limit=limit)
        plays = [
            item
            for item in (_play_observation(row) for row in rows if isinstance(row, dict))
            if item is not None
        ]
        rows = await creative_memory_db.list_materials(account_id, limit=limit)
        materials = [
            item
            for item in (_material_observation(row) for row in rows if isinstance(row, dict))
            if item is not None
        ]

        # Stable family order; ranking and truncation belong to the projection.
        return styles + plays + materials


__all__ = ["CreativeMemoryObservationSource"]
