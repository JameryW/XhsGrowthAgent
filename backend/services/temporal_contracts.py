"""Phase-4 temporal and execution contracts (ledger schemes 19-24).

These are small, deterministic building blocks for the state, timing and Ripple
workflows.  They do not change the graph topology by themselves; callers opt in
explicitly and the existing default path remains untouched.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any

__all__ = [
    "COMMERCIAL_BRIEF_REQUIRED_FIELDS",
    "CommercialBriefContractReport",
    "DraftAnalyticsSnapshot",
    "InhibitoryHawkesParams",
    "JitSubgraph",
    "NarrativeAnchor",
    "RevisionConflictError",
    "RevisionedValue",
    "RippleSalvage",
    "TimePopFeatures",
    "apply_expected_revision",
    "build_analytics_snapshot",
    "build_narrative_brief",
    "compile_jit_subgraph",
    "validate_commercial_brief_contract",
    "counterfactual_slots",
    "effective_intensity",
    "encode_time_features",
    "inhibit_factor",
    "narrative_anchors",
    "salvage_timed_out_payload",
]


class RevisionConflictError(RuntimeError):
    """Raised when an optimistic draft write has a stale revision."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"revision_conflict: expected={expected} actual={actual}")
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class RevisionedValue:
    """A value carrying the revision used for compare-and-swap writes."""

    revision: int
    value: Any
    updated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "value": self.value,
            "updated_at": self.updated_at.isoformat(),
        }


def apply_expected_revision(
    current: RevisionedValue | None,
    expected_revision: int,
    value: Any,
    *,
    now: datetime | None = None,
) -> RevisionedValue:
    """Apply a CAS write, rejecting a stale ``expected_revision``."""

    current_revision = current.revision if current is not None else 0
    if expected_revision != current_revision:
        raise RevisionConflictError(expected_revision, current_revision)
    return RevisionedValue(
        revision=current_revision + 1,
        value=value,
        updated_at=now or datetime.now(UTC),
    )


@dataclass(frozen=True)
class DraftAnalyticsSnapshot:
    """A physically separated analytics snapshot for one draft revision."""

    draft_id: str
    seq_no: int
    captured_at: datetime
    reads: int = 0
    likes: int = 0
    collects: int = 0
    comments: int = 0
    delta_views: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "seq_no": self.seq_no,
            "captured_at": self.captured_at.isoformat(),
            "reads": self.reads,
            "likes": self.likes,
            "collects": self.collects,
            "comments": self.comments,
            "delta_views": self.delta_views,
        }


def build_analytics_snapshot(
    draft_id: str,
    seq_no: int,
    *,
    reads: int = 0,
    likes: int = 0,
    collects: int = 0,
    comments: int = 0,
    previous_reads: int = 0,
    captured_at: datetime | None = None,
) -> DraftAnalyticsSnapshot:
    """Create one append-only snapshot with a safe non-negative view delta."""

    return DraftAnalyticsSnapshot(
        draft_id=draft_id,
        seq_no=max(1, int(seq_no)),
        captured_at=captured_at or datetime.now(UTC),
        reads=max(0, int(reads)),
        likes=max(0, int(likes)),
        collects=max(0, int(collects)),
        comments=max(0, int(comments)),
        delta_views=max(0, int(reads) - int(previous_reads)),
    )


@dataclass(frozen=True)
class TimePopFeatures:
    """Sinusoidal time features used by TimePop-style slot scoring."""

    sin_day: float
    cos_day: float
    sin_week: float
    cos_week: float
    hour_slot: int
    weekday: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "sin_day": round(self.sin_day, 6),
            "cos_day": round(self.cos_day, 6),
            "sin_week": round(self.sin_week, 6),
            "cos_week": round(self.cos_week, 6),
            "hour_slot": self.hour_slot,
            "weekday": self.weekday,
        }


def encode_time_features(moment: datetime) -> TimePopFeatures:
    """Encode 24h and 7d periodic position without a learned embedding."""

    local = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    hour_fraction = local.hour + local.minute / 60.0 + local.second / 3600.0
    day_angle = 2.0 * math.pi * hour_fraction / 24.0
    week_angle = 2.0 * math.pi * (local.weekday() + hour_fraction / 24.0) / 7.0
    return TimePopFeatures(
        sin_day=math.sin(day_angle),
        cos_day=math.cos(day_angle),
        sin_week=math.sin(week_angle),
        cos_week=math.cos(week_angle),
        hour_slot=min(47, int(hour_fraction * 2)),
        weekday=local.weekday(),
    )


def counterfactual_slots(day: date) -> list[dict[str, Any]]:
    """Return the 48 half-hour posting slots for one local calendar day."""

    slots: list[dict[str, Any]] = []
    for index in range(48):
        hour, minute = divmod(index * 30, 60)
        moment = datetime.combine(day, time(hour, minute), tzinfo=UTC)
        slots.append(
            {
                "slot": index,
                "label": f"{hour:02d}:{minute:02d}",
                "features": encode_time_features(moment).as_dict(),
            }
        )
    return slots


