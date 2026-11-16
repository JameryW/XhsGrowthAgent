"""Phase-3 launch contracts (ledger schemes 13-18).

The helpers in this module are deliberately deterministic and dependency-free so
that graph nodes and API routes can use them as guard rails without changing the
existing publishing contract.  They model the paper-inspired checks as bounded
engineering approximations; they are not a re-implementation of the papers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

__all__ = [
    "AccountSessionCircuitBreaker",
    "MultimodalSynergyReport",
    "RiskSignal",
    "RiskSignalStrip",
    "SessionCircuitSnapshot",
    "SessionState",
    "TagLayer",
    "TagPlan",
    "build_risk_signal_strip",
    "build_tag_plan",
    "classify_root_cause",
    "evaluate_multimodal_synergy",
    "estimate_note_cost",
    "sse_event_frame",
    "tag_plan_errors",
]

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
_EMPTY_VALUES = {"", None}


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _tokens(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(text or "")}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(_as_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(_as_text(item) for item in value)
    return str(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class SynergyDimension:
    """One explainable dimension of the multimodal launch gate."""

    name: str
    score: float
    weight: float
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": round(self.score, 2),
            "weight": self.weight,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class MultimodalSynergyReport:
    """Result of :func:`evaluate_multimodal_synergy`."""

    overall: float
    threshold: float
    passed: bool
    dimensions: tuple[SynergyDimension, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall": round(self.overall, 2),
            "threshold": self.threshold,
            "passed": self.passed,
            "dimensions": [item.as_dict() for item in self.dimensions],
            "recommendations": list(self.recommendations),
        }


def evaluate_multimodal_synergy(
    title: str,
    body: str,
    visual_plan: Mapping[str, Any] | None,
    *,
    niche: str = "",
    threshold: float = 60.0,
) -> MultimodalSynergyReport:
    """Score copy/visual complementarity, thumbnail readability and aesthetic fit.

    The score is intentionally explainable and cheap: it can run before an image
    is rendered, which is exactly where the cold-start gate needs it.
    """

    plan = _mapping(visual_plan)
    copy_text = f"{title or ''}\n{body or ''}".strip()
    visual_text = _as_text(plan)
    copy_tokens = _tokens(copy_text)
    visual_tokens = _tokens(visual_text)
    overlap = len(copy_tokens & visual_tokens) / max(1, len(copy_tokens))
    # Some overlap is healthy (the image should echo the promise).  Identical
    # copy pasted into the image is not, and zero overlap usually means the
    # visual plan lost the content promise entirely.
    complementarity = _clip(100.0 - abs(overlap - 0.25) * 160.0)
    if not visual_text:
        complementarity = 45.0

    overlay = _as_text(plan.get("text_overlay", plan.get("overlay_text", "")))
    prompts = plan.get("image_prompts") or plan.get("images") or ()
    image_count = int(plan.get("image_count") or len(prompts) or 1)
    title_length = len((title or "").strip())
    readability = 55.0
    if 1 <= title_length <= 20:
        readability += 15.0
    elif title_length <= 30:
        readability += 5.0
    if overlay and len(overlay) <= 12:
        readability += 15.0
    elif not overlay:
        readability += 8.0
    if 1 <= image_count <= 9:
        readability += 5.0
    readability = _clip(readability)

    style_text = _as_text(
        [
            plan.get("style_suggestion", ""),
            plan.get("layout_style", ""),
            plan.get("style", ""),
            plan.get("layout", ""),
        ]
    )
    aesthetic = 60.0
    if niche and _tokens(niche) & visual_tokens:
        aesthetic += 20.0
    if style_text.strip():
        aesthetic += 20.0
    aesthetic = _clip(aesthetic)

    dimensions = (
        SynergyDimension("complementarity", complementarity, 0.40, f"token_overlap={overlap:.2f}"),
        SynergyDimension("thumbnail_readability", readability, 0.35, f"title_len={title_length}"),
        SynergyDimension("aesthetic_fit", aesthetic, 0.25, f"niche={niche or 'unspecified'}"),
    )
    overall = sum(item.score * item.weight for item in dimensions)
    recommendations: list[str] = []
    if complementarity < 60:
        recommendations.append("让图片承担标题无法表达的场景/证据，避免图文重复或完全脱节")
    if readability < 60:
        recommendations.append("标题压到 20 字内，封面叠字不超过 12 字，首图控制在 9 张以内")
    if aesthetic < 65:
        recommendations.append("补充垂类风格与版式关键词，使视觉方案与赛道一致")
    return MultimodalSynergyReport(
        overall=overall,
        threshold=threshold,
        passed=overall >= threshold,
        dimensions=dimensions,
        recommendations=tuple(recommendations),
    )


@dataclass(frozen=True)
class TagLayer:
    """One layer of the TagLLM-style three-tier tag plan."""

    name: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "tags": list(self.tags)}


@dataclass(frozen=True)
class TagPlan:
    """A compact 5-8 tag plan with core/entity/long-tail layers."""

    core: TagLayer
    entity: TagLayer
    long_tail: TagLayer
    tags: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "core": self.core.as_dict(),
            "entity": self.entity.as_dict(),
            "long_tail": self.long_tail.as_dict(),
            "tags": list(self.tags),
        }


def _normalise_tag(tag: str) -> str:
    value = str(tag or "").strip().lstrip("#").strip()
    return re.sub(r"\s+", "", value)


def build_tag_plan(
    core_tags: Iterable[str],
    visual_entities: Iterable[str] = (),
    long_tail_terms: Iterable[str] = (),
    *,
    max_tags: int = 8,
) -> TagPlan:
    """Distill core, multimodal-entity and long-tail tags into one compact plan."""

    def _unique(values: Iterable[str], limit: int) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            tag = _normalise_tag(value)
            key = tag.casefold()
            if tag and key not in seen and len(tag) <= 24:
                seen.add(key)
                result.append(tag)
            if len(result) >= limit:
                break
        return result

    core = _unique(core_tags, 2)
    entity = _unique(visual_entities, 3)
    long_tail = _unique(long_tail_terms, 3)
    ordered: list[str] = []
    seen: set[str] = set()
    for tag in [*core, *entity, *long_tail]:
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            ordered.append(tag)
    ordered = ordered[:max_tags]
    return TagPlan(
        core=TagLayer("core", tuple(core)),
        entity=TagLayer("entity", tuple(entity)),
        long_tail=TagLayer("long_tail", tuple(long_tail)),
        tags=tuple(ordered),
    )


def tag_plan_errors(plan: TagPlan) -> list[str]:
    """Return human-readable contract errors for a tag plan."""

    errors: list[str] = []
    if not 5 <= len(plan.tags) <= 8:
        errors.append("tag_count_must_be_5_to_8")
    if not 1 <= len(plan.core.tags) <= 2:
        errors.append("core_tag_count_must_be_1_to_2")
    if not 2 <= len(plan.entity.tags) <= 3:
        errors.append("entity_tag_count_must_be_2_to_3")
    if not 2 <= len(plan.long_tail.tags) <= 3:
        errors.append("long_tail_tag_count_must_be_2_to_3")
    return errors


@dataclass(frozen=True)
class RiskSignal:
    """One legible risk badge for the review gate."""

    code: str
    level: str
    label: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "level": self.level,
            "label": self.label,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RiskSignalStrip:
    """Consolidated red/amber/green signal strip."""

    overall: str
    blocking: bool
    signals: tuple[RiskSignal, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "blocking": self.blocking,
            "signals": [item.as_dict() for item in self.signals],
        }


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def build_risk_signal_strip(
    *,
    publish_eligibility: Any = None,
    evaluation: Any = None,
    novelty: Any = None,
    plad: Any = None,
    creator_rule_diff: Any = None,
) -> RiskSignalStrip:
    """Build an explainable review-gate strip from existing signal payloads."""

    signals: list[RiskSignal] = []
    eligibility = _mapping(publish_eligibility)
    if eligibility:
        eligible = eligibility.get("eligible", eligibility.get("allowed", True))
        blocked = bool(eligibility.get("blocked") or eligibility.get("denied"))
        if eligible is False or blocked:
            reason = _as_text(
                eligibility.get("reasons")
                or eligibility.get("blocking_reasons")
                or eligibility.get("reason")
            )
            signals.append(RiskSignal("publish_eligibility", "red", "发布资格阻断", reason))
        else:
            signals.append(RiskSignal("publish_eligibility", "green", "发布资格通过"))

    evaluation_map = _mapping(evaluation)
    if evaluation_map:
        decision = str(evaluation_map.get("decision", "")).upper()
        quality_gate = _mapping(evaluation_map.get("quality_gate"))
        blocked_dimensions = quality_gate.get("blocked_dimensions") or []
        if decision == "REJECTED" or blocked_dimensions:
            signals.append(
                RiskSignal(
                    "quality_gate",
                    "red",
                    "质量底线未通过",
                    _as_text(blocked_dimensions) or decision,
                )
            )
        elif decision == "NEEDS_REVISION":
            signals.append(RiskSignal("quality_gate", "amber", "质量需要修改", decision))
        else:
            signals.append(RiskSignal("quality_gate", "green", "质量底线通过"))

    novelty_map = _mapping(novelty)
    if novelty_map:
        similarity = float(novelty_map.get("max_similarity") or 0.0)
        duplicate = bool(novelty_map.get("is_duplicate_risk"))
        if duplicate or similarity >= 0.82:
            signals.append(
                RiskSignal("novelty", "red", "历史相似度过高", f"max_similarity={similarity:.2f}")
            )
        elif similarity >= 0.70:
            signals.append(
                RiskSignal("novelty", "amber", "历史相似度偏高", f"max_similarity={similarity:.2f}")
            )
        else:
            signals.append(RiskSignal("novelty", "green", "新颖度通过"))

    plad_map = _mapping(plad)
    if plad_map:
        ai_likelihood = float(plad_map.get("ai_likelihood") or 0.0)
        level = "amber" if ai_likelihood >= 0.60 else "green"
        signals.append(RiskSignal("plad", level, "AI 味检查", f"ai_likelihood={ai_likelihood:.2f}"))

    if isinstance(creator_rule_diff, Mapping):
        changed = creator_rule_diff.get("changes") or []
        if changed:
            level = str(creator_rule_diff.get("level") or "amber")
            signals.append(
                RiskSignal("creator_rules", level, "Creator 规则变化", _as_text(changed))
            )
    elif creator_rule_diff:
        signals.append(
            RiskSignal("creator_rules", "amber", "Creator 规则变化", _as_text(creator_rule_diff))
        )

    levels = {signal.level for signal in signals}
    overall = "red" if "red" in levels else "amber" if "amber" in levels else "green"
    return RiskSignalStrip(
        overall=overall,
        blocking="red" in levels,
        signals=tuple(signals),
    )


class SessionState(StrEnum):
    """Three-state account/session circuit."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OPEN_COOLDOWN = "open_cooldown"


