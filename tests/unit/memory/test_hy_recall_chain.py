"""hy recall decoration (ledger #49): human edits attach only when they match."""

from __future__ import annotations

from typing import Any

import pytest

from backend.context.models import ContextItem, RetrievalMode, RetrievalResult
from backend.memory.hy.recall import decorate_hy_recall
from backend.services.memory_chain import MEMORY_CHAIN_ENV


class _Item:
    def __init__(self, value: Any) -> None:
        self.value = value


class FakeStore:
    def __init__(self, spans: list[dict[str, Any]] | None = None) -> None:
        self.data: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
        if spans is not None:
            self.data[(("accounts", "acc", "port_learning"), "spans")] = {"spans": spans}

    async def aget(self, namespace: Any, key: str) -> _Item | None:
        value = self.data.get((tuple(namespace), key))
        return _Item(value) if value is not None else None

    async def aput(self, namespace: Any, key: str, value: dict[str, Any]) -> None:
        self.data[(tuple(namespace), key)] = value


def _result(body: str = "这个产品首先很好用") -> RetrievalResult:
    return RetrievalResult(
        namespace="hy_chat",
        items=(ContextItem(body=body, source="hy_memory:chat", confidence=0.8, priority=80),),
        mode=RetrievalMode.HIT,
    )


class TestDecoration:
    async def test_switch_off_returns_the_same_object(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(MEMORY_CHAIN_ENV, raising=False)
        result = _result()
        store = FakeStore([{"old": "首先", "new": "直接"}])

        decorated = await decorate_hy_recall(result, account_id="acc", store=store)

        assert decorated is result

    async def test_matching_edit_is_attached_to_the_item(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, "1")
        result = _result()
        store = FakeStore([{"old": "首先", "new": "直接", "reason": "更口语"}])

        decorated = await decorate_hy_recall(result, account_id="acc", store=store)

        assert decorated is not result
        body = decorated.items[0].body
        assert body.startswith("这个产品首先很好用（人工改稿：")
        assert "旧「首先」→ 新「直接」" in body
        assert "（更口语）" in body
        # Only the body changes; retrieval metadata is preserved.
        assert decorated.items[0].source == "hy_memory:chat"
        assert decorated.mode is RetrievalMode.HIT

    async def test_without_port_memory_nothing_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, "1")
        result = _result()

        decorated = await decorate_hy_recall(result, account_id="acc", store=FakeStore())

        assert decorated is result

    async def test_unrelated_edit_is_not_attached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, "1")
        result = _result()
        store = FakeStore([{"old": "防晒", "new": "防晒霜"}])

        decorated = await decorate_hy_recall(result, account_id="acc", store=store)

        assert decorated is result

    async def test_missing_store_is_a_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, "1")
        result = _result()

        decorated = await decorate_hy_recall(result, account_id="acc", store=None)

        assert decorated is result

    async def test_empty_result_is_a_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, "1")
        result = RetrievalResult(namespace="hy_chat", mode=RetrievalMode.EMPTY)

        decorated = await decorate_hy_recall(
            result, account_id="acc", store=FakeStore([{"old": "首先", "new": "直接"}])
        )

        assert decorated is result
