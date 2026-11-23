"""Phase-8 interaction contracts (ledger schemes 43-48).

Deterministic helpers for local request guarding, DM quota uplift routing,
persistent visual memory, tool-output retention, evergreen revival and
double-ended review ETags. No HTTP server, database or LLM is imported here.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

__all__ = [
    "DEFAULT_ALLOWED_ORIGINS",
    "DmAllocation",
    "DmCandidate",
    "DmStratum",
    "EscalationDecision",
    "EvergreenCandidate",
    "LocalRequestDecision",
    "RETENTION_CONTRACTS",
    "RetentionContract",
    "RevivalPlan",
    "SceneVisualMemoryBank",
    "SceneVisualProfile",
    "StaleReviewETagError",
    "TerminalDecisionCard",
    "ToolProjection",
    "VisualDna",
    "allocate_dm_quota",
    "assert_review_etag",
    "build_revival_plan",
    "build_terminal_decision_card",
    "build_two_hop_reply",
    "build_visual_directive",
    "classify_dm_candidate",
    "compute_review_etag",
    "contains_external_contact",
    "evaluate_local_request",
    "generate_boot_token",
    "is_allowed_origin",
    "is_loopback_host",
    "project_tool_output",
    "scan_evergreen_notes",
    "should_escalate",
]

DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver", "0.0.0.0"}
_STATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_EXTERNAL_CONTACT_PATTERNS = (
    re.compile(r"(?:微信|weixin|wechat|vx|v信|qq)\s*[:：]?\s*[A-Za-z0-9_-]{4,}", re.IGNORECASE),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"https?://[^\s]+|www\.[^\s]+", re.IGNORECASE),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)

DEFAULT_SCENE_LAYOUTS: dict[str, tuple[str, ...]] = {
    "food": ("暖色微距首图 + 价格/热量角标 + 九宫格菜品", "拼图 + 店内环境"),
    "travel": ("路线地图 + 实景拼图 + 费用清单", "封面大字 + 行程表"),
    "outfit": ("全身镜面穿搭 + 单品标签 + 色卡", "三宫格对比"),
    "beauty": ("前后对比 + 成分特写 + 使用步骤", "产品平铺 + 质地微距"),
    "lifestyle": ("生活场景 + 手写标注 + 清单卡", "氛围拼图"),
    "fitness": ("动作分解 + 训练计划表 + 数据角标", "前后对比"),
    "home": ("空间改造前后 + 尺寸标注 + 采购清单", "俯拍全景 + 局部特写"),
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


def _normalized_host(host_header: str) -> str:
    """Strip a port from a Host header, including bracketed IPv6 hosts."""
    value = _text(host_header).lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


def is_loopback_host(host_header: str) -> bool:
    """Return True when a Host header names the local machine (or test client)."""
    return _normalized_host(host_header) in _LOCAL_HOSTS


def is_allowed_origin(origin: str, allowed_origins: Iterable[str] = ()) -> bool:
    """Return True when an Origin header is in the explicit local allow-list."""
    allowed = {_text(item).lower() for item in allowed_origins if _text(item)}
    if not allowed:
        allowed = set(DEFAULT_ALLOWED_ORIGINS)
    return _text(origin).lower() in allowed


@dataclass(frozen=True)
class LocalRequestDecision:
    """Result of the anti-CSWSH / anti-DNS-rebinding request check."""

    allowed: bool
    status_code: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "status_code": self.status_code, "reason": self.reason}


def evaluate_local_request(
    *,
    host: str,
    origin: str = "",
    method: str = "GET",
    is_websocket: bool = False,
    boot_token: str = "",
    presented_token: str = "",
    allowed_origins: Iterable[str] = (),
) -> LocalRequestDecision:
    """Evaluate Host/Origin/boot-token rules for a local-only API request."""
    if host and not is_loopback_host(host):
        return LocalRequestDecision(False, 421, "host_not_loopback")
    state_changing = is_websocket or _text(method).upper() in _STATE_METHODS
    if state_changing:
        origin_value = _text(origin)
        if is_websocket and not origin_value:
            return LocalRequestDecision(False, 403, "websocket_origin_missing")
        if origin_value and not is_allowed_origin(origin_value, allowed_origins):
            return LocalRequestDecision(False, 403, "origin_not_allowed")
        if _text(boot_token) and _text(presented_token) != _text(boot_token):
            return LocalRequestDecision(False, 403, "boot_token_mismatch")
    return LocalRequestDecision(True, 200, "ok")


def generate_boot_token(length: int = 32) -> str:
    """Generate a 256-bit-class ephemeral boot token for local web clients."""
    return secrets.token_urlsafe(max(16, int(length)))


class DmStratum(StrEnum):
    """Causal uplift strata from ledger scheme #44."""

    PERSUADABLE = "persuadables"
    SURE_THING = "sure_things"
    LOST_CAUSE = "lost_causes"
    SLEEPING_DOG = "sleeping_dogs"


