"""Phase-17 supervision contracts (ledger schemes 97-102).

Pure deterministic helpers for the agentic oversight index, amortized
preference questions, predictive-coding consolidation, three-state memory,
mixed-initiative review scaffolding and the five-layer maturity scorecard.
No default workflow wiring.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "AmortizedQuestion",
    "AoiInputs",
    "AoiReport",
    "Belief",
    "ConsolidationAction",
    "ConsolidationDecision",
    "EvoMemoryBundle",
    "GapHighlight",
    "KnowledgeGap",
    "LAYER_GATES",
    "LAYER_SCHEMES",
    "LayerGate",
    "LayerGateResult",
    "LayerMetrics",
    "MaturityScorecard",
    "PersistentFact",
    "PreCoMemConsolidator",
    "PreferenceQuestion",
    "ProfileHypothesis",
    "ReasoningState",
    "RelationalState",
    "RehearsalResult",
    "SourceCard",
    "amortized_voi",
    "compile_reasoning_state",
    "compute_aoi",
    "detect_knowledge_gaps",
    "effective_surprisal",
    "evaluate_maturity",
    "insert_source_card",
    "promote_hypothesis",
    "rehearsal_gate",
    "select_questions",
]

_METRIC_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:元|天|小时|公里|km|KM|米|℃|度|斤|kg|KG|人)")
_TERM_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_SCHEME_RE = re.compile(r"#?\s*(\d+)")


def _round(value: float) -> float:
    return round(float(value), 4)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _terms(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    bigrams = {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}
    words = set(_TERM_RE.findall(text))
    return bigrams | words


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a = {str(item) for item in left}
    b = {str(item) for item in right}
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _scheme_id(value: str) -> str:
    match = _SCHEME_RE.fullmatch(str(value).strip())
    if match is None:
        return str(value).strip()
    return f"#{match.group(1)}"


@dataclass(frozen=True)
class AoiInputs:
    delivered_value: float
    api_cost: float = 0.0
    human_minutes: float = 0.0
    human_weight: float = 1.0


@dataclass(frozen=True)
class AoiReport:
    aoi: float
    total_cost: float
    value_per_minute: float
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "aoi": _round(self.aoi),
            "total_cost": _round(self.total_cost),
            "value_per_minute": _round(self.value_per_minute),
            "reasons": list(self.reasons),
        }


def compute_aoi(inputs: AoiInputs) -> AoiReport:
    """Agentic oversight index: delivered value over compute + human burden (ledger #97)."""

    if inputs.human_weight < 0.0:
        raise ValueError("human_weight must be >= 0")
    if inputs.api_cost < 0.0 or inputs.human_minutes < 0.0:
        raise ValueError("api_cost and human_minutes must be >= 0")
    reasons: list[str] = []
    total_cost = float(inputs.api_cost) + float(inputs.human_weight) * float(inputs.human_minutes)
    if total_cost <= 0.0:
        aoi = 0.0
        reasons.append("no_cost")
    else:
        aoi = float(inputs.delivered_value) / total_cost
    if inputs.human_minutes <= 0.0:
        value_per_minute = 0.0
        reasons.append("no_human_minutes")
    else:
        value_per_minute = float(inputs.delivered_value) / float(inputs.human_minutes)
    return AoiReport(
        aoi=aoi,
        total_cost=total_cost,
        value_per_minute=value_per_minute,
        reasons=tuple(reasons or ("computed",)),
    )


@dataclass(frozen=True)
class RehearsalResult:
    agreement_rate: float
    samples: int
    promote: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "agreement_rate": _round(self.agreement_rate),
            "samples": self.samples,
            "promote": self.promote,
            "reasons": list(self.reasons),
        }


