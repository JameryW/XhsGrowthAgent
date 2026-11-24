"""Phase-12 optimization contracts (ledger schemes 67-72).

Pure deterministic helpers for harness evolution, belief tracking, forecast
co-evolution, multimodal scouting, cost-aware abstention, and organic-to-paid
boost decisions.  No LLM, database, or advertising API is called here.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

__all__ = [
    "AbstentionDecision",
    "BeliefTrapReport",
    "BeliefUpdate",
    "BoostInputs",
    "BoostRecommendation",
    "CostMatrix",
    "CoEvolutionUpdate",
    "CustomerBeliefState",
    "DeepScoutPlan",
    "ForecastRecord",
    "HarnessPreset",
    "HarnessVariant",
    "ScoutHop",
    "ScoutNote",
    "abstention_threshold",
    "co_evolve_forecasts",
    "detect_belief_trapping",
    "forecast_surprise",
    "pareto_frontier",
    "plan_multimodal_deep_scout",
    "recovery_actions",
    "recommend_boost",
    "route_with_abstention",
    "select_harness_presets",
    "update_belief_state",
]


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else default
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clip(value: Any) -> float:
    return min(1.0, max(0.0, _number(value)))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _texts(values: Iterable[Any] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    result: list[str] = []
    for value in values:
        text = _as_text(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


@dataclass(frozen=True)
class HarnessVariant:
    variant_id: str
    pass_rate: float
    token_cost_usd: float
    latency_s: float
    changes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "pass_rate": _round(self.pass_rate),
            "token_cost_usd": _round(self.token_cost_usd),
            "latency_s": _round(self.latency_s),
            "changes": list(self.changes),
        }


def _dominates(left: HarnessVariant, right: HarnessVariant) -> bool:
    no_worse = (
        left.pass_rate >= right.pass_rate
        and left.token_cost_usd <= right.token_cost_usd
        and left.latency_s <= right.latency_s
    )
    strictly_better = (
        left.pass_rate > right.pass_rate
        or left.token_cost_usd < right.token_cost_usd
        or left.latency_s < right.latency_s
    )
    return no_worse and strictly_better


def pareto_frontier(
    variants: Iterable[HarnessVariant | Mapping[str, Any]],
) -> tuple[HarnessVariant, ...]:
    """Return the pass-rate/cost/latency non-dominated variants."""

    items: list[HarnessVariant] = []
    for variant in variants:
        if isinstance(variant, HarnessVariant):
            items.append(variant)
        else:
            data = _mapping(variant)
            items.append(
                HarnessVariant(
                    variant_id=_as_text(data.get("variant_id") or data.get("id")),
                    pass_rate=_clip(data.get("pass_rate")),
                    token_cost_usd=max(0.0, _number(data.get("token_cost_usd"))),
                    latency_s=max(0.0, _number(data.get("latency_s"))),
                    changes=_texts(data.get("changes")),
                )
            )
    frontier: list[HarnessVariant] = []
    for index, item in enumerate(items):
        dominated = any(
            _dominates(other, item)
            for other_index, other in enumerate(items)
            if other_index != index
        )
        if not dominated:
            frontier.append(item)
    frontier.sort(key=lambda item: (-item.pass_rate, item.token_cost_usd, item.latency_s))
    return tuple(frontier)


@dataclass(frozen=True)
class HarnessPreset:
    name: str
    variant_id: str
    pass_rate: float
    token_cost_usd: float
    latency_s: float
    features: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "variant_id": self.variant_id,
            "pass_rate": _round(self.pass_rate),
            "token_cost_usd": _round(self.token_cost_usd),
            "latency_s": _round(self.latency_s),
            "features": list(self.features),
        }


def select_harness_presets(
    variants: Iterable[HarnessVariant | Mapping[str, Any]],
    *,
    limit: int = 3,
) -> tuple[HarnessPreset, ...]:
    """Name up to three frontier variants as lightweight/balanced/high-performance."""

    frontier = pareto_frontier(variants)
    if not frontier:
        return ()
    ordered = sorted(frontier, key=lambda item: (item.token_cost_usd, item.latency_s))
    names: tuple[str, ...]
    if len(ordered) == 1:
        names = ("balanced",)
    elif len(ordered) == 2:
        names = ("lightweight", "high-performance")
    else:
        names = ("lightweight", "balanced", "high-performance")
    count = max(1, min(int(_number(limit, 3)), len(ordered)))
    result: list[HarnessPreset] = []
    for index in range(count):
        item = ordered[index]
        name = names[index] if index < len(names) else f"preset-{index + 1}"
        result.append(
            HarnessPreset(
                name=name,
                variant_id=item.variant_id,
                pass_rate=item.pass_rate,
                token_cost_usd=item.token_cost_usd,
                latency_s=item.latency_s,
                features=item.changes,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class CustomerBeliefState:
    verified_slots: Mapping[str, str] = field(default_factory=dict)
    probabilistic_assumptions: Mapping[str, float] = field(default_factory=dict)
    unresolved_gaps: tuple[str, ...] = ()
    blocked_gap_type: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "verified_slots": dict(self.verified_slots),
            "probabilistic_assumptions": {
                str(key): _round(value) for key, value in self.probabilistic_assumptions.items()
            },
            "unresolved_gaps": list(self.unresolved_gaps),
            "blocked_gap_type": self.blocked_gap_type,
        }


@dataclass(frozen=True)
class BeliefUpdate:
    state: CustomerBeliefState
    conflicts: tuple[str, ...]
    resolved: tuple[str, ...]
    added_gaps: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.as_dict(),
            "conflicts": list(self.conflicts),
            "resolved": list(self.resolved),
            "added_gaps": list(self.added_gaps),
        }


def update_belief_state(
    state: CustomerBeliefState | Mapping[str, Any] | None,
    slots: Mapping[str, Any] | None,
    *,
    gaps: Iterable[str] = (),
) -> BeliefUpdate:
    """Merge explicitly stated slot values into the customer belief state."""

    if isinstance(state, CustomerBeliefState):
        base = state
    else:
        data = _mapping(state)
        base = CustomerBeliefState(
            verified_slots={
                str(key): _as_text(value)
                for key, value in _mapping(data.get("verified_slots")).items()
            },
            probabilistic_assumptions={
                str(key): _number(value)
                for key, value in _mapping(data.get("probabilistic_assumptions")).items()
            },
            unresolved_gaps=_texts(data.get("unresolved_gaps")),
            blocked_gap_type=_as_text(data.get("blocked_gap_type")),
        )
    verified = dict(base.verified_slots)
    conflicts: list[str] = []
    resolved: list[str] = []
    for key, raw_value in _mapping(slots).items():
        value = _as_text(raw_value)
        if not value:
            continue
        current = verified.get(key)
        if current and current != value:
            conflicts.append(key)
            continue
        verified[key] = value
        resolved.append(key)
    pending = [gap for gap in base.unresolved_gaps if gap not in verified]
    for gap in _texts(gaps):
        if gap not in verified and gap not in pending:
            pending.append(gap)
    new_state = replace(
        base,
        verified_slots=verified,
        unresolved_gaps=tuple(pending),
        blocked_gap_type=conflicts[0] if conflicts else base.blocked_gap_type,
    )
    added = tuple(gap for gap in pending if gap not in base.unresolved_gaps)
    return BeliefUpdate(
        state=new_state,
        conflicts=tuple(conflicts),
        resolved=tuple(resolved),
        added_gaps=added,
    )


@dataclass(frozen=True)
class BeliefTrapReport:
    trapped: bool
    reasons: tuple[str, ...]
    gap_persistence: int
    stagnation_count: int
    recurrence_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "trapped": self.trapped,
            "reasons": list(self.reasons),
            "gap_persistence": self.gap_persistence,
            "stagnation_count": self.stagnation_count,
            "recurrence_count": self.recurrence_count,
        }


def _gap_history(
    history: Iterable[CustomerBeliefState | Mapping[str, Any] | Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    result: list[tuple[str, ...]] = []
    for item in history:
        if isinstance(item, CustomerBeliefState):
            result.append(item.unresolved_gaps)
        elif isinstance(item, Mapping):
            result.append(_texts(item.get("unresolved_gaps")))
        else:
            result.append(_texts(item))
    return tuple(result)


def detect_belief_trapping(
    history: Iterable[CustomerBeliefState | Mapping[str, Any] | Sequence[str]],
    *,
    recommendations: Sequence[str] = (),
    rejected: Sequence[str] = (),
    persistence: int = 2,
    stagnation: int = 2,
    recurrence: int = 1,
) -> BeliefTrapReport:
    """Detect repeated gaps, non-decreasing gaps, and re-proposed rejects."""

    states = _gap_history(history)
    if not states:
        return BeliefTrapReport(False, (), 0, 0, 0)
    last = states[-1]
    persistence_need = max(1, int(_number(persistence, 2)))
    persistence_count = 0
    for gap in last:
        streak = 0
        for state in reversed(states):
            if gap in state:
                streak += 1
            else:
                break
        persistence_count = max(persistence_count, streak)
    recent = states[-max(2, int(_number(stagnation, 2)) + 1) :]
    counts = [len(state) for state in recent]
    stagnation_count = 0
    if len(counts) >= 2:
        for index in range(1, len(counts)):
            if counts[index] >= counts[index - 1]:
                stagnation_count += 1
    rejected_set = set(_texts(rejected))
    recurrence_count = sum(1 for item in _texts(recommendations) if item in rejected_set)
    reasons: list[str] = []
    if persistence_count >= persistence_need and last:
        reasons.append("gap_persistence")
    if stagnation_count >= max(1, int(_number(stagnation, 2))) and last:
        reasons.append("progress_stagnation")
    if recurrence_count >= max(1, int(_number(recurrence, 1))):
        reasons.append("belief_recurrence")
    return BeliefTrapReport(
        trapped=bool(reasons),
        reasons=tuple(reasons),
        gap_persistence=persistence_count,
        stagnation_count=stagnation_count,
        recurrence_count=recurrence_count,
    )


def recovery_actions(
    report: BeliefTrapReport,
    alternatives: Sequence[str] = (),
) -> tuple[str, ...]:
    """Suggest a concrete two-option recovery or a human hand-off."""

    if not report.trapped:
        return ()
    options = _texts(alternatives)
    if len(options) >= 2:
        return (options[0], options[1], "handoff_to_human")
    return ("offer_two_concrete_options", "handoff_to_human")


@dataclass(frozen=True)
class ForecastRecord:
    candidate_id: str
    predicted: float
    realized: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "predicted": _round(self.predicted),
            "realized": _round(self.realized),
        }


def forecast_surprise(predicted: float, realized: float) -> float:
    """Absolute surprise in log1p space."""

    predicted_value = max(0.0, _number(predicted))
    realized_value = max(0.0, _number(realized))
    return abs(math.log1p(realized_value) - math.log1p(predicted_value))


@dataclass(frozen=True)
class CoEvolutionUpdate:
    reinforce: tuple[str, ...]
    calibrate: tuple[str, ...]
    blind_spots: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "reinforce": list(self.reinforce),
            "calibrate": list(self.calibrate),
            "blind_spots": list(self.blind_spots),
        }


def co_evolve_forecasts(
    records: Iterable[ForecastRecord | Mapping[str, Any]],
    *,
    low_surprise: float = 0.35,
    blind_spot_surprise: float = 0.75,
    calibration_ratio: float = 0.8,
) -> CoEvolutionUpdate:
    """Split outcomes into reinforce, calibrate, and blind-spot buckets."""

    reinforce: list[str] = []
    calibrate: list[str] = []
    blind_spots: list[str] = []
    for item in records:
        if isinstance(item, ForecastRecord):
            record = item
        else:
            data = _mapping(item)
            record = ForecastRecord(
                candidate_id=_as_text(data.get("candidate_id") or data.get("id")),
                predicted=_number(data.get("predicted")),
                realized=_number(data.get("realized")),
            )
        surprise = forecast_surprise(record.predicted, record.realized)
        if surprise >= max(low_surprise, blind_spot_surprise):
            blind_spots.append(record.candidate_id)
        elif surprise <= low_surprise and record.realized >= record.predicted * calibration_ratio:
            reinforce.append(record.candidate_id)
        else:
            calibrate.append(record.candidate_id)
    return CoEvolutionUpdate(
        reinforce=tuple(reinforce),
        calibrate=tuple(calibrate),
        blind_spots=tuple(blind_spots),
    )


@dataclass(frozen=True)
class ScoutNote:
    note_id: str
    title: str
    followers: int = 0
    likes: int = 0
    collects: int = 0
    comments: int = 0
    age_days: float = 1.0
    image_texts: tuple[str, ...] = ()
    visual_entities: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "title": self.title,
            "followers": self.followers,
            "likes": self.likes,
            "collects": self.collects,
            "comments": self.comments,
            "age_days": _round(self.age_days),
            "image_texts": list(self.image_texts),
            "visual_entities": list(self.visual_entities),
        }


def _breakout_lift(note: ScoutNote) -> float:
    numerator = math.log1p(note.collects + 0.5 * note.likes + 2.0 * note.comments)
    denominator = 0.6 * math.log1p(10 + note.followers) + 0.4 * math.log1p(
        2 + max(1.0, note.age_days)
    )
    return numerator / denominator if denominator else 0.0


@dataclass(frozen=True)
class ScoutHop:
    hop: int
    action: str
    target: str
    output: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "hop": self.hop,
            "action": self.action,
            "target": self.target,
            "output": list(self.output),
        }


@dataclass(frozen=True)
class DeepScoutPlan:
    hops: tuple[ScoutHop, ...]
    selected_notes: tuple[str, ...]
    extracted_entities: tuple[str, ...]
    verification_queries: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "hops": [hop.as_dict() for hop in self.hops],
            "selected_notes": list(self.selected_notes),
            "extracted_entities": list(self.extracted_entities),
            "verification_queries": list(self.verification_queries),
        }


def _scout_note(value: ScoutNote | Mapping[str, Any]) -> ScoutNote:
    if isinstance(value, ScoutNote):
        return value
    data = _mapping(value)
    return ScoutNote(
        note_id=_as_text(data.get("note_id") or data.get("id")),
        title=_as_text(data.get("title")),
        followers=int(_number(data.get("followers"))),
        likes=int(_number(data.get("likes"))),
        collects=int(_number(data.get("collects"))),
        comments=int(_number(data.get("comments"))),
        age_days=max(1.0, _number(data.get("age_days"), 1.0)),
        image_texts=_texts(data.get("image_texts")),
        visual_entities=_texts(data.get("visual_entities")),
    )


def plan_multimodal_deep_scout(
    notes: Iterable[ScoutNote | Mapping[str, Any]],
    *,
    top_k: int = 5,
    breakout_scores: Mapping[str, float] | None = None,
) -> DeepScoutPlan:
    """Plan the three-hop text -> image -> verification scout."""

    items = [_scout_note(note) for note in notes]
    scores = {
        note.note_id: _number((breakout_scores or {}).get(note.note_id), _breakout_lift(note))
        for note in items
    }
    ranked = sorted(
        (note for note in items if note.note_id),
        key=lambda note: scores.get(note.note_id, 0.0),
        reverse=True,
    )
    selected = ranked[: max(1, int(_number(top_k, 5)))]
    entities: list[str] = []
    queries: list[str] = []
    for note in selected:
        for entity in note.visual_entities:
            if entity not in entities:
                entities.append(entity)
        for text in note.image_texts:
            if text and text not in entities:
                entities.append(text)
        for entity in note.visual_entities:
            query = f"verify:{entity}"
            if query not in queries:
                queries.append(query)
    hops = (
        ScoutHop(
            hop=1,
            action="text_recall",
            target="xhs_trending",
            output=tuple(note.note_id for note in selected),
        ),
        ScoutHop(
            hop=2,
            action="visualize",
            target="images[1,2,last]",
            output=tuple(entities),
        ),
        ScoutHop(
            hop=3,
            action="expand_verify",
            target="keyword_monitor",
            output=tuple(queries),
        ),
    )
    return DeepScoutPlan(
        hops=hops,
        selected_notes=tuple(note.note_id for note in selected),
        extracted_entities=tuple(entities),
        verification_queries=tuple(queries),
    )


@dataclass(frozen=True)
class CostMatrix:
    abstain_cost: float = 1.0
    compliance_error_cost: float = 50.0
    quote_error_cost: float = 50.0

    def error_cost(self, error_kind: str = "compliance") -> float:
        if error_kind == "quote":
            return max(0.0, _number(self.quote_error_cost, 50.0))
        return max(0.0, _number(self.compliance_error_cost, 50.0))

    def as_dict(self) -> dict[str, Any]:
        return {
            "abstain_cost": _round(self.abstain_cost),
            "compliance_error_cost": _round(self.compliance_error_cost),
            "quote_error_cost": _round(self.quote_error_cost),
        }


@dataclass(frozen=True)
class AbstentionDecision:
    action: str
    threshold: float
    expected_cost_auto: float
    expected_cost_abstain: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "threshold": _round(self.threshold),
            "expected_cost_auto": _round(self.expected_cost_auto),
            "expected_cost_abstain": _round(self.expected_cost_abstain),
            "reason": self.reason,
        }


def abstention_threshold(abstain_cost: float, error_cost: float) -> float:
    """Bayes-optimal abstention threshold for asymmetric error costs."""

    abstain = max(0.0, _number(abstain_cost, 1.0))
    error = max(0.0, _number(error_cost, 50.0))
    total = abstain + error
    if total <= 0.0:
        return 0.0
    return _clip(abstain / total)


def route_with_abstention(
    p_error: float,
    *,
    costs: CostMatrix | None = None,
    error_kind: str = "compliance",
) -> AbstentionDecision:
    """Route a candidate to auto-pass or human review by expected loss."""

    matrix = costs or CostMatrix()
    abstain_cost = max(0.0, _number(matrix.abstain_cost, 1.0))
    error_cost = matrix.error_cost(error_kind)
    threshold = abstention_threshold(abstain_cost, error_cost)
    probability = _clip(p_error)
    expected_auto = probability * error_cost
    expected_abstain = abstain_cost
    action = "abstain" if probability >= threshold else "auto_pass"
    reason = "expected_loss_threshold" if action == "abstain" else "below_threshold"
    return AbstentionDecision(
        action=action,
        threshold=threshold,
        expected_cost_auto=expected_auto,
        expected_cost_abstain=expected_abstain,
        reason=reason,
    )


@dataclass(frozen=True)
class BoostInputs:
    note_id: str
    ctr: float
    collect_rate: float
    dm_rate: float
    baseline_ctr_p80: float
    baseline_collect_dm_p85: float
    lead_value: float = 0.0
    close_rate: float = 0.0
    margin: float = 0.3

    def as_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "ctr": _round(self.ctr),
            "collect_rate": _round(self.collect_rate),
            "dm_rate": _round(self.dm_rate),
            "baseline_ctr_p80": _round(self.baseline_ctr_p80),
            "baseline_collect_dm_p85": _round(self.baseline_collect_dm_p85),
            "lead_value": _round(self.lead_value),
            "close_rate": _round(self.close_rate),
            "margin": _round(self.margin),
        }


@dataclass(frozen=True)
class BoostRecommendation:
    should_boost: bool
    target: str
    max_bid_cap: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "should_boost": self.should_boost,
            "target": self.target,
            "max_bid_cap": _round(self.max_bid_cap),
            "reason": self.reason,
        }


def recommend_boost(inputs: BoostInputs | Mapping[str, Any]) -> BoostRecommendation:
    """Recommend an oCPX target for a naturally validated seed note."""

    if isinstance(inputs, BoostInputs):
        data = inputs
    else:
        raw = _mapping(inputs)
        data = BoostInputs(
            note_id=_as_text(raw.get("note_id") or raw.get("id")),
            ctr=_number(raw.get("ctr")),
            collect_rate=_number(raw.get("collect_rate")),
            dm_rate=_number(raw.get("dm_rate")),
            baseline_ctr_p80=_number(raw.get("baseline_ctr_p80")),
            baseline_collect_dm_p85=_number(raw.get("baseline_collect_dm_p85")),
            lead_value=_number(raw.get("lead_value")),
            close_rate=_number(raw.get("close_rate")),
            margin=_number(raw.get("margin"), 0.3),
        )
    high_ctr = data.ctr >= data.baseline_ctr_p80
    high_quality = (data.collect_rate + data.dm_rate) >= data.baseline_collect_dm_p85
    if not (high_ctr and high_quality):
        return BoostRecommendation(
            should_boost=False,
            target="",
            max_bid_cap=0.0,
            reason="not_in_golden_six_hour_window",
        )
    if data.dm_rate >= data.collect_rate:
        cap = data.lead_value * data.close_rate * _clip(data.margin)
        return BoostRecommendation(
            should_boost=True,
            target="聚光私信开口 oCPC",
            max_bid_cap=max(0.0, cap),
            reason="high_intent_dm_signal",
        )
    return BoostRecommendation(
        should_boost=True,
        target="薯条赞藏互动量",
        max_bid_cap=0.0,
        reason="high_collect_signal",
    )
