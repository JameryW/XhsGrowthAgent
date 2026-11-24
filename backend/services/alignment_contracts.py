"""Phase-15 alignment contracts (ledger schemes 85-90).

Pure deterministic helpers for compaction safety, modular harness evolution,
early stopping, dual profiles, multi-party comment reasoning and cultural
evaluation.  No default workflow wiring.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "AffToMThreadState",
    "CompactionPlan",
    "ComplianceRule",
    "CulturalHint",
    "CulturalJudgeResult",
    "DualProfile",
    "EarlyStopDecision",
    "GainCtrlEarlyStopper",
    "GainPoint",
    "HarnessModule",
    "HarnessPatch",
    "PatchDecision",
    "ProfileChannels",
    "ProfileUpdateDecision",
    "RequirementIssue",
    "ThreadParticipant",
    "accept_profile_update",
    "apply_compaction_anchor",
    "build_afftom_thread_state",
    "channel_homophily",
    "compose_afftom_reply",
    "cultural_judge_score",
    "evaluate_harness_patch",
    "plan_compaction_anchor",
    "quality_framing_score",
    "retrieve_cultural_hints",
]


def _round(value: float) -> float:
    return round(float(value), 4)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a = {str(item) for item in left}
    b = {str(item) for item in right}
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _terms(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    bigrams = {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}
    words = set(re.findall(r"[A-Za-z0-9_]+", text))
    return bigrams | words


@dataclass(frozen=True)
class ComplianceRule:
    rule_id: str
    text: str
    severity: str = "high"


@dataclass(frozen=True)
class CompactionPlan:
    static_prefix: tuple[ComplianceRule, ...]
    reanchor: str
    policies_in_compaction: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "static_prefix": [
                {"rule_id": rule.rule_id, "text": rule.text, "severity": rule.severity}
                for rule in self.static_prefix
            ],
            "reanchor": self.reanchor,
            "policies_in_compaction": list(self.policies_in_compaction),
        }


def plan_compaction_anchor(
    rules: Iterable[ComplianceRule],
    *,
    max_reanchor_chars: int = 160,
) -> CompactionPlan:
    if max_reanchor_chars < 1:
        raise ValueError("max_reanchor_chars must be >= 1")
    ordered = tuple(rules)
    for rule in ordered:
        if not rule.rule_id or not rule.text:
            raise ValueError("rule id and text must not be empty")
    payload = "；".join(f"[{rule.rule_id}] {rule.text}" for rule in ordered)
    prefix = "<active_rules_reanchor>"
    suffix = "</active_rules_reanchor>"
    budget = max(1, max_reanchor_chars - len(prefix) - len(suffix))
    if len(payload) > budget:
        payload = payload[: max(0, budget - 1)] + "…"
    return CompactionPlan(
        static_prefix=ordered,
        reanchor=f"{prefix}{payload}{suffix}",
        policies_in_compaction=(),
    )


def apply_compaction_anchor(
    messages: Sequence[Mapping[str, str]],
    plan: CompactionPlan,
) -> tuple[dict[str, str], ...]:
    copied = [dict(message) for message in messages]
    copied.append({"role": "system", "content": plan.reanchor})
    return tuple(copied)


class HarnessModule(StrEnum):
    CONTEXT_STATE = "context_state"
    CONTROL = "control"
    TOOL_INTERFACE = "tool_interface"
    VERIFICATION = "verification"


@dataclass(frozen=True)
class RequirementIssue:
    issue_id: str
    rejection_reason: str
    target_module: HarnessModule


@dataclass(frozen=True)
class HarnessPatch:
    patch_id: str
    module: HarnessModule
    token_delta: int
    cost_delta: float = 0.0
    resolves_issue_ids: tuple[str, ...] = ()
    fallback_safe: bool = True


@dataclass(frozen=True)
class PatchDecision:
    accepted: bool
    reasons: tuple[str, ...]
    token_delta: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reasons": list(self.reasons),
            "token_delta": self.token_delta,
        }


def evaluate_harness_patch(
    issue: RequirementIssue,
    patch: HarnessPatch,
    *,
    fallback_regression: bool = False,
) -> PatchDecision:
    reasons: list[str] = []
    if patch.module != issue.target_module:
        reasons.append("module_mismatch")
    if issue.issue_id not in patch.resolves_issue_ids:
        reasons.append("issue_not_resolved")
    if fallback_regression:
        reasons.append("fallback_regression")
    if not patch.fallback_safe:
        reasons.append("fallback_unsafe")
    if patch.token_delta > 0 and patch.cost_delta >= 0:
        reasons.append("token_increase")
    return PatchDecision(
        accepted=not reasons,
        reasons=tuple(reasons or ("accepted",)),
        token_delta=patch.token_delta,
    )


@dataclass(frozen=True)
class GainPoint:
    iteration: int
    score: float


@dataclass(frozen=True)
class EarlyStopDecision:
    should_stop: bool
    expected_positive_gain: float
    threshold: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "should_stop": self.should_stop,
            "expected_positive_gain": _round(self.expected_positive_gain),
            "threshold": _round(self.threshold),
            "reason": self.reason,
        }


class GainCtrlEarlyStopper:
    """CPU-only estimate of the next round's positive score gain."""

    def __init__(
        self,
        *,
        threshold: float = 0.01,
        patience: int = 2,
        decay: float = 0.5,
        min_points: int = 3,
    ) -> None:
        if patience < 1:
            raise ValueError("patience must be >= 1")
        if min_points < 2:
            raise ValueError("min_points must be >= 2")
        if not 0.0 < decay <= 1.0:
            raise ValueError("decay must be in (0, 1]")
        self._threshold = threshold
        self._patience = patience
        self._decay = decay
        self._min_points = min_points
        self._points: list[GainPoint] = []

    def observe(self, score: float, *, iteration: int | None = None) -> GainPoint:
        point = GainPoint(
            iteration=len(self._points) if iteration is None else iteration,
            score=float(score),
        )
        self._points.append(point)
        return point

    def decide(self, *, budget_left: int = 1) -> EarlyStopDecision:
        if len(self._points) < self._min_points:
            return EarlyStopDecision(
                should_stop=False,
                expected_positive_gain=0.0,
                threshold=self._threshold,
                reason="insufficient_history",
            )
        scores = [point.score for point in self._points]
        gains = [scores[index] - scores[index - 1] for index in range(1, len(scores))]
        recent = gains[-self._patience :]
        positive = [max(0.0, value) for value in recent]
        expected = (sum(positive) / len(positive)) * self._decay ** max(0, budget_left - 1)
        if all(value <= 0 for value in recent):
            return EarlyStopDecision(
                should_stop=True,
                expected_positive_gain=expected,
                threshold=self._threshold,
                reason="stagnation",
            )
        if expected < self._threshold:
            return EarlyStopDecision(
                should_stop=True,
                expected_positive_gain=expected,
                threshold=self._threshold,
                reason="marginal_gain",
            )
        return EarlyStopDecision(
            should_stop=False,
            expected_positive_gain=expected,
            threshold=self._threshold,
            reason="continue",
        )

    @property
    def points(self) -> tuple[GainPoint, ...]:
        return tuple(self._points)


