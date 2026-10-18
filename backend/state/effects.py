"""Effect Ledger — one state machine for operations that change the outside world (P0-B).

A *step* may run several times (retries, crash recovery), but the **logical
effect** it produces must happen once. Publish already learned this the hard
way (P0-W4: a lost submit response reported as "failed" invites a duplicate
note); this module generalises that record so the next external-effect tool
(comment, DM, scheduled post) inherits the guard instead of re-deriving it.

Status machine (the one the design note asks for)::

    PREPARED ──► IN_FLIGHT ──► CONFIRMED
        │            │
        │            ├──► FAILED        (verdict received: did not happen)
        │            └──► UNKNOWN       (submitted, no verdict — MUST reconcile)
        └────────────┴──► RECONCILING ──► CONFIRMED / FAILED / UNKNOWN

Blocking rule: **IN_FLIGHT / CONFIRMED / UNKNOWN / RECONCILING block a retry;
PREPARED and FAILED do not** — PREPARED is only an intent, and FAILED is a
verdict that the effect did not happen. The dangerous mistake this encodes is the
one the design note names explicitly — reading UNKNOWN as FAILED releases the
guard and repeats the side effect. A retry is only safe when we have a verdict
that the effect did not happen.

Legacy vocabulary: existing publish records use ``published`` / ``unknown`` /
``failed``; ``from_store_dict`` normalises them so pre-migration rows keep
working without a data rewrite (the same no-checkpoint-rewrite discipline as
P1a's telemetry move).

Honest concurrency note: ``BaseStore`` offers no compare-and-swap, so
``mark()`` checks the version it read and refuses a stale write, but two
processes can still read the same version concurrently. A single-process
deployment behind the thread lease is safe; a multi-writer deployment needs a
database-level unique constraint on ``effect_id`` (the design note's
"get_or_create must rely on a unique constraint, CAS or transaction").
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

__all__ = [
    "BLOCKING_STATUSES",
    "DEFAULT_EFFECT_NS",
    "LEGAL_TRANSITIONS",
    "EffectBlockedError",
    "EffectLedger",
    "EffectRecord",
    "EffectStatus",
    "StaleEffectWriteError",
]

#: Ledger namespace for tools that do not pass their own (publish keeps its
#: historical ``("publish", "idempotency")`` so no row moves).
DEFAULT_EFFECT_NS: tuple[str, ...] = ("effects",)


class EffectStatus(StrEnum):
    PREPARED = "prepared"
    IN_FLIGHT = "in_flight"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RECONCILING = "reconciling"


#: Statuses that forbid another attempt.
#:
#: PREPARED is deliberately absent: it records an *intent*, nothing has been
#: submitted yet, and ``begin`` itself must be able to advance it to
#: IN_FLIGHT. FAILED is absent for the same reason from the other side — a
#: verdict of "did not happen" is exactly when a retry is safe. IN_FLIGHT /
#: CONFIRMED / UNKNOWN / RECONCILING all mean "something may already exist".
BLOCKING_STATUSES: frozenset[EffectStatus] = frozenset(
    {
        EffectStatus.IN_FLIGHT,
        EffectStatus.CONFIRMED,
        EffectStatus.UNKNOWN,
        EffectStatus.RECONCILING,
    }
)

#: Legal forward transitions. Terminal states accept nothing; a FAILED record
#: may re-enter IN_FLIGHT because that is a *new attempt* on the same key.
LEGAL_TRANSITIONS: Mapping[EffectStatus, frozenset[EffectStatus]] = {
    EffectStatus.PREPARED: frozenset({EffectStatus.IN_FLIGHT, EffectStatus.FAILED}),
    EffectStatus.IN_FLIGHT: frozenset(
        {EffectStatus.CONFIRMED, EffectStatus.FAILED, EffectStatus.UNKNOWN}
    ),
    EffectStatus.UNKNOWN: frozenset(
        {EffectStatus.RECONCILING, EffectStatus.CONFIRMED, EffectStatus.FAILED}
    ),
    EffectStatus.RECONCILING: frozenset(
        {EffectStatus.CONFIRMED, EffectStatus.FAILED, EffectStatus.UNKNOWN}
    ),
    EffectStatus.CONFIRMED: frozenset(),
    EffectStatus.FAILED: frozenset({EffectStatus.IN_FLIGHT}),
}

#: Legacy record vocabulary → ledger status. ``published`` was the old name of
#: CONFIRMED; the other two already match.
_LEGACY_STATUS: Mapping[str, EffectStatus] = {
    "published": EffectStatus.CONFIRMED,
    "confirmed": EffectStatus.CONFIRMED,
    "unknown": EffectStatus.UNKNOWN,
    "failed": EffectStatus.FAILED,
    "prepared": EffectStatus.PREPARED,
    "in_flight": EffectStatus.IN_FLIGHT,
    "reconciling": EffectStatus.RECONCILING,
}


class EffectBlockedError(Exception):
    """A retry was refused because a prior attempt may still take effect."""

    def __init__(self, record: EffectRecord) -> None:
        super().__init__(f"effect {record.effect_id} is {record.status.value}")
        self.record = record


class StaleEffectWriteError(Exception):
    """A transition was refused because the record moved since it was read."""


@dataclass(frozen=True)
class EffectRecord:
    """One logical effect and its last known state.

    ``attempt`` counts submissions of *this* effect (same ``effect_id``);
    retries reuse the id, which is what makes them retries instead of new
    effects. ``extra`` carries tool-specific fields (post_id, account_id…)
    without teaching the ledger every tool's vocabulary.
    """

    effect_id: str
    status: EffectStatus
    tool_name: str = ""
    task_id: str = ""
    step_id: str = ""
    attempt: int = 1
    request_digest: str = ""
    result_ref: str = ""
    error: str = ""
    updated_at: str = ""
    version: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def blocks_retry(self) -> bool:
        return self.status in BLOCKING_STATUSES

    def to_store_dict(self) -> dict[str, Any]:
        """Flat dict for ``BaseStore.aput`` — ``status`` is the ledger word."""
        data: dict[str, Any] = {
            "effect_id": self.effect_id,
            "status": self.status.value,
            "tool_name": self.tool_name,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "request_digest": self.request_digest,
            "result_ref": self.result_ref,
            "error": self.error,
            "updated_at": self.updated_at,
            "version": self.version,
        }
        data.update(self.extra)
        return data

    @classmethod
    def from_store_dict(cls, effect_id: str, raw: Mapping[str, Any]) -> EffectRecord:
        """Normalise a stored record, including pre-ledger publish rows."""
        status = _LEGACY_STATUS.get(str(raw.get("status") or "").strip().lower())
        if status is None:
            # An unrecognised status must not be read as FAILED (that would
            # release the guard); treat it as UNKNOWN, the conservative branch.
            status = EffectStatus.UNKNOWN
        known = {
            "effect_id",
            "status",
            "tool_name",
            "task_id",
            "step_id",
            "attempt",
            "request_digest",
            "result_ref",
            "error",
            "updated_at",
            "version",
        }
        extra = {k: v for k, v in raw.items() if k not in known}
        return cls(
            effect_id=effect_id,
            status=status,
            tool_name=str(raw.get("tool_name") or ""),
            task_id=str(raw.get("task_id") or ""),
            step_id=str(raw.get("step_id") or ""),
            attempt=max(1, int(raw.get("attempt") or 1)),
            request_digest=str(raw.get("request_digest") or ""),
            result_ref=str(raw.get("result_ref") or ""),
            error=str(raw.get("error") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            version=max(0, int(raw.get("version") or 0)),
            extra=extra,
        )


class EffectLedger:
    """Store-backed ledger. One instance per (store, namespace) pair."""

    def __init__(
        self,
        store: Any,
        namespace: tuple[str, ...] = DEFAULT_EFFECT_NS,
    ) -> None:
        self._store = store
        self._ns = namespace

    @property
    def namespace(self) -> tuple[str, ...]:
        return self._ns

    async def get(self, effect_id: str) -> EffectRecord | None:
        """Read one record, or None. Storage errors propagate — a caller that
        cannot read the guard must decide explicitly, never assume "no record"."""
        if self._store is None or not effect_id:
            return None
        item = await self._store.aget(self._ns, effect_id)
        value = getattr(item, "value", None) if item is not None else None
        if not isinstance(value, dict):
            return None
        return EffectRecord.from_store_dict(effect_id, value)

    async def begin(
        self,
        effect_id: str,
        *,
        tool_name: str = "",
        task_id: str = "",
        step_id: str = "",
        request_digest: str = "",
        force: bool = False,
    ) -> EffectRecord:
        """Claim the right to submit this effect, or raise :class:`EffectBlockedError`.

        This is the get_or_create seam. It reads the record and, when the
        prior status does not block (or ``force`` is set), writes IN_FLIGHT
        with an incremented attempt count before the caller submits.
        """
        prior = await self.get(effect_id)
        if prior is not None and prior.blocks_retry and not force:
            raise EffectBlockedError(prior)
        record = EffectRecord(
            effect_id=effect_id,
            status=EffectStatus.IN_FLIGHT,
            tool_name=tool_name or (prior.tool_name if prior else ""),
            task_id=task_id or (prior.task_id if prior else ""),
            step_id=step_id or (prior.step_id if prior else ""),
            attempt=(prior.attempt + 1) if prior else 1,
            request_digest=request_digest or (prior.request_digest if prior else ""),
            updated_at=_now(),
            version=(prior.version + 1) if prior else 1,
            extra=dict(prior.extra) if prior else {},
        )
        await self._write(record)
        return record

    async def mark(
        self,
        effect_id: str,
        status: EffectStatus,
        *,
        result_ref: str = "",
        error: str = "",
        extra: Mapping[str, Any] | None = None,
        expect_version: int | None = None,
    ) -> EffectRecord:
        """Move one record to ``status``, checking the transition is legal.

        ``expect_version`` is the optimistic-lock check: when the stored
        version moved past it, the write is refused rather than clobbering a
        concurrent writer's verdict.
        """
        prior = await self.get(effect_id)
        if prior is None:
            record = EffectRecord(
                effect_id=effect_id,
                status=status,
                result_ref=result_ref,
                error=error,
                updated_at=_now(),
                version=1,
                extra=dict(extra or {}),
            )
            await self._write(record)
            return record

        if expect_version is not None and prior.version != expect_version:
            raise StaleEffectWriteError(
                f"effect {effect_id}: expected version {expect_version}, found {prior.version}"
            )
        if status is not prior.status and status not in LEGAL_TRANSITIONS[prior.status]:
            raise ValueError(
                f"effect {effect_id}: illegal transition {prior.status.value} -> {status.value}"
            )
        merged_extra = dict(prior.extra)
        if extra:
            merged_extra.update(extra)
        record = EffectRecord(
            effect_id=effect_id,
            status=status,
            tool_name=prior.tool_name,
            task_id=prior.task_id,
            step_id=prior.step_id,
            attempt=prior.attempt,
            request_digest=prior.request_digest,
            result_ref=result_ref or prior.result_ref,
            error=error,
            updated_at=_now(),
            version=prior.version + 1,
            extra=merged_extra,
        )
        await self._write(record)
        return record

    async def _write(self, record: EffectRecord) -> None:
        await self._store.aput(self._ns, record.effect_id, record.to_store_dict())


def _now() -> str:
    return datetime.now(UTC).isoformat()
