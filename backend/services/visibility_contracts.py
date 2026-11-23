"""Phase-7 visibility contracts (ledger schemes 37-42).

Deterministic, dependency-free helpers for GEO keyword scoring, OneSearch
semantic ids, cross-account collision checks, workspace account binding,
long-article/shooting plans, storage tiering and the offline golden suite gate.

These contracts deliberately do not import the graph, HTTP stack, database or
LLM clients. Callers opt in from their own nodes/routes.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

__all__ = [
    "AccountBindingError",
    "CollisionFinding",
    "DEFAULT_GOLDEN_CASES",
    "GOLDEN_GATES",
    "GeoKeywordScore",
    "GoldenSuiteCase",
    "LongArticlePlan",
    "MatrixFingerprintLedger",
    "NoteFingerprint",
    "SemanticIdPath",
    "ShootingPlan",
    "ShootingSegment",
    "StorageTier",
    "StorageTierPlan",
    "account_binding_payload",
    "assert_account_binding",
    "build_golden_suite_manifest",
    "build_semantic_id_path",
    "build_shooting_plan",
    "content_digest",
    "detect_cross_account_collisions",
    "evaluate_golden_suite",
    "fingerprint_similarity",
    "geo_cite_score",
    "plan_long_article",
    "plan_storage_tier",
    "rank_geo_keywords",
    "semantic_id_coverage",
    "semantic_id_missing_levels",
]


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_GOLDEN_CASE_CATEGORIES = (
    "geo_gap",
    "commercial_brief",
    "carousel_compare",
    "prompt_injection",
    "cross_account_collision",
    "dm_compliance",
    "plad_vibe",
    "context_compaction",
)
GOLDEN_GATES: dict[str, float | int] = {
    "policy_compliance_recall": 1.0,
    "plad_human_pass_rate": 0.90,
    "cross_account_collision_leak": 0,
    "context_prefix_cache_hit_ratio": 0.85,
}


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


def _tokens(text: str) -> set[str]:
    """Tokenize CJK characters and latin/number runs for deterministic overlap."""
    return set(_TOKEN_PATTERN.findall(text.lower()))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity clamped to [0, 1]; empty/mismatched vectors score 0."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left <= 0.0 or norm_right <= 0.0:
        return 0.0
    return _unit(dot / (norm_left * norm_right))


def _timestamp(value: object) -> datetime | None:
    """Parse an ISO timestamp; naive values are treated as UTC."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class GeoKeywordScore:
    """One GEO-CiteScore keyword candidate."""

    keyword: str
    score: float
    intent_specificity: float
    search_demand: float
    supply_density: float
    evidence_dispersion: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "score": round(self.score, 6),
            "intent_specificity": round(self.intent_specificity, 4),
            "search_demand": round(self.search_demand, 4),
            "supply_density": round(self.supply_density, 4),
            "evidence_dispersion": round(self.evidence_dispersion, 4),
        }


def geo_cite_score(
    *,
    intent_specificity: float,
    search_demand: float,
    high_density_supply_count: float = 0.0,
    evidence_dispersion_penalty: float = 0.0,
) -> float:
    """GEO-CiteScore = specificity * log1p(demand) / (1 + supply + dispersion)."""
    specificity = _unit(_number(intent_specificity))
    demand = max(0.0, _number(search_demand))
    supply = max(0.0, _number(high_density_supply_count))
    dispersion = max(0.0, _number(evidence_dispersion_penalty))
    return round(specificity * math.log1p(demand) / (1.0 + supply + dispersion), 6)


