"""Memory Promotion Pipeline — the decision protocol (Slice A, 票 5r).

``docs/agent-os-upgrade-2026q4.md`` §3 row 7 records the gap this module starts
to close: hy-memory has an LLM extractor and an internal reconciler, but the
repository has no explicit "verify source → dedupe → promote" pipeline, so a
memory can reach a prompt without anyone deciding it may. Design PRD:
``.trellis/tasks/10-21-memory-promotion-pipeline/prd.md``.

This slice is **the protocol only** — a pure decision function and the value
objects it speaks. It performs no I/O, keeps no state, and cannot write a
memory or a prompt. That is deliberate and follows the same shape as
``backend.state.progress`` (P0-A): observe, price the decision, wire it later.

Design constraints (keep them when extending):

1. **The repository owns the gate, not the SDK.** An extractor's output is a
   *candidate*; whether it may become a trusted memory is decided from facts the
   repository can re-derive. ``SourceCheck`` is that input: the caller has
   already read the source, and this function only judges what was read.
2. **Read failures are not refusals.** A reader that raises propagates (no
   fallbacks here); ``SourceCheck.present is False`` means "read it, it is not
   there". ``degraded`` means "the reader itself is down" — the batch is judged
   without evaluating dedupe, because absence of a read is not evidence of
   absence.
3. **Only measured internal facts auto-promote.** Everything else is a human
   review (ADR-0002's review-before-learning invariant), not a silent adopt.
4. **Deterministic.** Same candidate + same checks + same policy ⇒ byte-equal
   decision. No clocks, no randomness, no iteration-order dependence.
5. **A malformed candidate is a bug, not a refusal.** Contract violations raise
   ``ValueError``; closed ``PromotionReason`` values are reserved for decisions
   the pipeline actually reached.

Slice status: A (this module + tests) **landed**; B (append-only ledger), C
(first ``internal_fact`` promotion), D (hy-memory candidates, review-only) are
still to come and are listed in the PRD §6.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from backend.context.models import TrustClass

__all__ = [
    "DEFAULT_PROMOTION_MIN_SAMPLES",
    "DEFAULT_PROMOTION_POLICY_VERSION",
    "DedupeVerdict",
    "ExistingEntry",
    "PromotionCandidate",
    "PromotionDecision",
    "PromotionDisposition",
    "PromotionPolicy",
    "PromotionReason",
    "SourceCheck",
    "candidate_id_for",
    "decide_promotion",
    "default_promotion_policy",
]

#: Git-pinned authority for machine ``policy_version`` (票 5aa / PRD §9 Q6).
#: Audit follows the commit that last changed this constant — not env / remote
#: config. Bump when a change alters machine-decision semantics
#: (``min_samples``, ``machine_promotable_classes``, or ``allowed_namespaces``);
#: docs/comment-only edits do not bump. Human-review rows reuse the REVIEW
#: row's ``policy_version`` and never re-mint from this constant.
DEFAULT_PROMOTION_POLICY_VERSION = "v1"

#: Machine-promote sample floor (票 5ab / PRD §9 Q4). Kept equal to
#: ``CreativeMemory.MIN_SAMPLES`` — both answer "how many measured samples
#: count". Changing this value alters decision semantics and **must** bump
#: ``DEFAULT_PROMOTION_POLICY_VERSION``. No cooldown window in MVP (dedupe /
#: supersede already handle same-key updates).
DEFAULT_PROMOTION_MIN_SAMPLES = 5


class PromotionDisposition(StrEnum):
    """What the pipeline decided to do with one candidate."""

    PROMOTE = "promote"
    """It may be written to its target namespace (Slice C performs the write)."""

    REVIEW = "review"
    """A human must decide; the pipeline refuses to guess (ADR-0002)."""

    REFUSE = "refuse"
    """It was judged and it may not become a memory (yet)."""


class PromotionReason(StrEnum):
    """Closed vocabulary of *why*. Every member is reachable (tests enumerate)."""

    # ── refusals ────────────────────────────────────────────────────────────
    SOURCE_MISSING = "source_missing"
    """The reader answered: there is no such row."""

    SOURCE_UNVERSIONED = "source_unversioned"
    """Either side has no version, so "this claim is current" cannot be checked."""

    SOURCE_DEGRADED = "source_degraded"
    """The reader itself was degraded; nothing about the candidate was judged."""

    TTL_EXPIRED = "ttl_expired"
    """The candidate's time-to-live is over; re-promotion must go through the gate."""

    EVIDENCE_MISSING = "evidence_missing"
    """At least one cited evidence id does not resolve."""

    INSUFFICIENT_SAMPLES = "insufficient_samples"
    """Measured candidates below the policy's sample floor are not patterns yet."""

    DUPLICATE = "duplicate"
    """The same key already carries this exact source version."""

    POLICY_BLOCKED = "policy_blocked"
    """The policy does not allow this namespace at all."""

    # ── reviews ─────────────────────────────────────────────────────────────
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    """The candidate is legible but its class (or an ambiguous key) needs a person."""

    SOURCE_STALE = "source_stale"
    """The candidate does not carry the source's current version."""

    # ── promotions ──────────────────────────────────────────────────────────
    VERIFIED_INTERNAL_FACT = "verified_internal_fact"
    """Measured, version-matched, evidence-backed, new key: auto-promotable."""

    SUPERSEDES_OLDER = "supersedes_older"
    """Same key and source family, newer version: replaces the stored record."""

    # ── human review outcomes (票 5y; never produced by decide_promotion) ──
    HUMAN_APPROVED = "human_approved"
    """A person approved a REVIEW row; the write path appends a human PROMOTE."""

    HUMAN_DISMISSED = "human_dismissed"
    """A person dismissed a REVIEW row; the write path appends a human REFUSE."""