@dataclass(frozen=True)
class DmCandidate:
    """One inbound DM candidate for quota allocation."""

    user_id: str
    base_conversion: float
    intervention_conversion: float
    intent_score: float = 0.0
    is_hostile: bool = False

    @property
    def uplift(self) -> float:
        return self.intervention_conversion - self.base_conversion

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "base_conversion": round(self.base_conversion, 4),
            "intervention_conversion": round(self.intervention_conversion, 4),
            "intent_score": round(self.intent_score, 4),
            "is_hostile": self.is_hostile,
            "uplift": round(self.uplift, 4),
        }


@dataclass(frozen=True)
class DmAllocation:
    """One quota allocation decision."""

    user_id: str
    stratum: DmStratum
    action: str
    expected_uplift: float
    quota_cost: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "stratum": self.stratum.value,
            "action": self.action,
            "expected_uplift": round(self.expected_uplift, 4),
            "quota_cost": self.quota_cost,
        }


def classify_dm_candidate(candidate: DmCandidate) -> DmStratum:
    """Classify a candidate into one of the four causal-uplift strata."""
    uplift = candidate.uplift
    if candidate.is_hostile or uplift <= 0.0:
        return DmStratum.SLEEPING_DOG
    if candidate.base_conversion >= 0.60 and uplift < 0.10:
        return DmStratum.SURE_THING
    if uplift >= 0.10 or (candidate.intent_score >= 0.60 and uplift >= 0.05):
        return DmStratum.PERSUADABLE
    return DmStratum.LOST_CAUSE


def allocate_dm_quota(candidates: Iterable[DmCandidate], *, daily_quota: int) -> list[DmAllocation]:
    """Allocate a hard daily DM quota by stratum and causal uplift."""
    quota = max(0, int(daily_quota))
    priority = {
        DmStratum.PERSUADABLE: 0,
        DmStratum.SURE_THING: 1,
        DmStratum.LOST_CAUSE: 2,
        DmStratum.SLEEPING_DOG: 3,
    }
    ordered = sorted(
        candidates,
        key=lambda item: (priority[classify_dm_candidate(item)], -item.uplift, item.user_id),
    )
    used = 0
    allocations: list[DmAllocation] = []
    for candidate in ordered:
        stratum = classify_dm_candidate(candidate)
        if stratum is DmStratum.PERSUADABLE:
            if used < quota:
                action = "full_fsm"
                cost = 1
                used += 1
            else:
                action = "defer_next_day"
                cost = 0
        elif stratum is DmStratum.SURE_THING:
            if used < quota:
                action = "one_shot_card"
                cost = 1
                used += 1
            else:
                action = "defer_next_day"
                cost = 0
        elif stratum is DmStratum.LOST_CAUSE:
            action = "public_reply_only"
            cost = 0
        else:
            action = "silent_block"
            cost = 0
        allocations.append(
            DmAllocation(
                user_id=candidate.user_id,
                stratum=stratum,
                action=action,
                expected_uplift=max(0.0, candidate.uplift),
                quota_cost=cost,
            )
        )
    return allocations


def contains_external_contact(text: str) -> bool:
    """True when text contains a phone/email/URL/WeChat-style external contact."""
    value = _text(text)
    return any(pattern.search(value) for pattern in _EXTERNAL_CONTACT_PATTERNS)


def build_two_hop_reply(answer: str, keyword: str) -> str:
    """Strip external contacts and route the user to an inbound-DM two-hop funnel."""
    cleaned = _text(answer)
    for pattern in _EXTERNAL_CONTACT_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    token = _text(keyword) or "档期"
    guidance = f"更多细节整理在置顶第2张图，戳我头像发【{token}】给你发档期表。"
    return f"{cleaned} {guidance}".strip()


