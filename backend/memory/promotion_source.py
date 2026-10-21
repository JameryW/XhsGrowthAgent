"""Independent re-read of durable Creative Memory rows (Slice C, 票 5u).

The observe-only pass (Slice B) built its ``SourceCheck`` from the very rows it
had just scanned, which is enough to *observe* but not to *write*. Slice C opens
the write path, so verification must not be the scan confirming itself: this
module reads the durable row again by id and lets the re-read decide
"present / current / absent".

It stays a narrow, injectable seam (a reader callable) so the promotion pass is
testable without Postgres, and direction is preserved: ``backend/memory`` owns
the storage adapter; ``backend/context`` / ``backend/creator_agent`` never import
the DB module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from backend.creator_agent.models import ContentObservation, ContentObservationKind
from backend.creator_agent.proposals import observation_evidence_id
from backend.memory.promotion import SourceCheck

__all__ = ["CreativeMemoryPromotionSource", "read_style_row"]

StyleRowReader = Callable[[str, str], Awaitable[Mapping[str, Any] | None]]


async def read_style_row(account_id: str, style_id: str) -> Mapping[str, Any] | None:
    """Re-read one durable Style DNA row (raises on storage failure)."""
    from backend.db import creative_memory as creative_memory_db

    return await creative_memory_db.get_style(account_id, style_id)


class CreativeMemoryPromotionSource:
    """Verification seam: the durable row, read independently of the scan."""

    def __init__(self, reader: StyleRowReader | None = None) -> None:
        self._reader = reader if reader is not None else read_style_row

    async def source_check(self, account_id: str, observation: ContentObservation) -> SourceCheck:
        """Map the *re-read* row onto protocol ``SourceCheck``.

        The evidence id is derived from the row's own identity
        (``ev_style_<id>``), so "the row exists" is what makes it resolvable;
        that derivation lives in ``creator_agent.proposals`` and is reused rather
        than re-invented.

        A reader failure propagates (the protocol treats it as an exception, not
        a refusal). A durable row without ``last_used`` cannot be versioned, so
        it raises instead of being judged against a version nobody has.
        """
        if observation.kind is not ContentObservationKind.STYLE:
            raise ValueError("promotion verification currently covers Creative Memory styles only")
        row = await self._reader(account_id, observation.source_id)
        if row is None:
            return SourceCheck(present=False, version="")
        version = str(row.get("last_used") or "").strip()
        if not version:
            raise ValueError(
                f"durable style row {observation.source_id!r} has no last_used; "
                "it cannot be versioned and therefore cannot be verified"
            )
        return SourceCheck(
            present=True,
            version=version,
            evidence_found=(observation_evidence_id(observation),),
        )
