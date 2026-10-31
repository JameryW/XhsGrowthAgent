"""hy-memory candidates at the gate (Slice D, 票 5v) — REVIEW-only.

The gap this slice closes: SDK-extracted memories never passed any gate. What is
pinned here is the safety property — every hy candidate is ``REVIEW``, a degraded
read is refused *and recorded*, a policy that would machine-promote one is
rejected instead of silently writing, and nothing is ever written into a memory
namespace. The missing re-read is documented rather than papered over.
"""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from backend.context.models import RetrievalMode, RetrievalResult
from backend.memory.promotion import (
    DedupeVerdict,
    PromotionDisposition,
    PromotionPolicy,
    PromotionReason,
)
from backend.memory.promotion_hy import (
    HY_SOURCE_PREFIX,
    HyMemoryBatch,
    batch_from_bridge,
    batch_from_retrieval,
    candidate_from_hy_memory,
    degraded_batch_candidate,
    observe_hy_candidates,
)
from backend.memory.promotion_ledger import PromotionLedger
from backend.memory.promotion_observations import TARGET_NAMESPACE

_ACCOUNT = "acc-1"
_TARGET_NS = ("accounts", _ACCOUNT, TARGET_NAMESPACE)


def _memory(
    content: str = "用户偏好测评体标题",
    *,
    memory_id: str = "mem_1",
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {"content": content, "scene": "chat", "channel": "normal"}
    if memory_id:
        row["memory_id"] = memory_id
    if metadata is not None:
        row["metadata"] = metadata
    return row


def _batch(*rows: dict[str, object], scene: str = "chat") -> HyMemoryBatch:
    return HyMemoryBatch(account_id=_ACCOUNT, scene=scene, memories=tuple(rows))


class TestBatchConstruction:
    def test_a_degraded_batch_must_carry_its_error(self) -> None:
        with pytest.raises(ValueError, match="must carry its error"):
            HyMemoryBatch(account_id=_ACCOUNT, scene="chat", degraded=True)

    def test_a_healthy_batch_must_not_carry_an_error(self) -> None:
        with pytest.raises(ValueError, match="must not carry"):
            HyMemoryBatch(account_id=_ACCOUNT, scene="chat", error="stale error")

    def test_a_batch_needs_an_account_and_scene(self) -> None:
        with pytest.raises(ValueError, match="account_id"):
            HyMemoryBatch(account_id="  ", scene="chat")
        with pytest.raises(ValueError, match="scene"):
            HyMemoryBatch(account_id=_ACCOUNT, scene=" ")


class TestFromRetrieval:
    def test_hit_carries_the_rows_and_the_scene(self) -> None:
        result = RetrievalResult(
            namespace="hy_working",
            mode=RetrievalMode.HIT,
            raw_items=(_memory(),),
        )
        batch = batch_from_retrieval(result, account_id=_ACCOUNT)
        assert batch.scene == "working"
        assert batch.degraded is False
        assert list(batch.memories) == [_memory()]

    def test_empty_is_a_healthy_zero_row_read(self) -> None:
        batch = batch_from_retrieval(
            RetrievalResult(namespace="hy_chat", mode=RetrievalMode.EMPTY),
            account_id=_ACCOUNT,
        )
        assert batch.degraded is False
        assert batch.memories == ()

    def test_degraded_carries_the_error(self) -> None:
        batch = batch_from_retrieval(
            RetrievalResult(
                namespace="hy_chat", mode=RetrievalMode.DEGRADED, error="TimeoutError: slow"
            ),
            account_id=_ACCOUNT,
        )
        assert batch.degraded is True
        assert batch.error == "TimeoutError: slow"

    def test_degraded_without_an_error_gets_an_explicit_fallback(self) -> None:
        batch = batch_from_retrieval(
            RetrievalResult(namespace="hy_chat", mode=RetrievalMode.DEGRADED),
            account_id=_ACCOUNT,
        )
        assert batch.error == "degraded without an error summary"


class _Bridge:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        enabled: bool = True,
        last_error: str = "",
    ) -> None:
        self._rows = rows
        self.enabled = enabled
        self._last_error = last_error
        self.calls: list[tuple[str, int]] = []

    async def list_memories(self, *, account_id: str, limit: int) -> list[dict[str, object]]:
        self.calls.append((account_id, limit))
        return list(self._rows)

    def last_error(self) -> str:
        return self._last_error