def rank_geo_keywords(
    keywords: Iterable[Mapping[str, Any]], *, limit: int = 10
) -> list[GeoKeywordScore]:
    """Rank keyword mappings by GEO-CiteScore (descending, then keyword)."""
    scores: list[GeoKeywordScore] = []
    for item in keywords:
        keyword = _text(item.get("keyword"))
        if not keyword:
            continue
        specificity = _number(item.get("intent_specificity"))
        demand = _number(item.get("search_demand"))
        supply = _number(item.get("high_density_supply_count"))
        dispersion = _number(item.get("evidence_dispersion_penalty"))
        scores.append(
            GeoKeywordScore(
                keyword=keyword,
                score=geo_cite_score(
                    intent_specificity=specificity,
                    search_demand=demand,
                    high_density_supply_count=supply,
                    evidence_dispersion_penalty=dispersion,
                ),
                intent_specificity=_unit(specificity),
                search_demand=max(0.0, demand),
                supply_density=max(0.0, supply),
                evidence_dispersion=max(0.0, dispersion),
            )
        )
    scores.sort(key=lambda item: (-item.score, item.keyword))
    return scores[: max(0, int(limit))]


@dataclass(frozen=True)
class SemanticIdPath:
    """OneSearch-V2 five-level semantic id path."""

    l1: str
    l2: str
    l3: str
    l4: str
    l5: str

    def levels(self) -> tuple[str, ...]:
        return (self.l1, self.l2, self.l3, self.l4, self.l5)

    def as_dict(self) -> dict[str, Any]:
        return {"l1": self.l1, "l2": self.l2, "l3": self.l3, "l4": self.l4, "l5": self.l5}


def build_semantic_id_path(l1: str, l2: str, l3: str, l4: str, l5: str) -> SemanticIdPath:
    """Build a five-level semantic id; every level must be non-empty."""
    values = tuple(_text(value) for value in (l1, l2, l3, l4, l5))
    if not all(values):
        raise ValueError("semantic id levels must all be non-empty")
    return SemanticIdPath(*values)


def semantic_id_coverage(text: str, path: SemanticIdPath) -> float:
    """Fraction of the five semantic levels represented in ``text``."""
    tokens = _tokens(text)
    levels = path.levels()
    if not levels:
        return 0.0
    matched = sum(1 for level in levels if _tokens(level) & tokens)
    return round(matched / len(levels), 4)


def semantic_id_missing_levels(text: str, path: SemanticIdPath) -> tuple[str, ...]:
    """Return the L1..L5 labels whose tokens are absent from ``text``."""
    tokens = _tokens(text)
    missing: list[str] = []
    for index, level in enumerate(path.levels(), start=1):
        if not (_tokens(level) & tokens):
            missing.append(f"L{index}")
    return tuple(missing)


@dataclass(frozen=True)
class NoteFingerprint:
    """A published/scheduled note used by the matrix collision guard."""

    note_id: str
    account_id: str
    title: str = ""
    body: str = ""
    visual_template: str = ""
    published_at: str = ""
    embedding: tuple[float, ...] = field(default_factory=tuple)

    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()

    def as_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "account_id": self.account_id,
            "title": self.title,
            "body": self.body,
            "visual_template": self.visual_template,
            "published_at": self.published_at,
            "embedding": list(self.embedding),
        }


@dataclass(frozen=True)
class CollisionFinding:
    """One cross-account collision finding."""

    other_note_id: str
    other_account_id: str
    similarity: float
    hours_apart: float | None
    reasons: tuple[str, ...]
    actions: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "other_note_id": self.other_note_id,
            "other_account_id": self.other_account_id,
            "similarity": round(self.similarity, 4),
            "hours_apart": None if self.hours_apart is None else round(self.hours_apart, 2),
            "reasons": list(self.reasons),
            "actions": list(self.actions),
        }


def fingerprint_similarity(left: NoteFingerprint, right: NoteFingerprint) -> float:
    """Cosine similarity when both embeddings exist, otherwise token Jaccard."""
    if left.embedding and right.embedding and len(left.embedding) == len(right.embedding):
        return round(_cosine(left.embedding, right.embedding), 4)
    left_tokens = _tokens(left.text())
    right_tokens = _tokens(right.text())
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    return round(len(left_tokens & right_tokens) / len(union), 4)


def _hours_apart(left: NoteFingerprint, right: NoteFingerprint) -> float | None:
    left_time = _timestamp(left.published_at)
    right_time = _timestamp(right.published_at)
    if left_time is None or right_time is None:
        return None
    return abs((left_time - right_time).total_seconds()) / 3600.0