class DedupeVerdict(StrEnum):
    """How the candidate relates to what the target namespace already holds."""

    NEW = "new"
    SUPERSEDES = "supersedes"
    DUPLICATE = "duplicate"
    NEEDS_REVIEW = "needs_review"
    NOT_EVALUATED = "not_evaluated"
    """Nothing was compared: the refusal happened before the target was read.

    Kept separate from ``NEW`` on purpose — "we did not look" and "we looked and
    it is new" are different facts, and the ledger must not read one as the other.
    """


@dataclass(frozen=True)
class PromotionCandidate:
    """One memory the pipeline is asked to judge.

    ``source_ref`` is the traceable identity of the row behind the claim
    (``creative-memory://<kind>/<id>``, ``content-history://<post_id>``, …).
    ``source_version`` is the source row's version (ISO-8601 timestamp or a row
    version); the pipeline compares it lexicographically, so producers must use a
    sortable spelling. No clock lives here: ``observed_at`` is data.
    """

    namespace: str
    key: str
    body: str
    trust_class: TrustClass
    source_ref: str
    source_version: str
    observed_at: str
    evidence_ids: tuple[str, ...] = ()
    sample_count: int = 0
    measured_rate: float | None = None
    ttl_seconds: int | None = None
    proposed_by: str = ""

    def __post_init__(self) -> None:
        for name in ("namespace", "key", "body", "source_ref", "observed_at"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"candidate.{name} must be a non-empty string")
        if not isinstance(self.trust_class, TrustClass):
            raise ValueError("candidate.trust_class must be a TrustClass member")
        if self.sample_count < 0:
            raise ValueError("candidate.sample_count must be >= 0")
        if self.measured_rate is not None and not 0.0 <= self.measured_rate <= 1.0:
            raise ValueError("candidate.measured_rate must be within [0, 1]")
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError("candidate.ttl_seconds must be > 0 when given")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("candidate.evidence_ids must not repeat")

    @property
    def id(self) -> str:
        return candidate_id_for(self.namespace, self.source_ref)


