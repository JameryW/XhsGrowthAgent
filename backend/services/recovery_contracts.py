"""Phase-9 recovery contracts (ledger schemes 49-54).

Deterministic helpers for revision diff chains, TRAJDEBUG critical-error
rollback, backbone-aware harness selection, MedMMV combined uncertainty,
MemCut closure deletion and MemComposer memory assembly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "ClosureDeletionResult",
    "ComposedMemory",
    "FactRevisionChain",
    "HarnessCard",
    "InputIntegrityReport",
    "MemoryCandidate",
    "MemoryKind",
    "MemoryRecord",
    "ModelFamily",
    "OutlineCandidate",
    "OutlineScore",
    "RevisionEntry",
    "RollbackPlan",
    "TrajectoryError",
    "build_repair_directive",
    "build_revision_chain",
    "check_input_integrity",
    "classify_error_lifecycle",
    "collect_source_closure",
    "combined_uncertainty",
    "compose_memories",
    "delete_memory_closure",
    "locate_critical_error",
    "rank_outlines",
    "render_revision_diffs",
    "resolve_current_facts",
    "select_harness_card",
    "select_primary_outline",
]


def _number(value: object, default: float = 0.0) -> float:
    """Coerce an unknown scalar to float without raising on bad input."""
    if isinstance(value, bool):
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _text(value: object) -> str:
    """Coerce an unknown value to a stripped string."""
    return value.strip() if isinstance(value, str) else ""


def _unit(value: float) -> float:
    """Clamp a float into [0, 1]."""
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class RevisionEntry:
    """One human revision attached to a memory fact or note field."""

    revision_id: str
    source_turn_id: str
    field: str
    old_text: str
    new_text: str
    operator_comment: str = ""
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "source_turn_id": self.source_turn_id,
            "field": self.field,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "operator_comment": self.operator_comment,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class FactRevisionChain:
    """A fact plus its most recent human revisions (zero-LLM decoration)."""

    fact_id: str
    fact_text: str
    revisions: tuple[RevisionEntry, ...] = field(default_factory=tuple)
    supersedes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "fact_text": self.fact_text,
            "revisions": [revision.as_dict() for revision in self.revisions],
            "supersedes": self.supersedes,
        }


def build_revision_chain(
    fact_id: str,
    fact_text: str,
    revisions: Iterable[RevisionEntry],
    *,
    limit: int = 3,
    supersedes: str = "",
) -> FactRevisionChain:
    """Attach the latest ``limit`` revisions to a fact without calling an LLM."""
    ordered = sorted(revisions, key=lambda item: (item.created_at, item.revision_id))
    recent = tuple(ordered[-max(0, int(limit)) :]) if limit else ()
    return FactRevisionChain(
        fact_id=_text(fact_id),
        fact_text=_text(fact_text),
        revisions=recent,
        supersedes=_text(supersedes),
    )


def render_revision_diffs(chain: FactRevisionChain) -> list[dict[str, Any]]:
    """Render exact old/new diff payloads for prompt injection."""
    return [
        {
            "revision_id": revision.revision_id,
            "source_turn_id": revision.source_turn_id,
            "field": revision.field,
            "old": revision.old_text,
            "new": revision.new_text,
            "operator_comment": revision.operator_comment,
            "created_at": revision.created_at,
        }
        for revision in chain.revisions
    ]


def resolve_current_facts(facts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fold a supersedes chain and return only its current leaf facts."""
    items = [dict(item) for item in facts]
    superseded_by: dict[str, str] = {}
    for item in items:
        fact_id = _text(item.get("fact_id"))
        parent = _text(item.get("supersedes"))
        if fact_id and parent:
            superseded_by[parent] = fact_id
    current: list[dict[str, Any]] = []
    for item in items:
        fact_id = _text(item.get("fact_id"))
        if not fact_id or fact_id in superseded_by:
            continue
        current.append(
            {
                "fact_id": fact_id,
                "text": _text(item.get("text")),
                "supersedes": _text(item.get("supersedes")),
                "reason": _text(item.get("reason")),
            }
        )
    current.sort(key=lambda item: str(item["fact_id"]))
    return current


@dataclass(frozen=True)
class TrajectoryError:
    """One local error observed in a long-running agent trajectory."""

    step: int
    node: str
    message: str
    category: str = "local"
    is_critical: bool = False
    downstream_recovered: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "node": self.node,
            "message": self.message,
            "category": self.category,
            "is_critical": self.is_critical,
            "downstream_recovered": self.downstream_recovered,
        }