def detect_cross_account_collisions(
    candidate: NoteFingerprint,
    ledger: Iterable[NoteFingerprint],
    *,
    window_hours: float = 72.0,
    similarity_threshold: float = 0.55,
    min_schedule_gap_hours: float = 4.0,
) -> list[CollisionFinding]:
    """Find cross-account notes that collide on topic, template or schedule."""
    findings: list[CollisionFinding] = []
    window = max(0.0, float(window_hours))
    threshold = _unit(_number(similarity_threshold, 0.55))
    min_gap = max(0.0, float(min_schedule_gap_hours))
    for note in ledger:
        if note.account_id == candidate.account_id:
            continue
        hours = _hours_apart(candidate, note)
        if hours is not None and hours > window:
            continue
        similarity = fingerprint_similarity(candidate, note)
        reasons: list[str] = []
        actions: list[str] = []
        if similarity >= threshold:
            reasons.append("topic_similarity")
            actions.append("switch_narrative")
        if candidate.visual_template and candidate.visual_template == note.visual_template:
            reasons.append("visual_template_reuse")
            actions.append("change_visual_template")
        if hours is not None and hours < min_gap:
            reasons.append("schedule_too_close")
            actions.append("shift_schedule")
        if not reasons:
            continue
        findings.append(
            CollisionFinding(
                other_note_id=note.note_id,
                other_account_id=note.account_id,
                similarity=similarity,
                hours_apart=hours,
                reasons=tuple(reasons),
                actions=tuple(actions),
            )
        )
    findings.sort(key=lambda item: (-item.similarity, item.other_note_id))
    return findings


class MatrixFingerprintLedger:
    """In-memory ledger for the cross-account 72h collision guard."""

    def __init__(self, notes: Iterable[NoteFingerprint] = ()) -> None:
        self._notes: list[NoteFingerprint] = list(notes)

    def add(self, note: NoteFingerprint) -> None:
        self._notes.append(note)

    def extend(self, notes: Iterable[NoteFingerprint]) -> None:
        self._notes.extend(notes)

    def notes(self) -> tuple[NoteFingerprint, ...]:
        return tuple(self._notes)

    def find(
        self,
        candidate: NoteFingerprint,
        *,
        window_hours: float = 72.0,
        similarity_threshold: float = 0.55,
        min_schedule_gap_hours: float = 4.0,
    ) -> list[CollisionFinding]:
        return detect_cross_account_collisions(
            candidate,
            self._notes,
            window_hours=window_hours,
            similarity_threshold=similarity_threshold,
            min_schedule_gap_hours=min_schedule_gap_hours,
        )

    def __len__(self) -> int:
        return len(self._notes)


class AccountBindingError(Exception):
    """Raised when a review/publish action targets the wrong workspace account."""

    code = "account_binding_mismatch"
    status_code = 409

    def __init__(self, expected_account_id: str, actual_account_id: str) -> None:
        self.expected_account_id = expected_account_id
        self.actual_account_id = actual_account_id
        super().__init__(
            f"account binding mismatch: expected {expected_account_id!r}, got {actual_account_id!r}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "expected_account_id": self.expected_account_id,
            "actual_account_id": self.actual_account_id,
        }


def assert_account_binding(expected_account_id: str, actual_account_id: str) -> None:
    """Raise 409-style error when a non-empty expected account does not match."""
    expected = _text(expected_account_id)
    actual = _text(actual_account_id)
    if expected and expected != actual:
        raise AccountBindingError(expected, actual)


def account_binding_payload(expected_account_id: str, actual_account_id: str) -> dict[str, Any]:
    """Non-raising account binding result for API/event payloads."""
    expected = _text(expected_account_id)
    actual = _text(actual_account_id)
    ok = not expected or expected == actual
    return {
        "ok": ok,
        "code": "" if ok else "account_binding_mismatch",
        "expected_account_id": expected,
        "actual_account_id": actual,
    }


@dataclass(frozen=True)
class ShootingSegment:
    """One 3-second Live-Photo/video hook segment."""

    start_seconds: float
    end_seconds: float
    purpose: str
    instruction: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_seconds": round(self.start_seconds, 2),
            "end_seconds": round(self.end_seconds, 2),
            "purpose": self.purpose,
            "instruction": self.instruction,
        }


