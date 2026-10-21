"""Append-only ledger for memory promotion decisions (Slice B, 票 5s).

The protocol in :mod:`backend.memory.promotion` answers *may this candidate be
promoted*. This module answers the equally important *what was decided*, in a
form that is written once and never edited: one record per decision, keyed by an
id derived from the decision itself.

Stored in the account's memory namespace (``accounts/<id>/memory_promotions``)
rather than a new Postgres table — PRD §9 Q5's ruling, recorded in
``docs/memory-promotion.md`` §7:

- the record is immutable and its id is derived, so writing the same decision
  twice overwrites identical bytes rather than changing history;
- it lives where the memories live, so a later read (Slice C) does not need a
  second connection or a migration;
- the moment operators need cross-account queries, the writer below is the one
  place to mirror into Postgres — the decision objects do not change.

Failure semantics follow the repository's rule rather than a convenient one: a
store that raises **raises** here (the caller decides what a failed append
means); a missing store is a configuration fact, reported as
``LedgerAppendOutcome.NO_STORE`` / ``LedgerPage.available is False`` — never as
"recorded" and never as "no decisions".
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from backend.memory.promotion import (
    ExistingEntry,
    PromotionCandidate,
    PromotionDecision,
    PromotionDisposition,
)

__all__ = [
    "LedgerAppendOutcome",
    "LedgerPage",
    "PromotionLedger",
    "PromotionRecord",
    "current_entries",
    "promotion_id_for",
]

_NAMESPACE_SUFFIX = "memory_promotions"


class LedgerAppendOutcome(StrEnum):
    """What happened to one append. There is no silent success value."""

    RECORDED = "recorded"
    NO_STORE = "no_store"
    """The deployment has no memory store; nothing was written (not a failure)."""


def promotion_id_for(decision: PromotionDecision, *, source_version: str) -> str:
    """Deterministic ledger key: one (candidate, source version, verdict) = one id.

    The source version is part of the id so a supersede is a *new* row: an
    append-only ledger may not overwrite the record of the version it replaced.
    The policy version and outcome are part of it for the same reason — a policy
    change produces history, not a rewrite.
    """
    digest = hashlib.sha256(
        "|".join(
            (
                decision.candidate_id,
                source_version,
                decision.disposition.value,
                decision.reason.value,
                decision.policy_version,
            )
        ).encode()
    ).hexdigest()
    return f"promo_{digest[:16]}"


@dataclass(frozen=True)
class PromotionRecord:
    """One immutable decision row.

    ``recorded_at`` is the only clock this module touches; it is injected by the
    caller (``append(..., recorded_at=...)``) so tests are deterministic and a
    backfill can preserve real time.
    """

    promotion_id: str
    candidate_id: str
    namespace: str
    key: str
    source_ref: str
    source_version: str
    disposition: str
    reason: str
    dedupe: str
    verified: bool
    supersedes: tuple[str, ...]
    decided_by: str
    policy_version: str
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "promotion_id": self.promotion_id,
            "candidate_id": self.candidate_id,
            "namespace": self.namespace,
            "key": self.key,
            "source_ref": self.source_ref,
            "source_version": self.source_version,
            "disposition": self.disposition,
            "reason": self.reason,
            "dedupe": self.dedupe,
            "verified": self.verified,
            "supersedes": list(self.supersedes),
            "decided_by": self.decided_by,
            "policy_version": self.policy_version,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PromotionRecord:
        """Read one stored row; a malformed row raises (the ledger is a record,
        not best-effort telemetry — a row nobody can parse is a bug to surface).
        """
        return cls(
            promotion_id=str(raw["promotion_id"]),
            candidate_id=str(raw["candidate_id"]),
            namespace=str(raw["namespace"]),
            key=str(raw["key"]),
            source_ref=str(raw["source_ref"]),
            source_version=str(raw["source_version"]),
            disposition=str(raw["disposition"]),
            reason=str(raw["reason"]),
            dedupe=str(raw["dedupe"]),
            verified=bool(raw["verified"]),
            supersedes=tuple(str(item) for item in raw.get("supersedes", ())),
            decided_by=str(raw["decided_by"]),
            policy_version=str(raw["policy_version"]),
            recorded_at=str(raw["recorded_at"]),
        )


@dataclass(frozen=True)
class LedgerPage:
    """One read of an account's ledger.

    ``available`` separates "no store configured" from "store has no rows yet":
    an observer must not read the first as "nothing was ever decided".
    ``complete`` is the other half: a page that hit its limit may be missing the
    record that would make a candidate a duplicate, so dedupe must refuse to
    decide on it rather than guess.
    """

    records: tuple[PromotionRecord, ...]
    available: bool
    complete: bool = True


class PromotionLedger:
    """Append-only writer/reader for promotion decisions.

    The store is an injected ``BaseStore`` (or ``None`` when the deployment has
    no memory backend); this class never falls back to an in-process dict — that
    would make a lost append look like a recorded decision.
    """

    def __init__(self, store: Any | None) -> None:
        self._store = store

    @staticmethod
    def namespace(account_id: str) -> tuple[str, str, str]:
        return ("accounts", account_id, _NAMESPACE_SUFFIX)

    async def append(
        self,
        account_id: str,
        candidate: PromotionCandidate,
        decision: PromotionDecision,
        *,
        recorded_at: str | None = None,
    ) -> LedgerAppendOutcome:
        """Write one decision. Raises if the store raises."""
        if self._store is None:
            return LedgerAppendOutcome.NO_STORE
        record = PromotionRecord(
            promotion_id=promotion_id_for(decision, source_version=candidate.source_version),
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
            recorded_at=recorded_at or datetime.now(UTC).isoformat(),
        )
        await self._store.aput(
            self.namespace(account_id),
            key=record.promotion_id,
            value=record.to_dict(),
        )
        return LedgerAppendOutcome.RECORDED

    async def records(self, account_id: str, *, limit: int = 200) -> LedgerPage:
        """Newest-first page of records. Raises if the store raises.

        ``complete`` is false when the store returned exactly ``limit`` rows:
        there may be more, so a caller that dedupes against current records must
        raise its limit rather than treat a partial page as the whole ledger.
        """
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if self._store is None:
            return LedgerPage(records=(), available=False, complete=True)
        items = await self._store.asearch(self.namespace(account_id), limit=limit)
        parsed = [PromotionRecord.from_dict(item.value) for item in items]
        parsed.sort(key=lambda record: (record.recorded_at, record.promotion_id), reverse=True)
        return LedgerPage(
            records=tuple(parsed),
            available=True,
            complete=len(parsed) < limit,
        )


def current_entries(records: Sequence[PromotionRecord]) -> tuple[ExistingEntry, ...]:
    """The target keys' current promote records, as protocol ``ExistingEntry``s.

    "Current" is derived, not stored: a promote record is superseded when a
    later record lists its id in ``supersedes``. Two current promote records on
    one key mean the ledger contradicts itself (the decision function can only
    supersede, never fork), so that is raised rather than guessed.
    """
    promoted = [record for record in records if record.disposition == PromotionDisposition.PROMOTE]
    superseded = {promotion_id for record in records for promotion_id in record.supersedes}
    current: dict[str, PromotionRecord] = {}
    for record in promoted:
        if record.promotion_id in superseded:
            continue
        previous = current.get(record.key)
        if previous is not None:
            raise ValueError(
                f"ledger has two current promote records for key {record.key!r}: "
                f"{previous.promotion_id!r} and {record.promotion_id!r}"
            )
        current[record.key] = record
    return tuple(
        ExistingEntry(
            key=record.key,
            source_ref=record.source_ref,
            source_version=record.source_version,
            promotion_id=record.promotion_id,
        )
        for record in current.values()
    )
