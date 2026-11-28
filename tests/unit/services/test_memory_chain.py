"""Memory write path (ledger #49 + #99): deterministic routing and diff decoration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.services.memory_chain import (
    MEMORY_CHAIN_ENV,
    FactRecord,
    attach_revision_notes,
    current_facts,
    load_fact_records,
    load_hypotheses,
    memory_chain_enabled,
    promote_hypotheses,
    record_observation,
    revision_pairs_from_port_spans,
)
from backend.services.supervision_contracts import ConsolidationAction


class _Item:
    def __init__(self, value: Any) -> None:
        self.value = value


class FakeStore:
    def __init__(self) -> None:
        self.data: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
        self.writes = 0

    async def aget(self, namespace: Any, key: str) -> _Item | None:
        value = self.data.get((tuple(namespace), key))
        return _Item(value) if value is not None else None

    async def aput(self, namespace: Any, key: str, value: dict[str, Any]) -> None:
        self.writes += 1
        self.data[(tuple(namespace), key)] = value


class BrokenStore:
    async def aget(self, namespace: Any, key: str) -> Any:
        raise RuntimeError("store down")

    async def aput(self, namespace: Any, key: str, value: Any) -> None:
        raise RuntimeError("store down")


def _seed(store: FakeStore, account_id: str, records: list[FactRecord]) -> None:
    store.data[(("accounts", account_id, "fact_chain"), "records")] = {
        "records": [record.as_dict() for record in records]
    }


class TestSwitch:
    def test_defaults_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(MEMORY_CHAIN_ENV, raising=False)
        assert memory_chain_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "on", " yes "])
    def test_truthy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, value)
        assert memory_chain_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "off", ""])
    def test_falsy_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(MEMORY_CHAIN_ENV, value)
        assert memory_chain_enabled() is False


class TestFactChain:
    async def test_bootstrap_creates_one_fact(self) -> None:
        store = FakeStore()

        route = await record_observation(store, "acc", observation="账号人设：川西自驾老司机")

        assert route.action is ConsolidationAction.MAINTAIN
        assert route.reason == "bootstrap"
        assert route.stored is True
        assert route.fact_id.startswith("insight:")
        records = await load_fact_records(store, "acc")
        assert [record.text for record in records] == ["账号人设：川西自驾老司机"]

    async def test_repeated_observation_corroborates_in_place(self) -> None:
        store = FakeStore()
        first = await record_observation(store, "acc", observation="账号人设：川西自驾老司机")

        second = await record_observation(store, "acc", observation="账号人设：川西自驾老司机")

        assert second.corroborated is True
        assert second.action is ConsolidationAction.MAINTAIN
        assert second.fact_id == first.fact_id
        records = await load_fact_records(store, "acc")
        assert len(records) == 1
        assert records[0].evidence_count == 2

    async def test_unrelated_observation_becomes_its_own_fact(self) -> None:
        store = FakeStore()
        await record_observation(store, "acc", observation="账号人设：川西自驾老司机")

        route = await record_observation(store, "acc", observation="封面禁用荧光绿色")

        assert route.reason == "bootstrap"
        assert len(current_facts(await load_fact_records(store, "acc"))) == 2

    async def test_explicit_contradiction_supersedes_the_belief(self) -> None:
        store = FakeStore()
        first = await record_observation(store, "acc", observation="旺季需提前 7 天订车")

        route = await record_observation(
            store, "acc", observation="旺季需提前 14 天订车", contradiction=0.9
        )

        assert route.action is ConsolidationAction.CORRECT
        assert route.reason == "explicit_contradiction"
        assert route.belief_id == first.fact_id
        assert route.stored is True
        leaves = current_facts(await load_fact_records(store, "acc"))
        assert [leaf["text"] for leaf in leaves] == ["旺季需提前 14 天订车"]
        assert leaves[0]["supersedes"] == first.fact_id

    async def test_ambiguous_contradiction_parks_a_hypothesis(self) -> None:
        store = FakeStore()
        await record_observation(store, "acc", observation="旺季押金 3000 元可退")

        route = await record_observation(
            store, "acc", observation="旺季押金 3000 元可退", contradiction=0.55
        )

        assert route.action is ConsolidationAction.PROFILE
        assert route.reason == "ambiguous_contradiction_waiting_room"
        assert route.stored is False
        leaves = current_facts(await load_fact_records(store, "acc"))
        assert [leaf["text"] for leaf in leaves] == ["旺季押金 3000 元可退"]
        hypotheses = await load_hypotheses(store, "acc")
        assert len(hypotheses) == 1
        assert hypotheses[0].corroborations == 1

    async def test_namespaces_are_per_account(self) -> None:
        store = FakeStore()
        await record_observation(store, "acc-a", observation="账号人设：川西自驾老司机")
        await record_observation(store, "acc-b", observation="账号人设：城市通勤测评")

        assert len(await load_fact_records(store, "acc-a")) == 1
        texts = [record.text for record in await load_fact_records(store, "acc-b")]
        assert texts == ["账号人设：城市通勤测评"]

    async def test_broken_store_reads_as_empty_chain(self) -> None:
        assert await load_fact_records(BrokenStore(), "acc") == []
        assert await load_hypotheses(BrokenStore(), "acc") == []

    async def test_missing_store_is_a_noop(self) -> None:
        route = await record_observation(None, "acc", observation="账号人设：川西自驾老司机")

        assert route.stored is True
        assert route.reason == "bootstrap"

    async def test_empty_observation_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            await record_observation(FakeStore(), "acc", observation="   ")

    async def test_fact_id_is_deterministic(self) -> None:
        first = await record_observation(FakeStore(), "acc", observation="账号人设：川西自驾老司机")
        second = await record_observation(
            FakeStore(), "acc", observation="账号人设：川西自驾老司机"
        )

        assert first.fact_id == second.fact_id


class TestWaitingRoomPromotion:
    async def test_weeks_count_distinct_iso_weeks(self) -> None:
        store = FakeStore()
        start = datetime(2026, 3, 3, 9, 0, tzinfo=UTC)
        await record_observation(store, "acc", observation="旺季押金 3000 元可退", now=start)
        first = await record_observation(
            store, "acc", observation="旺季押金 3000 元可退", contradiction=0.55, now=start
        )
        same_week = await record_observation(
            store,
            "acc",
            observation="旺季押金 3000 元可退",
            contradiction=0.55,
            now=start + timedelta(days=1),
        )
        next_week = await record_observation(
            store,
            "acc",
            observation="旺季押金 3000 元可退",
            contradiction=0.55,
            now=start + timedelta(days=7),
        )

        assert first.hypothesis_id == same_week.hypothesis_id == next_week.hypothesis_id
        hypotheses = await load_hypotheses(store, "acc")
        assert hypotheses[0].corroborations == 3
        assert hypotheses[0].weeks_observed == 2

    async def test_promotion_requires_both_corroborations_and_weeks(self) -> None:
        store = FakeStore()
        start = datetime(2026, 3, 3, 9, 0, tzinfo=UTC)
        await record_observation(store, "acc", observation="旺季押金 3000 元可退", now=start)
        await record_observation(
            store, "acc", observation="旺季押金 3000 元可退", contradiction=0.55, now=start
        )
        await record_observation(
            store,
            "acc",
            observation="旺季押金 3000 元可退",
            contradiction=0.55,
            now=start + timedelta(days=1),
        )

        pending = await promote_hypotheses(store, "acc")

        assert len(pending) == 1
        assert pending[0].action is ConsolidationAction.PROFILE
        assert pending[0].reason == "awaiting_corroboration"
        assert pending[0].fact_id == ""

    async def test_promoted_hypothesis_becomes_a_superseding_fact(self) -> None:
        store = FakeStore()
        start = datetime(2026, 3, 3, 9, 0, tzinfo=UTC)
        belief = await record_observation(
            store, "acc", observation="旺季押金 3000 元可退", now=start
        )
        await record_observation(
            store, "acc", observation="旺季押金 3000 元可退", contradiction=0.55, now=start
        )
        await record_observation(
            store,
            "acc",
            observation="旺季押金 3000 元可退",
            contradiction=0.55,
            now=start + timedelta(days=7),
        )

        promotions = await promote_hypotheses(store, "acc")

        assert promotions[0].action is ConsolidationAction.CORRECT
        assert promotions[0].reason == "hypothesis_confirmed"
        assert promotions[0].fact_id.startswith("promoted:")
        leaves = current_facts(await load_fact_records(store, "acc"))
        assert [leaf["fact_id"] for leaf in leaves] == [promotions[0].fact_id]
        assert leaves[0]["supersedes"] == belief.fact_id
        assert await load_hypotheses(store, "acc") == []

    async def test_empty_waiting_room_promotes_nothing(self) -> None:
        assert await promote_hypotheses(FakeStore(), "acc") == []


class TestRevisionDecoration:
    def test_port_spans_are_mapped_and_incomplete_rows_skipped(self) -> None:
        revisions = revision_pairs_from_port_spans(
            [
                {"old": "首先", "new": "直接", "field": "body", "reason": "更口语"},
                {"old": "首先", "new": "首先", "field": "body"},
                {"old": "", "new": "x"},
                "not-a-span",
            ]
        )

        assert len(revisions) == 1
        assert revisions[0].revision_id == "port:0"
        assert revisions[0].old_text == "首先"
        assert revisions[0].operator_comment == "更口语"

    def test_matching_edit_is_attached_under_the_fact(self) -> None:
        revisions = revision_pairs_from_port_spans(
            [{"old": "首先", "new": "直接", "reason": "更口语"}]
        )

        decorated = attach_revision_notes(["这个产品首先很好用"], revisions)

        assert decorated == ["这个产品首先很好用（人工改稿：旧「首先」→ 新「直接」（更口语））"]

    def test_unrelated_text_is_left_untouched(self) -> None:
        revisions = revision_pairs_from_port_spans([{"old": "首先", "new": "直接"}])

        assert attach_revision_notes(["川西自驾路线清单"], revisions) == ["川西自驾路线清单"]

    def test_limit_keeps_the_latest_edits(self) -> None:
        spans = [
            {"old": "首先", "new": "第一", "last_seen": "2026-03-01T00:00:00+00:00"},
            {"old": "首先", "new": "第二", "last_seen": "2026-03-02T00:00:00+00:00"},
            {"old": "首先", "new": "第三", "last_seen": "2026-03-03T00:00:00+00:00"},
        ]

        decorated = attach_revision_notes(
            ["首先很好用"], revision_pairs_from_port_spans(spans), limit=2
        )

        assert "旧「首先」→ 新「第二」" in decorated[0]
        assert "旧「首先」→ 新「第三」" in decorated[0]
        assert "新「第一」" not in decorated[0]

    def test_no_revisions_is_a_passthrough(self) -> None:
        assert attach_revision_notes(["保持不变"], []) == ["保持不变"]
