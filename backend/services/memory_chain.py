"""Memory write-path contracts (ledger schemes #49 and #99).

The ledger's two memory ideas were contracts only until now:

- ``#49`` — a fact keeps the exact human revisions it went through, and a
  ``supersedes`` pointer records state transitions (old quote → new quote)
  instead of a flattened summary;
- ``#99`` — a new observation that merely *might* mean a lasting change goes
  into an explicit waiting room (``PROFILE``) rather than overwriting a belief;
  it graduates only after repeated corroboration across at least two weeks.

This module owns the durable side of both: read/write helpers over the
LangGraph ``BaseStore`` (same shape as :mod:`backend.services.port`), the
``MAINTAIN`` / ``PROFILE`` / ``CORRECT`` routing, hypothesis promotion, and the
zero-LLM decorator that attaches learned human edits under a recalled fact.

Correction is driven by *explicit contradiction evidence*, not by wording:
a price or date change («旺季提前 7 天» → «旺季提前 14 天») overlaps almost
entirely with the belief it replaces, so text divergence alone can never reach
the contract's CORRECT threshold. The caller therefore states contradiction
confidence, and this module escalates in bands — the contract still supplies the
divergence-only surprisal used for reporting and for the no-contradiction path.

Everything here is deterministic: matching is character/token overlap, never
embeddings, and no network or model call happens on any path. The switch
``XHS_MEMORY_CHAIN`` is opt-in; ``memory_chain_enabled()`` is the only thing the
call sites need to consult, and when it is off they must behave byte-identically
to before.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.services.recovery_contracts import (
    RevisionEntry,
    build_revision_chain,
    render_revision_diffs,
    resolve_current_facts,
)
from backend.services.supervision_contracts import (
    Belief,
    ConsolidationAction,
    PreCoMemConsolidator,
    ProfileHypothesis,
    promote_hypothesis,
)

logger = logging.getLogger("xhs_growth.services.memory_chain")

__all__ = [
    "MEMORY_CHAIN_ENV",
    "FactRecord",
    "HypothesisPromotion",
    "ObservationRoute",
    "attach_revision_notes",
    "current_facts",
    "load_fact_records",
    "load_hypotheses",
    "memory_chain_enabled",
    "promote_hypotheses",
    "record_observation",
    "revision_pairs_from_port_spans",
    "save_fact_records",
    "save_hypotheses",
]

MEMORY_CHAIN_ENV = "XHS_MEMORY_CHAIN"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_CHAIN_SUFFIX = "fact_chain"
_HYPOTHESIS_SUFFIX = "fact_hypotheses"
_RECORDS_KEY = "records"
_HYPOTHESES_KEY = "hypotheses"
#: Two observations below this overlap are treated as unrelated facts, not as a
#: conflict with the belief — silence is better than a false correction.
_MATCH_THRESHOLD = 0.5
#: A learned human edit is attached only when it clearly touches this text.
_REVISION_OVERLAP = 0.6
#: Contradiction bands. ``>= correct`` replaces the belief; ``>= profile`` parks a
#: hypothesis instead of touching the fact chain.
_CORRECT_CONTRADICTION = 0.8
_PROFILE_CONTRADICTION = 0.4
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


def memory_chain_enabled() -> bool:
    """Whether the opt-in memory write-path wiring is active."""
    return os.environ.get(MEMORY_CHAIN_ENV, "").strip().lower() in _TRUTHY


def _grams(text: str) -> set[str]:
    """Deterministic overlap features: latin tokens + CJK character bigrams."""
    features: set[str] = set()
    for match in _TOKEN_RE.finditer(text or ""):
        token = match.group(0)
        if token.isascii():
            features.add(token.lower())
        elif len(token) == 1:
            features.add(token)
        else:
            features.update(token[index : index + 2] for index in range(len(token) - 1))
    return features


def _overlap(left: str, right: str) -> float:
    """Jaccard overlap of :func:`_grams`; empty input has no overlap."""
    first, second = _grams(left), _grams(right)
    if not first or not second:
        return 0.0
    return round(len(first & second) / len(first | second), 6)


def _text(value: object) -> str:
    """Coerce an unknown value to a stripped string."""
    return value.strip() if isinstance(value, str) else ""


def _int(value: object, default: int = 1) -> int:
    """Coerce an unknown value to a non-negative int."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return default