@dataclass(frozen=True)
class VisualDna:
    """Immutable account-level visual anchors."""

    account_id: str
    primary_color: str = "#FFFFFF"
    secondary_color: str = "#111111"
    accent_color: str = "#FF4D4F"
    title_weight_ratio: float = 1.6
    subject_tokens: tuple[str, ...] = field(default_factory=tuple)
    negative_tokens: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "accent_color": self.accent_color,
            "title_weight_ratio": round(self.title_weight_ratio, 2),
            "subject_tokens": list(self.subject_tokens),
            "negative_tokens": list(self.negative_tokens),
        }


@dataclass(frozen=True)
class SceneVisualProfile:
    """Feedback-revisable visual profile for one scene."""

    scene: str
    preferred_layouts: tuple[str, ...]
    weight: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "preferred_layouts": list(self.preferred_layouts),
            "weight": round(self.weight, 3),
        }


class SceneVisualMemoryBank:
    """Two-layer visual memory: immutable brand DNA + feedback-revised scenes."""

    def __init__(
        self,
        dna_by_account: Mapping[str, VisualDna] | None = None,
        scene_profiles: Mapping[str, SceneVisualProfile] | None = None,
    ) -> None:
        self._dna: dict[str, VisualDna] = dict(dna_by_account or {})
        self._scenes: dict[str, SceneVisualProfile] = dict(scene_profiles or {})

    def get_dna(self, account_id: str) -> VisualDna:
        key = _text(account_id) or "default"
        existing = self._dna.get(key)
        if existing is not None:
            return existing
        return VisualDna(account_id=key)

    def set_dna(self, dna: VisualDna) -> None:
        self._dna[dna.account_id] = dna

    def adapt_scene(self, scene: str, *, feedback_score: float = 0.0) -> SceneVisualProfile:
        key = _text(scene).lower() or "lifestyle"
        existing = self._scenes.get(key)
        if existing is None:
            existing = SceneVisualProfile(
                scene=key,
                preferred_layouts=DEFAULT_SCENE_LAYOUTS.get(key, ("单图聚焦",)),
            )
        weight = max(0.5, min(2.0, existing.weight + 0.1 * _number(feedback_score)))
        updated = SceneVisualProfile(
            scene=key,
            preferred_layouts=existing.preferred_layouts,
            weight=round(weight, 3),
        )
        self._scenes[key] = updated
        return updated


def build_visual_directive(
    bank: SceneVisualMemoryBank, account_id: str, scene: str
) -> dict[str, Any]:
    """Compose the visual_designer directive from brand DNA and scene profile."""
    profile = bank.adapt_scene(scene)
    dna = bank.get_dna(account_id)
    return {
        "account_id": dna.account_id,
        "scene": profile.scene,
        "palette": {
            "primary": dna.primary_color,
            "secondary": dna.secondary_color,
            "accent": dna.accent_color,
        },
        "title_weight_ratio": dna.title_weight_ratio,
        "preferred_layouts": list(profile.preferred_layouts),
        "scene_weight": profile.weight,
        "subject_tokens": list(dna.subject_tokens),
        "negative_tokens": list(dna.negative_tokens),
    }


@dataclass(frozen=True)
class RetentionContract:
    """Per-tool projection contract for the Tool Gateway."""

    tool: str
    fields: tuple[str, ...]
    max_chars: int


RETENTION_CONTRACTS: dict[str, RetentionContract] = {
    "xhs_trending": RetentionContract(
        tool="xhs_trending", fields=("notes", "keywords", "captured_at"), max_chars=6000
    ),
    "competitor_analyzer": RetentionContract(
        tool="competitor_analyzer", fields=("competitors", "summary", "captured_at"), max_chars=6000
    ),
    "analytics_reader": RetentionContract(
        tool="analytics_reader", fields=("note_id", "snapshots", "metrics"), max_chars=4000
    ),
    "ripple_predict": RetentionContract(
        tool="ripple_predict", fields=("prediction", "provider_insights", "job_id"), max_chars=4000
    ),
    "keyword_monitor": RetentionContract(
        tool="keyword_monitor", fields=("keywords", "captured_at"), max_chars=3000
    ),
}