def rehearsal_gate(
    decisions: Sequence[bool],
    expected: Sequence[bool],
    *,
    min_samples: int = 20,
    threshold: float = 0.95,
) -> RehearsalResult:
    """Shadow rehearsal before raising the delegation level (ledger #97)."""

    if len(decisions) != len(expected):
        raise ValueError("decisions and expected must have the same length")
    if min_samples < 1:
        raise ValueError("min_samples must be >= 1")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be in [0, 1]")
    samples = len(decisions)
    if samples == 0:
        return RehearsalResult(
            agreement_rate=0.0,
            samples=0,
            promote=False,
            reasons=("insufficient_samples",),
        )
    matches = sum(
        1 for actual, want in zip(decisions, expected, strict=True) if bool(actual) == bool(want)
    )
    agreement = matches / samples
    reasons: list[str] = []
    if samples < min_samples:
        reasons.append("insufficient_samples")
    if agreement < threshold:
        reasons.append("agreement_below_threshold")
    promote = not reasons
    return RehearsalResult(
        agreement_rate=agreement,
        samples=samples,
        promote=promote,
        reasons=tuple(reasons or ("promote_auto_approve",)),
    )


@dataclass(frozen=True)
class PreferenceQuestion:
    question_id: str
    target_preference: str
    reuse_probability: float
    utility_gain: float
    friction_cost: float
    reusable_across_weeks: bool = True


@dataclass(frozen=True)
class AmortizedQuestion:
    question: PreferenceQuestion
    amortized_voi: float
    accepted: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question.question_id,
            "target_preference": self.question.target_preference,
            "amortized_voi": _round(self.amortized_voi),
            "accepted": self.accepted,
        }


def amortized_voi(question: PreferenceQuestion, *, future_tasks: int = 1) -> float:
    """Value of asking now, amortized over future tasks that can reuse it (ledger #98)."""

    if not question.reusable_across_weeks:
        return _round(-float(question.friction_cost))
    tasks = max(1, int(future_tasks))
    value = float(question.reuse_probability) * float(question.utility_gain) * tasks
    return _round(value - float(question.friction_cost))


def select_questions(
    questions: Sequence[PreferenceQuestion],
    *,
    future_tasks: int = 1,
    max_questions: int = 1,
    min_voi: float = 0.0,
    top_ratio: float = 0.276,
) -> tuple[AmortizedQuestion, ...]:
    """Keep only the high-leverage share of candidate questions (ledger #98)."""

    if max_questions < 0:
        raise ValueError("max_questions must be >= 0")
    if not 0.0 <= top_ratio <= 1.0:
        raise ValueError("top_ratio must be in [0, 1]")
    scored = [
        AmortizedQuestion(
            question=question,
            amortized_voi=amortized_voi(question, future_tasks=future_tasks),
            accepted=False,
        )
        for question in questions
    ]
    scored.sort(key=lambda item: (-item.amortized_voi, item.question.question_id))
    eligible = [
        item
        for item in scored
        if item.question.reusable_across_weeks and item.amortized_voi > min_voi
    ]
    budget = max(1, math.ceil(len(questions) * top_ratio)) if questions else 0
    allowed = min(max_questions, budget, len(eligible))
    accepted_ids = {item.question.question_id for item in eligible[:allowed]}
    return tuple(
        AmortizedQuestion(
            question=item.question,
            amortized_voi=item.amortized_voi,
            accepted=item.question.question_id in accepted_ids,
        )
        for item in scored
    )


class ConsolidationAction(StrEnum):
    MAINTAIN = "maintain"
    PROFILE = "profile"
    CORRECT = "correct"


@dataclass(frozen=True)
class Belief:
    fact_id: str
    text: str
    confidence: float = 0.6
    evidence_count: int = 1


@dataclass(frozen=True)
class ConsolidationDecision:
    action: ConsolidationAction
    surprisal: float
    belief_id: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": str(self.action),
            "surprisal": _round(self.surprisal),
            "belief_id": self.belief_id,
            "reason": self.reason,
        }


def effective_surprisal(
    observation: str,
    belief: Belief,
    *,
    contradiction: float = 0.0,
) -> float:
    """Semantic divergence blended with contradiction evidence (ledger #99)."""

    divergence = 1.0 - _jaccard(_terms(observation), _terms(belief.text))
    blended = 0.65 * _clamp(divergence) + 0.35 * _clamp(contradiction)
    return _round(_clamp(blended))