@dataclass(frozen=True)
class RollbackPlan:
    """Targeted checkpoint rewind generated by the TRAJDEBUG router."""

    critical_step: int
    node: str
    checkpoint_hint: str
    directive: str
    preserved_steps: tuple[int, ...]
    dormant_steps: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "critical_step": self.critical_step,
            "node": self.node,
            "checkpoint_hint": self.checkpoint_hint,
            "directive": self.directive,
            "preserved_steps": list(self.preserved_steps),
            "dormant_steps": list(self.dormant_steps),
        }


def classify_error_lifecycle(
    errors: Iterable[TrajectoryError],
) -> dict[str, tuple[int, ...]]:
    """Split errors into critical, dormant and self-healed lifecycle buckets."""
    critical: list[int] = []
    dormant: list[int] = []
    self_healed: list[int] = []
    for error in errors:
        if error.downstream_recovered:
            self_healed.append(error.step)
        elif error.is_critical:
            critical.append(error.step)
        else:
            dormant.append(error.step)
    return {
        "critical": tuple(sorted(critical)),
        "dormant": tuple(sorted(dormant)),
        "self_healed": tuple(sorted(self_healed)),
    }


def build_repair_directive(error: TrajectoryError) -> str:
    """Build the one-line repair constraint injected into L4 after a rewind."""
    node = _text(error.node) or "unknown"
    message = _text(error.message) or "critical error"
    return f"Rewind to before {node}: fix `{message}`; preserve earlier verified artifacts."


def locate_critical_error(
    errors: Iterable[TrajectoryError], node_order: Sequence[str] = ()
) -> RollbackPlan | None:
    """Locate the earliest unrecovered critical error and its rollback plan."""
    items = list(errors)
    rank = {_text(node): index for index, node in enumerate(node_order)}
    critical = [error for error in items if error.is_critical and not error.downstream_recovered]
    if not critical:
        return None
    critical.sort(key=lambda error: (error.step, rank.get(_text(error.node), 999)))
    root = critical[0]
    preserved = tuple(
        sorted(
            error.step
            for error in items
            if error.step < root.step and not error.is_critical and not error.downstream_recovered
        )
    )
    dormant = tuple(
        sorted(
            error.step
            for error in items
            if not error.is_critical and not error.downstream_recovered
        )
    )
    return RollbackPlan(
        critical_step=root.step,
        node=_text(root.node),
        checkpoint_hint=f"checkpoint-before-{_text(root.node) or 'node'}-step-{root.step}",
        directive=build_repair_directive(root),
        preserved_steps=preserved,
        dormant_steps=dormant,
    )


class ModelFamily(StrEnum):
    """Backbone family used to select a harness card."""

    MIMO = "mimo"
    DEEPSEEK = "deepseek"
    OTHER = "other"


@dataclass(frozen=True)
class HarnessCard:
    """Model-specific harness configuration for fallback-safe routing."""

    family: ModelFamily
    system_suffix: str
    json_strictness: str
    few_shot_format: str
    temperature: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family.value,
            "system_suffix": self.system_suffix,
            "json_strictness": self.json_strictness,
            "few_shot_format": self.few_shot_format,
            "temperature": round(self.temperature, 2),
        }


_HARNESS_CARDS: dict[ModelFamily, HarnessCard] = {
    ModelFamily.MIMO: HarnessCard(
        family=ModelFamily.MIMO,
        system_suffix="先给出结论，再按组内相对优劣精炼候选版本。",
        json_strictness="schema-first",
        few_shot_format="grouped-candidates",
        temperature=0.7,
    ),
    ModelFamily.DEEPSEEK: HarnessCard(
        family=ModelFamily.DEEPSEEK,
        system_suffix=(
            "[Step 0 - Input Integrity Check]: Before polishing or matching, explicitly list any "
            "missing, truncated, or self-contradictory fields in Context C or Tool Output T; if "
            "critical facts are missing, emit NEEDS_UPSTREAM_REPAIR instead of guessing."
        ),
        json_strictness="strict",
        few_shot_format="single-example",
        temperature=0.4,
    ),
    ModelFamily.OTHER: HarnessCard(
        family=ModelFamily.OTHER,
        system_suffix="",
        json_strictness="strict",
        few_shot_format="single-example",
        temperature=0.6,
    ),
}


def select_harness_card(model_id: str) -> HarnessCard:
    """Select the harness card matching the actual backbone model id."""
    value = _text(model_id).lower()
    if "mimo" in value:
        return _HARNESS_CARDS[ModelFamily.MIMO]
    if "deepseek" in value:
        return _HARNESS_CARDS[ModelFamily.DEEPSEEK]
    return _HARNESS_CARDS[ModelFamily.OTHER]