@dataclass(frozen=True)
class SessionCircuitSnapshot:
    account_id: str
    state: SessionState
    failure_count: int
    opened_at: datetime | None
    reason: str
    cooldown_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "reason": self.reason,
            "cooldown_seconds": self.cooldown_seconds,
        }


_TRIP_MARKERS = (
    "signature_unavailable",
    "signature unavailable",
    "login_required",
    "login required",
    "session_expired",
    "session expired",
    "slider_challenge",
    "slider challenge",
    "captcha",
    "验证码",
    "滑块",
    "登录失效",
)


class AccountSessionCircuitBreaker:
    """Small deterministic breaker for Playwright/CDP account sessions.

    Explicit authentication/slider/signature failures open the circuit
    immediately; ordinary transient failures only degrade it after three
    consecutive occurrences.
    """

    def __init__(
        self,
        account_id: str,
        *,
        cooldown_seconds: float = 1800.0,
        degraded_threshold: int = 3,
    ) -> None:
        self.account_id = account_id
        self.cooldown_seconds = cooldown_seconds
        self.degraded_threshold = max(1, degraded_threshold)
        self._state = SessionState.HEALTHY
        self._failure_count = 0
        self._opened_at: datetime | None = None
        self._reason = ""

    @staticmethod
    def classify_failure(error_code: str = "", message: str = "") -> str | None:
        haystack = f"{error_code} {message}".casefold()
        if any(marker in haystack for marker in _TRIP_MARKERS):
            return "trip"
        if any(
            marker in haystack for marker in ("timeout", "temporarily", "network", "5xx", "429")
        ):
            return "degrade"
        return None

    def _now(self, now: datetime | None) -> datetime:
        return now or datetime.now(UTC)

    def record_success(self, now: datetime | None = None) -> SessionCircuitSnapshot:
        self._state = SessionState.HEALTHY
        self._failure_count = 0
        self._opened_at = None
        self._reason = ""
        return self.snapshot(now)

    def record_failure(
        self,
        error_code: str = "",
        message: str = "",
        *,
        now: datetime | None = None,
    ) -> SessionCircuitSnapshot:
        current = self._now(now)
        kind = self.classify_failure(error_code, message)
        if kind == "trip":
            self._state = SessionState.OPEN_COOLDOWN
            self._opened_at = current
            self._reason = f"{error_code}: {message}".strip(": ")
            self._failure_count += 1
        elif kind == "degrade":
            self._failure_count += 1
            if self._failure_count >= self.degraded_threshold:
                self._state = SessionState.DEGRADED
                self._reason = f"{error_code}: {message}".strip(": ")
        return self.snapshot(current)

    def allow_attempt(self, now: datetime | None = None) -> bool:
        current = self._now(now)
        if self._state is SessionState.OPEN_COOLDOWN:
            if self._opened_at and current - self._opened_at >= timedelta(
                seconds=self.cooldown_seconds
            ):
                self._state = SessionState.HEALTHY
                self._opened_at = None
                self._reason = ""
                return True
            return False
        return True

    def snapshot(self, now: datetime | None = None) -> SessionCircuitSnapshot:
        return SessionCircuitSnapshot(
            account_id=self.account_id,
            state=self._state,
            failure_count=self._failure_count,
            opened_at=self._opened_at,
            reason=self._reason,
            cooldown_seconds=self.cooldown_seconds,
        )