def rank_counterfactual_slots(
    day: date,
    scorer: Callable[[dict[str, Any]], float],
) -> list[dict[str, Any]]:
    """Rank the 48 slots by a caller-provided score (highest first)."""

    ranked = []
    for slot in counterfactual_slots(day):
        item = dict(slot)
        item["score"] = float(scorer(slot))
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], item["slot"]))
    return ranked


@dataclass(frozen=True)
class InhibitoryHawkesParams:
    """Parameters for a bounded self-inhibiting Hawkes approximation."""

    mu: float = 1.0
    alpha: float = 0.6
    beta: float = 0.8
    tau_refractory: float = 2.0
    refractory_hours: float = 6.0
    similarity_threshold: float = 0.65
    similarity_window_hours: float = 24.0
    horizon_days: float = 14.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "mu": self.mu,
            "alpha": self.alpha,
            "beta": self.beta,
            "tau_refractory": self.tau_refractory,
            "refractory_hours": self.refractory_hours,
            "similarity_threshold": self.similarity_threshold,
            "similarity_window_hours": self.similarity_window_hours,
            "horizon_days": self.horizon_days,
        }


def inhibit_factor(
    delta_hours: float,
    similarity: float,
    params: InhibitoryHawkesParams | None = None,
) -> float:
    """Return 0..1 excitation multiplier for a near-duplicate recent post."""

    cfg = params or InhibitoryHawkesParams()
    delta = max(0.0, float(delta_hours))
    if (
        delta < cfg.similarity_window_hours
        and float(similarity) > cfg.similarity_threshold
        and delta < cfg.refractory_hours
    ):
        return 1.0 - math.exp(-delta / max(cfg.tau_refractory, 1e-6))
    return 1.0


def effective_intensity(
    base_intensity: float,
    recent_events: Iterable[tuple[float, float]],
    params: InhibitoryHawkesParams | None = None,
) -> float:
    """Compute intensity from ``(delta_hours, similarity)`` recent events."""

    cfg = params or InhibitoryHawkesParams()
    intensity = max(0.0, float(base_intensity))
    for delta_hours, similarity in recent_events:
        decay = math.exp(-cfg.beta * max(0.0, float(delta_hours)))
        intensity += cfg.alpha * decay * inhibit_factor(delta_hours, similarity, cfg)
    return intensity


COMMERCIAL_BRIEF_REQUIRED_FIELDS: tuple[str, ...] = (
    "brand_name",
    "product_name",
    "selling_points",
    "content_direction",
    "target_audience",
)


@dataclass(frozen=True)
class CommercialBriefContractReport:
    """Deterministic readiness check for a parsed commercial brief."""

    ready: bool
    missing_fields: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "missing_fields": list(self.missing_fields),
            "warnings": list(self.warnings),
        }


def _has_brief_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def validate_commercial_brief_contract(
    brief: Mapping[str, Any] | None,
) -> CommercialBriefContractReport:
    """Check the fields a commercial brief needs before shooting/publishing.

    This is a validator, not a gate: the caller decides whether to block.  A
    missing field is reported so the brief gate can ask a specific question
    instead of silently generating a generic note.
    """

    data = brief or {}
    missing = tuple(
        field_name
        for field_name in COMMERCIAL_BRIEF_REQUIRED_FIELDS
        if not _has_brief_value(data.get(field_name))
    )
    warnings: list[str] = []
    if not _has_brief_value(data.get("required_hashtags")):
        warnings.append("required_hashtags empty")
    if not _has_brief_value(data.get("shooting_requirements")):
        warnings.append("shooting_requirements empty")
    return CommercialBriefContractReport(
        ready=not missing,
        missing_fields=missing,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class JitSubgraph:
    """A declarative plan for one JIT workflow mode."""

    mode: str
    nodes: tuple[str, ...]
    skip_nodes: tuple[str, ...] = field(default_factory=tuple)
    rationale: str = ""
    graph_nodes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "nodes": list(self.nodes),
            "skip_nodes": list(self.skip_nodes),
            "rationale": self.rationale,
            "validated_against_graph": bool(self.graph_nodes),
        }