class TestFromBridge:
    async def test_a_disabled_bridge_is_a_healthy_empty_read(self) -> None:
        bridge = _Bridge([_memory()], enabled=False)
        batch = await batch_from_bridge(bridge, account_id=_ACCOUNT)
        assert batch.degraded is False
        assert batch.memories == ()
        assert bridge.calls == []

    async def test_rows_are_read_through_the_management_api(self) -> None:
        bridge = _Bridge([_memory()])
        batch = await batch_from_bridge(bridge, account_id=_ACCOUNT, scene="chat", limit=7)
        assert list(batch.memories) == [_memory()]
        assert bridge.calls == [(_ACCOUNT, 7)]

    async def test_an_empty_result_with_a_last_error_is_degraded(self) -> None:
        bridge = _Bridge([], last_error="ClientError: unreachable")
        batch = await batch_from_bridge(bridge, account_id=_ACCOUNT)
        assert batch.degraded is True
        assert batch.error == "ClientError: unreachable"

    async def test_rows_with_a_stale_last_error_stay_healthy(self) -> None:
        # last_error is per-loop "most recent failure"; a successful read that
        # returns rows is not degraded just because an older call failed.
        bridge = _Bridge([_memory()], last_error="old failure")
        batch = await batch_from_bridge(bridge, account_id=_ACCOUNT)
        assert batch.degraded is False
        assert len(batch.memories) == 1


class TestCandidateMapping:
    def test_a_clean_row_maps_to_memory_trust(self) -> None:
        candidate = candidate_from_hy_memory(_memory())
        assert candidate.namespace == TARGET_NAMESPACE
        assert candidate.trust_class.value == "memory"
        assert candidate.body == "用户偏好测评体标题"
        assert candidate.source_ref == f"{HY_SOURCE_PREFIX}chat/mem_1"
        assert candidate.source_version.startswith("content-")
        assert candidate.observed_at == candidate.source_version
        assert candidate.evidence_ids == (f"ev_hy_{candidate.key.removeprefix('hy:')}",)
        assert candidate.ttl_seconds is None  # 票 5z: default null / supersede-only
        assert candidate.proposed_by == "hy-memory"

    def test_metadata_carries_the_version_when_present(self) -> None:
        candidate = candidate_from_hy_memory(
            _memory(metadata={"source_version": "2026-10-01T00:00:00Z"})
        )
        assert candidate.source_version == "2026-10-01T00:00:00Z"

    def test_an_explicit_source_ref_wins(self) -> None:
        candidate = candidate_from_hy_memory(
            _memory(metadata={"source_ref": "hy-memory://insight/42"})
        )
        assert candidate.source_ref == "hy-memory://insight/42"
        assert candidate.evidence_ids == (f"ev_hy_{candidate.key.removeprefix('hy:')}",)

    def test_no_id_means_a_content_addressed_identity(self) -> None:
        first = candidate_from_hy_memory(_memory(memory_id=""))
        second = candidate_from_hy_memory(_memory(memory_id=""))
        assert first.source_ref == second.source_ref
        assert first.key == second.key
        other = candidate_from_hy_memory(_memory(memory_id="", content="另一条"))
        assert other.source_ref != first.source_ref

    def test_text_fallbacks_are_read(self) -> None:
        outcome: object = "no error"
        try:
            outcome = candidate_from_hy_memory({"statement": "用户偏好短标题", "memory_id": "m"})
        except Exception as exc:  # judged below: a readable row must not raise
            outcome = exc
        assert not isinstance(outcome, Exception), outcome
        assert outcome.body == "用户偏好短标题"  # type: ignore[union-attr]

    def test_a_row_without_content_raises(self) -> None:
        outcome: object = "no error"
        try:
            candidate_from_hy_memory({"memory_id": "m"})
        except Exception as exc:
            outcome = exc
        assert isinstance(outcome, ValueError), outcome
        assert "content" in str(outcome), outcome

    def test_counts_and_rates_are_parsed_strictly(self) -> None:
        outcome: object = "no error"
        try:
            good = candidate_from_hy_memory(
                _memory(metadata={"sample_count": 7, "measured_rate": 0.6})
            )
            bad = candidate_from_hy_memory(
                _memory(metadata={"sample_count": True, "measured_rate": 1.7})
            )
            outcome = (good, bad)
        except Exception as exc:  # judged below: bad metadata must not crash the pass
            outcome = exc
        assert not isinstance(outcome, Exception), outcome
        good, bad = outcome  # type: ignore[misc]
        assert good.sample_count == 7
        assert good.measured_rate == 0.6
        assert bad.sample_count == 0
        assert bad.measured_rate is None

    def test_a_degraded_batch_candidate_is_keyed_by_its_error(self) -> None:
        first = degraded_batch_candidate(
            HyMemoryBatch(account_id=_ACCOUNT, scene="chat", degraded=True, error="boom")
        )
        second = degraded_batch_candidate(
            HyMemoryBatch(account_id=_ACCOUNT, scene="chat", degraded=True, error="boom")
        )
        other = degraded_batch_candidate(
            HyMemoryBatch(account_id=_ACCOUNT, scene="chat", degraded=True, error="other")
        )
        assert first.key == second.key
        assert first.key != other.key
        assert "boom" in first.body
        assert first.trust_class.value == "memory"


