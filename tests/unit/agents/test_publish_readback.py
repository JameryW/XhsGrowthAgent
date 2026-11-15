"""Startup readback for publish effects left UNKNOWN by a crash."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from backend.agents.publisher import PUBLISH_IDEMPOTENCY_NS, readback_unknown_publishes
from backend.state.effects import EffectLedger, EffectStatus


class _FakeStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}

    async def aget(self, namespace: tuple[str, ...], key: str) -> Any:
        value = self.rows.get((namespace, key))
        return None if value is None else SimpleNamespace(key=key, value=deepcopy(value))

    async def aput(self, namespace: tuple[str, ...], key: str, value: dict[str, Any]) -> None:
        self.rows[(namespace, key)] = deepcopy(value)

    async def asearch(
        self,
        namespace: tuple[str, ...],
        query: str | None = None,
        limit: int = 10,
        **_: Any,
    ) -> list[Any]:
        items = [
            SimpleNamespace(key=key, value=deepcopy(value))
            for (ns, key), value in self.rows.items()
            if ns == namespace
        ]
        return items[:limit]


@pytest.mark.asyncio
async def test_readback_confirms_unknown_publish_from_platform_list() -> None:
    store = _FakeStore()
    ledger = EffectLedger(store, PUBLISH_IDEMPOTENCY_NS)
    await ledger.mark(
        "eff-1",
        EffectStatus.UNKNOWN,
        extra={"title": "春日野餐清单", "account_id": "acc-1"},
    )

    async def _fetcher(account_id: str) -> list[dict[str, Any]]:
        assert account_id == "acc-1"
        return [{"title": "春日野餐清单", "note_id": "note-9"}]

    result = await readback_unknown_publishes(store, platform_note_fetcher=_fetcher)

    assert result["checked"] == 1
    assert result["confirmed"] == 1
    assert result["uncertain"] == 0
    assert result["records"][0]["result"] == "confirmed"
    assert result["records"][0]["evidence"]["post_id"] == "note-9"

    record = await ledger.get("eff-1")
    assert record is not None
    assert record.status is EffectStatus.CONFIRMED
    assert record.extra["post_id"] == "note-9"


@pytest.mark.asyncio
async def test_readback_keeps_titleless_record_uncertain() -> None:
    store = _FakeStore()
    ledger = EffectLedger(store, PUBLISH_IDEMPOTENCY_NS)
    await ledger.mark("eff-2", EffectStatus.UNKNOWN, extra={"account_id": "acc-1"})

    async def _fetcher(account_id: str) -> list[dict[str, Any]]:  # pragma: no cover - must not run
        raise AssertionError("a titleless record must not hit the platform")

    result = await readback_unknown_publishes(store, platform_note_fetcher=_fetcher)

    assert result["checked"] == 1
    assert result["confirmed"] == 0
    assert result["uncertain"] == 1
    assert result["records"][0]["result"] == "uncertain_no_title"
    record = await ledger.get("eff-2")
    assert record is not None
    assert record.status is EffectStatus.UNKNOWN


@pytest.mark.asyncio
async def test_readback_reports_storage_failure_instead_of_raising() -> None:
    class _BrokenStore(_FakeStore):
        async def asearch(self, *args: Any, **kwargs: Any) -> list[Any]:
            raise RuntimeError("store down")

    result = await readback_unknown_publishes(_BrokenStore())

    assert result["checked"] == 0
    assert result["confirmed"] == 0
    assert "store down" in result["error"]