@dataclass(frozen=True)
class ProfileChannels:
    preference: frozenset[str] = frozenset()
    quality: frozenset[str] = frozenset()
    context: frozenset[str] = frozenset()
    audience: frozenset[str] = frozenset()

    def channel(self, name: str) -> frozenset[str]:
        allowed = {"preference", "quality", "context", "audience"}
        if name not in allowed:
            raise ValueError(f"unknown profile channel: {name}")
        return frozenset(getattr(self, name))

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "preference": sorted(self.preference),
            "quality": sorted(self.quality),
            "context": sorted(self.context),
            "audience": sorted(self.audience),
        }


@dataclass(frozen=True)
class DualProfile:
    account_id: str
    channels: ProfileChannels

    def as_dict(self) -> dict[str, Any]:
        return {"account_id": self.account_id, "channels": self.channels.as_dict()}


@dataclass(frozen=True)
class ProfileUpdateDecision:
    accepted: bool
    improved_channels: tuple[str, ...]
    coverage: Mapping[str, float]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "improved_channels": list(self.improved_channels),
            "coverage": {key: _round(value) for key, value in self.coverage.items()},
            "reasons": list(self.reasons),
        }


def channel_homophily(
    profile: ProfileChannels,
    candidate: Mapping[str, Iterable[str]],
) -> float:
    scores = [
        _jaccard(profile.channel(name), candidate.get(name, ()))
        for name in ("preference", "quality", "context", "audience")
    ]
    return _round(sum(scores) / len(scores))