class TestObservationPass:
    async def test_every_candidate_is_review_only(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)

        result = await observe_hy_candidates(
            ledger,
            _ACCOUNT,
            _batch(_memory(), _memory(content="另一个偏好", memory_id="mem_2")),
        )

        assert result.ledger_available is True
        assert result.recorded == 2
        assert len(result.promotions) == 2
        for item in result.promotions:
            assert item.decision.disposition is PromotionDisposition.REVIEW
            assert item.decision.reason is PromotionReason.NEEDS_HUMAN_REVIEW
            assert item.decision.verified is True
            assert item.decision.dedupe is DedupeVerdict.NEW
        # D never writes a memory: the target namespace stays empty.
        assert list(await store.asearch(_TARGET_NS)) == []

    async def test_rich_metadata_does_not_earn_a_promote(self) -> None:
        """Sample counts and rates are for the reviewer, not for machine promotion."""
        store = InMemoryStore()
        result = await observe_hy_candidates(
            PromotionLedger(store),
            _ACCOUNT,
            _batch(_memory(metadata={"sample_count": 50, "measured_rate": 0.9})),
        )
        decision = result.promotions[0].decision
        assert decision.disposition is PromotionDisposition.REVIEW
        assert decision.candidate_id.startswith("cand_")

    async def test_a_policy_that_would_promote_hy_memory_is_rejected(self) -> None:
        from backend.context.models import TrustClass

        store = InMemoryStore()
        policy = PromotionPolicy(machine_promotable_classes=(TrustClass.MEMORY,))
        outcome: object = "promoted"
        try:
            outcome = await observe_hy_candidates(
                PromotionLedger(store),
                _ACCOUNT,
                _batch(_memory(metadata={"sample_count": 7, "measured_rate": 0.6})),
                policy=policy,
            )
        except Exception as exc:
            outcome = exc
        assert isinstance(outcome, RuntimeError), outcome
        assert "never promotes" in str(outcome), outcome
        assert (await PromotionLedger(store).records(_ACCOUNT)).records == ()

    async def test_a_degraded_batch_is_refused_and_recorded(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        batch = HyMemoryBatch(
            account_id=_ACCOUNT, scene="working", degraded=True, error="TimeoutError: slow"
        )

        result = await observe_hy_candidates(ledger, _ACCOUNT, batch)

        assert result.refused_batch is True
        assert result.degraded_reason == "TimeoutError: slow"
        assert result.promotions == ()
        assert result.recorded == 1
        assert result.batch_refusal is not None
        assert result.batch_refusal.decision.reason is PromotionReason.SOURCE_DEGRADED
        assert result.batch_refusal.decision.disposition is PromotionDisposition.REFUSE
        records = (await ledger.records(_ACCOUNT)).records
        assert len(records) == 1
        assert records[0].reason == "source_degraded"
        assert records[0].detail == "TimeoutError: slow"

    async def test_a_repeated_degraded_batch_is_one_record(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        batch = HyMemoryBatch(account_id=_ACCOUNT, scene="chat", degraded=True, error="boom")
        await observe_hy_candidates(ledger, _ACCOUNT, batch)
        await observe_hy_candidates(ledger, _ACCOUNT, batch)
        assert len((await ledger.records(_ACCOUNT)).records) == 1

    async def test_an_empty_batch_records_nothing(self) -> None:
        store = InMemoryStore()
        result = await observe_hy_candidates(PromotionLedger(store), _ACCOUNT, _batch())
        assert result.recorded == 0
        assert result.promotions == ()
        assert (await PromotionLedger(store).records(_ACCOUNT)).records == ()

    async def test_dry_run_still_reads_but_records_nothing(self) -> None:
        store = InMemoryStore()
        ledger = PromotionLedger(store)
        result = await observe_hy_candidates(ledger, _ACCOUNT, _batch(_memory()), record=False)
        assert len(result.promotions) == 1
        assert result.recorded == 0
        assert (await ledger.records(_ACCOUNT)).records == ()

    async def test_a_missing_ledger_is_reported(self) -> None:
        result = await observe_hy_candidates(PromotionLedger(None), _ACCOUNT, _batch(_memory()))
        assert result.ledger_available is False
        assert result.recorded == 0
        assert len(result.promotions) == 1

    async def test_another_accounts_batch_is_refused(self) -> None:
        outcome: object = "judged"
        try:
            outcome = await observe_hy_candidates(
                PromotionLedger(InMemoryStore()),
                _ACCOUNT,
                HyMemoryBatch(account_id="other", scene="chat", memories=(_memory(),)),
            )
        except Exception as exc:
            outcome = exc
        assert isinstance(outcome, ValueError), outcome
        assert "another account" in str(outcome), outcome

    async def test_a_blank_account_is_rejected(self) -> None:
        outcome: object = "judged"
        try:
            await observe_hy_candidates(PromotionLedger(InMemoryStore()), "  ", _batch())
        except Exception as exc:
            outcome = exc
        assert isinstance(outcome, ValueError), outcome
        assert "account_id" in str(outcome), outcome

    async def test_the_same_batch_reaches_the_same_decisions(self) -> None:
        first = await observe_hy_candidates(
            PromotionLedger(InMemoryStore()), _ACCOUNT, _batch(_memory())
        )
        second = await observe_hy_candidates(
            PromotionLedger(InMemoryStore()), _ACCOUNT, _batch(_memory())
        )
        assert first.promotions[0].decision == second.promotions[0].decision
