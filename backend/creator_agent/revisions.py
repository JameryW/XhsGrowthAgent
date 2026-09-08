"""Pure read projection for the Creator Agent Model Revision History."""

from __future__ import annotations

from collections.abc import Iterable

from backend.creator_agent.models import (
    ModelRevision,
    ModelRevisionPage,
    decode_model_revision_cursor,
    encode_model_revision_cursor,
)


def build_model_revision_page(
    revisions: Iterable[ModelRevision],
    *,
    cursor: str | None = None,
    limit: int = 20,
) -> ModelRevisionPage:
    """Assemble a deterministic page from immutable revision snapshots.

    The cursor is applied after the full history is ordered so ``total`` always
    describes the complete account history rather than the remaining rows.
    This projection is storage-independent, which keeps the memory fallback and
    the Postgres adapter behaviorally equivalent by construction.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    decoded_cursor = decode_model_revision_cursor(cursor) if cursor is not None else None

    ordered = sorted(revisions, key=lambda item: item.revision, reverse=True)
    total = len(ordered)
    if decoded_cursor is not None:
        ordered = [item for item in ordered if item.revision < decoded_cursor]

    selected = ordered[: limit + 1]
    has_next = len(selected) > limit
    items = [item.model_copy(deep=True) for item in selected[:limit]]
    next_cursor = encode_model_revision_cursor(items[-1].revision) if has_next and items else None
    return ModelRevisionPage(items=items, total=total, limit=limit, next_cursor=next_cursor)


__all__ = ["build_model_revision_page"]