def candidate_id_for(namespace: str, source_ref: str) -> str:
    """Deterministic id so the same candidate is one candidate across runs.

    A random id would let the same claim be promoted twice; the ledger (Slice B)
    is append-only and can refuse a repeated id, but only if the id is derived
    from what identifies the candidate rather than from when it was seen.
    """
    digest = hashlib.sha256(f"{namespace}\x1f{source_ref}".encode()).hexdigest()
    return f"cand_{digest[:16]}"


@dataclass(frozen=True)
class SourceCheck:
    """Facts about the candidate's source, resolved by the caller's reader.

    The reader is expected to raise on a read failure (no fallback in the
    pipeline); an answered "no such row" is ``present=False``. ``evidence_found``
    / ``evidence_missing`` are the reader's per-id answers for
    ``PromotionCandidate.evidence_ids`` and are not re-derived here.
    """

    present: bool
    version: str = ""
    evidence_found: tuple[str, ...] = ()
    evidence_missing: tuple[str, ...] = ()
    degraded: bool = False
    ttl_expired: bool = False

    def __post_init__(self) -> None:
        if self.present and not self.degraded and not self.version.strip():
            raise ValueError("a present source must carry its version")
        if len(self.evidence_missing) != len(set(self.evidence_missing)):
            raise ValueError("evidence_missing must not repeat")


@dataclass(frozen=True)
class ExistingEntry:
    """What the target key currently holds (a promotion record, not a raw row)."""

    key: str
    source_ref: str
    source_version: str
    promotion_id: str


@dataclass(frozen=True)
class PromotionPolicy:
    """The thresholds a deployment may tune; defaults mirror the PRD.

    ``min_samples`` defaults to ``DEFAULT_PROMOTION_MIN_SAMPLES`` and must stay
    equal to ``CreativeMemory.MIN_SAMPLES`` (票 5ab). Draft-proposal floors
    (``_DRAFT_MIN_SAMPLES``) are a different gate and are not this constant.

    ``policy_version`` defaults to ``DEFAULT_PROMOTION_POLICY_VERSION``. Prefer
    ``default_promotion_policy()`` over constructing a bare ``PromotionPolicy()``
    when the intent is "use the Git-pinned deployment default".
    """

    min_samples: int = DEFAULT_PROMOTION_MIN_SAMPLES
    machine_promotable_classes: tuple[TrustClass, ...] = (TrustClass.INTERNAL_FACT,)
    allowed_namespaces: tuple[str, ...] | None = None
    policy_version: str = DEFAULT_PROMOTION_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.min_samples < 1:
            raise ValueError("policy.min_samples must be >= 1")
        if not self.policy_version.strip():
            raise ValueError("policy.policy_version must be a non-empty string")
        for trust_class in self.machine_promotable_classes:
            if not isinstance(trust_class, TrustClass):
                raise ValueError("machine_promotable_classes must hold TrustClass members")


def default_promotion_policy() -> PromotionPolicy:
    """Return the Git-pinned default policy (票 5aa / 5ab).

    Reads ``DEFAULT_PROMOTION_POLICY_VERSION`` and
    ``DEFAULT_PROMOTION_MIN_SAMPLES`` at call time so tests can monkeypatch
    either constant and observe the change on the next decision. Do not
    scatter hard-coded policy_version / min_samples literals at call sites —
    bump the module constants instead (and bump policy_version when
    min_samples semantics change).
    """
    return PromotionPolicy(
        min_samples=DEFAULT_PROMOTION_MIN_SAMPLES,
        policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
    )