def _float(value: object, default: float = 0.0) -> float:
    """Coerce an unknown value to a float."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _namespace(account_id: str, suffix: str) -> tuple[str, ...]:
    return ("accounts", account_id or "default", suffix)


def _digest(text: str) -> str:
    """Stable short id for a fact seeded from free text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _confidence(record: FactRecord) -> float:
    """Belief confidence grows with corroboration but never reaches certainty."""
    return min(0.95, 0.5 + 0.1 * max(0, record.evidence_count - 1))


@dataclass(frozen=True)
class FactRecord:
    """One version of a durable fact, plus the version it replaced."""

    fact_id: str
    text: str
    kind: str = "insight"
    created_at: str = ""
    supersedes: str = ""
    source: str = ""
    evidence_count: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "text": self.text,
            "kind": self.kind,
            "created_at": self.created_at,
            "supersedes": self.supersedes,
            "source": self.source,
            "evidence_count": self.evidence_count,
        }


def _record_from_mapping(value: object) -> FactRecord | None:
    """Tolerant reader: a malformed row is skipped, never guessed at."""
    if not isinstance(value, dict):
        return None
    fact_id = _text(value.get("fact_id"))
    text = _text(value.get("text"))
    if not fact_id or not text:
        return None
    return FactRecord(
        fact_id=fact_id,
        text=text,
        kind=_text(value.get("kind")) or "insight",
        created_at=_text(value.get("created_at")),
        supersedes=_text(value.get("supersedes")),
        source=_text(value.get("source")),
        evidence_count=max(1, _int(value.get("evidence_count"))),
    )


async def _load_rows(store: Any, account_id: str, suffix: str, key: str) -> list[dict[str, Any]]:
    """Best-effort read of one stored list; a missing store/record is empty."""
    if store is None:
        return []
    try:
        item = await store.aget(_namespace(account_id, suffix), key)
    except Exception as exc:  # pragma: no cover - defensive store boundary
        logger.debug("memory chain read skipped (%s): %s", suffix, exc)
        return []
    value = getattr(item, "value", None) if item is not None else None
    if not isinstance(value, dict):
        return []
    rows = value.get(key)
    return [dict(row) for row in rows or [] if isinstance(row, dict)]


async def _save_rows(
    store: Any, account_id: str, suffix: str, key: str, rows: list[dict[str, Any]]
) -> None:
    """Persist one stored list; failures surface to the caller."""
    if store is None:
        return
    try:
        await store.aput(_namespace(account_id, suffix), key, {key: rows})
    except Exception as exc:  # pragma: no cover - defensive store boundary
        logger.debug("memory chain write skipped (%s): %s", suffix, exc)
        raise


async def load_fact_records(store: Any, account_id: str) -> list[FactRecord]:
    """Read the fact chain (all versions, oldest first)."""
    rows = await _load_rows(store, account_id, _CHAIN_SUFFIX, _RECORDS_KEY)
    return [record for record in (_record_from_mapping(row) for row in rows) if record]


async def save_fact_records(store: Any, account_id: str, records: Sequence[FactRecord]) -> None:
    """Persist the fact chain."""
    await _save_rows(
        store, account_id, _CHAIN_SUFFIX, _RECORDS_KEY, [record.as_dict() for record in records]
    )


@dataclass(frozen=True)
class _Parked:
    """A waiting-room row plus the week its latest corroboration came from."""

    hypothesis: ProfileHypothesis
    last_week: int = 0

    def as_row(self) -> dict[str, Any]:
        hypothesis = self.hypothesis
        return {
            "hypothesis_id": hypothesis.hypothesis_id,
            "statement": hypothesis.statement,
            "confidence": hypothesis.confidence,
            "corroborations": hypothesis.corroborations,
            "weeks_observed": hypothesis.weeks_observed,
            "last_week": self.last_week,
        }


def _parked_from_row(row: dict[str, Any]) -> _Parked | None:
    hypothesis_id = _text(row.get("hypothesis_id"))
    statement = _text(row.get("statement"))
    if not hypothesis_id or not statement:
        return None
    return _Parked(
        hypothesis=ProfileHypothesis(
            hypothesis_id=hypothesis_id,
            statement=statement,
            confidence=min(1.0, max(0.0, _float(row.get("confidence"), 0.4))),
            corroborations=max(1, _int(row.get("corroborations"))),
            weeks_observed=max(1, _int(row.get("weeks_observed"))),
        ),
        last_week=max(0, _int(row.get("last_week"), 0)),
    )


async def _load_parked(store: Any, account_id: str) -> list[_Parked]:
    rows = await _load_rows(store, account_id, _HYPOTHESIS_SUFFIX, _HYPOTHESES_KEY)
    return [item for item in (_parked_from_row(row) for row in rows) if item]