class PreCoMemConsolidator:
    """Route observations to maintain / waiting room / soft correction (ledger #99)."""

    def __init__(self, *, profile_threshold: float = 0.45, correct_threshold: float = 0.75) -> None:
        if not 0.0 <= profile_threshold <= 1.0:
            raise ValueError("profile_threshold must be in [0, 1]")
        if not 0.0 <= correct_threshold <= 1.0:
            raise ValueError("correct_threshold must be in [0, 1]")
        if correct_threshold < profile_threshold:
            raise ValueError("correct_threshold must be >= profile_threshold")
        self._profile_threshold = profile_threshold
        self._correct_threshold = correct_threshold

    def decide(
        self,
        observation: str,
        belief: Belief,
        *,
        contradiction: float = 0.0,
    ) -> ConsolidationDecision:
        surprisal = effective_surprisal(observation, belief, contradiction=contradiction)
        if surprisal >= self._correct_threshold:
            action = ConsolidationAction.CORRECT
            reason = "reliable_contradiction"
        elif surprisal >= self._profile_threshold:
            action = ConsolidationAction.PROFILE
            reason = "ambiguous_signal_waiting_room"
        else:
            action = ConsolidationAction.MAINTAIN
            reason = "consistent_with_belief"
        return ConsolidationDecision(
            action=action,
            surprisal=surprisal,
            belief_id=belief.fact_id,
            reason=reason,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "profile_threshold": _round(self._profile_threshold),
            "correct_threshold": _round(self._correct_threshold),
        }


@dataclass(frozen=True)
class ProfileHypothesis:
    hypothesis_id: str
    statement: str
    confidence: float = 0.4
    corroborations: int = 1
    weeks_observed: int = 1


def promote_hypothesis(
    hypothesis: ProfileHypothesis,
    *,
    min_corroborations: int = 2,
    min_weeks: int = 2,
) -> ConsolidationDecision:
    """Waiting-room hypothesis only graduates after repeated corroboration (ledger #99)."""

    if min_corroborations < 1 or min_weeks < 1:
        raise ValueError("min_corroborations and min_weeks must be >= 1")
    confirmed = (
        hypothesis.corroborations >= min_corroborations and hypothesis.weeks_observed >= min_weeks
    )
    return ConsolidationDecision(
        action=ConsolidationAction.CORRECT if confirmed else ConsolidationAction.PROFILE,
        surprisal=_round(_clamp(1.0 - hypothesis.confidence)),
        belief_id=hypothesis.hypothesis_id,
        reason="hypothesis_confirmed" if confirmed else "awaiting_corroboration",
    )


@dataclass(frozen=True)
class PersistentFact:
    fact_id: str
    text: str
    scope: tuple[str, ...] = ()
    valid_from: str = ""
    valid_until: str = ""
    superseded_by: str = ""


@dataclass(frozen=True)
class RelationalState:
    fact_id: str
    relation: str
    target_id: str
    note: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "fact_id": self.fact_id,
            "relation": self.relation,
            "target_id": self.target_id,
            "note": self.note,
        }


@dataclass(frozen=True)
class ReasoningState:
    instructions: tuple[str, ...]
    activated: tuple[str, ...]
    masked: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "instructions": list(self.instructions),
            "activated": list(self.activated),
            "masked": list(self.masked),
        }

    def render(self) -> str:
        return "\n".join(self.instructions)


@dataclass(frozen=True)
class EvoMemoryBundle:
    facts: tuple[PersistentFact, ...]
    relations: tuple[RelationalState, ...]
    reasoning: ReasoningState

    def as_dict(self) -> dict[str, Any]:
        return {
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "text": fact.text,
                    "scope": list(fact.scope),
                    "valid_until": fact.valid_until,
                    "superseded_by": fact.superseded_by,
                }
                for fact in self.facts
            ],
            "relations": [relation.as_dict() for relation in self.relations],
            "reasoning": self.reasoning.as_dict(),
        }


