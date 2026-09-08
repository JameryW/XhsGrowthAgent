"""Read seam for durable content-production observations.

The Creator Agent core must not learn how content production stores its history.
It only declares what it can consume: a source that hands back already
account-scoped observations.  The Creative Memory adapter on the other side of
this seam maps its own storage onto these types.
"""

from __future__ import annotations

from typing import Protocol

from backend.creator_agent.models import ContentObservationScan


class CreatorContentObservationSource(Protocol):
    """Supplies durable Creative Memory observations for one account."""

    async def observations(self, account_id: str, *, window: int) -> ContentObservationScan:
        """Scan up to ``window`` candidate rows per family for ``account_id``.

        ``window`` is a scan budget, never a page size: the caller decides how
        many proposals to return separately, so the requested page size can never
        change which observations were considered.  Implementations set
        ``saturated`` when a family filled the whole window, meaning storage may
        hold rows that were not examined, and must return an empty scan rather
        than raising when the account has no content history.  Synthetic or
        cold-start placeholder rows must never be returned.
        """
        ...


__all__ = ["CreatorContentObservationSource"]
