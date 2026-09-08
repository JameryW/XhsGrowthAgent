"""Read seam for durable content-production observations.

The Creator Agent core must not learn how content production stores its history.
It only declares what it can consume: a source that hands back already
account-scoped observations.  The Creative Memory adapter on the other side of
this seam maps its own storage onto these types.
"""

from __future__ import annotations

from typing import Protocol

from backend.creator_agent.models import ContentObservation


class CreatorContentObservationSource(Protocol):
    """Supplies durable Creative Memory observations for one account."""

    async def observations(self, account_id: str, *, limit: int) -> list[ContentObservation]:
        """Return up to ``limit`` observations owned by ``account_id``.

        Implementations must return an empty list rather than raising when the
        account has no content history, and must never return synthetic or
        cold-start placeholder rows.
        """
        ...


__all__ = ["CreatorContentObservationSource"]