@dataclass(frozen=True)
class InputIntegrityReport:
    """Deterministic pre-call integrity check for fallback models."""

    missing: tuple[str, ...]
    truncated: tuple[str, ...]
    contradictory: tuple[str, ...]

    @property
    def needs_upstream_repair(self) -> bool:
        return bool(self.missing or self.truncated or self.contradictory)

    def as_dict(self) -> dict[str, Any]:
        return {
            "missing": list(self.missing),
            "truncated": list(self.truncated),
            "contradictory": list(self.contradictory),
            "needs_upstream_repair": self.needs_upstream_repair,
        }


def check_input_integrity(
    payload: Mapping[str, Any], required_fields: Iterable[str]
) -> InputIntegrityReport:
    """Flag missing/truncated/contradictory input fields before a fallback call."""
    missing: list[str] = []
    truncated: list[str] = []
    contradictory: list[str] = []
    for field_name in required_fields:
        key = _text(field_name)
        if not key:
            continue
        if key not in payload or payload[key] in (None, "", [], {}):
            missing.append(key)
            continue
        value = payload[key]
        if isinstance(value, str) and (
            value.rstrip().endswith(("...", "…"))
            or value.strip().lower() in {"[truncated]", "truncated"}
        ):
            truncated.append(key)
    conflicts = payload.get("_conflicts")
    if isinstance(conflicts, Mapping):
        contradictory.extend(_text(key) for key in conflicts if _text(key))
    elif isinstance(conflicts, (list, tuple, set)):
        contradictory.extend(_text(item) for item in conflicts if _text(item))
    if payload.get("contradictory") is True:
        contradictory.append("_payload")
    return InputIntegrityReport(
        missing=tuple(sorted(set(missing))),
        truncated=tuple(sorted(set(truncated))),
        contradictory=tuple(sorted(set(contradictory))),
    )


@dataclass(frozen=True)
class OutlineCandidate:
    """A content outline scored before heavy generation."""

    outline_id: str
    evidence_alignment: float
    persona_coherence: float
    estimated_repair_cost: float
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "outline_id": self.outline_id,
            "evidence_alignment": round(self.evidence_alignment, 4),
            "persona_coherence": round(self.persona_coherence, 4),
            "estimated_repair_cost": round(self.estimated_repair_cost, 4),
            "label": self.label,
        }


@dataclass(frozen=True)
class OutlineScore:
    """Combined-uncertainty score for one outline."""

    candidate: OutlineCandidate
    combined_uncertainty: float

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.candidate.as_dict(),
            "combined_uncertainty": round(self.combined_uncertainty, 4),
        }


def combined_uncertainty(
    *,
    evidence_alignment: float,
    persona_coherence: float,
    estimated_repair_cost: float,
) -> float:
    """MedMMV CU = 0.45*(1-evidence) + 0.30*(1-persona) + 0.25*repair_cost."""
    evidence = _unit(_number(evidence_alignment))
    persona = _unit(_number(persona_coherence))
    repair = _unit(_number(estimated_repair_cost))
    return round(0.45 * (1.0 - evidence) + 0.30 * (1.0 - persona) + 0.25 * repair, 4)


def rank_outlines(outlines: Iterable[OutlineCandidate]) -> list[OutlineScore]:
    """Rank outlines by ascending combined uncertainty (best first)."""
    scores = [
        OutlineScore(
            candidate=outline,
            combined_uncertainty=combined_uncertainty(
                evidence_alignment=outline.evidence_alignment,
                persona_coherence=outline.persona_coherence,
                estimated_repair_cost=outline.estimated_repair_cost,
            ),
        )
        for outline in outlines
    ]
    scores.sort(key=lambda item: (item.combined_uncertainty, item.candidate.outline_id))
    return scores


def select_primary_outline(outlines: Iterable[OutlineCandidate]) -> OutlineScore:
    """Select the lowest-CU outline; raises when no candidates exist."""
    ranked = rank_outlines(outlines)
    if not ranked:
        raise ValueError("at least one outline candidate is required")
    return ranked[0]


@dataclass(frozen=True)
class MemoryRecord:
    """A derived memory object with source-turn lineage."""

    record_id: str
    source_turn_ids: tuple[str, ...]
    kind: str = "fact"
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "source_turn_ids": list(self.source_turn_ids),
            "kind": self.kind,
            "text": self.text,
        }


@dataclass(frozen=True)
class ClosureDeletionResult:
    """Result of a minimal-evidence-cut transitive deletion."""

    deleted_ids: tuple[str, ...]
    retained_ids: tuple[str, ...]
    expanded_turns: tuple[str, ...]
    residual_recovery_rate: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "deleted_ids": list(self.deleted_ids),
            "retained_ids": list(self.retained_ids),
            "expanded_turns": list(self.expanded_turns),
            "residual_recovery_rate": round(self.residual_recovery_rate, 4),
        }