def compile_jit_subgraph(
    mode: str,
    input_state: Mapping[str, Any] | None = None,
) -> JitSubgraph:
    """Return a small, explicit node plan for a workflow mode.

    The actual graph builder remains the authority for execution; this plan is
    used by callers that need to explain or preflight a mode before dispatch.
    """

    state = input_state or {}
    # Validate against the graph builder rather than maintaining a second,
    # silently drifting node vocabulary.  This still does not compile a
    # separate StateGraph; it makes an invalid plan fail before dispatch.
    from backend.graph.builder import build_graph

    graph_nodes = tuple(build_graph().nodes)

    def _plan(
        plan_mode: str,
        nodes: tuple[str, ...],
        skip_nodes: tuple[str, ...],
        rationale: str,
    ) -> JitSubgraph:
        unknown = (set(nodes) | set(skip_nodes)) - set(graph_nodes)
        if unknown:
            raise ValueError(f"jit subgraph names unknown graph nodes: {sorted(unknown)}")
        return JitSubgraph(plan_mode, nodes, skip_nodes, rationale, graph_nodes)

    if mode == "free":
        nodes: tuple[str, ...] = (
            "orchestrator",
            "copywriter",
            "visual_designer",
            "review_gate",
            "evaluator_gate",
            "publish_gate",
            "publisher",
            "analyst",
        )
        return _plan(mode, nodes, ("trend_scout", "content_strategist"), "free skips strategy")
    if mode == "brief":
        nodes = (
            "orchestrator",
            "brief_analyzer",
            "brief_gate",
            "shooting_planner",
            "copywriter",
            "visual_designer",
            "review_gate",
            "evaluator_gate",
            "publish_gate",
            "publisher",
            "analyst",
        )
        return _plan(mode, nodes, ("trend_scout", "content_strategist"), "brief uses contract")
    if state.get("topic") and not state.get("brief"):
        return _plan(
            mode or "full",
            ("orchestrator", "trend_scout", "content_strategist", "copywriter"),
            (),
            "topic supplied but strategy not yet built",
        )
    return _plan(
        mode or "full",
        (
            "orchestrator",
            "trend_scout",
            "content_strategist",
            "copywriter",
            "visual_designer",
            "review_gate",
            "evaluator_gate",
            "publish_gate",
            "publisher",
            "analyst",
        ),
        (),
        "full pipeline",
    )


@dataclass(frozen=True)
class NarrativeAnchor:
    """One orthogonal narrative prior for VERSION_GEN."""

    key: str
    label: str
    title_pattern: str
    structure: tuple[str, ...]
    tone: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "title_pattern": self.title_pattern,
            "structure": list(self.structure),
            "tone": self.tone,
        }


_NARRATIVE_ANCHORS: tuple[NarrativeAnchor, ...] = (
    NarrativeAnchor(
        "search_direct",
        "搜索直给",
        "参数流标题：品类 + 关键参数 + 使用场景",
        ("结论", "参数", "使用步骤", "适用人群"),
        "直接、可检索",
    ),
    NarrativeAnchor(
        "pain_contrast",
        "痛点反差",
        "踩坑流标题：错误做法 + 反转结果",
        ("痛点", "踩坑", "转折", "正确做法"),
        "有反差、可共鸣",
    ),
    NarrativeAnchor(
        "minimal_visual",
        "极简视觉",
        "场景清单标题：低决策成本 + 清单",
        ("场景", "清单", "视觉证据", "收藏提示"),
        "克制、画面感",
    ),
)


def narrative_anchors() -> tuple[NarrativeAnchor, ...]:
    """Return the three fixed, orthogonal narrative priors."""

    return _NARRATIVE_ANCHORS


def build_narrative_brief(anchor: NarrativeAnchor, topic: str) -> dict[str, Any]:
    """Turn one narrative anchor into a compact VERSION_GEN brief."""

    return {
        "topic": topic,
        "anchor": anchor.key,
        "label": anchor.label,
        "title_pattern": anchor.title_pattern,
        "structure": list(anchor.structure),
        "tone": anchor.tone,
    }


@dataclass(frozen=True)
class RippleSalvage:
    """Result of salvaging a timed-out Ripple job."""

    usable: bool
    stage: str
    payload: dict[str, Any] = field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    fallback: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "usable": self.usable,
            "stage": self.stage,
            "payload": self.payload,
            "missing_fields": list(self.missing_fields),
            "fallback": self.fallback,
        }


def salvage_timed_out_payload(
    payload: Mapping[str, Any] | None,
    *,
    required_fields: Sequence[str] = ("estimated_reach", "viral_probability"),
) -> RippleSalvage:
    """Extract a usable partial Ripple prediction and mark missing fields."""

    source = payload if isinstance(payload, Mapping) else {}
    candidates = [
        source.get("prediction"),
        source.get("partial_result"),
        source.get("result"),
        source.get("collect_first"),
        source,
    ]
    merged: dict[str, Any] = {}
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            merged.update(candidate)
    missing = tuple(field for field in required_fields if merged.get(field) is None)
    if not missing:
        return RippleSalvage(True, "partial", payload=dict(merged))
    fallback = {
        "status": "degraded",
        "reason": "ripple_timed_out",
        "missing_fields": list(missing),
        "estimated_reach": merged.get("estimated_reach", 0),
        "viral_probability": merged.get("viral_probability", 0.0),
    }
    return RippleSalvage(
        False, "timed_out", payload=dict(merged), missing_fields=missing, fallback=fallback
    )