def compile_reasoning_state(
    facts: Sequence[PersistentFact],
    relations: Sequence[RelationalState] = (),
    *,
    request_context: Iterable[str] = (),
    current_date: str = "",
) -> ReasoningState:
    """Facts plus relational state compiled into a 3-line request instruction (ledger #100)."""

    context = {str(item) for item in request_context if str(item)}
    activated: list[str] = []
    masked: list[str] = []
    activated_text: list[str] = []
    for fact in facts:
        superseded = bool(fact.superseded_by)
        expired = bool(fact.valid_until and current_date and fact.valid_until < current_date)
        out_of_scope = bool(fact.scope) and not set(fact.scope) & context
        if superseded or expired or out_of_scope:
            masked.append(fact.fact_id)
        else:
            activated.append(fact.fact_id)
            activated_text.append(fact.text)
    relation_lines = [
        f"{relation.fact_id}-{relation.relation}->{relation.target_id}"
        for relation in relations
        if relation.fact_id in activated and relation.target_id in activated
    ]
    instructions = (
        "激活：" + ("；".join(activated_text) if activated_text else "无"),
        "屏蔽：" + ("；".join(masked) if masked else "无"),
        "关联：" + ("；".join(relation_lines) if relation_lines else "无"),
    )
    return ReasoningState(
        instructions=instructions,
        activated=tuple(activated),
        masked=tuple(masked),
    )


@dataclass(frozen=True)
class KnowledgeGap:
    span: str
    reason: str
    severity: str = "medium"

    def as_dict(self) -> dict[str, str]:
        return {"span": self.span, "reason": self.reason, "severity": self.severity}


@dataclass(frozen=True)
class SourceCard:
    card_id: str
    title: str
    snippet: str
    source_url: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "card_id": self.card_id,
            "title": self.title,
            "snippet": self.snippet,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class GapHighlight:
    gap: KnowledgeGap
    cards: tuple[SourceCard, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "gap": self.gap.as_dict(),
            "cards": [card.as_dict() for card in self.cards],
        }


def detect_knowledge_gaps(
    draft: str,
    *,
    required_topics: Iterable[str] = (),
    supported_metrics: Iterable[str] = (),
) -> tuple[KnowledgeGap, ...]:
    """Highlight missing topics and unsupported numbers for inline review (ledger #101)."""

    supported = {str(item).strip() for item in supported_metrics if str(item).strip()}
    gaps: list[KnowledgeGap] = []
    seen: set[tuple[str, str]] = set()
    for topic in required_topics:
        name = str(topic).strip()
        if not name or name in draft:
            continue
        key = (name, "missing_required_topic")
        if key in seen:
            continue
        seen.add(key)
        gaps.append(KnowledgeGap(span=name, reason="missing_required_topic", severity="high"))
    for match in _METRIC_RE.findall(draft):
        metric = match.strip()
        if metric in supported:
            continue
        key = (metric, "unsupported_metric")
        if key in seen:
            continue
        seen.add(key)
        gaps.append(KnowledgeGap(span=metric, reason="unsupported_metric", severity="medium"))
    return tuple(gaps)


def build_gap_highlights(
    gaps: Sequence[KnowledgeGap],
    cards: Sequence[SourceCard],
    *,
    max_cards: int = 2,
) -> tuple[GapHighlight, ...]:
    if max_cards < 0:
        raise ValueError("max_cards must be >= 0")
    highlights: list[GapHighlight] = []
    for gap in gaps:
        terms = _terms(gap.span)
        matched: list[SourceCard] = []
        for card in cards:
            if _jaccard(terms, _terms(card.snippet + card.title)) > 0.0:
                matched.append(card)
        highlights.append(GapHighlight(gap=gap, cards=tuple(matched[:max_cards])))
    return tuple(highlights)


def insert_source_card(draft: str, gap: KnowledgeGap, card: SourceCard) -> str:
    """Attach a source-anchored card next to the highlighted gap (ledger #101)."""

    insertion = f"（补充：{card.snippet}｜来源：{card.title}）"
    if gap.span and gap.span in draft:
        return draft.replace(gap.span, f"{gap.span}{insertion}", 1)
    return f"{draft}{insertion}"


@dataclass(frozen=True)
class LayerGate:
    metric: str
    op: str
    target: float


@dataclass(frozen=True)
class LayerGateResult:
    metric: str
    value: float
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "value": _round(self.value), "passed": self.passed}


