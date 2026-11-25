"""Phase-16 memory contracts (ledger schemes 91-96).

Pure deterministic helpers for selective forgetting, streaming memory
intervention, compound recall, anti-presupposition guarding, decision-fork
isolation and preference-aligned evaluation.  No default workflow wiring.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "CompoundRecallResult",
    "EpicIndexStats",
    "EpicPreferenceIndex",
    "ForkContext",
    "ForkMessage",
    "MemoryScope",
    "PearlGramState",
    "PreferenceEntry",
    "PresuppositionFinding",
    "PresuppositionReport",
    "RecallCandidate",
    "RecallHop",
    "SelectiveForgetResult",
    "SensitiveAttribute",
    "StreamingMemoryAction",
    "StreamingMemoryDecision",
    "TrajectoryMetrics",
    "VisualTrajectoryScore",
    "build_presupposition_safe_reply",
    "evaluate_stream_event",
    "evaluate_visual_trajectory",
    "isolate_fork_context",
    "remind_compound_recall",
    "scan_presuppositions",
]

_CLAUSE_SPLIT_RE = re.compile(r"([，。！？；;])")
_TERM_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_FAILED_ROLES = frozenset({"failed_attempt", "error", "traceback", "rejected_draft"})
_NEGATIVE_HINT_RE = re.compile(r"避免|不要|禁止|切勿|禁用|不得")
_ERROR_MARKERS = ("Traceback (most recent call last)", "Error:", "Exception:")


def _round(value: float) -> float:
    return round(float(value), 4)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _terms(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    bigrams = {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}
    words = set(_TERM_RE.findall(text))
    return bigrams | words


@dataclass(frozen=True)
class SelectiveForgetResult:
    decayed_dimensions: tuple[str, ...]
    kept_dimensions: tuple[str, ...]
    detection_delay: int
    residuals: Mapping[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decayed_dimensions": list(self.decayed_dimensions),
            "kept_dimensions": list(self.kept_dimensions),
            "detection_delay": self.detection_delay,
            "residuals": {key: _round(value) for key, value in self.residuals.items()},
        }


class PearlGramState:
    """Per-dimension Gram diagonal with prediction-error-driven selective decay.

    Ledger #91.  Only dimensions whose residual exceeds the threshold lose
    confidence; stable dimensions keep their accumulated evidence so a local
    preference drift does not wipe out the long-lived baseline.
    """

    def __init__(
        self,
        *,
        residual_threshold: float = 0.25,
        decay: float = 0.5,
        floor: float = 0.05,
    ) -> None:
        if not 0.0 < decay <= 1.0:
            raise ValueError("decay must be in (0, 1]")
        if residual_threshold < 0.0:
            raise ValueError("residual_threshold must be >= 0")
        if floor < 0.0:
            raise ValueError("floor must be >= 0")
        self._residual_threshold = residual_threshold
        self._decay = decay
        self._floor = floor
        self._gram: dict[str, float] = {}

    def observe(self, features: Mapping[str, float], *, weight: float = 1.0) -> None:
        if weight <= 0.0:
            raise ValueError("weight must be > 0")
        for name, value in features.items():
            self._gram[name] = self._gram.get(name, 0.0) + weight * float(value) ** 2

    def confidence(self, dimension: str) -> float:
        return _round(self._gram.get(dimension, 0.0))

    def dimensions(self) -> tuple[str, ...]:
        return tuple(sorted(self._gram))

    def as_dict(self) -> dict[str, Any]:
        return {
            "gram": {key: _round(value) for key, value in sorted(self._gram.items())},
            "residual_threshold": _round(self._residual_threshold),
            "decay": _round(self._decay),
        }

    def register_residual(self, residuals: Mapping[str, float]) -> SelectiveForgetResult:
        decayed: list[str] = []
        kept: list[str] = []
        reported: dict[str, float] = {}
        for name in sorted(self._gram):
            residual = float(residuals.get(name, 0.0))
            reported[name] = residual
            if residual >= self._residual_threshold and residual > 0.0:
                self._gram[name] = max(self._floor, self._gram[name] * (1.0 - self._decay))
                decayed.append(name)
            else:
                kept.append(name)
        return SelectiveForgetResult(
            decayed_dimensions=tuple(decayed),
            kept_dimensions=tuple(kept),
            detection_delay=1,
            residuals=reported,
        )


class StreamingMemoryAction(StrEnum):
    SILENCE = "silence"
    SUPPLEMENT = "supplement"
    PRE_COMMIT_INTERVENTION = "pre_commit_intervention"


class MemoryScope(StrEnum):
    TOPIC_GRAPH = "topic_graph"
    PROJECT_VALUE = "project_value"


@dataclass(frozen=True)
class StreamingMemoryDecision:
    action: StreamingMemoryAction
    scope: MemoryScope
    reason: str
    matched_terms: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": str(self.action),
            "scope": str(self.scope),
            "reason": self.reason,
            "matched_terms": list(self.matched_terms),
        }


def evaluate_stream_event(
    node_output: str,
    *,
    forbidden_terms: Iterable[str] = (),
    supplement_terms: Iterable[str] = (),
    scope: MemoryScope = MemoryScope.TOPIC_GRAPH,
) -> StreamingMemoryDecision:
    """Decide silence / supplementation / pre-commit intervention (ledger #92).

    Conflicting project constraints always win over optional supplements so a
    forbidden artefact can never be published with a friendly hint attached.
    """

    text = node_output or ""
    conflicts = tuple(sorted({term for term in forbidden_terms if term and term in text}))
    if conflicts:
        return StreamingMemoryDecision(
            action=StreamingMemoryAction.PRE_COMMIT_INTERVENTION,
            scope=scope,
            reason="forbidden_term_conflict",
            matched_terms=conflicts,
        )
    supplements = tuple(sorted({term for term in supplement_terms if term and term in text}))
    if supplements:
        return StreamingMemoryDecision(
            action=StreamingMemoryAction.SUPPLEMENT,
            scope=scope,
            reason="supplement_available",
            matched_terms=supplements,
        )
    return StreamingMemoryDecision(
        action=StreamingMemoryAction.SILENCE,
        scope=scope,
        reason="no_conflict",
        matched_terms=(),
    )


@dataclass(frozen=True)
class RecallCandidate:
    memory_id: str
    text: str
    score: float = 0.0


@dataclass(frozen=True)
class RecallHop:
    hop: int
    query_terms: tuple[str, ...]
    selected: tuple[str, ...]
    added_terms: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "hop": self.hop,
            "query_terms": list(self.query_terms),
            "selected": list(self.selected),
            "added_terms": list(self.added_terms),
        }


@dataclass(frozen=True)
class CompoundRecallResult:
    selected: tuple[RecallCandidate, ...]
    hops: tuple[RecallHop, ...]
    stop_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected": [
                {"memory_id": item.memory_id, "score": _round(item.score)} for item in self.selected
            ],
            "hops": [hop.as_dict() for hop in self.hops],
            "stop_reason": self.stop_reason,
        }


def _overlap_ratio(text: str, terms: set[str]) -> float:
    if not terms:
        return 0.0
    return len(terms & _scoring_terms(text)) / len(terms)


def _scoring_terms(text: str) -> set[str]:
    """Multi-character terms only; single CJK characters would dominate overlap."""

    return {term for term in _terms(text) if len(term) >= 2}


def _slots_covered(selected: Sequence[RecallCandidate], required_slots: Sequence[str]) -> bool:
    if not required_slots:
        return True
    joined = "".join(item.text for item in selected)
    return all(slot in joined for slot in required_slots)


def _compound_terms(
    text: str,
    query_terms: set[str],
    remaining: Sequence[RecallCandidate],
    limit: int,
) -> list[str]:
    """Terms of ``text`` that also appear in still-unselected memories.

    Compound cueing (ledger #93) only works when the added cue actually links to
    another memory, so candidates are ranked by how many remaining memories they
    can unlock instead of by raw lexical order.
    """

    if limit <= 0:
        return []
    pool: dict[str, int] = {}
    for candidate in remaining:
        for term in _terms(candidate.text):
            if len(term) < 2 or term in query_terms:
                continue
            pool[term] = pool.get(term, 0) + 1
    own = [
        term for term in _terms(text) if len(term) >= 2 and term not in query_terms and term in pool
    ]
    own.sort(key=lambda term: (-pool[term], term))
    return own[:limit]


def remind_compound_recall(
    candidates: Sequence[RecallCandidate],
    query: str,
    *,
    required_slots: Iterable[str] = (),
    max_hops: int = 3,
    per_hop: int = 1,
    min_score: float = 0.0,
    max_added_terms: int = 3,
) -> CompoundRecallResult:
    """Recurrent compound-cue recall with self-terminating sufficiency (ledger #93)."""

    if max_hops < 1:
        raise ValueError("max_hops must be >= 1")
    if per_hop < 1:
        raise ValueError("per_hop must be >= 1")
    if max_added_terms < 0:
        raise ValueError("max_added_terms must be >= 0")
    slots = tuple(dict.fromkeys(str(slot) for slot in required_slots if str(slot)))
    remaining = [item for item in candidates if item.score >= min_score]
    query_terms = _scoring_terms(query)
    selected: list[RecallCandidate] = []
    hops: list[RecallHop] = []
    stop_reason = "exhausted"
    for hop in range(1, max_hops + 1):
        ranked = sorted(
            remaining,
            key=lambda item: (
                -_overlap_ratio(item.text, query_terms),
                -float(item.score),
                item.memory_id,
            ),
        )
        picked = [item for item in ranked[:per_hop] if _overlap_ratio(item.text, query_terms) > 0.0]
        if not picked:
            stop_reason = "exhausted"
            break
        picked_ids = {item.memory_id for item in picked}
        remaining = [item for item in remaining if item.memory_id not in picked_ids]
        added: list[str] = []
        for item in picked:
            for term in _compound_terms(item.text, query_terms, remaining, max_added_terms):
                if term not in added and len(added) < max_added_terms:
                    added.append(term)
        selected.extend(picked)
        query_terms |= set(added)
        hops.append(
            RecallHop(
                hop=hop,
                query_terms=tuple(sorted(query_terms)),
                selected=tuple(item.memory_id for item in picked),
                added_terms=tuple(added),
            )
        )
        if _slots_covered(selected, slots):
            stop_reason = "sufficient"
            break
        if not remaining:
            stop_reason = "exhausted"
            break
        if hop == max_hops:
            stop_reason = "max_hops"
    return CompoundRecallResult(selected=tuple(selected), hops=tuple(hops), stop_reason=stop_reason)


@dataclass(frozen=True)
class SensitiveAttribute:
    label: str
    terms: tuple[str, ...]
    severity: str = "high"


@dataclass(frozen=True)
class PresuppositionFinding:
    label: str
    term: str
    clause: str
    severity: str = "high"

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "term": self.term,
            "clause": self.clause,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class PresuppositionReport:
    draft: str
    safe_draft: str
    findings: tuple[PresuppositionFinding, ...]
    blocked: bool
    removed_clauses: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "draft": self.draft,
            "safe_draft": self.safe_draft,
            "findings": [finding.as_dict() for finding in self.findings],
            "blocked": self.blocked,
            "removed_clauses": self.removed_clauses,
        }


def _clauses(text: str) -> list[tuple[str, str]]:
    parts = _CLAUSE_SPLIT_RE.split(text)
    result: list[tuple[str, str]] = []
    for index in range(0, len(parts), 2):
        content = parts[index]
        delimiter = parts[index + 1] if index + 1 < len(parts) else ""
        if content or delimiter:
            result.append((content, delimiter))
    return result


def _presupposition_terms(
    draft: str,
    attributes: Sequence[SensitiveAttribute],
    *,
    mentioned_terms: Iterable[str],
    allowed_labels: Iterable[str],
) -> list[tuple[str, str, str, str, int]]:
    mentioned = {str(term) for term in mentioned_terms if str(term)}
    allowed = {str(label) for label in allowed_labels if str(label)}
    hits: list[tuple[str, str, str, str, int]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, (content, _delimiter) in enumerate(_clauses(draft)):
        clause = content.strip()
        if not clause:
            continue
        for attribute in attributes:
            if attribute.label in allowed:
                continue
            for term in attribute.terms:
                if not term or term not in content or term in mentioned:
                    continue
                key = (attribute.label, term, clause)
                if key in seen:
                    continue
                seen.add(key)
                hits.append((attribute.label, term, clause, attribute.severity, index))
    return hits


def scan_presuppositions(
    draft: str,
    attributes: Sequence[SensitiveAttribute],
    *,
    mentioned_terms: Iterable[str] = (),
    allowed_labels: Iterable[str] = (),
) -> tuple[PresuppositionFinding, ...]:
    """Find sensitive attributes asserted without being mentioned this turn (ledger #94)."""

    return tuple(
        PresuppositionFinding(label=label, term=term, clause=clause, severity=severity)
        for label, term, clause, severity, _index in _presupposition_terms(
            draft,
            attributes,
            mentioned_terms=mentioned_terms,
            allowed_labels=allowed_labels,
        )
    )


def build_presupposition_safe_reply(
    draft: str,
    attributes: Sequence[SensitiveAttribute],
    *,
    mentioned_terms: Iterable[str] = (),
    allowed_labels: Iterable[str] = (),
) -> PresuppositionReport:
    """Drop presupposition-carrying clauses while keeping the rest verbatim (ledger #94)."""

    hits = _presupposition_terms(
        draft,
        attributes,
        mentioned_terms=mentioned_terms,
        allowed_labels=allowed_labels,
    )
    offending = {index for _label, _term, _clause, _severity, index in hits}
    kept: list[str] = []
    for index, (content, delimiter) in enumerate(_clauses(draft)):
        if index in offending:
            continue
        kept.append(content + delimiter)
    safe_draft = "".join(kept).strip()
    findings = tuple(
        PresuppositionFinding(label=label, term=term, clause=clause, severity=severity)
        for label, term, clause, severity, _index in hits
    )
    return PresuppositionReport(
        draft=draft,
        safe_draft=safe_draft,
        findings=findings,
        blocked=bool(findings),
        removed_clauses=len(offending),
    )


@dataclass(frozen=True)
class ForkMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ForkContext:
    messages: tuple[ForkMessage, ...]
    negative_constraints: tuple[str, ...]
    removed_messages: int
    removed_chars: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "messages": [{"role": item.role, "content": item.content} for item in self.messages],
            "negative_constraints": list(self.negative_constraints),
            "removed_messages": self.removed_messages,
            "removed_chars": self.removed_chars,
        }


def isolate_fork_context(
    history: Sequence[ForkMessage],
    *,
    max_negative_constraints: int = 3,
) -> ForkContext:
    """Strip failed attempts and keep clean material plus 1-line constraints (ledger #95)."""

    if max_negative_constraints < 0:
        raise ValueError("max_negative_constraints must be >= 0")
    kept: list[ForkMessage] = []
    constraints: list[str] = []
    removed_messages = 0
    removed_chars = 0
    for message in history:
        content = message.content or ""
        failed_role = message.role in _FAILED_ROLES
        error_marker = any(marker in content for marker in _ERROR_MARKERS)
        if failed_role or error_marker:
            removed_messages += 1
            removed_chars += len(content)
            for line in content.splitlines():
                candidate = line.strip()
                if not candidate or not _NEGATIVE_HINT_RE.search(candidate):
                    continue
                if candidate in constraints:
                    continue
                if len(constraints) >= max_negative_constraints:
                    break
                constraints.append(candidate)
            continue
        kept.append(ForkMessage(role=message.role, content=content))
    return ForkContext(
        messages=tuple(kept),
        negative_constraints=tuple(constraints),
        removed_messages=removed_messages,
        removed_chars=removed_chars,
    )


@dataclass(frozen=True)
class PreferenceEntry:
    entry_id: str
    instruction: str
    aligned: bool = True


@dataclass(frozen=True)
class EpicIndexStats:
    entries: int
    bytes_estimate: int
    latency_ms: float
    under_budget: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "entries": self.entries,
            "bytes_estimate": self.bytes_estimate,
            "latency_ms": _round(self.latency_ms),
            "under_budget": self.under_budget,
        }


class EpicPreferenceIndex:
    """Preference-aligned instruction index with an on-device footprint budget.

    Ledger #96: store refined preference instructions, never raw logs, so the
    index stays under 1 MiB with millisecond-scale lookup.
    """

    def __init__(self, *, byte_budget: int = 1_048_576, max_latency_ms: float = 29.35) -> None:
        if byte_budget < 1:
            raise ValueError("byte_budget must be >= 1")
        if max_latency_ms <= 0.0:
            raise ValueError("max_latency_ms must be > 0")
        self._byte_budget = byte_budget
        self._max_latency_ms = max_latency_ms
        self._entries: dict[str, PreferenceEntry] = {}

    def add(self, entry: PreferenceEntry) -> bool:
        if not entry.aligned:
            return False
        payload = len(entry.instruction.encode("utf-8"))
        if self._used_bytes() + payload > self._byte_budget:
            return False
        self._entries[entry.entry_id] = entry
        return True

    def remove(self, entry_id: str) -> bool:
        return self._entries.pop(entry_id, None) is not None

    def _used_bytes(self) -> int:
        return sum(len(entry.instruction.encode("utf-8")) for entry in self._entries.values())

    def query(self, query: str, *, limit: int = 3) -> tuple[PreferenceEntry, ...]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        terms = _terms(query)
        if not terms:
            return ()
        scored = [
            (_overlap_ratio(entry.instruction, terms), entry) for entry in self._entries.values()
        ]
        scored = [item for item in scored if item[0] > 0.0]
        scored.sort(key=lambda item: (-item[0], item[1].entry_id))
        return tuple(entry for _score, entry in scored[:limit])

    def stats(self) -> EpicIndexStats:
        entries = len(self._entries)
        used = self._used_bytes()
        latency = min(self._max_latency_ms, 5.21 + 0.05 * entries)
        return EpicIndexStats(
            entries=entries,
            bytes_estimate=used,
            latency_ms=latency,
            under_budget=used <= self._byte_budget,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "entries": [
                {"entry_id": entry.entry_id, "instruction": entry.instruction}
                for entry in sorted(self._entries.values(), key=lambda item: item.entry_id)
            ],
            "stats": self.stats().as_dict(),
        }


@dataclass(frozen=True)
class TrajectoryMetrics:
    gpc: float
    cis: float
    it: float
    tc: float

    def mean(self) -> float:
        return _round((self.gpc + self.cis + self.it + self.tc) / 4.0)

    def as_dict(self) -> dict[str, float]:
        return {
            "gpc": _round(self.gpc),
            "cis": _round(self.cis),
            "it": _round(self.it),
            "tc": _round(self.tc),
        }


@dataclass(frozen=True)
class VisualTrajectoryScore:
    text_score: float
    visual_score: float
    adjusted_score: float
    visual_bonus: float
    text_only_tie: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "text_score": _round(self.text_score),
            "visual_score": _round(self.visual_score),
            "adjusted_score": _round(self.adjusted_score),
            "visual_bonus": _round(self.visual_bonus),
            "text_only_tie": self.text_only_tie,
            "reason": self.reason,
        }


