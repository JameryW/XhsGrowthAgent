"""Analyst write path (ledger #99): a parked insight never reaches long-term memory."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.agents import analyst as analyst_module
from backend.agents.analyst import _safe_store_insight
from backend.services.memory_chain import MEMORY_CHAIN_ENV, ObservationRoute
from backend.services.supervision_contracts import ConsolidationAction


class FakeMemory:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, dict[str, Any]]] = []

    async def store_insight(self, store: Any, insight: str, metadata: dict[str, Any]) -> None:
        self.calls.append((store, insight, metadata))


def _route(*, stored: bool, action: ConsolidationAction = ConsolidationAction.MAINTAIN) -> Any:
    return ObservationRoute(
        action=action,
        surprisal=0.12,
        belief_id="insight:abc",
        fact_id="insight:abc" if stored else "",
        hypothesis_id="" if stored else "profile:insight:abc",
        reason="bootstrap" if stored else "ambiguous_contradiction_waiting_room",
        stored=stored,
        corroborated=stored,
    )


class TestAnalystMemoryChain:
    async def test_switch_off_stores_directly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(MEMORY_CHAIN_ENV, raising=False)
        mm = FakeMemory()

        await _safe_store_insight(mm, object(), "收藏率提升 12%", "post-1", account_id="acc")

        assert len(mm.calls) == 1
        assert mm.calls[0][2] == {"source": "analyst", "post_id": "post-1"}

    async def test_maintain_still_stores_in_long_term_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, "1")
        mm = FakeMemory()
        record = AsyncMock(return_value=_route(stored=True))

        with (
            patch.object(analyst_module, "memory_chain_enabled", return_value=True),
            patch("backend.services.memory_chain.record_observation", record),
        ):
            await _safe_store_insight(mm, object(), "收藏率提升 12%", "post-1", account_id="acc")

        record.assert_awaited_once()
        assert record.await_args.kwargs["observation"] == "收藏率提升 12%"
        assert len(mm.calls) == 1

    async def test_parked_insight_is_not_stored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, "1")
        mm = FakeMemory()
        record = AsyncMock(return_value=_route(stored=False, action=ConsolidationAction.PROFILE))

        with (
            patch.object(analyst_module, "memory_chain_enabled", return_value=True),
            patch("backend.services.memory_chain.record_observation", record),
        ):
            await _safe_store_insight(mm, object(), "收藏率提升 12%", "post-1", account_id="acc")

        assert mm.calls == []

    async def test_routing_failure_falls_back_to_direct_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, "1")
        mm = FakeMemory()
        record = AsyncMock(side_effect=RuntimeError("store down"))

        with (
            patch.object(analyst_module, "memory_chain_enabled", return_value=True),
            patch("backend.services.memory_chain.record_observation", record),
        ):
            await _safe_store_insight(mm, object(), "收藏率提升 12%", "post-1", account_id="acc")

        assert len(mm.calls) == 1

    async def test_no_account_id_skips_the_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, "1")
        mm = FakeMemory()
        record = AsyncMock(return_value=_route(stored=True))

        with (
            patch.object(analyst_module, "memory_chain_enabled", return_value=True),
            patch("backend.services.memory_chain.record_observation", record),
        ):
            await _safe_store_insight(mm, object(), "收藏率提升 12%", "post-1")

        record.assert_not_awaited()
        assert len(mm.calls) == 1
