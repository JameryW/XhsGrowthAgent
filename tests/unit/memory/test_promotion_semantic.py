"""Semantic near-dupe hints after NEEDS_REVIEW (票 5ac / PRD §9 Q3).

Pins: cost only when ``dedupe == NEEDS_REVIEW``; hint attaches to ledger detail;
store/index missing or asearch failure → skip-hint (unavailable marker); never
rewrites disposition/reason/dedupe; plain-string detail is not corrupted;
``decide_promotion`` stays I/O-free.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.store.memory import InMemoryStore

from backend.context.models import TrustClass
from backend.creator_agent.models import ContentObservation, ContentObservationKind
from backend.memory.promotion import (
    DedupeVerdict,
    ExistingEntry,
    PromotionCandidate,
    PromotionDecision,
    PromotionDisposition,
    PromotionReason,
    SourceCheck,
    decide_promotion,
)
from backend.memory.promotion_ledger import PromotionLedger
from backend.memory.promotion_observations import observe_style_promotions
from backend.memory.promotion_semantic import (
    DETAIL_KEY,
    detail_with_near_dupe_hint,
    merge_promotion_detail,
    near_dupe_hint_for,
)

_ACCOUNT = "acc-1"
_VERSION = "2026-10-01T00:00:00Z"


def _candidate(**overrides: Any) -> PromotionCandidate:
    base: dict[str, Any] = {
        "namespace": "strategy_notes",
        "key": "style:style_1",
        "body": "风格「治愈/温暖治愈」历史互动率 0.400（样本 10）",
        "trust_class": TrustClass.INTERNAL_FACT,
        "source_ref": "creative-memory://style/style_1",
        "source_version": _VERSION,
        "observed_at": _VERSION,
        "evidence_ids": ("ev_style_style_1",),
        "sample_count": 10,
        "measured_rate": 0.4,
    }
    base.update(overrides)
    return PromotionCandidate(**base)


def _needs_review_decision() -> PromotionDecision:
    existing = (
        ExistingEntry(
            key="style:style_1",
            source_ref="creative-memory://play/other",
            source_version=_VERSION,
            promotion_id="promo_other",
        ),
    )
    decision = decide_promotion(
        _candidate(),
        source=SourceCheck(
            present=True,
            version=_VERSION,
            evidence_found=("ev_style_style_1",),
        ),
        existing=existing,
    )
    assert decision.dedupe is DedupeVerdict.NEEDS_REVIEW
    return decision


def _promote_decision() -> PromotionDecision:
    decision = decide_promotion(
        _candidate(),
        source=SourceCheck(
            present=True,
            version=_VERSION,
            evidence_found=("ev_style_style_1",),
        ),
        existing=(),
    )
    assert decision.dedupe is DedupeVerdict.NEW
    return decision


class TestNearDupeHintFor:
    def test_non_needs_review_skips_without_search(self) -> None:
        store = MagicMock()
        store.asearch = AsyncMock()
        hint = asyncio.run(
            near_dupe_hint_for(
                _promote_decision(),
                _candidate(),
                store=store,
                account_id=_ACCOUNT,
                index_enabled=True,
            )
        )
        assert hint is None
        store.asearch.assert_not_called()

    def test_needs_review_with_hits_returns_neighbors(self) -> None:
        store = MagicMock()
        store.asearch = AsyncMock(
            return_value=[
                SimpleNamespace(
                    key="style:other",
                    value={
                        "note": "相近风格笔记",
                        "source_ref": "creative-memory://style/other",
                        "promotion_id": "promo_hit",
                    },
                    score=0.91,
                ),
                SimpleNamespace(key="style:style_1", value={"note": "self"}, score=0.99),
            ]
        )
        hint = asyncio.run(
            near_dupe_hint_for(
                _needs_review_decision(),
                _candidate(),
                store=store,
                account_id=_ACCOUNT,
                index_enabled=True,
            )
        )
        assert hint == {
            DETAIL_KEY: {
                "status": "hits",
                "neighbors": [
                    {
                        "key": "style:other",
                        "source_ref": "creative-memory://style/other",
                        "promotion_id": "promo_hit",
                        "score": 0.91,
                    }
                ],
            }
        }
        store.asearch.assert_awaited_once()
        args, kwargs = store.asearch.await_args
        assert args[0] == ("accounts", _ACCOUNT, "strategy_notes")
        assert kwargs["query"] == _candidate().body

    def test_needs_review_empty_search_is_none_status(self) -> None:
        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        hint = asyncio.run(
            near_dupe_hint_for(
                _needs_review_decision(),
                _candidate(),
                store=store,
                account_id=_ACCOUNT,
                index_enabled=True,
            )
        )
        assert hint == {DETAIL_KEY: {"status": "none"}}

    def test_missing_store_is_unavailable_skip_hint(self) -> None:
        decision = _needs_review_decision()
        hint = asyncio.run(
            near_dupe_hint_for(
                decision,
                _candidate(),
                store=None,
                account_id=_ACCOUNT,
                index_enabled=True,
            )
        )
        assert hint == {DETAIL_KEY: {"status": "unavailable"}}
        assert decision.disposition is PromotionDisposition.REVIEW
        assert decision.dedupe is DedupeVerdict.NEEDS_REVIEW

    def test_disabled_index_is_unavailable_without_asearch(self) -> None:
        store = MagicMock()
        store.asearch = AsyncMock()
        hint = asyncio.run(
            near_dupe_hint_for(
                _needs_review_decision(),
                _candidate(),
                store=store,
                account_id=_ACCOUNT,
                index_enabled=False,
            )
        )
        assert hint == {DETAIL_KEY: {"status": "unavailable"}}
        store.asearch.assert_not_called()

    def test_asearch_failure_is_unavailable_and_keeps_decision(self) -> None:
        store = MagicMock()
        store.asearch = AsyncMock(side_effect=RuntimeError("embed down"))
        decision = _needs_review_decision()
        hint = asyncio.run(
            near_dupe_hint_for(
                decision,
                _candidate(),
                store=store,
                account_id=_ACCOUNT,
                index_enabled=True,
            )
        )
        assert hint == {DETAIL_KEY: {"status": "unavailable"}}
        assert decision.reason is PromotionReason.NEEDS_HUMAN_REVIEW


class TestMergePromotionDetail:
    def test_empty_existing_becomes_json_hint(self) -> None:
        merged = merge_promotion_detail("", {DETAIL_KEY: {"status": "none"}})
        assert json.loads(merged) == {DETAIL_KEY: {"status": "none"}}

    def test_json_object_merges_key(self) -> None:
        existing = json.dumps(
            {"reviewed_promotion_id": "promo_r", "review_note": "ok"},
            ensure_ascii=False,
            sort_keys=True,
        )
        merged = merge_promotion_detail(existing, {DETAIL_KEY: {"status": "hits", "neighbors": []}})
        parsed = json.loads(merged)
        assert parsed["reviewed_promotion_id"] == "promo_r"
        assert parsed["review_note"] == "ok"
        assert parsed[DETAIL_KEY]["status"] == "hits"

    def test_plain_string_is_not_corrupted(self) -> None:
        existing = "TimeoutError: slow"
        merged = merge_promotion_detail(existing, {DETAIL_KEY: {"status": "unavailable"}})
        assert merged == existing

    def test_none_hint_leaves_existing(self) -> None:
        assert merge_promotion_detail("keep", None) == "keep"
        assert merge_promotion_detail("", None) == ""


class TestDecidePromotionStaysPure:
    def test_decide_promotion_has_no_store_or_index_side_effects(self) -> None:
        with (
            patch("backend.memory.index.semantic_index_status") as status,
            patch("backend.memory.promotion_semantic.near_dupe_hint_for") as hint,
        ):
            decision = decide_promotion(
                _candidate(),
                source=SourceCheck(
                    present=True,
                    version=_VERSION,
                    evidence_found=("ev_style_style_1",),
                ),
                existing=(
                    ExistingEntry(
                        key="style:style_1",
                        source_ref="creative-memory://play/other",
                        source_version=_VERSION,
                        promotion_id="promo_other",
                    ),
                ),
            )
        assert decision.dedupe is DedupeVerdict.NEEDS_REVIEW
        status.assert_not_called()
        hint.assert_not_called()


class _HintAwareStore(InMemoryStore):
    """Ledger list stays real; target-namespace query returns scripted neighbors."""

    def __init__(self, hits: list[Any]) -> None:
        super().__init__()
        self._hits = hits

    async def asearch(self, namespace: tuple[str, ...], *args: Any, **kwargs: Any) -> list[Any]:
        if namespace == ("accounts", _ACCOUNT, "strategy_notes") and kwargs.get("query"):
            return list(self._hits)
        return await super().asearch(namespace, *args, **kwargs)


class TestObserveWiresHint:
    def test_needs_review_observe_writes_near_dupe_detail(self) -> None:
        from backend.memory.promotion_ledger import PromotionRecord

        hits = [
            SimpleNamespace(
                key="style:near",
                value={"note": "near", "source_ref": "creative-memory://style/near"},
                score=0.8,
            )
        ]
        store = _HintAwareStore(hits)
        ledger = PromotionLedger(store)

        # Competing promote on the same key → next style observe is NEEDS_REVIEW.
        asyncio.run(
            store.aput(
                ledger.namespace(_ACCOUNT),
                key="promo_seed",
                value=PromotionRecord(
                    promotion_id="promo_seed",
                    candidate_id="cand_seed",
                    namespace="strategy_notes",
                    key="style:style_1",
                    source_ref="creative-memory://play/other",
                    source_version=_VERSION,
                    disposition="promote",
                    reason="verified_internal_fact",
                    dedupe="new",
                    verified=True,
                    supersedes=(),
                    decided_by="machine",
                    policy_version="v1",
                    recorded_at=_VERSION,
                    body="seed",
                ).to_dict(),
            )
        )

        observation = ContentObservation(
            kind=ContentObservationKind.STYLE,
            source_id="style_1",
            description="治愈/温暖治愈",
            measured_rate=0.4,
            sample_count=10,
            observed_at=_VERSION,
        )

        with patch(
            "backend.memory.promotion_semantic.semantic_index_status",
            return_value={"enabled": True},
        ):
            result = asyncio.run(observe_style_promotions(ledger, _ACCOUNT, [observation]))

        assert len(result.promotions) == 1
        decision = result.promotions[0].decision
        assert decision.dedupe is DedupeVerdict.NEEDS_REVIEW
        assert decision.disposition is PromotionDisposition.REVIEW

        page = asyncio.run(ledger.records(_ACCOUNT))
        review_rows = [row for row in page.records if row.disposition == "review"]
        assert len(review_rows) == 1
        detail = json.loads(review_rows[0].detail)
        assert detail[DETAIL_KEY]["status"] == "hits"
        assert detail[DETAIL_KEY]["neighbors"][0]["key"] == "style:near"

    def test_detail_with_hint_helper_round_trip(self) -> None:
        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        detail = asyncio.run(
            detail_with_near_dupe_hint(
                _needs_review_decision(),
                _candidate(),
                store=store,
                account_id=_ACCOUNT,
                index_enabled=True,
            )
        )
        assert json.loads(detail) == {DETAIL_KEY: {"status": "none"}}
