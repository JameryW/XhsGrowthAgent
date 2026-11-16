"""Physical draft analytics snapshots stay out of the draft CAS document."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from backend.db.draft_analytics import (
    append_draft_analytics_snapshot,
    list_draft_analytics_snapshots,
    snapshot_namespace,
)
from backend.services.temporal_contracts import build_analytics_snapshot


@dataclass
class _Item:
    value: dict


class _Store:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, ...], dict[str, dict]] = {}

    async def aput(self, namespace: tuple[str, ...], key: str, value: dict) -> None:
        self.rows.setdefault(namespace, {})[key] = value

    async def asearch(self, namespace: tuple[str, ...], limit: int = 10) -> list[_Item]:
        return [_Item(value=value) for value in list(self.rows.get(namespace, {}).values())[:limit]]


@pytest.mark.asyncio
async def test_snapshots_append_in_sequence_and_are_listed_oldest_first():
    store = _Store()
    first = build_analytics_snapshot(
        "draft-1",
        2,
        reads=120,
        likes=10,
        collects=5,
        comments=2,
        previous_reads=80,
        captured_at=datetime(2026, 11, 16, tzinfo=UTC),
    )
    second = build_analytics_snapshot(
        "draft-1",
        3,
        reads=180,
        previous_reads=120,
        captured_at=datetime(2026, 11, 17, tzinfo=UTC),
    )

    await append_draft_analytics_snapshot(store, "acc-1", second)
    await append_draft_analytics_snapshot(store, "acc-1", first)

    rows = await list_draft_analytics_snapshots(store, "acc-1", "draft-1")
    assert [row["seq_no"] for row in rows] == [2, 3]
    assert rows[0]["delta_views"] == 40
    assert snapshot_namespace("acc-1", "draft-1")[-1] == "draft-1"
