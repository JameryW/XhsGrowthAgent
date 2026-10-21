"""Apply promotions: the first write path of the pipeline (Slice C, 票 5u).

Slice B decided and recorded; this module is where a decision finally changes
what a prompt can recall. The order is deliberate and documented in
``docs/memory-promotion.md`` §8:

1. read the ledger's current entries (a partial page is refused);
2. re-read the durable source (verification must not be the scan confirming
   itself);
3. decide with the Slice A protocol;
4. for ``PROMOTE``: append the ledger record **first**, then write the target
   namespace. A crash between the two leaves a ledger row whose target is
   missing — readable as "pending", never guessed as "written" (the alternative
   order would write memories nobody can attribute);
5. for ``REFUSE`` / ``REVIEW``: append the record, write nothing.

``dry_run=True`` still reads the ledger (current records change the decision) but
writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.creator_agent.models import ContentObservation, ContentObservationKind
from backend.memory.promotion import (
    ExistingEntry,
    PromotionCandidate,
    PromotionDecision,
    PromotionDisposition,
    PromotionPolicy,
    decide_promotion,
)
from backend.memory.promotion_ledger import (
    LedgerAppendOutcome,
    PromotionLedger,
    promotion_id_for,
)
from backend.memory.promotion_observations import (
    TARGET_NAMESPACE,
    candidate_from_observation,
    current_target_entries,
)
from backend.memory.promotion_source import CreativeMemoryPromotionSource

__all__ = [
    "AppliedPromotion",
    "PromotionApplication",
    "promote_style_observations",
    "write_promoted_memory",
]

_PROMOTED_BODY_KEY = "note"


@dataclass(frozen=True)
class AppliedPromotion:
    """One candidate, its verdict, and whether the target namespace was written."""

    candidate: PromotionCandidate
    decision: PromotionDecision
    applied: bool


@dataclass(frozen=True)
class PromotionApplication:
    """Result of one applying pass.

    ``recorded`` counts ledger rows written; ``applied`` counts target-namespace
    writes. They are separate facts: a promote can be recorded and not written
    (dry run, or a crash between the two steps).
    """

    promotions: tuple[AppliedPromotion, ...]
    recorded: int
    applied: int
    ledger_available: bool


async def write_promoted_memory(
    store: Any,
    account_id: str,
    candidate: PromotionCandidate,
    decision: PromotionDecision,
    *,
    recorded_at: str | None = None,
) -> str:
    """Write one verified memory into ``strategy_notes`` and return its id.

    The value carries the provenance the Context Compiler can render later
    (``verified`` / ``source_version`` / ``ttl_seconds`` / explicit
    ``trust_class``), keyed by the candidate's deterministic key so a supersede
    replaces the same row instead of accumulating near-copies.
    """
    promotion_id = promotion_id_for(decision, source_version=candidate.source_version)
    value: dict[str, Any] = {
        _PROMOTED_BODY_KEY: candidate.body,
        "promotion_id": promotion_id,
        "source_ref": candidate.source_ref,
        "source_version": candidate.source_version,
        "verified": decision.verified,
        "trust_class": candidate.trust_class.value,
        "ttl_seconds": candidate.ttl_seconds,
        "promoted_at": recorded_at or datetime.now(UTC).isoformat(),
        "policy_version": decision.policy_version,
        "decided_by": decision.decided_by,
    }
    await store.aput(("accounts", account_id, TARGET_NAMESPACE), key=candidate.key, value=value)
    return promotion_id


async def promote_style_observations(
    ledger: PromotionLedger,
    store: Any,
    account_id: str,
    observations: list[ContentObservation],
    *,
    policy: PromotionPolicy | None = None,
    source: CreativeMemoryPromotionSource | None = None,
    dry_run: bool = False,
    recorded_at: str | None = None,
) -> PromotionApplication:
    """Verify, decide and (unless dry-run) apply promotion for style observations.

    The source check is an **independent re-read**; a stale scan is not a
    promotion. Every verdict is recorded (the ledger is the audit trail); only
    ``PROMOTE`` reaches the target namespace, and only after its ledger row was
    written.
    """
    account_id = (account_id or "").strip()
    if not account_id:
        raise ValueError("account_id must be a non-empty string")
    verifier = source if source is not None else CreativeMemoryPromotionSource()

    existing_entries, ledger_available = await current_target_entries(ledger, account_id)
    existing: list[ExistingEntry] = list(existing_entries)
    promotions: list[AppliedPromotion] = []
    recorded = 0
    applied = 0
    for observation in observations:
        if observation.kind is not ContentObservationKind.STYLE:
            continue
        candidate = candidate_from_observation(observation)
        check = await verifier.source_check(account_id, observation)
        decision = decide_promotion(
            candidate,
            source=check,
            existing=tuple(existing),
            policy=policy,
        )
        was_applied = False
        if not dry_run:
            outcome = await ledger.append(account_id, candidate, decision)
            if outcome is LedgerAppendOutcome.RECORDED:
                recorded += 1
                if decision.disposition is PromotionDisposition.PROMOTE:
                    # Ledger first, target second: a crash in between is a
                    # pending row, not an unattributable memory.
                    await write_promoted_memory(
                        store, account_id, candidate, decision, recorded_at=recorded_at
                    )
                    applied += 1
                    was_applied = True
        if decision.disposition is PromotionDisposition.PROMOTE:
            existing.append(
                ExistingEntry(
                    key=candidate.key,
                    source_ref=candidate.source_ref,
                    source_version=candidate.source_version,
                    promotion_id=promotion_id_for(
                        decision, source_version=candidate.source_version
                    ),
                )
            )
        promotions.append(
            AppliedPromotion(candidate=candidate, decision=decision, applied=was_applied)
        )

    return PromotionApplication(
        promotions=tuple(promotions),
        recorded=recorded,
        applied=applied,
        ledger_available=ledger_available,
    )