def accept_profile_update(
    current: ProfileChannels,
    proposed: ProfileChannels,
    holdout: Mapping[str, Iterable[str]],
) -> ProfileUpdateDecision:
    coverage: dict[str, float] = {}
    improved: list[str] = []
    for name in ("preference", "quality", "context", "audience"):
        holdout_values = {str(item) for item in holdout.get(name, ())}
        if not holdout_values:
            coverage[name] = 0.0
            continue
        before = len(current.channel(name) & holdout_values) / len(holdout_values)
        after = len(proposed.channel(name) & holdout_values) / len(holdout_values)
        coverage[name] = after
        if after > before:
            improved.append(name)
    accepted = bool(improved)
    reasons = ("channel_coverage_gain",) if accepted else ("no_channel_gain",)
    return ProfileUpdateDecision(
        accepted=accepted,
        improved_channels=tuple(improved),
        coverage=coverage,
        reasons=reasons,
    )


@dataclass(frozen=True)
class ThreadParticipant:
    role: str
    concern: str
    emotion: str = "neutral"


@dataclass(frozen=True)
class AffToMThreadState:
    asker_concern: str
    challenger_trigger: str
    lurker_threshold: str

    def as_dict(self) -> dict[str, str]:
        return {
            "asker_concern": self.asker_concern,
            "challenger_trigger": self.challenger_trigger,
            "lurker_threshold": self.lurker_threshold,
        }


def build_afftom_thread_state(
    participants: Sequence[ThreadParticipant],
) -> AffToMThreadState:
    asker = next((item for item in participants if item.role == "asker"), None)
    challenger = next((item for item in participants if item.role == "challenger"), None)
    lurkers = [item for item in participants if item.role == "lurker"]
    threshold = "；".join(item.concern for item in lurkers if item.concern)
    return AffToMThreadState(
        asker_concern=asker.concern if asker else "未明确",
        challenger_trigger=challenger.concern if challenger else "未明确",
        lurker_threshold=threshold or "未明确",
    )


def compose_afftom_reply(
    state: AffToMThreadState,
    *,
    hard_standard: str,
    hook: str,
    max_chars: int = 280,
) -> str:
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    empathy = f"理解你担心的{state.challenger_trigger}，这种谨慎很正常。"
    standard = f"我们的硬标准：{hard_standard}"
    close = hook.strip()
    text = " ".join(part for part in (empathy, standard, close) if part)
    if len(text) > max_chars:
        text = text[: max(0, max_chars - 1)] + "…"
    return text


@dataclass(frozen=True)
class CulturalHint:
    text: str
    source: str = ""
    score: float = 0.0


@dataclass(frozen=True)
class CulturalJudgeResult:
    base_score: float
    adjusted_score: float
    hints: tuple[CulturalHint, ...]
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "base_score": _round(self.base_score),
            "adjusted_score": _round(self.adjusted_score),
            "hints": [
                {"text": hint.text, "source": hint.source, "score": _round(hint.score)}
                for hint in self.hints
            ],
            "reasons": list(self.reasons),
        }


def retrieve_cultural_hints(
    query: str,
    hints: Sequence[CulturalHint],
    *,
    limit: int = 3,
) -> tuple[CulturalHint, ...]:
    if limit < 0:
        raise ValueError("limit must be >= 0")
    query_terms = _terms(query)
    if not query_terms:
        return ()
    scored: list[tuple[float, CulturalHint]] = []
    for hint in hints:
        overlap = len(query_terms & _terms(hint.text))
        if overlap == 0:
            continue
        relevance = overlap / max(1, len(query_terms)) + 0.1 * float(hint.score)
        scored.append((relevance, hint))
    scored.sort(key=lambda item: (-item[0], item[1].text))
    return tuple(hint for _, hint in scored[:limit])


def cultural_judge_score(
    base_score: float,
    hints: Sequence[CulturalHint],
) -> CulturalJudgeResult:
    bonus = min(8.07, 1.5 * len(hints))
    adjusted = _clamp(float(base_score) + bonus)
    reasons = (
        f"cultural_hints:{len(hints)}",
        f"bonus:{_round(bonus)}",
    )
    return CulturalJudgeResult(
        base_score=float(base_score),
        adjusted_score=adjusted,
        hints=tuple(hints),
        reasons=reasons,
    )


_QUALITY_MARKERS = (
    "车龄",
    "防滑链",
    "氧气瓶",
    "救援",
    "实测",
    "透明",
    "全险",
    "免费取消",
    "无损",
    "具体型号",
)
_PRICE_HOOKS = ("全网最低", "99元起", "最低价", "白菜价", "骨折价", "绝对便宜")


def quality_framing_score(text: str) -> float:
    markers = sum(1 for marker in _QUALITY_MARKERS if marker in text)
    hooks = sum(1 for hook in _PRICE_HOOKS if hook in text)
    score = 50.0 + min(50.0, 8.0 * markers) - min(60.0, 12.0 * hooks)
    return _round(_clamp(score))