async def _save_parked(store: Any, account_id: str, parked: Sequence[_Parked]) -> None:
    await _save_rows(
        store,
        account_id,
        _HYPOTHESIS_SUFFIX,
        _HYPOTHESES_KEY,
        [item.as_row() for item in parked],
    )


async def load_hypotheses(store: Any, account_id: str) -> list[ProfileHypothesis]:
    """Read the waiting room (unconfirmed beliefs)."""
    return [item.hypothesis for item in await _load_parked(store, account_id)]


async def save_hypotheses(
    store: Any, account_id: str, hypotheses: Sequence[ProfileHypothesis]
) -> None:
    """Persist waiting-room hypotheses without week bookkeeping."""
    await _save_parked(store, account_id, [_Parked(hypothesis=item) for item in hypotheses])


def current_facts(records: Iterable[FactRecord]) -> list[dict[str, Any]]:
    """Fold the ``supersedes`` chain down to the current leaf facts."""
    return resolve_current_facts([record.as_dict() for record in records])


def _superseded_ids(records: Sequence[FactRecord]) -> set[str]:
    return {record.supersedes for record in records if record.supersedes}


def _live_records(records: Sequence[FactRecord]) -> list[FactRecord]:
    superseded = _superseded_ids(records)
    return [record for record in records if record.fact_id not in superseded]


def _best_belief(
    records: Sequence[FactRecord], *, observation: str, kind: str
) -> FactRecord | None:
    """The closest current belief of the same kind, or ``None`` when unrelated."""
    candidates = [record for record in _live_records(records) if record.kind == kind]
    if not candidates:
        return None
    scored = [(_overlap(observation, record.text), record) for record in candidates]
    score, best = max(scored, key=lambda pair: (pair[0], pair[1].fact_id))
    return best if score >= _MATCH_THRESHOLD else None


def _iso_week(stamp: datetime) -> int:
    return int(stamp.isocalendar()[1])


@dataclass(frozen=True)
class ObservationRoute:
    """What one observation did to the fact chain."""

    action: ConsolidationAction
    surprisal: float
    belief_id: str
    fact_id: str
    hypothesis_id: str
    reason: str
    stored: bool
    corroborated: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": str(self.action),
            "surprisal": round(self.surprisal, 4),
            "belief_id": self.belief_id,
            "fact_id": self.fact_id,
            "hypothesis_id": self.hypothesis_id,
            "reason": self.reason,
            "stored": self.stored,
            "corroborated": self.corroborated,
        }


def _route_action(
    decision_action: ConsolidationAction,
    decision_reason: str,
    *,
    contradiction: float,
) -> tuple[ConsolidationAction, str]:
    """Escalate the contract action when the caller states contradiction evidence.

    Same-words/different-fact corrections cannot be expressed by divergence, so
    an explicit contradiction confidence decides the band; a contradiction too
    weak to act on still parks the observation rather than silently corroborating.
    """
    if contradiction >= _CORRECT_CONTRADICTION:
        return ConsolidationAction.CORRECT, "explicit_contradiction"
    if (
        contradiction >= _PROFILE_CONTRADICTION
        and decision_action is not ConsolidationAction.CORRECT
    ):
        return ConsolidationAction.PROFILE, "ambiguous_contradiction_waiting_room"
    return decision_action, decision_reason


def _bootstrap(
    records: Sequence[FactRecord], *, observation: str, kind: str, source: str, stamp: str
) -> tuple[list[FactRecord], ObservationRoute]:
    fact_id = f"{kind}:{_digest(observation)}"
    record = FactRecord(
        fact_id=fact_id,
        text=observation,
        kind=kind,
        created_at=stamp,
        source=source,
    )
    return [*records, record], ObservationRoute(
        action=ConsolidationAction.MAINTAIN,
        surprisal=0.0,
        belief_id="",
        fact_id=fact_id,
        hypothesis_id="",
        reason="bootstrap",
        stored=True,
        corroborated=False,
    )


