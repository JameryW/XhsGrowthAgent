"""Append-only storage for draft analytics snapshots.

The draft JSON keeps a small display series for backwards compatibility, but the
authoritative history lives in its own store namespace. That keeps analytics
writes out of the draft document's CAS path: a failed analytics read can no
longer overwrite an editor's pending changes.
"""

from __future__ import annotations

from typing import Any

from backend.services.temporal_contracts import DraftAnalyticsSnapshot

DRAFT_ANALYTICS_NAMESPACE = "draft_analytics_snapshots"


def snapshot_namespace(account_id: str, draft_id: str) -> tuple[str, ...]:
    return ("accounts", account_id or "default", DRAFT_ANALYTICS_NAMESPACE, draft_id)


async def append_draft_analytics_snapshot(
    store: Any,
    account_id: str,
    snapshot: DraftAnalyticsSnapshot,
) -> dict[str, Any]:
    """Persist one snapshot under a sequence-ordered key and return its body."""
    value = snapshot.as_dict()
    await store.aput(
        snapshot_namespace(account_id, snapshot.draft_id),
        f"{snapshot.seq_no:06d}",
        value,
    )
    return value


async def list_draft_analytics_snapshots(
    store: Any,
    account_id: str,
    draft_id: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return snapshots in ascending sequence order (oldest first)."""
    items = await store.asearch(
        snapshot_namespace(account_id, draft_id),
        limit=max(1, int(limit)),
    )
    values: list[dict[str, Any]] = []
    for item in items:
        value = getattr(item, "value", None)
        if isinstance(value, dict):
            values.append(value)
    values.sort(key=lambda item: int(item.get("seq_no", 0) or 0))
    return values


__all__ = [
    "DRAFT_ANALYTICS_NAMESPACE",
    "append_draft_analytics_snapshot",
    "list_draft_analytics_snapshots",
    "snapshot_namespace",
]