def _transitive_closure(
    records: Sequence[MemoryRecord], sensitive_turn_ids: Iterable[str]
) -> tuple[set[str], set[str]]:
    active_turns = {_text(turn) for turn in sensitive_turn_ids if _text(turn)}
    if not active_turns:
        return set(), set()
    deleted: set[str] = set()
    changed = True
    while changed:
        changed = False
        for record in records:
            if record.record_id in deleted:
                continue
            record_turns = {_text(turn) for turn in record.source_turn_ids if _text(turn)}
            if record_turns & active_turns:
                deleted.add(record.record_id)
                new_turns = record_turns - active_turns
                if new_turns:
                    active_turns |= new_turns
                    changed = True
    return deleted, active_turns


def collect_source_closure(
    records: Iterable[MemoryRecord], sensitive_turn_ids: Iterable[str]
) -> set[str]:
    """Return every record id in the source-turn evidence closure."""
    deleted, _ = _transitive_closure(list(records), sensitive_turn_ids)
    return deleted


def delete_memory_closure(
    records: Iterable[MemoryRecord], sensitive_turn_ids: Iterable[str]
) -> ClosureDeletionResult:
    """Delete the minimal evidence cut closure and report zero residual recovery."""
    items = list(records)
    sensitive = {_text(turn) for turn in sensitive_turn_ids if _text(turn)}
    deleted, expanded_turns = _transitive_closure(items, sensitive)
    retained = [record.record_id for record in items if record.record_id not in deleted]
    return ClosureDeletionResult(
        deleted_ids=tuple(sorted(deleted)),
        retained_ids=tuple(sorted(retained)),
        expanded_turns=tuple(sorted(expanded_turns - sensitive)),
        residual_recovery_rate=0.0,
    )


class MemoryKind(StrEnum):
    """Deterministic MemComposer topology buckets."""

    COMPLIANCE = "compliance"
    PERSONA = "persona"
    SCENE_PATTERN = "scene_pattern"
    HUMAN_DIFF = "human_diff"
    OTHER = "other"


_KIND_ORDER = {
    MemoryKind.COMPLIANCE: 0,
    MemoryKind.PERSONA: 1,
    MemoryKind.SCENE_PATTERN: 2,
    MemoryKind.HUMAN_DIFF: 3,
    MemoryKind.OTHER: 4,
}


@dataclass(frozen=True)
class MemoryCandidate:
    """One candidate memory for query-aware assembly."""

    memory_id: str
    content: str
    kind: MemoryKind = MemoryKind.OTHER
    relevance: float = 0.0
    utility: float = 0.0
    tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "kind": self.kind.value,
            "relevance": round(self.relevance, 4),
            "utility": round(self.utility, 4),
            "tokens": self.tokens,
        }


@dataclass(frozen=True)
class ComposedMemory:
    """Assembled memory selection with token accounting."""

    selected: tuple[MemoryCandidate, ...]
    total_tokens: int
    omitted_ids: tuple[str, ...]
    estimated_savings: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected": [item.as_dict() for item in self.selected],
            "total_tokens": self.total_tokens,
            "omitted_ids": list(self.omitted_ids),
            "estimated_savings": round(self.estimated_savings, 4),
        }


def compose_memories(
    candidates: Iterable[MemoryCandidate],
    *,
    max_tokens: int = 1600,
    max_items: int = 6,
    epsilon: float = 0.001,
) -> ComposedMemory:
    """Assemble memories by fixed topology and marginal utility density."""
    pool = list(candidates)
    budget = max(0, int(max_tokens))
    item_cap = max(0, int(max_items))
    floor = max(0.0, _number(epsilon, 0.001))
    ordered = sorted(
        pool,
        key=lambda item: (
            _KIND_ORDER.get(item.kind, 4),
            -_unit(item.relevance),
            -_unit(item.utility),
            item.memory_id,
        ),
    )
    selected: list[MemoryCandidate] = []
    total_tokens = 0
    omitted: list[str] = []
    for item in ordered:
        if len(selected) >= item_cap:
            omitted.append(item.memory_id)
            continue
        token_cost = max(1, int(item.tokens))
        density = _unit(item.utility) * _unit(item.relevance) / token_cost
        if density < floor:
            omitted.append(item.memory_id)
            continue
        if total_tokens + token_cost > budget:
            omitted.append(item.memory_id)
            continue
        selected.append(item)
        total_tokens += token_cost
    all_tokens = sum(max(1, int(item.tokens)) for item in pool)
    savings = 1.0 - (total_tokens / all_tokens) if all_tokens else 0.0
    return ComposedMemory(
        selected=tuple(selected),
        total_tokens=total_tokens,
        omitted_ids=tuple(omitted),
        estimated_savings=max(0.0, min(1.0, savings)),
    )