@dataclass(frozen=True)
class LayerMetrics:
    layer: str
    landed: tuple[str, ...]
    total: int
    ratio: float
    gates: tuple[LayerGateResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "landed": list(self.landed),
            "total": self.total,
            "ratio": _round(self.ratio),
            "gates": [gate.as_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class MaturityScorecard:
    layers: tuple[LayerMetrics, ...]
    overall_ratio: float
    gaps: tuple[str, ...]
    gates_passed: bool
    next_actions: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "layers": [layer.as_dict() for layer in self.layers],
            "overall_ratio": _round(self.overall_ratio),
            "gaps": list(self.gaps),
            "gates_passed": self.gates_passed,
            "next_actions": list(self.next_actions),
        }


LAYER_SCHEMES: Mapping[str, tuple[str, ...]] = {
    "layer1": ("#19", "#41", "#83", "#53"),
    "layer2": ("#10", "#85", "#49", "#99", "#100", "#93"),
    "layer3": ("#46", "#82", "#81", "#57", "#25", "#30", "#51", "#95"),
    "layer4": ("#5", "#1", "#79", "#32", "#76", "#91", "#75"),
    "layer5": ("#43", "#39", "#55", "#62", "#3", "#56", "#97", "#98"),
}

LAYER_GATES: Mapping[str, tuple[LayerGate, ...]] = {
    "layer1": (
        LayerGate("db_size_reduction", "<=", -0.8),
        LayerGate("privacy_residual", "<=", 0.0),
    ),
    "layer2": (
        LayerGate("cache_hit_ratio", ">=", 0.85),
        LayerGate("compaction_violation_rate", "<=", 0.0),
    ),
    "layer3": (
        LayerGate("gui_token_saving", ">=", 0.8),
        LayerGate("pass_power_k", ">=", 0.95),
    ),
    "layer4": (LayerGate("detection_delay", "<=", 1.0),),
    "layer5": (
        LayerGate("human_minutes", "<=", 30.0),
        LayerGate("aoi_trend", ">=", 0.0),
    ),
}


def _gate_passes(op: str, value: float, target: float) -> bool:
    if op == ">=":
        return value >= target
    if op == "<=":
        return value <= target
    raise ValueError(f"unsupported gate op: {op}")


def evaluate_maturity(
    landed: Mapping[str, Iterable[str]],
    *,
    metrics: Mapping[str, Mapping[str, float]] | None = None,
) -> MaturityScorecard:
    """Five-layer maturity scorecard for the ledger rollout (ledger #102)."""

    observed = {layer: {_scheme_id(item) for item in values} for layer, values in landed.items()}
    measured = metrics or {}
    layers: list[LayerMetrics] = []
    gaps: list[str] = []
    landed_total = 0
    planned_total = 0
    all_gates_passed = True
    for layer, schemes in LAYER_SCHEMES.items():
        present = tuple(sorted(observed.get(layer, set()) & set(schemes)))
        landed_total += len(present)
        planned_total += len(schemes)
        for scheme in schemes:
            if scheme not in present:
                gaps.append(f"{layer}:{scheme}")
        gate_results: list[LayerGateResult] = []
        for gate in LAYER_GATES.get(layer, ()):
            raw = measured.get(layer, {}).get(gate.metric)
            if raw is None:
                gate_results.append(LayerGateResult(metric=gate.metric, value=0.0, passed=False))
                gaps.append(f"{layer}:metric:{gate.metric}")
                all_gates_passed = False
                continue
            value = float(raw)
            passed = _gate_passes(gate.op, value, gate.target)
            gate_results.append(LayerGateResult(metric=gate.metric, value=value, passed=passed))
            if not passed:
                all_gates_passed = False
        ratio = len(present) / len(schemes) if schemes else 0.0
        layers.append(
            LayerMetrics(
                layer=layer,
                landed=present,
                total=len(schemes),
                ratio=ratio,
                gates=tuple(gate_results),
            )
        )
    overall = landed_total / planned_total if planned_total else 0.0
    return MaturityScorecard(
        layers=tuple(layers),
        overall_ratio=overall,
        gaps=tuple(gaps),
        gates_passed=all_gates_passed,
        next_actions=tuple(gaps[:3]),
    )
