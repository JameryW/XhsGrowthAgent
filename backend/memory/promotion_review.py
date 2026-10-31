"""Human review write path for Memory Promotion REVIEW rows (票 5y / PRD §9 Q1).

Slice D left hy-memory (and other non-machine-promotable) candidates at
``REVIEW`` with no write path — "human approval before write" was enforced only
by the absence of an endpoint. This module is that endpoint's domain core:

- locate an open ``REVIEW`` ledger row by ``promotion_id``;
- refuse a second human close (conflict) or a missing/cross-account id (missing);
- construct a **human-authored** ``PromotionDecision`` (never re-run
  ``decide_promotion`` — a ``MEMORY`` candidate cannot machine-flip to PROMOTE);
- ``approved``: ledger append of human ``PROMOTE`` **first**, then
  ``write_promoted_memory`` (Slice C crash semantics);
- ``dismissed``: ledger append of human ``REFUSE`` only.

The old REVIEW row is never mutated. Closure is linked via structured
``detail`` (``reviewed_promotion_id`` + optional ``review_note``).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from backend.context.models import TrustClass
from backend.creator_agent.models import (
    ContentObservation,
    ContentObservationKind,
    CreatorReviewDisposition,
)
from backend.memory.promotion import (
    DedupeVerdict,
    PromotionCandidate,
    PromotionDecision,
    PromotionDisposition,
    PromotionReason,
)
from backend.memory.promotion_apply import write_promoted_memory
from backend.memory.promotion_ledger import (
    LedgerAppendOutcome,
    PromotionLedger,
    PromotionRecord,
    promotion_id_for,
)
from backend.memory.promotion_observations import candidate_from_observation
from backend.memory.promotion_source import StyleRowReader, read_style_row
from backend.memory.promotion_ttl import resolve_promotion_ttl

__all__ = [
    "HUMAN_DECIDED_BY",
    "PromotionReviewBodyUnavailableError",
    "PromotionReviewConflictError",
    "PromotionReviewMissingError",
    "PromotionReviewResult",
    "PromotionStoreUnavailableError",
    "encode_review_detail",
    "parse_review_detail",
    "review_promotion",
]

HUMAN_DECIDED_BY = "human"

_CREATIVE_STYLE_PREFIX = "creative-memory://style/"

CandidateRebuilder = Callable[[PromotionRecord, str], Awaitable[PromotionCandidate]]


class PromotionReviewMissingError(Exception):
    """No open REVIEW row for this id in the account's ledger."""

    def __init__(self, promotion_id: str) -> None:
        self.promotion_id = promotion_id
        super().__init__(f"memory promotion review {promotion_id!r} not found")


class PromotionReviewConflictError(Exception):
    """The REVIEW row was already closed by a human decision."""

    def __init__(self, promotion_id: str, existing_disposition: str) -> None:
        self.promotion_id = promotion_id
        self.existing_disposition = existing_disposition
        super().__init__(
            f"memory promotion review {promotion_id!r} already closed "
            f"with disposition {existing_disposition!r}"
        )


class PromotionStoreUnavailableError(Exception):
    """Write path requires a configured memory store (GET reports available=False)."""

    def __init__(self) -> None:
        super().__init__("memory promotion store is unavailable")


class PromotionReviewBodyUnavailableError(Exception):
    """Candidate body cannot be reconstructed; refusing an empty memory write."""

    def __init__(self, promotion_id: str, reason: str) -> None:
        self.promotion_id = promotion_id
        self.reason = reason
        super().__init__(f"cannot rebuild candidate body for promotion {promotion_id!r}: {reason}")


@dataclass(frozen=True)
class PromotionReviewResult:
    """Outcome of one human review: the new ledger row and whether target was written."""

    review_record: PromotionRecord
    closure_record: PromotionRecord
    applied: bool
    disposition: CreatorReviewDisposition