def _park(
    parked: Sequence[_Parked],
    *,
    observation: str,
    belief_id: str,
    week: int,
) -> tuple[list[_Parked], str]:
    """Park an ambiguous signal, or corroborate the hypothesis already parked.

    ``weeks_observed`` counts *distinct ISO weeks*: five same-week notes are one
    week of evidence, which is exactly what the waiting room exists to enforce.
    """
    matches = [
        item
        for item in parked
        if item.hypothesis.hypothesis_id == f"profile:{belief_id}"
        or _overlap(observation, item.hypothesis.statement) >= _MATCH_THRESHOLD
    ]
    kept = [item for item in parked if item not in matches]
    if matches:
        existing = matches[0]
        hypothesis = existing.hypothesis
        new_week = existing.last_week == 0 or week != existing.last_week
        updated = ProfileHypothesis(
            hypothesis_id=hypothesis.hypothesis_id,
            statement=(
                observation
                if _overlap(observation, hypothesis.statement) < 0.9
                else hypothesis.statement
            ),
            confidence=min(0.9, hypothesis.confidence + 0.1),
            corroborations=hypothesis.corroborations + 1,
            weeks_observed=hypothesis.weeks_observed + (1 if new_week else 0),
        )
        return [*kept, _Parked(hypothesis=updated, last_week=week)], updated.hypothesis_id
    hypothesis_id = f"profile:{belief_id or _digest(observation)}"
    created = ProfileHypothesis(
        hypothesis_id=hypothesis_id,
        statement=observation,
        confidence=0.4,
        corroborations=1,
        weeks_observed=1,
    )
    return [*kept, _Parked(hypothesis=created, last_week=week)], hypothesis_id


async def record_observation(
    store: Any,
    account_id: str,
    *,
    observation: str,
    kind: str = "insight",
    contradiction: float = 0.0,
    source: str = "analyst",
    now: datetime | None = None,
    consolidator: PreCoMemConsolidator | None = None,
) -> ObservationRoute:
    """Route one observation through MAINTAIN / PROFILE / CORRECT.

    ``PROFILE`` writes to the waiting room only: a maybe-signal must never become
    a durable rule, otherwise the next workflow treats a hypothesis as a
    conclusion. ``CORRECT`` requires explicit contradiction evidence — an
    unrelated text is a *new* fact, not a correction.
    """
    text = _text(observation)
    if not text:
        raise ValueError("observation must be a non-empty string")
    clock = now if now is not None else datetime.now(UTC)
    stamp = clock.isoformat(timespec="seconds")
    records = await load_fact_records(store, account_id)

    belief = _best_belief(records, observation=text, kind=kind)
    if belief is None:
        updated, route = _bootstrap(
            records, observation=text, kind=kind, source=source, stamp=stamp
        )
        await save_fact_records(store, account_id, updated)
        return route

    engine = consolidator or PreCoMemConsolidator()
    decision = engine.decide(
        text,
        Belief(
            fact_id=belief.fact_id,
            text=belief.text,
            confidence=_confidence(belief),
            evidence_count=belief.evidence_count,
        ),
        contradiction=contradiction,
    )
    action, reason = _route_action(decision.action, decision.reason, contradiction=contradiction)

    if action is ConsolidationAction.MAINTAIN:
        updated = [
            FactRecord(
                fact_id=record.fact_id,
                text=record.text,
                kind=record.kind,
                created_at=record.created_at,
                supersedes=record.supersedes,
                source=record.source,
                evidence_count=(
                    record.evidence_count + 1
                    if record.fact_id == belief.fact_id
                    else record.evidence_count
                ),
            )
            for record in records
        ]
        await save_fact_records(store, account_id, updated)
        return ObservationRoute(
            action=ConsolidationAction.MAINTAIN,
            surprisal=decision.surprisal,
            belief_id=belief.fact_id,
            fact_id=belief.fact_id,
            hypothesis_id="",
            reason=reason,
            stored=True,
            corroborated=True,
        )

    if action is ConsolidationAction.PROFILE:
        updated_parked, hypothesis_id = _park(
            await _load_parked(store, account_id),
            observation=text,
            belief_id=belief.fact_id,
            week=_iso_week(clock),
        )
        await _save_parked(store, account_id, updated_parked)
        return ObservationRoute(
            action=ConsolidationAction.PROFILE,
            surprisal=decision.surprisal,
            belief_id=belief.fact_id,
            fact_id="",
            hypothesis_id=hypothesis_id,
            reason=reason,
            stored=False,
            corroborated=False,
        )

    fact_id = f"{belief.fact_id}@{stamp}"
    replacement = FactRecord(
        fact_id=fact_id,
        text=text,
        kind=kind,
        created_at=stamp,
        supersedes=belief.fact_id,
        source=source,
    )
    remaining = [
        item
        for item in await _load_parked(store, account_id)
        if item.hypothesis.hypothesis_id != f"profile:{belief.fact_id}"
    ]
    await save_fact_records(store, account_id, [*records, replacement])
    await _save_parked(store, account_id, remaining)
    return ObservationRoute(
        action=ConsolidationAction.CORRECT,
        surprisal=decision.surprisal,
        belief_id=belief.fact_id,
        fact_id=fact_id,
        hypothesis_id="",
        reason=reason,
        stored=True,
        corroborated=False,
    )