def classify_root_cause(
    *,
    error_code: str = "",
    message: str = "",
    phase: str = "",
) -> dict[str, Any]:
    """Classify a failed unit of work into a stable root-cause bucket."""

    text = f"{error_code} {message} {phase}".casefold()
    if any(
        marker in text
        for marker in ("signature_unavailable", "login", "session", "captcha", "滑块")
    ):
        bucket, retryable = "session_circuit_open", False
    elif any(marker in text for marker in ("compliance", "forbidden", "banned", "违禁", "审核")):
        bucket, retryable = "deterministic_compliance_block", False
    elif any(
        marker in text for marker in ("timeout", "timed_out", "rate_limit", "429", "5xx", "network")
    ):
        bucket, retryable = "transient_model_or_network", True
    elif any(marker in text for marker in ("human_reject", "rejected", "驳回")):
        bucket, retryable = "human_rejected", False
    else:
        bucket, retryable = "unknown", True
    return {
        "bucket": bucket,
        "retryable": retryable,
        "error_code": error_code,
        "phase": phase,
    }


def estimate_note_cost(
    events: Iterable[Mapping[str, Any]],
    *,
    input_price_per_mtok: float = 2.0,
    output_price_per_mtok: float = 8.0,
) -> dict[str, Any]:
    """Sum prompt/completion tokens and estimated USD cost for one note."""

    input_tokens = 0
    output_tokens = 0
    explicit_cost = 0.0
    count = 0
    for event in events:
        if not isinstance(event, Mapping):
            continue
        payload = _mapping(event.get("payload", event))
        input_tokens += int(payload.get("input_tokens") or payload.get("prompt_tokens") or 0)
        output_tokens += int(payload.get("output_tokens") or payload.get("completion_tokens") or 0)
        if payload.get("cost_usd") is not None:
            explicit_cost += float(payload["cost_usd"])
        count += 1
    computed = (
        input_tokens / 1_000_000 * input_price_per_mtok
        + output_tokens / 1_000_000 * output_price_per_mtok
    )
    return {
        "event_count": count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": round(explicit_cost or computed, 6),
    }


def sse_event_frame(seq: int | str, event_type: str, payload: Any) -> str:
    """Format a durable workflow event as an SSE frame."""

    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"id: {seq}\nevent: {event_type}\ndata: {data}\n\n"