@dataclass(frozen=True)
class PromotionDecision:
    """The judged outcome. One candidate ⇒ one decision (the ledger's unit)."""

    candidate_id: str
    disposition: PromotionDisposition
    reason: PromotionReason
    dedupe: DedupeVerdict
    verified: bool
    supersedes: tuple[str, ...]
    decided_by: str
    policy_version: str
    """True only for checks this pass actually made: source read and present,
    version matched, cited evidence resolved. Never means "the claim is true"."""

    def to_dict(self) -> dict[str, object]:
        """Stable, JSON-friendly shape (the ledger stores this, not the object)."""
        return {
            "candidate_id": self.candidate_id,
            "disposition": self.disposition.value,
            "reason": self.reason.value,
            "dedupe": self.dedupe.value,
            "verified": self.verified,
            "supersedes": list(self.supersedes),
            "decided_by": self.decided_by,
            "policy_version": self.policy_version,
        }


def _decision(
    candidate: PromotionCandidate,
    *,
    disposition: PromotionDisposition,
    reason: PromotionReason,
    dedupe: DedupeVerdict,
    verified: bool,
    supersedes: tuple[str, ...] = (),
    policy: PromotionPolicy,
) -> PromotionDecision:
    return PromotionDecision(
        candidate_id=candidate.id,
        disposition=disposition,
        reason=reason,
        dedupe=dedupe,
        verified=verified,
        supersedes=supersedes,
        decided_by="machine",
        policy_version=policy.policy_version,
    )


def _dedupe(
    candidate: PromotionCandidate, existing: Sequence[ExistingEntry]
) -> tuple[DedupeVerdict, tuple[str, ...], bool]:
    """Compare against the target namespace's current records.

    Returns ``(verdict, superseded promotion ids, candidate_is_older)``. Only
    exact key/source identity is compared here: semantic near-duplicates are a
    reviewer hint (needs an embedding and a judgement), not something this pure
    function can settle.
    """
    on_key = [entry for entry in existing if entry.key == candidate.key]
    same_source = [entry for entry in on_key if entry.source_ref == candidate.source_ref]
    if same_source:
        newest = max(entry.source_version for entry in same_source)
        ids = tuple(sorted(entry.promotion_id for entry in same_source))
        if candidate.source_version == newest:
            return DedupeVerdict.DUPLICATE, (), False
        if candidate.source_version < newest:
            return DedupeVerdict.DUPLICATE, (), True
        return DedupeVerdict.SUPERSEDES, ids, False
    if on_key:
        # Two different sources competing for one key: a person decides which
        # claim is the current one, not a version comparison.
        return DedupeVerdict.NEEDS_REVIEW, (), False
    if any(entry.source_ref == candidate.source_ref for entry in existing):
        # The same source already promoted something under another key; either
        # the source is being split deliberately or this is a duplicate in
        # disguise. Both need a person.
        return DedupeVerdict.NEEDS_REVIEW, (), False
    return DedupeVerdict.NEW, (), False