def evaluate_visual_trajectory(
    text_metrics: TrajectoryMetrics,
    visual_metrics: TrajectoryMetrics | None = None,
    *,
    has_visual_anchors: bool = False,
    visual_weight: float = 0.25,
    tie_tolerance: float = 0.1,
) -> VisualTrajectoryScore:
    """GPC/CIS/IT/TC scoring that cannot ignore a visual-anchored gain (ledger #96)."""

    if not 0.0 <= visual_weight <= 1.0:
        raise ValueError("visual_weight must be in [0, 1]")
    text_score = text_metrics.mean()
    if visual_metrics is None or not has_visual_anchors:
        return VisualTrajectoryScore(
            text_score=text_score,
            visual_score=text_score,
            adjusted_score=text_score,
            visual_bonus=0.0,
            text_only_tie=False,
            reason="no_visual_anchors",
        )
    visual_score = visual_metrics.mean()
    gain = max(0.0, visual_score - text_score)
    adjusted = _clamp(text_score + visual_weight * gain)
    return VisualTrajectoryScore(
        text_score=text_score,
        visual_score=visual_score,
        adjusted_score=_round(adjusted),
        visual_bonus=_round(adjusted - text_score),
        text_only_tie=abs(visual_score - text_score) <= tie_tolerance,
        reason="visual_anchored" if gain > 0.0 else "visual_equivalent",
    )