def encode_review_detail(*, reviewed_promotion_id: str, review_note: str = "") -> str:
    """Structured detail so conflict detection and tests can parse the link."""
    payload = {
        "reviewed_promotion_id": reviewed_promotion_id,
        "review_note": review_note,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def parse_review_detail(detail: str) -> dict[str, str]:
    """Return ``reviewed_promotion_id`` / ``review_note`` when detail is ours."""
    raw = (detail or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    reviewed = parsed.get("reviewed_promotion_id")
    note = parsed.get("review_note")
    out: dict[str, str] = {}
    if isinstance(reviewed, str) and reviewed.strip():
        out["reviewed_promotion_id"] = reviewed.strip()
    if isinstance(note, str):
        out["review_note"] = note
    return out


def _human_closure_of(
    records: tuple[PromotionRecord, ...], review_promotion_id: str
) -> PromotionRecord | None:
    """Find a human PROMOTE/REFUSE that closed this REVIEW id, if any."""
    for record in records:
        if record.decided_by != HUMAN_DECIDED_BY:
            continue
        if record.disposition not in (
            PromotionDisposition.PROMOTE.value,
            PromotionDisposition.REFUSE.value,
        ):
            continue
        meta = parse_review_detail(record.detail)
        if meta.get("reviewed_promotion_id") == review_promotion_id:
            return record
    return None


def _style_id_from_ref(source_ref: str) -> str | None:
    if not source_ref.startswith(_CREATIVE_STYLE_PREFIX):
        return None
    style_id = source_ref[len(_CREATIVE_STYLE_PREFIX) :].strip()
    return style_id or None


def _observation_from_style_row(style_id: str, row: dict[str, Any]) -> ContentObservation:
    tone = str(row.get("tone") or "").strip()
    visual = str(row.get("visual_style") or "").strip()
    parts = [part for part in (tone, visual) if part]
    description = "/".join(parts) if parts else style_id
    rate_raw = row.get("engagement_rate")
    if isinstance(rate_raw, bool) or not isinstance(rate_raw, (int, float)):
        raise ValueError(f"style row {style_id!r} has no usable engagement_rate")
    measured = min(max(float(rate_raw), 0.0), 1.0)
    samples_raw = row.get("sample_count")
    samples = (
        max(int(samples_raw), 0)
        if isinstance(samples_raw, (int, float)) and not isinstance(samples_raw, bool)
        else 0
    )
    observed_at = str(row.get("last_used") or "").strip()
    if not observed_at:
        raise ValueError(f"style row {style_id!r} has no last_used")
    return ContentObservation(
        kind=ContentObservationKind.STYLE,
        source_id=style_id,
        description=description[:300],
        measured_rate=measured,
        sample_count=samples,
        observed_at=observed_at,
    )


def _candidate_from_ledger_body(record: PromotionRecord) -> PromotionCandidate:
    """Rebuild from the body snapshotted on the REVIEW row (hy / no re-read)."""
    body = (record.body or "").strip()
    if not body:
        raise PromotionReviewBodyUnavailableError(
            record.promotion_id,
            f"no body snapshot on REVIEW row and no re-read for {record.source_ref!r}",
        )
    trust = (
        TrustClass.INTERNAL_FACT
        if record.source_ref.startswith(_CREATIVE_STYLE_PREFIX)
        else TrustClass.MEMORY
    )
    return PromotionCandidate(
        namespace=record.namespace,
        key=record.key,
        body=body,
        trust_class=trust,
        source_ref=record.source_ref,
        source_version=record.source_version,
        observed_at=record.source_version,
        # Same resolve entry as observe/hy — human approve must not invent a
        # different TTL than the table (票 5z single resolve point).
        ttl_seconds=resolve_promotion_ttl(record.namespace),
        proposed_by="human-review",
    )


def _make_default_rebuilder(reader: StyleRowReader) -> CandidateRebuilder:
    async def _rebuild(record: PromotionRecord, account_id: str) -> PromotionCandidate:
        style_id = _style_id_from_ref(record.source_ref)
        if style_id is not None:
            row = await reader(account_id, style_id)
            if row is None or not isinstance(row, dict):
                # Prefer a fresh durable re-read; fall back to the ledger snapshot
                # so a deleted/malformed style row does not brick an open REVIEW.
                return _candidate_from_ledger_body(record)
            try:
                observation = _observation_from_style_row(style_id, row)
                candidate = candidate_from_observation(observation)
            except ValueError:
                return _candidate_from_ledger_body(record)
            # Keep ledger identity (key / version / namespace) even if the durable
            # row has moved on — the human is closing *this* REVIEW row.
            return PromotionCandidate(
                namespace=record.namespace,
                key=record.key,
                body=candidate.body,
                trust_class=candidate.trust_class,
                source_ref=record.source_ref,
                source_version=record.source_version,
                observed_at=record.source_version,
                evidence_ids=candidate.evidence_ids,
                sample_count=candidate.sample_count,
                measured_rate=candidate.measured_rate,
                ttl_seconds=candidate.ttl_seconds,
                proposed_by="human-review",
            )
        # hy-memory (and other non-style refs) have no trusted re-read — the
        # body snapshotted at observe time is the only honest source.
        return _candidate_from_ledger_body(record)

    return _rebuild


def _human_decision(
    record: PromotionRecord,
    *,
    disposition: CreatorReviewDisposition,
) -> PromotionDecision:
    """Author a human decision; never call ``decide_promotion``."""
    if disposition is CreatorReviewDisposition.APPROVED:
        return PromotionDecision(
            candidate_id=record.candidate_id,
            disposition=PromotionDisposition.PROMOTE,
            reason=PromotionReason.HUMAN_APPROVED,
            dedupe=DedupeVerdict.NOT_EVALUATED,
            verified=False,
            # Link without mutating the REVIEW row; current_entries ignores
            # non-promote ids listed here.
            supersedes=(record.promotion_id,),
            decided_by=HUMAN_DECIDED_BY,
            policy_version=record.policy_version,
        )
    return PromotionDecision(
        candidate_id=record.candidate_id,
        disposition=PromotionDisposition.REFUSE,
        reason=PromotionReason.HUMAN_DISMISSED,
        dedupe=DedupeVerdict.NOT_EVALUATED,
        verified=False,
        supersedes=(record.promotion_id,),
        decided_by=HUMAN_DECIDED_BY,
        policy_version=record.policy_version,
    )


def _dismiss_placeholder_candidate(record: PromotionRecord) -> PromotionCandidate:
    """Minimal candidate for a dismiss append when body re-read is unnecessary.

    ``PromotionCandidate`` requires a non-empty body, but dismiss never writes
    the target namespace — so a stable placeholder is enough and avoids a hard
    dependency on the durable source for the refuse path.
    """
    trust = (
        TrustClass.INTERNAL_FACT
        if record.source_ref.startswith(_CREATIVE_STYLE_PREFIX)
        else TrustClass.MEMORY
    )
    return PromotionCandidate(
        namespace=record.namespace,
        key=record.key,
        body=f"[human dismissed {record.promotion_id}]",
        trust_class=trust,
        source_ref=record.source_ref,
        source_version=record.source_version,
        observed_at=record.source_version,
        proposed_by="human-review",
    )


async def review_promotion(
    ledger: PromotionLedger,
    store: Any | None,
    account_id: str,
    promotion_id: str,
    disposition: CreatorReviewDisposition,
    *,
    review_note: str = "",
    rebuild_candidate: CandidateRebuilder | None = None,
    style_reader: StyleRowReader | None = None,
    recorded_at: str | None = None,
) -> PromotionReviewResult:
    """Close one open REVIEW row with a human approve/dismiss.

    ``approved`` reconstructs the candidate body (Creative Memory style re-read
    when possible, else the body snapshotted on the REVIEW ledger row), appends
    a human ``PROMOTE``, then writes ``strategy_notes``. ``dismissed`` appends a
    human ``REFUSE`` and writes nothing.
    """
    account_id = (account_id or "").strip()
    promotion_id = (promotion_id or "").strip()
    if not account_id:
        raise ValueError("account_id must be a non-empty string")
    if not promotion_id:
        raise ValueError("promotion_id must be a non-empty string")
    if not isinstance(disposition, CreatorReviewDisposition):
        raise ValueError("disposition must be a CreatorReviewDisposition member")

    if store is None:
        raise PromotionStoreUnavailableError()

    page = await ledger.records(account_id)
    if not page.available:
        raise PromotionStoreUnavailableError()
    if not page.complete:
        raise RuntimeError(
            "promotion ledger page is incomplete; raise the limit before reviewing "
            "(a missing record can be the human closure)"
        )

    review_record = next(
        (record for record in page.records if record.promotion_id == promotion_id),
        None,
    )
    if review_record is None:
        raise PromotionReviewMissingError(promotion_id)
    if review_record.disposition != PromotionDisposition.REVIEW.value:
        raise PromotionReviewMissingError(promotion_id)

    existing_closure = _human_closure_of(page.records, promotion_id)
    if existing_closure is not None:
        raise PromotionReviewConflictError(promotion_id, existing_closure.disposition)

    decision = _human_decision(review_record, disposition=disposition)
    detail = encode_review_detail(
        reviewed_promotion_id=promotion_id,
        review_note=review_note,
    )

    if disposition is CreatorReviewDisposition.APPROVED:
        rebuilder = rebuild_candidate or _make_default_rebuilder(
            style_reader if style_reader is not None else read_style_row
        )
        candidate = await rebuilder(review_record, account_id)
        if not candidate.body.strip():
            raise PromotionReviewBodyUnavailableError(
                promotion_id, "rebuilt candidate body is empty"
            )
        outcome = await ledger.append(
            account_id, candidate, decision, recorded_at=recorded_at, detail=detail
        )
        if outcome is LedgerAppendOutcome.NO_STORE:
            raise PromotionStoreUnavailableError()
        # Ledger first, target second — same crash semantics as Slice C.
        await write_promoted_memory(store, account_id, candidate, decision, recorded_at=recorded_at)
        applied = True
    else:
        candidate = _dismiss_placeholder_candidate(review_record)
        outcome = await ledger.append(
            account_id, candidate, decision, recorded_at=recorded_at, detail=detail
        )
        if outcome is LedgerAppendOutcome.NO_STORE:
            raise PromotionStoreUnavailableError()
        applied = False

    closure_id = promotion_id_for(decision, source_version=candidate.source_version)
    refreshed = await ledger.records(account_id)
    closure_record = next(
        (record for record in refreshed.records if record.promotion_id == closure_id),
        None,
    )
    if closure_record is None:
        # Append succeeded; synthesize from what we wrote so the API still
        # returns a concrete row even if the re-read page races.
        closure_record = PromotionRecord(
            promotion_id=closure_id,
            candidate_id=decision.candidate_id,
            namespace=candidate.namespace,
            key=candidate.key,
            source_ref=candidate.source_ref,
            source_version=candidate.source_version,
            disposition=decision.disposition.value,
            reason=decision.reason.value,
            dedupe=decision.dedupe.value,
            verified=decision.verified,
            supersedes=decision.supersedes,
            decided_by=decision.decided_by,
            policy_version=decision.policy_version,
            recorded_at=recorded_at or "",
            detail=detail,
            body=candidate.body,
        )

    return PromotionReviewResult(
        review_record=review_record,
        closure_record=closure_record,
        applied=applied,
        disposition=disposition,
    )