def decide_promotion(
    candidate: PromotionCandidate,
    *,
    source: SourceCheck,
    existing: Sequence[ExistingEntry] = (),
    policy: PromotionPolicy | None = None,
) -> PromotionDecision:
    """Judge one candidate. Pure and deterministic.

    Precedence (first match wins; it is part of the contract because a decision
    must not depend on which check a caller happened to run first):

    1. reader degraded → ``REFUSE(source_degraded)``, dedupe untouched;
    2. candidate has no version → ``REFUSE(source_unversioned)``;
    3. source absent → ``REFUSE(source_missing)``;
    4. TTL expired → ``REFUSE(ttl_expired)``;
    5. any cited evidence unresolved → ``REFUSE(evidence_missing)``;
    6. namespace not allowed by policy → ``REFUSE(policy_blocked)``;
    7. source version ≠ candidate version → ``REVIEW(source_stale)``;
    8. trust class not machine-promotable → ``REVIEW(needs_human_review)``
       (the dedupe verdict still travels, for the reviewer);
    9. measured class below the sample floor → ``REFUSE(insufficient_samples)``;
    10. dedupe on the target key: newer version of the same source family →
        ``PROMOTE(supersedes_older)``; equal version → ``REFUSE(duplicate)``;
        older version → ``REVIEW(source_stale)``; competing source / same source
        under another key → ``REVIEW(needs_human_review)``;
    11. otherwise → ``PROMOTE(verified_internal_fact)``.

    A refused candidate never carries ``verified=True``: the checks that make up
    "verified" (read, version match, evidence) may not all have been made.
    ``SourceCheck`` guarantees a present, non-degraded source carries a version,
    which is why the unversioned check only has to look at the candidate.
    """
    if policy is None:
        policy = default_promotion_policy()

    if source.degraded:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REFUSE,
            reason=PromotionReason.SOURCE_DEGRADED,
            dedupe=DedupeVerdict.NOT_EVALUATED,
            verified=False,
            policy=policy,
        )
    if not candidate.source_version.strip():
        return _decision(
            candidate,
            disposition=PromotionDisposition.REFUSE,
            reason=PromotionReason.SOURCE_UNVERSIONED,
            dedupe=DedupeVerdict.NOT_EVALUATED,
            verified=False,
            policy=policy,
        )
    if not source.present:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REFUSE,
            reason=PromotionReason.SOURCE_MISSING,
            dedupe=DedupeVerdict.NOT_EVALUATED,
            verified=False,
            policy=policy,
        )
    if source.ttl_expired:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REFUSE,
            reason=PromotionReason.TTL_EXPIRED,
            dedupe=DedupeVerdict.NOT_EVALUATED,
            verified=False,
            policy=policy,
        )
    if source.evidence_missing:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REFUSE,
            reason=PromotionReason.EVIDENCE_MISSING,
            dedupe=DedupeVerdict.NOT_EVALUATED,
            verified=False,
            policy=policy,
        )
    if policy.allowed_namespaces is not None and candidate.namespace not in (
        policy.allowed_namespaces
    ):
        return _decision(
            candidate,
            disposition=PromotionDisposition.REFUSE,
            reason=PromotionReason.POLICY_BLOCKED,
            dedupe=DedupeVerdict.NOT_EVALUATED,
            verified=False,
            policy=policy,
        )
    if source.version != candidate.source_version:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REVIEW,
            reason=PromotionReason.SOURCE_STALE,
            dedupe=DedupeVerdict.NOT_EVALUATED,
            verified=False,
            policy=policy,
        )

    verdict, superseded, older = _dedupe(candidate, existing)
    if candidate.trust_class not in policy.machine_promotable_classes:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REVIEW,
            reason=PromotionReason.NEEDS_HUMAN_REVIEW,
            dedupe=verdict,
            verified=True,
            policy=policy,
        )
    if candidate.sample_count < policy.min_samples or candidate.measured_rate is None:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REFUSE,
            reason=PromotionReason.INSUFFICIENT_SAMPLES,
            dedupe=verdict,
            verified=True,
            policy=policy,
        )
    if older:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REVIEW,
            reason=PromotionReason.SOURCE_STALE,
            dedupe=verdict,
            verified=True,
            policy=policy,
        )
    if verdict is DedupeVerdict.DUPLICATE:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REFUSE,
            reason=PromotionReason.DUPLICATE,
            dedupe=verdict,
            verified=True,
            policy=policy,
        )
    if verdict is DedupeVerdict.SUPERSEDES:
        return _decision(
            candidate,
            disposition=PromotionDisposition.PROMOTE,
            reason=PromotionReason.SUPERSEDES_OLDER,
            dedupe=verdict,
            verified=True,
            supersedes=superseded,
            policy=policy,
        )
    if verdict is DedupeVerdict.NEEDS_REVIEW:
        return _decision(
            candidate,
            disposition=PromotionDisposition.REVIEW,
            reason=PromotionReason.NEEDS_HUMAN_REVIEW,
            dedupe=verdict,
            verified=True,
            policy=policy,
        )
    return _decision(
        candidate,
        disposition=PromotionDisposition.PROMOTE,
        reason=PromotionReason.VERIFIED_INTERNAL_FACT,
        dedupe=verdict,
        verified=True,
        policy=policy,
    )
