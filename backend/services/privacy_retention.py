"""Personal-data retention defaults + cleanup hooks (P1-3).

Retention (env, days, default 90):
- XHS_PRIVACY_AUDIENCE_RETENTION_DAYS
- XHS_PRIVACY_COMMENTS_RETENTION_DAYS
- XHS_PRIVACY_DM_RETENTION_DAYS
- XHS_PRIVACY_RELATIONSHIP_RETENTION_DAYS

Cleanup removes expired Relationship Memory rows, engagement inbound peer
caches older than retention (via risk-gate last-hit / wall stamps when
available), and scrape caches. Audience Member delete/export live on the
Creator Agent adapter/routes.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("xhs_growth.privacy_retention")

DEFAULT_RETENTION_DAYS = 90


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(float(value)):
        return default
    return max(1, value)


def retention_days() -> dict[str, int]:
    """Configurable retention windows (days) for privacy-sensitive families."""
    return {
        "audience": _env_int("XHS_PRIVACY_AUDIENCE_RETENTION_DAYS", DEFAULT_RETENTION_DAYS),
        "comments": _env_int("XHS_PRIVACY_COMMENTS_RETENTION_DAYS", DEFAULT_RETENTION_DAYS),
        "dm": _env_int("XHS_PRIVACY_DM_RETENTION_DAYS", DEFAULT_RETENTION_DAYS),
        "relationship": _env_int("XHS_PRIVACY_RELATIONSHIP_RETENTION_DAYS", DEFAULT_RETENTION_DAYS),
    }


def cutoff_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=max(1, int(days)))).isoformat()


def _parse_iso(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
    except ValueError:
        return None


async def purge_expired_relationships(*, retention: int | None = None) -> dict[str, Any]:
    """Delete Relationship Memory rows older than retention (by last_interaction)."""
    days = int(retention if retention is not None else retention_days()["relationship"])
    cutoff = cutoff_iso(days)
    from backend.db.creator_agent import get_repository

    removed = await get_repository().purge_relationships_before(cutoff)
    return {"family": "relationship", "cutoff": cutoff, "removed": removed, "days": days}


async def purge_expired_scrape_cache(*, retention: int | None = None) -> dict[str, Any]:
    """Drop scrape cache entries older than comments retention (shared window)."""
    from backend.services.scrape_budget import purge_cache_before

    days = int(retention if retention is not None else retention_days()["comments"])
    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed = purge_cache_before(cutoff)
    return {
        "family": "scrape_cache",
        "cutoff": cutoff.isoformat(),
        "removed": removed,
        "days": days,
    }


async def purge_expired_engagement_peers(*, retention: int | None = None) -> dict[str, Any]:
    """Clear inbound DM peer caches for accounts with no recent engagement activity.

    Peers are a privacy-sensitive whitelist. When the account's last engagement
    wall stamp (or last risk hit) is older than DM retention, drop the set.
    """
    from backend.services import xhs_risk_gate as rg

    days = int(retention if retention is not None else retention_days()["dm"])
    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed_accounts = 0
    # engagement_wall keys look like account:{id}
    stale_aids: set[str] = set()
    for key, at_raw in list(rg._engagement_wall.items()):  # noqa: SLF001
        at = _parse_iso(str(at_raw or ""))
        aid = key.split(":", 1)[-1] if ":" in key else key
        if at is None or at < cutoff:
            stale_aids.add(aid)
    # Also clear peers for accounts that only appear in inbound map with old risk hit.
    for aid in list(rg._inbound_peers.keys()):  # noqa: SLF001
        hit = rg._last_risk_hit.get(aid) or {}  # noqa: SLF001
        hit_at = _parse_iso(str(hit.get("at") or ""))
        eng_at_raw = rg._engagement_wall.get(f"account:{aid}") or rg._engagement_wall.get(aid)  # noqa: SLF001
        eng_at = _parse_iso(str(eng_at_raw or ""))
        newest = max([t for t in (hit_at, eng_at) if t is not None], default=None)
        if (newest is None or newest < cutoff or aid in stale_aids) and aid in rg._inbound_peers:  # noqa: SLF001
            rg._inbound_peers.pop(aid, None)  # noqa: SLF001
            removed_accounts += 1
    if removed_accounts:
        rg._schedule_persist()  # noqa: SLF001
    return {
        "family": "dm_inbound_peers",
        "cutoff": cutoff.isoformat(),
        "removed_accounts": removed_accounts,
        "days": days,
    }


async def run_privacy_cleanup() -> dict[str, Any]:
    """Run all retention purge hooks (best-effort; called from lifespan / ops)."""
    purged: list[dict[str, Any]] = []
    results: dict[str, Any] = {
        "retention_days": retention_days(),
        "purged": purged,
    }
    for fn in (
        purge_expired_relationships,
        purge_expired_scrape_cache,
        purge_expired_engagement_peers,
    ):
        try:
            purged.append(await fn())
        except Exception as exc:  # noqa: BLE001 — cleanup must not break startup
            logger.warning("privacy cleanup %s failed: %s", fn.__name__, exc)
            purged.append({"family": fn.__name__, "error": str(exc)})
    return results


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "cutoff_iso",
    "purge_expired_engagement_peers",
    "purge_expired_relationships",
    "purge_expired_scrape_cache",
    "retention_days",
    "run_privacy_cleanup",
]
