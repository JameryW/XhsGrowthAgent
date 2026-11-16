"""Phase-6 distribution and replay contracts (ledger schemes 31-36)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

__all__ = [
    "BreakoutCandidate",
    "CarouselSlide",
    "ExposureDiagnostics",
    "FanProfile",
    "FanRelationStore",
    "SCENARIO_WEIGHTS",
    "breakout_lift",
    "build_icebreaker",
    "compile_public_replay_bundle",
    "diagnose_exposure",
    "estimate_credibility",
    "plan_carousel",
    "rank_breakouts",
    "score_scenario",
]


@dataclass(frozen=True)
class ExposureDiagnostics:
    """EGMF exposure-gate diagnostics."""

    credibility: float
    suspected_throttle: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    engagement_above_baseline: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "credibility": round(self.credibility, 4),
            "suspected_throttle": self.suspected_throttle,
            "reasons": list(self.reasons),
            "engagement_above_baseline": self.engagement_above_baseline,
        }


def estimate_credibility(
    reads: int,
    age_hours: float,
    *,
    reads_target: int = 1000,
    is_throttled: bool = False,
) -> float:
    """Credibility score in [0, 1] used to distrust tiny-exposure samples."""

    reads_value = max(0.0, float(reads))
    target = max(1.0, float(reads_target))
    age = max(0.0, float(age_hours))
    volume = min(1.0, math.log1p(reads_value) / math.log1p(target))
    maturity = min(1.0, age / 48.0)
    return max(0.0, volume * maturity * (0.0 if is_throttled else 1.0))


def diagnose_exposure(
    *,
    reads: int,
    age_hours: float,
    ctr: float,
    collect_rate: float,
    baseline_ctr: float,
    baseline_collect_rate: float,
    baseline_reads: float,
    is_throttled: bool = False,
    reads_target: int = 1000,
) -> ExposureDiagnostics:
    """Detect a high-engagement / low-exposure pattern consistent with throttling."""

    engagement_above_baseline = ctr >= baseline_ctr or collect_rate >= baseline_collect_rate
    low_exposure = reads < 0.25 * max(1.0, baseline_reads) or reads < 200
    reasons: list[str] = []
    if is_throttled:
        reasons.append("explicitly_throttled")
    if low_exposure:
        reasons.append("reads_below_exposure_floor")
    if engagement_above_baseline:
        reasons.append("engagement_above_baseline")
    suspected = (is_throttled or low_exposure) and engagement_above_baseline
    return ExposureDiagnostics(
        credibility=estimate_credibility(
            reads, age_hours, reads_target=reads_target, is_throttled=is_throttled
        ),
        suspected_throttle=suspected,
        reasons=tuple(reasons),
        engagement_above_baseline=engagement_above_baseline,
    )


SCENARIO_WEIGHTS: dict[str, dict[str, float]] = {
    "trend": {"engagement": 0.40, "freshness": 0.30, "novelty": 0.30},
    "brief": {"engagement": 0.30, "contract": 0.40, "visual": 0.30},
    "free": {"engagement": 0.45, "novelty": 0.35, "execution": 0.20},
}


def score_scenario(metrics: Mapping[str, float], mode: str = "trend") -> float:
    """SAIM-style scenario-specific weighted score."""

    weights = SCENARIO_WEIGHTS.get(mode, SCENARIO_WEIGHTS["trend"])
    total = sum(max(0.0, float(metrics.get(key, 0.0))) * weight for key, weight in weights.items())
    return round(total, 4)


@dataclass(frozen=True)
class CarouselSlide:
    index: int
    role: str
    purpose: str
    token_budget: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "role": self.role,
            "purpose": self.purpose,
            "token_budget": self.token_budget,
        }


def plan_carousel(image_count: int, *, total_token_budget: int = 1000) -> list[CarouselSlide]:
    """Plan a P1 hook -> P2 conclusion -> evidence -> PN save-list arc."""

    count = max(1, int(image_count))
    budget = max(count, int(total_token_budget))
    if count == 1:
        return [CarouselSlide(1, "hook", "单图：封面钩子 + 收藏理由", budget)]
    if count == 2:
        shares = (int(budget * 0.55), budget - int(budget * 0.55))
        return [
            CarouselSlide(1, "hook", "封面钩子", shares[0]),
            CarouselSlide(2, "save_list", "结论 + 收藏清单", shares[1]),
        ]
    middle = count - 3
    middle_budget = max(middle, int(budget * 0.30)) if middle else 0
    remaining = budget - middle_budget
    hook_budget = max(1, int(remaining * 0.60))
    conclusion_budget = max(1, int(remaining * 0.15))
    last_budget = max(1, remaining - hook_budget - conclusion_budget)
    slides = [CarouselSlide(1, "hook", "P1：封面钩子 + 主承诺", hook_budget)]
    slides.append(CarouselSlide(2, "conclusion", "P2：结论卡 + 关键收益", conclusion_budget))
    each = max(1, middle_budget // middle) if middle else 0
    for offset in range(middle):
        slides.append(CarouselSlide(3 + offset, "evidence", "证据/步骤卡：一图一信息", each))
    slides.append(CarouselSlide(count, "save_list", "PN：收藏清单 + 行动提示", last_budget))
    return slides


@dataclass(frozen=True)
class BreakoutCandidate:
    note_id: str
    collects: int
    likes: int
    comments: int
    followers: int
    age_days: float
    lift: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "collects": self.collects,
            "likes": self.likes,
            "comments": self.comments,
            "followers": self.followers,
            "age_days": self.age_days,
            "lift": round(self.lift, 4),
        }


def breakout_lift(
    collects: int,
    likes: int,
    comments: int,
    followers: int,
    age_days: float,
) -> float:
    """Follower-normalized breakout lift from the ledger formula."""

    numerator = math.log1p(max(0, collects) + 0.5 * max(0, likes) + 2 * max(0, comments))
    denominator = 0.6 * math.log(10 + max(0, followers)) + 0.4 * math.log(2 + max(0.0, age_days))
    return numerator / max(denominator, 1e-9)


def rank_breakouts(
    notes: Iterable[Mapping[str, Any] | BreakoutCandidate],
    *,
    top_percent: float = 0.15,
    max_followers: int = 10_000,
) -> list[BreakoutCandidate]:
    """Rank small-follower breakout notes and keep the top percentile."""

    candidates: list[BreakoutCandidate] = []
    for note in notes:
        if isinstance(note, BreakoutCandidate):
            item = note
        else:
            item = BreakoutCandidate(
                note_id=str(note.get("note_id", note.get("id", ""))),
                collects=int(note.get("collects", 0)),
                likes=int(note.get("likes", 0)),
                comments=int(note.get("comments", 0)),
                followers=int(note.get("followers", 0)),
                age_days=float(note.get("age_days", 0)),
            )
        if item.followers >= max_followers:
            continue
        candidates.append(
            BreakoutCandidate(
                item.note_id,
                item.collects,
                item.likes,
                item.comments,
                item.followers,
                item.age_days,
                breakout_lift(
                    item.collects, item.likes, item.comments, item.followers, item.age_days
                ),
            )
        )
    candidates.sort(key=lambda item: (-item.lift, item.note_id))
    keep = max(1, math.ceil(len(candidates) * max(0.0, min(1.0, top_percent))))
    return candidates[:keep]


@dataclass
class FanProfile:
    user_id: str
    nickname: str = ""
    interests: list[str] = field(default_factory=list)
    stage: str = "new"
    last_interaction: datetime | None = None
    interaction_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "nickname": self.nickname,
            "interests": list(self.interests),
            "stage": self.stage,
            "last_interaction": (
                self.last_interaction.isoformat() if self.last_interaction else None
            ),
            "interaction_count": self.interaction_count,
        }


class FanRelationStore:
    """Small in-process relation memory; durable stores can persist ``as_dict``."""

    def __init__(self) -> None:
        self._fans: dict[str, FanProfile] = {}

    def upsert(self, profile: FanProfile) -> FanProfile:
        existing = self._fans.get(profile.user_id)
        if existing:
            existing.nickname = profile.nickname or existing.nickname
            existing.interests = list(dict.fromkeys([*existing.interests, *profile.interests]))
            existing.stage = profile.stage
            existing.last_interaction = profile.last_interaction or existing.last_interaction
            existing.interaction_count += profile.interaction_count
            return existing
        self._fans[profile.user_id] = profile
        return profile

    def get(self, user_id: str) -> FanProfile | None:
        return self._fans.get(user_id)

    def recall(self, keyword: str = "", limit: int = 20) -> list[FanProfile]:
        needle = keyword.casefold().strip()
        values = list(self._fans.values())
        if needle:
            values = [
                profile
                for profile in values
                if needle in profile.nickname.casefold()
                or any(needle in interest.casefold() for interest in profile.interests)
            ]
        return sorted(values, key=lambda profile: (-profile.interaction_count, profile.user_id))[
            :limit
        ]


def build_icebreaker(profile: FanProfile, topic: str = "") -> str:
    """Build a deterministic pinned/seed comment opener for a known fan."""

    interest = profile.interests[0] if profile.interests else topic or "这篇内容"
    if profile.stage in {"returning", "vip"} and profile.nickname:
        return f"又见面啦，{profile.nickname}！上次你关注的{interest}这次有更新，先看这条～"
    return f"看到你对{interest}感兴趣，这条先替你整理好了，欢迎收藏慢慢看～"


_SECRET_KEYS = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|cookie)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def _redact(value: Any, key: str = "") -> Any:
    if _SECRET_KEYS.search(key or ""):
        return "[redacted]"
    if isinstance(value, str):
        return _PHONE_RE.sub("[phone]", _EMAIL_RE.sub("[email]", value))
    if isinstance(value, Mapping):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def compile_public_replay_bundle(
    thread_id: str,
    events: Iterable[Mapping[str, Any]],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Compile a deterministic, redacted public replay bundle."""

    frames = []
    for event in events:
        frame = {
            "seq": event.get("seq"),
            "kind": event.get("kind", "event"),
            "ts": event.get("ts"),
            "payload": _redact(event.get("payload", {})),
        }
        frames.append(frame)
    body = {
        "thread_id": thread_id,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "frames": frames,
    }
    canonical = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    body["bundle_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return body
