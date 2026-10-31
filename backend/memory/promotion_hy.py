"""hy-memory candidates at the promotion gate (Slice D, 票 5v) — machine REVIEW.

The gap row 7 started from: the SDK's LLM-extracted memories never passed any
gate. This module lets them enter the *same* protocol, but only as ``REVIEW``
candidates — nothing here writes a memory, and ``observe_hy_candidates`` refuses
a policy that would machine-promote them. Human approval (and the target write)
lives in ``promotion_review`` (票 5y), not by re-running ``decide_promotion``.

Honest limits, from ``docs/hy-memory.md`` §9 / ``docs/memory-promotion.md`` §9:

- **The SDK has no trustworthy re-read.** ``search`` failures are swallowed into
  "empty"; ``last_error`` only covers client-build/call failures. So a hy row can
  be *read* but not *independently verified*: its version is content-addressed
  (a hash of the text and its metadata), not a store revision, and the machine
  protocol's ``REVIEW`` path is terminal here.
- **Degradation is not the candidate's fault.** A degraded batch is recorded as
  one ``REFUSE(source_degraded)`` row (keyed by its error), so "could not read"
  is never presented as "nothing there"; a healthy read of zero rows stays empty.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.context.models import RetrievalMode, RetrievalResult, TrustClass
from backend.memory.promotion import (
    ExistingEntry,
    PromotionCandidate,
    PromotionDecision,
    PromotionDisposition,
    PromotionPolicy,
    SourceCheck,
    decide_promotion,
)
from backend.memory.promotion_ledger import LedgerAppendOutcome, PromotionLedger
from backend.memory.promotion_observations import TARGET_NAMESPACE, current_target_entries

__all__ = [
    "HY_SOURCE_PREFIX",
    "HyMemoryBatch",
    "HyObservedPromotion",
    "HyPromotionPass",
    "batch_from_bridge",
    "batch_from_retrieval",
    "candidate_from_hy_memory",
    "degraded_batch_candidate",
    "observe_hy_candidates",
]

HY_SOURCE_PREFIX = "hy-memory://"

#: Metadata keys a producer may use to name the row's version. The SDK does not
#: guarantee any of them; content-addressed fallback below is the documented one.
_VERSION_KEYS = ("source_version", "updated_at", "observed_at", "created_at")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class HyMemoryBatch:
    """One bounded read of an account's hy-memory rows, plus the read verdict.

    ``degraded`` is the read's own fact: it must carry the error summary, and a
    healthy batch must not carry one. That asymmetry is what stops "read failed"
    from being rendered as "no memories".
    """

    account_id: str
    scene: str
    memories: tuple[Mapping[str, Any], ...] = ()
    degraded: bool = False
    error: str = ""
    saturated: bool = False

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise ValueError("hy batch.account_id must be a non-empty string")
        if not self.scene.strip():
            raise ValueError("hy batch.scene must be a non-empty string")
        if self.degraded and not self.error.strip():
            raise ValueError("a degraded hy batch must carry its error summary")
        if not self.degraded and self.error.strip():
            raise ValueError("a healthy hy batch must not carry an error summary")


def batch_from_retrieval(result: RetrievalResult, *, account_id: str) -> HyMemoryBatch:
    """Map ``recall_hy_memory``'s result onto a batch.

    ``DEGRADED`` carries the adapter's error; ``HIT`` carries the normalized rows;
    ``EMPTY`` is a healthy read of zero rows. The mapping lives here so callers
    cannot accidentally read ``EMPTY`` as a failure (or the reverse).
    """
    scene = result.namespace.removeprefix("hy_") or "chat"
    if result.mode is RetrievalMode.DEGRADED:
        return HyMemoryBatch(
            account_id=account_id,
            scene=scene,
            degraded=True,
            error=result.error or "degraded without an error summary",
        )
    memories = tuple(result.raw_items or ()) if result.mode is RetrievalMode.HIT else ()
    return HyMemoryBatch(account_id=account_id, scene=scene, memories=memories)


async def batch_from_bridge(
    bridge: Any, *, account_id: str, scene: str = "chat", limit: int = 50
) -> HyMemoryBatch:
    """Read raw rows through the bridge's management API (not through recall).

    ``list_memories`` returns SDK rows (not semantic hits); a disabled bridge is a
    healthy empty read, and a non-empty ``last_error`` on an empty result is the
    only degradation signal this API exposes.
    """
    if not bridge.enabled:
        return HyMemoryBatch(account_id=account_id, scene=scene, memories=())
    rows = await bridge.list_memories(account_id=account_id, limit=limit)
    last_error = bridge.last_error()
    if not rows and last_error:
        return HyMemoryBatch(
            account_id=account_id, scene=scene, degraded=True, error=str(last_error)
        )
    return HyMemoryBatch(account_id=account_id, scene=scene, memories=tuple(rows))


def _content_of(memory: Mapping[str, Any]) -> str:
    for key in ("content", "statement", "text", "memory"):
        raw = memory.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    raise ValueError("hy-memory row has no readable content; it cannot become a candidate")


def _metadata_of(memory: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = memory.get("metadata")
    return raw if isinstance(raw, Mapping) else {}


def _source_identity(memory: Mapping[str, Any], scene: str, content: str) -> str:
    metadata = _metadata_of(memory)
    explicit = metadata.get("source_ref")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    memory_id = memory.get("memory_id") or memory.get("id") or metadata.get("memory_id")
    if isinstance(memory_id, str) and memory_id.strip():
        return f"{HY_SOURCE_PREFIX}{scene}/{memory_id.strip()}"
    # No id from the engine: the text is the identity. Same text → same candidate,
    # which is exactly what an append-only ledger needs.
    return f"{HY_SOURCE_PREFIX}{scene}/content-{_digest(content)}"


def _source_version(memory: Mapping[str, Any], content: str) -> str:
    metadata = _metadata_of(memory)
    for key in _VERSION_KEYS:
        raw = metadata.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    # Content-addressed fallback: a version of *this text*, not of the store row.
    return f"content-{_digest(content)}"


def _as_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _as_rate(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    rate = float(value)
    return rate if 0.0 <= rate <= 1.0 else None


def candidate_from_hy_memory(
    memory: Mapping[str, Any], *, scene: str = "chat"
) -> PromotionCandidate:
    """Map one hy-memory row onto a protocol candidate (``MEMORY`` trust class).

    The trust class is what makes the protocol return ``REVIEW`` instead of
    ``PROMOTE``; it is not a downgrade the caller can override here.
    """
    content = _content_of(memory)
    source_ref = _source_identity(memory, scene, content)
    source_version = _source_version(memory, content)
    metadata = _metadata_of(memory)
    return PromotionCandidate(
        namespace=TARGET_NAMESPACE,
        key=f"hy:{_digest(source_ref)}",
        body=content,
        trust_class=TrustClass.MEMORY,
        source_ref=source_ref,
        source_version=source_version,
        observed_at=source_version,
        evidence_ids=(f"ev_hy_{_digest(source_ref)}",),
        sample_count=_as_count(metadata.get("sample_count")),
        measured_rate=_as_rate(metadata.get("measured_rate")),
        proposed_by="hy-memory",
    )


def degraded_batch_candidate(batch: HyMemoryBatch) -> PromotionCandidate:
    """One auditable candidate representing a batch that could not be read.

    It is not a memory and never enters the target namespace; it exists so the
    refusal has a ledger row (keyed by the error, so a repeated failure is the
    same row, not a growing pile).
    """
    fingerprint = _digest(f"{batch.scene}\x1f{batch.error}")
    return PromotionCandidate(
        namespace=TARGET_NAMESPACE,
        key=f"hy_batch:{batch.scene}:{fingerprint}",
        body=f"hy-memory 批次降级（scene={batch.scene}）：{batch.error}",
        trust_class=TrustClass.MEMORY,
        source_ref=f"{HY_SOURCE_PREFIX}batch/{batch.scene}/{fingerprint}",
        source_version=f"batch-{fingerprint}",
        observed_at=f"batch-{fingerprint}",
        proposed_by="hy-memory",
    )


@dataclass(frozen=True)
class HyObservedPromotion:
    candidate: PromotionCandidate
    decision: PromotionDecision


@dataclass(frozen=True)
class HyPromotionPass:
    """Result of one hy observation pass.

    ``batch_refusal`` is the ledger row for a degraded read; ``promotions`` holds
    the row decisions (all ``REVIEW`` in this slice). ``recorded`` counts ledger
    writes; a dry run still reads the ledger but records nothing.
    """

    promotions: tuple[HyObservedPromotion, ...]
    batch_refusal: HyObservedPromotion | None
    recorded: int
    ledger_available: bool
    refused_batch: bool
    degraded_reason: str


async def observe_hy_candidates(
    ledger: PromotionLedger,
    account_id: str,
    batch: HyMemoryBatch,
    *,
    policy: PromotionPolicy | None = None,
    record: bool = True,
) -> HyPromotionPass:
    """Decide (and record) hy-memory candidates; never writes a memory.

    A policy that would machine-promote a ``MEMORY`` candidate is rejected: this
    slice has no verification reader for the SDK, so a promote here would be a
    write nobody could attribute.
    """
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("account_id must be a non-empty string")
    if batch.account_id.strip() != account_id:
        raise ValueError(
            f"hy batch belongs to {batch.account_id!r}, not {account_id!r}; refusing "
            "to judge another account's memories"
        )

    existing_entries, ledger_available = await current_target_entries(ledger, account_id)
    existing: list[ExistingEntry] = list(existing_entries)

    if batch.degraded:
        candidate = degraded_batch_candidate(batch)
        decision = decide_promotion(
            candidate,
            source=SourceCheck(present=False, degraded=True),
            existing=(),
            policy=policy,
        )
        recorded = 0
        if record:
            outcome = await ledger.append(account_id, candidate, decision, detail=batch.error)
            if outcome is LedgerAppendOutcome.RECORDED:
                recorded += 1
        return HyPromotionPass(
            promotions=(),
            batch_refusal=HyObservedPromotion(candidate=candidate, decision=decision),
            recorded=recorded,
            ledger_available=ledger_available,
            refused_batch=True,
            degraded_reason=batch.error,
        )

    promotions: list[HyObservedPromotion] = []
    recorded = 0
    for memory in batch.memories:
        candidate = candidate_from_hy_memory(memory, scene=batch.scene)
        decision = decide_promotion(
            candidate,
            # The row itself is the read; the SDK offers no second, trustworthy
            # read. This is why Slice D is terminal at REVIEW.
            source=SourceCheck(
                present=True,
                version=candidate.source_version,
                evidence_found=candidate.evidence_ids,
            ),
            existing=tuple(existing),
            policy=policy,
        )
        if decision.disposition is PromotionDisposition.PROMOTE:
            raise RuntimeError(
                "Slice D observes hy-memory candidates and never promotes them; "
                "a policy that machine-promotes MEMORY belongs to a later slice "
                "with a real verification reader"
            )
        if record:
            outcome = await ledger.append(account_id, candidate, decision)
            if outcome is LedgerAppendOutcome.RECORDED:
                recorded += 1
        promotions.append(HyObservedPromotion(candidate=candidate, decision=decision))

    return HyPromotionPass(
        promotions=tuple(promotions),
        batch_refusal=None,
        recorded=recorded,
        ledger_available=ledger_available,
        refused_batch=False,
        degraded_reason="",
    )