@dataclass(frozen=True)
class ShootingPlan:
    """Structured shooting plan returned by the shooting_plan node contract."""

    scene: str
    hook_segments: tuple[ShootingSegment, ...]
    broll_checklist: tuple[str, ...]
    long_article: bool
    poi: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "hook_segments": [segment.as_dict() for segment in self.hook_segments],
            "broll_checklist": list(self.broll_checklist),
            "long_article": self.long_article,
            "poi": self.poi,
        }


def build_shooting_plan(
    scene: str,
    *,
    body: str = "",
    poi: str = "",
    long_article_threshold: int = 800,
) -> ShootingPlan:
    """Build the fixed 0-1.5s / 1.5-3.0s hook plus B-roll checklist."""
    scene_key = _text(scene).lower() or "lifestyle"
    text = _text(body)
    hook_segments = (
        ShootingSegment(
            start_seconds=0.0,
            end_seconds=1.5,
            purpose="visual_disruption",
            instruction="首帧动态反差/动作定格，在双列流中截停划动",
        ),
        ShootingSegment(
            start_seconds=1.5,
            end_seconds=3.0,
            purpose="focal_zoom",
            instruction="核心实物特写 + 关键数字角标",
        ),
    )
    broll_checklist = (
        "机位角度：主体 45 度与正面各一条",
        "光线色温：自然光 5600K，避免混合色温",
        "道具摆放：核心产品居中，背景留白 30%",
        "口播/字幕时间轴与卡片切换点对齐",
    )
    return ShootingPlan(
        scene=scene_key,
        hook_segments=hook_segments,
        broll_checklist=broll_checklist,
        long_article=bool(text) and len(text) >= max(1, int(long_article_threshold)),
        poi=_text(poi),
    )


@dataclass(frozen=True)
class LongArticlePlan:
    """Long-article rendering plan for the publisher contract."""

    mode: str
    total_chars: int
    sections: tuple[str, ...]
    render_pages: int
    poi: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "total_chars": self.total_chars,
            "sections": list(self.sections),
            "render_pages": self.render_pages,
            "poi": self.poi,
        }


def plan_long_article(
    body: str,
    *,
    threshold: int = 800,
    section_chars: int = 400,
    poi: str = "",
) -> LongArticlePlan:
    """Choose standard vs. long-article mode and split into render sections."""
    text = _text(body)
    limit = max(1, int(section_chars))
    if len(text) < max(1, int(threshold)):
        return LongArticlePlan(
            mode="standard",
            total_chars=len(text),
            sections=(text,) if text else (),
            render_pages=1 if text else 0,
            poi=_text(poi),
        )
    sections = tuple(text[index : index + limit] for index in range(0, len(text), limit))
    return LongArticlePlan(
        mode="long_article",
        total_chars=len(text),
        sections=sections,
        render_pages=len(sections),
        poi=_text(poi),
    )


class StorageTier(StrEnum):
    """Three-tier PostgreSQL retention lifecycle."""

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


@dataclass(frozen=True)
class StorageTierPlan:
    """Retention decision for one workflow run."""

    tier: StorageTier
    checkpoint_folding: bool
    retain_full_events: bool
    archive_format: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "checkpoint_folding": self.checkpoint_folding,
            "retain_full_events": self.retain_full_events,
            "archive_format": self.archive_format,
            "reason": self.reason,
        }


