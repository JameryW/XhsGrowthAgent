"""Pure projection from Creative Memory observations to Evidence Proposals.

This module is deliberately storage-independent and side-effect free: it turns
already-scoped observations into traceable Evidence candidates plus, where the
observation is strong enough, a draft Preference the creator may adopt.  Nothing
here can reach a Creator Model, a revision, or a Learning Signal, which keeps
ADR-0002's "no model change without creator approval" invariant true by
construction rather than by convention.
"""

from __future__ import annotations

import hashlib

from backend.creator_agent.models import (
    ContentObservation,
    ContentObservationKind,
    Evidence,
    EvidenceProposal,
    EvidenceSource,
    Preference,
    PreferenceStance,
)

# Laplace-style shrinkage prior: an observation with few samples earns little
# confidence no matter how flattering its measured rate looks.
_SAMPLE_PRIOR = 5.0

# A draft preference is only worth the creator's attention when the observation
# is both confident and backed by real reuse.
_DRAFT_MIN_CONFIDENCE = 0.3
_DRAFT_MIN_SAMPLES = 3


def observation_source_ref(observation: ContentObservation) -> str:
    """Stable, traceable reference to the durable row behind an observation."""
    return f"creative-memory://{observation.kind.value}/{observation.source_id}"


def observation_evidence_id(observation: ContentObservation) -> str:
    """Deterministic evidence id so adoption and later dedupe agree."""
    return f"ev_{observation.kind.value}_{observation.source_id}"[:128]


def observation_confidence(observation: ContentObservation) -> float:
    """Measured rate shrunk by sample size, clamped and rounded for reporting.

    A missing sample count shrinks hard (``1 / (1 + prior)``), so a lone
    anecdote cannot masquerade as a pattern.
    """
    shrinkage = observation.sample_count / (observation.sample_count + _SAMPLE_PRIOR)
    raw = observation.measured_rate * shrinkage
    return round(min(max(raw, 0.0), 1.0), 3)


def observation_claim(observation: ContentObservation) -> str:
    """Render the measured values only, with no wording the data cannot support."""
    description = observation.description
    rate = f"{observation.measured_rate:.3f}"
    samples = observation.sample_count
    if observation.kind is ContentObservationKind.STYLE:
        return f"风格「{description}」历史互动率 {rate}（样本 {samples}）"
    if observation.kind is ContentObservationKind.PLAY:
        return f"打法「{description}」平均互动率 {rate}（验证 {samples} 次）"
    return f"素材「{description}」复用效果 {rate}（复用 {samples} 次）"


def _proposal_id(observation: ContentObservation) -> str:
    digest = hashlib.sha256(
        f"{observation.kind.value}|{observation.source_id}".encode()
    ).hexdigest()
    return f"prop_{digest[:16]}"


def _draft_preference(
    observation: ContentObservation, evidence_id: str, confidence: float
) -> Preference:
    return Preference(
        preference_id=f"pref_{observation.kind.value}_{observation.source_id}"[:128],
        label=observation.description,
        stance=PreferenceStance.PREFER,
        strength=confidence,
        rationale=observation_claim(observation),
        evidence_ids=[evidence_id],
    )


def build_evidence_proposals(
    observations: list[ContentObservation],
    *,
    cited_source_refs: set[str] | frozenset[str] = frozenset(),
    min_confidence: float | None = None,
    limit: int = 50,
) -> list[EvidenceProposal]:
    """Project observations into stable, deduplicated, read-only proposals.

    Ordering is confidence descending with ``kind``/``source_id`` as tie-breaker,
    so repeated calls over the same data return byte-identical results.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if min_confidence is not None and not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")

    seen: set[str] = set()
    proposals: list[tuple[float, EvidenceProposal]] = []
    for observation in observations:
        source_ref = observation_source_ref(observation)
        evidence_id = observation_evidence_id(observation)
        if source_ref in cited_source_refs or source_ref in seen:
            continue
        confidence = observation_confidence(observation)
        if min_confidence is not None and confidence < min_confidence:
            continue
        seen.add(source_ref)
        evidence = Evidence(
            evidence_id=evidence_id,
            source_kind=EvidenceSource.CREATOR_CONTENT,
            source_ref=source_ref,
            claim=observation_claim(observation),
            observed_at=observation.observed_at,
            confidence=confidence,
        )
        draft = (
            _draft_preference(observation, evidence_id, confidence)
            if confidence >= _DRAFT_MIN_CONFIDENCE
            and observation.sample_count >= _DRAFT_MIN_SAMPLES
            else None
        )
        proposals.append(
            (
                confidence,
                EvidenceProposal(
                    proposal_id=_proposal_id(observation),
                    evidence=evidence,
                    draft_preference=draft,
                ),
            )
        )

    proposals.sort(
        key=lambda item: (
            -item[0],
            item[1].evidence.source_ref,
        )
    )
    return [proposal for _, proposal in proposals[:limit]]


__all__ = [
    "build_evidence_proposals",
    "observation_claim",
    "observation_confidence",
    "observation_evidence_id",
    "observation_source_ref",
]