@dataclass(frozen=True)
class ToolProjection:
    """Compact tool result plus its size accounting."""

    tool: str
    payload: dict[str, Any]
    original_chars: int
    projected_chars: int
    retention_ratio: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "payload": self.payload,
            "original_chars": self.original_chars,
            "projected_chars": self.projected_chars,
            "retention_ratio": round(self.retention_ratio, 4),
        }


def project_tool_output(
    tool_name: str,
    payload: Mapping[str, Any],
    *,
    max_chars: int | None = None,
) -> ToolProjection:
    """Project a tool payload onto its retention contract before state/L4."""
    name = _text(tool_name)
    contract = RETENTION_CONTRACTS.get(name)
    if contract is not None:
        selected = {key: payload[key] for key in contract.fields if key in payload}
        limit = max(64, int(max_chars if max_chars is not None else contract.max_chars))
    else:
        selected = dict(payload)
        limit = max(64, int(max_chars if max_chars is not None else 8000))
    original = json.dumps(dict(payload), ensure_ascii=False, default=str)
    encoded = json.dumps(selected, ensure_ascii=False, default=str)
    if len(encoded) > limit:
        per_field = max(16, limit // max(1, len(selected)))
        clipped: dict[str, Any] = {}
        for key, value in selected.items():
            if isinstance(value, str) and len(value) > per_field:
                clipped[key] = value[:per_field] + "…"
            else:
                clipped[key] = value
        selected = clipped
        encoded = json.dumps(selected, ensure_ascii=False, default=str)
    original_chars = len(original)
    projected_chars = len(encoded)
    ratio = projected_chars / original_chars if original_chars else 0.0
    return ToolProjection(
        tool=name,
        payload=selected,
        original_chars=original_chars,
        projected_chars=projected_chars,
        retention_ratio=ratio,
    )


@dataclass(frozen=True)
class EscalationDecision:
    """CascadeRec history-gated tier decision."""

    tier: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "reason": self.reason}


def should_escalate(
    *,
    note_count: int,
    sample_credibility: float,
    is_commercial: bool = False,
) -> EscalationDecision:
    """Escalate only for dense history or high-value commercial briefs."""
    if is_commercial:
        return EscalationDecision("tier2", "commercial_high_value")
    if int(note_count) >= 5 and _unit(_number(sample_credibility)) >= 0.35:
        return EscalationDecision("tier2", "history_dense")
    return EscalationDecision("tier1", "cold_start_or_sparse_history")


@dataclass(frozen=True)
class EvergreenCandidate:
    """A mature high-collect note eligible for Lindy revival."""

    note_id: str
    age_days: float
    collect_rate: float
    search_traffic_delta: float
    title: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "age_days": round(self.age_days, 2),
            "collect_rate": round(self.collect_rate, 4),
            "search_traffic_delta": round(self.search_traffic_delta, 4),
            "title": self.title,
        }


def scan_evergreen_notes(
    notes: Iterable[Mapping[str, Any]],
    *,
    min_age_days: float = 120.0,
    max_age_days: float = 180.0,
    traffic_drop: float = 0.25,
    top_quantile: float = 0.25,
) -> list[EvergreenCandidate]:
    """Find notes in the 120-180d window or with a >25% search-traffic drop."""
    items = list(notes)
    if not items:
        return []
    collect_rates = sorted(max(0.0, _number(item.get("collect_rate"))) for item in items)
    cut_index = max(0, int(len(collect_rates) * (1.0 - _unit(_number(top_quantile, 0.25)))))
    threshold = collect_rates[min(cut_index, len(collect_rates) - 1)]
    drop = abs(_number(traffic_drop, 0.25))
    candidates: list[EvergreenCandidate] = []
    for item in items:
        note_id = _text(item.get("note_id"))
        if not note_id:
            continue
        age = max(0.0, _number(item.get("age_days")))
        collect_rate = max(0.0, _number(item.get("collect_rate")))
        delta = _number(item.get("search_traffic_delta"))
        in_window = float(min_age_days) <= age <= float(max_age_days)
        traffic_falling = delta <= -drop
        if collect_rate >= threshold and (in_window or traffic_falling):
            candidates.append(
                EvergreenCandidate(
                    note_id=note_id,
                    age_days=age,
                    collect_rate=collect_rate,
                    search_traffic_delta=delta,
                    title=_text(item.get("title")),
                )
            )
    candidates.sort(key=lambda item: (-item.collect_rate, item.note_id))
    return candidates


