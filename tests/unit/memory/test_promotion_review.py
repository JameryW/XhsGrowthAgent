"""Human review write path for open REVIEW ledger rows (票 5y).

Pins: approve appends human PROMOTE then writes strategy_notes; dismiss appends
human REFUSE with no target write; already-closed REVIEW → conflict; missing id
→ missing; no store → unavailable; old REVIEW row never mutates; detail links
the closure to the reviewed promotion_id.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.store.memory import InMemoryStore

from backend.context.models import TrustClass
from backend.creator_agent.models import CreatorReviewDisposition
from backend.memory.promotion import (
    DEFAULT_PROMOTION_POLICY_VERSION,
    DedupeVerdict,
    PromotionCandidate,
    PromotionDecision,
    PromotionDisposition,
    PromotionReason,
)
from backend.memory.promotion_ledger import PromotionLedger, promotion_id_for
from backend.memory.promotion_review import (
    HUMAN_DECIDED_BY,
    PromotionReviewConflictError,
    PromotionReviewMissingError,
    PromotionStoreUnavailableError,
    encode_review_detail,
    parse_review_detail,
    review_promotion,
)

_ACCOUNT = "acc-review"
_VERSION = "2026-10-01T00:00:00Z"
_TARGET_NS = ("accounts", _ACCOUNT, "strategy_notes")
_RECORDED = "2026-10-29T12:00:00+00:00"
_CLOSED_AT = "2026-10-29T13:00:00+00:00"


def _review_candidate(*, trust: TrustClass = TrustClass.MEMORY) -> PromotionCandidate:
    return PromotionCandidate(
        namespace="strategy_notes",
        key="hy:deadbeef",
        body="一条待人审的 hy 记忆",
        trust_class=trust,
        source_ref="hy-memory://chat/mem_1",
        source_version=_VERSION,
        observed_at=_VERSION,
        evidence_ids=("ev_hy_deadbeef",),
        proposed_by="hy-memory",
    )


def _style_candidate() -> PromotionCandidate:
    return PromotionCandidate(
        namespace="strategy_notes",
        key="style:style_1",
        body="风格「治愈/温暖治愈」历史互动率 0.400（样本 10）",
        trust_class=TrustClass.INTERNAL_FACT,
        source_ref="creative-memory://style/style_1",
        source_version=_VERSION,
        observed_at=_VERSION,
        evidence_ids=("ev_style_style_1",),
        sample_count=10,
        measured_rate=0.4,
        proposed_by="creative-memory-observation",
    )


def _review_decision(candidate: PromotionCandidate) -> PromotionDecision:
    return PromotionDecision(
        candidate_id=candidate.id,
        disposition=PromotionDisposition.REVIEW,
        reason=PromotionReason.NEEDS_HUMAN_REVIEW,
        dedupe=DedupeVerdict.NEW,
        verified=True,
        supersedes=(),
        decided_by="machine",
        policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
    )


async def _seed_review(store: InMemoryStore, candidate: PromotionCandidate | None = None) -> str:
    candidate = candidate or _review_candidate()
    decision = _review_decision(candidate)
    await PromotionLedger(store).append(_ACCOUNT, candidate, decision, recorded_at=_RECORDED)
    return promotion_id_for(decision, source_version=candidate.source_version)


async def _rebuild_from_seed(
    record: Any, account_id: str, *, body: str | None = None
) -> PromotionCandidate:
    return PromotionCandidate(
        namespace=record.namespace,
        key=record.key,
        body=body or "人审通过后写入的正文",
        trust_class=TrustClass.MEMORY,
        source_ref=record.source_ref,
        source_version=record.source_version,
        observed_at=record.source_version,
        evidence_ids=("ev_hy_deadbeef",),
        proposed_by="human-review",
    )


class TestReviewDetailEncoding:
    def test_round_trip(self) -> None:
        raw = encode_review_detail(reviewed_promotion_id="promo_abc", review_note="看起来可以")
        assert parse_review_detail(raw) == {
            "reviewed_promotion_id": "promo_abc",
            "review_note": "看起来可以",
        }

    def test_malformed_detail_is_empty(self) -> None:
        assert parse_review_detail("not-json") == {}
        assert parse_review_detail("") == {}


class TestReviewPromotionApprove:
    async def test_approve_hy_uses_ledger_body_without_custom_rebuilder(self) -> None:
        """hy has no trusted re-read; approve must use the body snapshotted on append."""
        store = InMemoryStore()
        review_id = await _seed_review(store)

        result = await review_promotion(
            PromotionLedger(store),
            store,
            _ACCOUNT,
            review_id,
            CreatorReviewDisposition.APPROVED,
            review_note="hy ok",
            recorded_at=_CLOSED_AT,
        )

        assert result.applied is True
        assert result.closure_record.reason == "human_approved"
        written = await store.aget(_TARGET_NS, "hy:deadbeef")
        assert written is not None
        assert written.value["note"] == "一条待人审的 hy 记忆"
        assert written.value["trust_class"] == TrustClass.MEMORY.value
        assert written.value["decided_by"] == HUMAN_DECIDED_BY
        assert written.value["ttl_seconds"] is None  # 票 5z: ledger rebuild via resolve

    async def test_approve_appends_human_promote_and_writes_target(self) -> None:
        store = InMemoryStore()
        review_id = await _seed_review(store)

        result = await review_promotion(
            PromotionLedger(store),
            store,
            _ACCOUNT,
            review_id,
            CreatorReviewDisposition.APPROVED,
            review_note="ok",
            rebuild_candidate=_rebuild_from_seed,
            recorded_at=_CLOSED_AT,
        )

        assert result.applied is True
        assert result.disposition is CreatorReviewDisposition.APPROVED
        closure = result.closure_record
        assert closure.disposition == "promote"
        assert closure.reason == "human_approved"
        assert closure.decided_by == HUMAN_DECIDED_BY
        assert closure.supersedes == (review_id,)
        meta = parse_review_detail(closure.detail)
        assert meta["reviewed_promotion_id"] == review_id
        assert meta["review_note"] == "ok"

        # Original REVIEW row is untouched.
        page = await PromotionLedger(store).records(_ACCOUNT)
        original = next(r for r in page.records if r.promotion_id == review_id)
        assert original.disposition == "review"
        assert original.decided_by == "machine"
        assert original.detail == ""

        written = await store.aget(_TARGET_NS, "hy:deadbeef")
        assert written is not None
        assert written.value["note"] == "人审通过后写入的正文"
        assert written.value["promotion_id"] == closure.promotion_id
        assert written.value["decided_by"] == HUMAN_DECIDED_BY
        assert written.value["verified"] is False

    async def test_approve_with_default_style_rebuilder(self) -> None:
        store = InMemoryStore()
        candidate = _style_candidate()
        review_id = await _seed_review(store, candidate)

        async def _reader(account_id: str, style_id: str) -> dict[str, Any]:
            assert account_id == _ACCOUNT
            assert style_id == "style_1"
            return {
                "style_id": "style_1",
                "tone": "治愈",
                "visual_style": "温暖治愈",
                "engagement_rate": 0.4,
                "sample_count": 10,
                "last_used": _VERSION,
            }

        result = await review_promotion(
            PromotionLedger(store),
            store,
            _ACCOUNT,
            review_id,
            CreatorReviewDisposition.APPROVED,
            style_reader=_reader,
            recorded_at=_CLOSED_AT,
        )

        assert result.applied is True
        written = await store.aget(_TARGET_NS, "style:style_1")
        assert written is not None
        assert "治愈" in written.value["note"]
        assert written.value["trust_class"] == TrustClass.INTERNAL_FACT.value


class TestReviewPromotionDismiss:
    async def test_dismiss_appends_refuse_without_target_write(self) -> None:
        store = InMemoryStore()
        review_id = await _seed_review(store)

        result = await review_promotion(
            PromotionLedger(store),
            store,
            _ACCOUNT,
            review_id,
            CreatorReviewDisposition.DISMISSED,
            review_note="不合适",
            recorded_at=_CLOSED_AT,
        )

        assert result.applied is False
        closure = result.closure_record
        assert closure.disposition == "refuse"
        assert closure.reason == "human_dismissed"
        assert closure.decided_by == HUMAN_DECIDED_BY
        assert parse_review_detail(closure.detail)["reviewed_promotion_id"] == review_id
        assert await store.aget(_TARGET_NS, "hy:deadbeef") is None


class TestReviewPromotionConflicts:
    async def test_second_review_is_a_conflict(self) -> None:
        store = InMemoryStore()
        review_id = await _seed_review(store)
        await review_promotion(
            PromotionLedger(store),
            store,
            _ACCOUNT,
            review_id,
            CreatorReviewDisposition.DISMISSED,
            recorded_at=_CLOSED_AT,
        )

        with pytest.raises(PromotionReviewConflictError) as exc_info:
            await review_promotion(
                PromotionLedger(store),
                store,
                _ACCOUNT,
                review_id,
                CreatorReviewDisposition.APPROVED,
                rebuild_candidate=_rebuild_from_seed,
            )
        assert exc_info.value.promotion_id == review_id
        assert exc_info.value.existing_disposition == "refuse"

    async def test_missing_id_raises(self) -> None:
        store = InMemoryStore()
        await _seed_review(store)
        with pytest.raises(PromotionReviewMissingError):
            await review_promotion(
                PromotionLedger(store),
                store,
                _ACCOUNT,
                "promo_does_not_exist",
                CreatorReviewDisposition.DISMISSED,
            )

    async def test_promote_row_is_not_reviewable(self) -> None:
        store = InMemoryStore()
        candidate = _style_candidate()
        decision = PromotionDecision(
            candidate_id=candidate.id,
            disposition=PromotionDisposition.PROMOTE,
            reason=PromotionReason.VERIFIED_INTERNAL_FACT,
            dedupe=DedupeVerdict.NEW,
            verified=True,
            supersedes=(),
            decided_by="machine",
            policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
        )
        await PromotionLedger(store).append(_ACCOUNT, candidate, decision, recorded_at=_RECORDED)
        promo_id = promotion_id_for(decision, source_version=candidate.source_version)
        with pytest.raises(PromotionReviewMissingError):
            await review_promotion(
                PromotionLedger(store),
                store,
                _ACCOUNT,
                promo_id,
                CreatorReviewDisposition.APPROVED,
                rebuild_candidate=_rebuild_from_seed,
            )

    async def test_no_store_is_unavailable(self) -> None:
        with pytest.raises(PromotionStoreUnavailableError):
            await review_promotion(
                PromotionLedger(None),
                None,
                _ACCOUNT,
                "promo_x",
                CreatorReviewDisposition.DISMISSED,
            )
