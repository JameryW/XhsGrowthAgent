"""Observe-only promotion pass over Creative Memory rows (Slice B, 票 5s).

This is the first *real* candidate source wired into the protocol: durable
Creative Memory style rows read through the existing
``CreativeMemoryObservationSource`` seam. The pass decides every candidate and
**records the decision**; it never writes the target namespace and never touches
a prompt (Slice C performs the first promotion, behind the same ledger).

Only ``style`` observations are in scope. Plays and materials are deliberately
left out: their target namespace has not been decided (PRD §9), and inventing a
mapping now would put a product decision behind a test fixture.

Failure semantics (keep them):

- a ledger that is unavailable (no store) does not stop the *decisions* — it is
  a configuration fact, reported as ``ledger_available=False`` and ``recorded=0``;
- a ledger read that hits its limit is **not** a partial view to decide on: the
  pass raises, because the missing record might be the duplicate that makes a
  candidate a no-op;
- a source row without a timestamp raises (it cannot be versioned, so the
  decision would be ``source_unversioned`` against a lie); malformed rows are
  surfaced, not skipped.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.context.models import TrustClass
from backend.creator_agent.models import ContentObservation, ContentObservationKind
from backend.creator_agent.proposals import (
    observation_claim,
    observation_evidence_id,
    observation_source_ref,
)
from backend.memory.promotion import (
    ExistingEntry,
    PromotionCandidate,
    PromotionDecision,
    PromotionDisposition,
    PromotionPolicy,
    SourceCheck,
    decide_promotion,
)
from backend.memory.promotion_ledger import (
    LedgerAppendOutcome,
    PromotionLedger,
    current_entries,
    promotion_id_for,
)

__all__ = [
    "ObservedPromotion",
    "ObservationPass",
    "candidate_from_observation",
    "observe_style_promotions",
    "source_check_from_observation",
]

#: The one target namespace this slice observes. Slice C promotes into it; the
#: other memory namespaces are not promotion targets until the PRD says why.
TARGET_NAMESPACE = "strategy_notes"


@dataclass(frozen=True)
class ObservedPromotion:
    """A candidate and the decision reached for it (one ledger row)."""

    candidate: PromotionCandidate
    decision: PromotionDecision


@dataclass(frozen=True)
class ObservationPass:
    """Result of one observe-only pass.

    ``ledger_available`` and ``recorded`` are separate on purpose: decisions were
    reached either way, but an unavailable store means nothing was written —
    reading that as "recorded zero decisions" would be the same lie the ledger
    exists to prevent.
    """

    promotions: tuple[ObservedPromotion, ...]
    ledger_available: bool
    recorded: int


def candidate_from_observation(observation: ContentObservation) -> PromotionCandidate:
    """Map one durable Creative Memory style row onto a promotion candidate."""
    if observation.kind is not ContentObservationKind.STYLE:
        raise ValueError("Slice B observes Creative Memory styles only")
    if not observation.observed_at.strip():
        raise ValueError(
            "style observation has no timestamp; it cannot be versioned, so it "
            "cannot be judged (use the durable row's last_used)"
        )
    return PromotionCandidate(
        namespace=TARGET_NAMESPACE,
        key=f"style:{observation.source_id}",
        body=observation_claim(observation),
        trust_class=TrustClass.INTERNAL_FACT,
        source_ref=observation_source_ref(observation),
        source_version=observation.observed_at,
        observed_at=observation.observed_at,
        evidence_ids=(observation_evidence_id(observation),),
        sample_count=observation.sample_count,
        measured_rate=observation.measured_rate,
        proposed_by="creative-memory-observation",
    )


def source_check_from_observation(observation: ContentObservation) -> SourceCheck:
    """The observe-only check: the row we just read is the source, at the version
    it reports. Slice C replaces this with an independent re-read before a write."""
    return SourceCheck(
        present=True,
        version=observation.observed_at,
        evidence_found=(observation_evidence_id(observation),),
    )


def _is_style(observation: ContentObservation) -> bool:
    return observation.kind is ContentObservationKind.STYLE


async def current_target_entries(
    ledger: PromotionLedger, account_id: str
) -> tuple[tuple[ExistingEntry, ...], bool]:
    """Current promote records for the target namespace, plus ledger availability.

    Raises when the ledger page is incomplete: the record that did not fit could
    be the duplicate that makes the candidate a no-op, so a partial page must not
    be used to decide. Shared by the observe-only pass and the applying pass so
    the two cannot disagree about what "current" means.
    """
    page = await ledger.records(account_id)
    if page.available and not page.complete:
        raise RuntimeError(
            "promotion ledger page is incomplete; raise the limit before deciding "
            "on it (a missing record can be the duplicate)"
        )
    target_records = [record for record in page.records if record.namespace == TARGET_NAMESPACE]
    return current_entries(target_records), page.available


async def observe_style_promotions(
    ledger: PromotionLedger,
    account_id: str,
    observations: list[ContentObservation],
    *,
    policy: PromotionPolicy | None = None,
    record: bool = True,
) -> ObservationPass:
    """Decide (and record) a promotion verdict for every style observation.

    Existing records are the ledger's *current* entries for the target
    namespace; a promote decided earlier in the same pass is folded back in so a
    second observation of the same key supersedes or duplicates instead of
    forking the ledger.

    ``record=False`` is the dry-run switch: the ledger is still **read** (a
    decision made without its current records would be a different decision),
    but nothing is written and ``recorded`` stays 0.
    """
    existing_entries, ledger_available = await current_target_entries(ledger, account_id)
    existing: list[ExistingEntry] = list(existing_entries)

    promotions: list[ObservedPromotion] = []
    recorded = 0
    for observation in observations:
        if not _is_style(observation):
            continue
        candidate = candidate_from_observation(observation)
        decision = decide_promotion(
            candidate,
            source=source_check_from_observation(observation),
            existing=tuple(existing),
            policy=policy,
        )
        if record:
            outcome = await ledger.append(account_id, candidate, decision)
            if outcome is LedgerAppendOutcome.RECORDED:
                recorded += 1
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
        promotions.append(ObservedPromotion(candidate=candidate, decision=decision))

    return ObservationPass(
        promotions=tuple(promotions),
        ledger_available=ledger_available,
        recorded=recorded,
    )