@dataclass(frozen=True)
class RevivalPlan:
    """Low-cost evergreen refresh plan."""

    note_id: str
    action: str
    title_suffix: str
    refresh_fields: tuple[str, ...]
    pinned_comment: str
    estimated_cost_ratio: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "action": self.action,
            "title_suffix": self.title_suffix,
            "refresh_fields": list(self.refresh_fields),
            "pinned_comment": self.pinned_comment,
            "estimated_cost_ratio": round(self.estimated_cost_ratio, 2),
        }


def build_revival_plan(
    candidate: EvergreenCandidate, *, now: datetime | None = None
) -> RevivalPlan:
    """Build the 20%-cost sister-note revival plan for one evergreen candidate."""
    current = now if now is not None else datetime.now(UTC)
    year = current.year
    return RevivalPlan(
        note_id=candidate.note_id,
        action="sister_note_refresh",
        title_suffix=f"【{year}/{year + 1} 最新实测翻新版】",
        refresh_fields=("年份", "节假日档期", "价格", "政策/规则"),
        pinned_comment=f"旧帖置顶：已更新 {year} 最新实测版，点主页查看。",
        estimated_cost_ratio=0.2,
    )


def compute_review_etag(thread_id: str, checkpoint_ns: str, artifact_sha256: str) -> str:
    """Compute the double-ended review optimistic-lock token."""
    material = f"{thread_id}:{checkpoint_ns}:{artifact_sha256}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


class StaleReviewETagError(Exception):
    """Raised when another client already approved/revised the same review."""

    code = "stale_review_etag"
    status_code = 409

    def __init__(self, expected_etag: str, current_etag: str) -> None:
        self.expected_etag = expected_etag
        self.current_etag = current_etag
        super().__init__(f"stale review etag: expected {expected_etag!r}, got {current_etag!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "expected_etag": self.expected_etag,
            "current_etag": self.current_etag,
        }


def assert_review_etag(expected_etag: str, current_etag: str) -> None:
    """Raise 409-style error when an explicitly supplied review ETag is stale."""
    expected = _text(expected_etag)
    if expected and expected != _text(current_etag):
        raise StaleReviewETagError(expected, _text(current_etag))


@dataclass(frozen=True)
class TerminalDecisionCard:
    """Compact one-line decision card for the /xhs-review terminal."""

    account_id: str
    plad_score: float
    rqgm_score: float
    semantic_id_complete: bool
    max_cosine: float
    review_etag: str

    def render(self) -> str:
        plad_state = "PASS" if self.plad_score >= 0.82 else "WARN"
        rqgm_state = "PASS" if self.rqgm_score >= 0.75 else "WARN"
        semantic_state = "PASS" if self.semantic_id_complete else "MISS"
        cosine_state = "PASS" if self.max_cosine <= 0.82 else "RISK"
        return (
            f"[绑定账号: @{self.account_id}] | "
            f"[PLAD 人类语感: {self.plad_score:.1f} {plad_state}] | "
            f"[RQGM 门控: {self.rqgm_score:.2f} {rqgm_state}] | "
            f"[OneSearch 5-SID: {semantic_state}] | "
            f"[30篇最大余弦: {self.max_cosine:.2f} {cosine_state}] | "
            f"[etag: {self.review_etag}]"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "plad_score": round(self.plad_score, 2),
            "rqgm_score": round(self.rqgm_score, 4),
            "semantic_id_complete": self.semantic_id_complete,
            "max_cosine": round(self.max_cosine, 4),
            "review_etag": self.review_etag,
            "line": self.render(),
        }


def build_terminal_decision_card(
    *,
    account_id: str,
    plad_score: float,
    rqgm_score: float,
    semantic_id_complete: bool,
    max_cosine: float,
    review_etag: str,
) -> TerminalDecisionCard:
    """Build the compact ANSI-free terminal decision card."""
    return TerminalDecisionCard(
        account_id=_text(account_id) or "unknown",
        plad_score=_unit(_number(plad_score)),
        rqgm_score=_unit(_number(rqgm_score)),
        semantic_id_complete=bool(semantic_id_complete),
        max_cosine=_unit(_number(max_cosine)),
        review_etag=_text(review_etag),
    )