def plan_storage_tier(
    *,
    age_hours: float,
    status: str = "completed",
    snapshots_collected: int = 0,
    snapshot_target: int = 10,
) -> StorageTierPlan:
    """Pick hot/warm/cold retention from age, status and snapshot completeness."""
    hours = max(0.0, _number(age_hours))
    status_key = _text(status).lower()
    active = status_key in {"running", "interrupted", "paused", "awaiting_review", "review"}
    if active or hours < 48.0:
        return StorageTierPlan(
            tier=StorageTier.HOT,
            checkpoint_folding=False,
            retain_full_events=True,
            archive_format="",
            reason="active_or_under_48h",
        )
    if hours > 90.0 * 24.0:
        return StorageTierPlan(
            tier=StorageTier.COLD,
            checkpoint_folding=True,
            retain_full_events=False,
            archive_format="parquet-jsonl-monthly",
            reason="older_than_90d",
        )
    folding = max(0, int(snapshots_collected)) >= max(1, int(snapshot_target))
    return StorageTierPlan(
        tier=StorageTier.WARM,
        checkpoint_folding=folding,
        retain_full_events=not folding,
        archive_format="" if not folding else "hydrated-run-summary",
        reason="48h_to_90d_snapshot_complete" if folding else "48h_to_90d_awaiting_snapshots",
    )


def build_state_compaction_plan(workflows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate retention decisions and an estimated row reduction for a batch."""
    counts = {tier.value: 0 for tier in StorageTier}
    plans: list[dict[str, Any]] = []
    for item in workflows:
        plan = plan_storage_tier(
            age_hours=_number(item.get("age_hours")),
            status=_text(item.get("status")) or "completed",
            snapshots_collected=int(_number(item.get("snapshots_collected"))),
            snapshot_target=int(_number(item.get("snapshot_target"), 10.0)),
        )
        counts[plan.tier.value] += 1
        plans.append(plan.as_dict())
    total = len(plans)
    retained_ratio = 1.0
    if total:
        retained_ratio = (
            counts[StorageTier.HOT.value]
            + counts[StorageTier.WARM.value] * 0.2
            + counts[StorageTier.COLD.value] * 0.05
        ) / total
    return {
        "workflow_count": total,
        "tier_counts": counts,
        "estimated_row_reduction": round(max(0.0, 1.0 - retained_ratio), 4),
        "plans": plans,
    }


@dataclass(frozen=True)
class GoldenSuiteCase:
    """One offline golden-suite case descriptor."""

    case_id: str
    category: str
    expects_block: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "expects_block": self.expects_block,
        }


def _default_golden_cases() -> tuple[GoldenSuiteCase, ...]:
    cases: list[GoldenSuiteCase] = []
    for index in range(1, 51):
        category = _GOLDEN_CASE_CATEGORIES[(index - 1) % len(_GOLDEN_CASE_CATEGORIES)]
        cases.append(
            GoldenSuiteCase(case_id=f"case-{index:03d}", category=category, expects_block=True)
        )
    return tuple(cases)


DEFAULT_GOLDEN_CASES: tuple[GoldenSuiteCase, ...] = _default_golden_cases()


def build_golden_suite_manifest(
    cases: Iterable[GoldenSuiteCase] | None = None,
) -> dict[str, Any]:
    """Build a deterministic 50-case (by default) golden-suite manifest."""
    items = tuple(cases) if cases is not None else DEFAULT_GOLDEN_CASES
    category_counts: dict[str, int] = {}
    for case in items:
        category_counts[case.category] = category_counts.get(case.category, 0) + 1
    return {
        "case_count": len(items),
        "category_counts": category_counts,
        "cases": [case.as_dict() for case in items],
        "required_gates": dict(GOLDEN_GATES),
    }


def evaluate_golden_suite(
    *,
    policy_compliance_recall: float,
    plad_human_pass_rate: float,
    cross_account_collision_leak: int,
    context_prefix_cache_hit_ratio: float,
) -> dict[str, Any]:
    """Apply the four hard CI gates from ledger scheme #42."""
    gates = {
        "policy_compliance_recall": _unit(_number(policy_compliance_recall)) >= 1.0,
        "plad_human_pass_rate": _unit(_number(plad_human_pass_rate)) >= 0.90,
        "cross_account_collision_leak": int(_number(cross_account_collision_leak)) == 0,
        "context_prefix_cache_hit_ratio": _unit(_number(context_prefix_cache_hit_ratio)) >= 0.85,
    }
    failed = [name for name, passed in gates.items() if not passed]
    return {"passed": not failed, "gates": gates, "failed_gates": failed}


def content_digest(text: str) -> str:
    """Stable short content digest used by review/replay contracts."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