@dataclass(frozen=True)
class HypothesisPromotion:
    """One waiting-room decision made by :func:`promote_hypotheses`."""

    hypothesis_id: str
    statement: str
    action: ConsolidationAction
    reason: str
    fact_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "action": str(self.action),
            "reason": self.reason,
            "fact_id": self.fact_id,
        }


async def promote_hypotheses(
    store: Any,
    account_id: str,
    *,
    min_corroborations: int = 2,
    min_weeks: int = 2,
    now: datetime | None = None,
) -> list[HypothesisPromotion]:
    """Graduate waiting-room hypotheses that survived the corroboration gate."""
    clock = now if now is not None else datetime.now(UTC)
    stamp = clock.isoformat(timespec="seconds")
    parked = await _load_parked(store, account_id)
    if not parked:
        return []
    records = await load_fact_records(store, account_id)
    remaining: list[_Parked] = []
    promotions: list[HypothesisPromotion] = []
    appended: list[FactRecord] = []
    for item in parked:
        hypothesis = item.hypothesis
        decision = promote_hypothesis(
            hypothesis, min_corroborations=min_corroborations, min_weeks=min_weeks
        )
        if decision.action is not ConsolidationAction.CORRECT:
            remaining.append(item)
            promotions.append(
                HypothesisPromotion(
                    hypothesis_id=hypothesis.hypothesis_id,
                    statement=hypothesis.statement,
                    action=decision.action,
                    reason=decision.reason,
                    fact_id="",
                )
            )
            continue
        belief = _best_belief(records, observation=hypothesis.statement, kind="insight")
        fact_id = f"promoted:{hypothesis.hypothesis_id}"
        appended.append(
            FactRecord(
                fact_id=fact_id,
                text=hypothesis.statement,
                kind="insight",
                created_at=stamp,
                supersedes=belief.fact_id if belief is not None else "",
                source="promotion",
                evidence_count=max(1, hypothesis.corroborations),
            )
        )
        promotions.append(
            HypothesisPromotion(
                hypothesis_id=hypothesis.hypothesis_id,
                statement=hypothesis.statement,
                action=decision.action,
                reason=decision.reason,
                fact_id=fact_id,
            )
        )
    if appended:
        await save_fact_records(store, account_id, [*records, *appended])
    await _save_parked(store, account_id, remaining)
    return promotions


def revision_pairs_from_port_spans(spans: Iterable[dict[str, Any]]) -> list[RevisionEntry]:
    """Turn learned PORT span dicts into revision-history entries."""
    revisions: list[RevisionEntry] = []
    for index, span in enumerate(spans):
        if not isinstance(span, dict):
            continue
        old_text = _text(span.get("old"))
        new_text = _text(span.get("new"))
        if not old_text or not new_text or old_text == new_text:
            continue
        revisions.append(
            RevisionEntry(
                revision_id=f"port:{index}",
                source_turn_id="",
                field=_text(span.get("field")) or "body",
                old_text=old_text,
                new_text=new_text,
                operator_comment=_text(span.get("reason")),
                created_at=_text(span.get("last_seen")),
            )
        )
    return revisions


def _revision_matches(text: str, revision: RevisionEntry) -> bool:
    """A learned edit belongs to this text only when it clearly touches it."""
    old = revision.old_text.strip()
    if len(old) < 2:
        return False
    if old in text:
        return True
    return _overlap(old, text) >= _REVISION_OVERLAP


def attach_revision_notes(
    texts: Sequence[str],
    revisions: Iterable[RevisionEntry],
    *,
    limit: int = 3,
) -> list[str]:
    """Attach the latest matching human edits under each text (zero LLM)."""
    items = list(revisions)
    decorated: list[str] = []
    for text in texts:
        matches = [revision for revision in items if _revision_matches(text, revision)]
        if not matches:
            decorated.append(text)
            continue
        chain = build_revision_chain("recalled", text, matches, limit=limit)
        diffs = render_revision_diffs(chain)
        if not diffs:
            decorated.append(text)
            continue
        notes = "；".join(
            f"旧「{diff['old']}」→ 新「{diff['new']}」"
            + (f"（{diff['operator_comment']}）" if diff.get("operator_comment") else "")
            for diff in diffs
        )
        decorated.append(f"{text}（人工改稿：{notes}）")
    return decorated
