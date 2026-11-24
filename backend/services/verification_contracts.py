"""Phase-11 verification contracts (ledger schemes 61-66).

Deterministic checks for variant claims, cross-component completion, session
scheduling, scoped memory revision, card rewinds, and bounded metric
verification.  The module never calls an LLM and never touches a database.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "CardRewindPlan",
    "CardSample",
    "Claim",
    "ClaimDispute",
    "CompletionGraphReport",
    "CompletionIssue",
    "JointVerificationResult",
    "MetricClaim",
    "MosaicSessionScheduler",
    "QueryBatch",
    "ScopedRevisionResult",
    "SessionDecision",
    "SessionProposal",
    "SessionStats",
    "SessionType",
    "VerificationReport",
    "assert_typed_completion",
    "audit_variant_claims",
    "build_bounded_query_batches",
    "detect_card_rewind",
    "extract_numeric_claims",
    "scoped_revision",
    "verify_metric_claims",
]


_CN_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")
_CLAIM_RE = re.compile(r"([\u4e00-\u9fffA-Za-z]{1,8})\s*[:：]?\s*(\d+(?:\.\d+)?%?)")
_IMAGE_REF_RE = re.compile(r"图\s*([0-9一二两三四五六七八九十]+)")
_IMAGE_ORDINAL_RE = re.compile(r"第\s*([0-9一二两三四五六七八九十]+)\s*张图")
_EFFECT_ALIASES = {
    "commercial_disclosure": ("commercial_disclosure", "disclosure", "蒲公英", "报备"),
    "ab_test": ("ab_test", "a/b", "赛马"),
    "pinned_comment": ("pinned_comment", "置顶评论", "置顶神评"),
}


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
class Claim:
    key: str
    text: str
    value: str

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "text": self.text, "value": self.value}


def _claim_key(prefix: str, number: str) -> str:
    clean = re.sub(r"[\s，。；：:、,.!?]+", "", prefix)
    if clean:
        return clean[-6:]
    return f"metric:{number}"


def extract_numeric_claims(text: str) -> tuple[Claim, ...]:
    """Extract simple numeric/factual claims from a variant body."""

    claims: list[Claim] = []
    for match in _CLAIM_RE.finditer(text):
        prefix, number = match.group(1), match.group(2)
        key = _claim_key(prefix, number)
        claims.append(Claim(key=key, text=match.group(0).strip(), value=number))
    if claims:
        return tuple(claims)
    for match in _NUMBER_RE.finditer(text):
        number = match.group(0)
        claims.append(Claim(key=f"metric:{number}", text=number, value=number))
    return tuple(claims)


def _claim_values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for claim in extract_numeric_claims(text):
        result[claim.key] = claim.value
    return result


@dataclass(frozen=True)
class ClaimDispute:
    key: str
    values: tuple[str, ...]
    resolved: bool
    resolution: str
    evidence_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "values": list(self.values),
            "resolved": self.resolved,
            "resolution": self.resolution,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class VerificationReport:
    disputed: tuple[ClaimDispute, ...]
    consensus_unsupported: tuple[str, ...]
    blocked: bool
    unverified_claims: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "disputed": [item.as_dict() for item in self.disputed],
            "consensus_unsupported": list(self.consensus_unsupported),
            "blocked": self.blocked,
            "unverified_claims": list(self.unverified_claims),
        }


def _variant_texts(variants: Iterable[str | Mapping[str, Any]]) -> tuple[str, ...]:
    result: list[str] = []
    for variant in variants:
        if isinstance(variant, Mapping):
            text = _as_text(variant.get("text") or variant.get("body") or variant.get("content"))
        else:
            text = _as_text(variant)
        result.append(text)
    return tuple(result)


def _evidence_texts(evidence: Iterable[str | Mapping[str, Any]]) -> tuple[str, ...]:
    result: list[str] = []
    for item in evidence:
        if isinstance(item, Mapping):
            text = _as_text(item.get("text") or item.get("content") or item.get("value"))
        else:
            text = _as_text(item)
        if text:
            result.append(text)
    return tuple(result)


def audit_variant_claims(
    variants: Iterable[str | Mapping[str, Any]],
    evidence: Iterable[str | Mapping[str, Any]] = (),
) -> VerificationReport:
    """Adjudicate cross-variant disputes and challenge consensus claims."""

    texts = _variant_texts(variants)
    claim_sets = [_claim_values(text) for text in texts]
    evidence_text = " ".join(_evidence_texts(evidence))
    keys: set[str] = set()
    for claims in claim_sets:
        keys.update(claims)
    disputed: list[ClaimDispute] = []
    unverified: list[str] = []
    for key in sorted(keys):
        values = tuple(sorted({claims[key] for claims in claim_sets if key in claims}))
        if len(values) <= 1:
            continue
        supported = tuple(value for value in values if value in evidence_text)
        if len(supported) == 1:
            resolution = supported[0]
            resolved = True
        else:
            resolution = ""
            resolved = False
            unverified.append(key)
        disputed.append(
            ClaimDispute(
                key=key,
                values=values,
                resolved=resolved,
                resolution=resolution,
            )
        )
    consensus: list[str] = []
    for key in sorted(keys):
        common = [claims[key] for claims in claim_sets if key in claims]
        if len(common) == len(claim_sets) and len(set(common)) == 1:
            value = common[0]
            if value not in evidence_text:
                consensus.append(key)
                if key not in unverified:
                    unverified.append(key)
    return VerificationReport(
        disputed=tuple(disputed),
        consensus_unsupported=tuple(consensus),
        blocked=bool(unverified),
        unverified_claims=tuple(sorted(set(unverified))),
    )


@dataclass(frozen=True)
class CompletionIssue:
    edge: str
    source: str
    target: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge": self.edge,
            "source": self.source,
            "target": self.target,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CompletionGraphReport:
    issues: tuple[CompletionIssue, ...]
    blocked: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "issues": [item.as_dict() for item in self.issues],
            "blocked": self.blocked,
        }


def _card_texts(carousel: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    for item in carousel:
        if isinstance(item, Mapping):
            result.append(_as_text(item.get("text") or item.get("caption") or item.get("content")))
        else:
            result.append(_as_text(item))
    return tuple(result)


def _effect_names(effects: Iterable[Any]) -> set[str]:
    names: set[str] = set()
    for item in effects:
        if isinstance(item, Mapping):
            value = _as_text(item.get("effect") or item.get("kind") or item.get("name"))
        else:
            value = _as_text(item)
        if value:
            names.add(value.lower())
    return names


def _has_effect(effects: set[str], canonical: str) -> bool:
    aliases = _EFFECT_ALIASES.get(canonical, (canonical,))
    return any(alias.lower() in effects for alias in aliases)


def _image_index(token: str) -> int:
    if token.isdigit():
        return int(token)
    if token in _CN_DIGITS:
        return _CN_DIGITS[token]
    if token == "十":
        return 10
    return 0


def assert_typed_completion(
    *,
    title: str = "",
    body: str = "",
    carousel: Iterable[Any] = (),
    hashtags: Iterable[Any] = (),
    decisions: Iterable[Mapping[str, Any] | str] = (),
    effects: Iterable[Any] = (),
    evidence_ids: Iterable[str] = (),
) -> CompletionGraphReport:
    """Verify grounding, coupling, and realization edges for one note."""

    issues: list[CompletionIssue] = []
    evidence = set(_texts(evidence_ids))
    cards = _card_texts(carousel)
    effect_set = _effect_names(effects)
    combined = f"{_as_text(title)}\n{_as_text(body)}"
    for decision in decisions:
        if not isinstance(decision, Mapping):
            continue
        label = _as_text(decision.get("decision") or decision.get("name") or "decision")
        ids = _texts(decision.get("evidence_ids"))
        requires = bool(decision.get("requires_evidence", True))
        if requires and not ids:
            issues.append(CompletionIssue("grounding", label, "", "decision_without_evidence"))
        for evidence_id in ids:
            if evidence_id not in evidence:
                issues.append(
                    CompletionIssue(
                        "grounding",
                        label,
                        evidence_id,
                        "evidence_id_not_in_context",
                    )
                )
    for match in _IMAGE_REF_RE.finditer(combined):
        index = _image_index(match.group(1))
        if index < 1 or index > len(cards) or not cards[index - 1]:
            issues.append(
                CompletionIssue(
                    "coupling",
                    "body",
                    f"carousel[{index}]",
                    "referenced_card_missing",
                )
            )
    for match in _IMAGE_ORDINAL_RE.finditer(combined):
        index = _image_index(match.group(1))
        if index < 1 or index > len(cards) or not cards[index - 1]:
            issues.append(
                CompletionIssue(
                    "coupling",
                    "body",
                    f"carousel[{index}]",
                    "referenced_card_missing",
                )
            )
    if "左滑" in combined and len(cards) < 2:
        issues.append(
            CompletionIssue("coupling", "body", "carousel", "left_swipe_without_carousel")
        )
    if "置顶评论" in combined and not _has_effect(effect_set, "pinned_comment"):
        issues.append(
            CompletionIssue(
                "realization",
                "body",
                "pinned_comment",
                "pinned_comment_not_scheduled",
            )
        )
    for decision in decisions:
        if not isinstance(decision, Mapping):
            continue
        kind = _as_text(decision.get("effect") or decision.get("kind")).lower()
        for canonical in _EFFECT_ALIASES:
            if (canonical in kind or kind in _EFFECT_ALIASES[canonical]) and not _has_effect(
                effect_set, canonical
            ):
                issues.append(
                    CompletionIssue(
                        "realization",
                        _as_text(decision.get("decision") or kind),
                        canonical,
                        "effect_not_scheduled",
                    )
                )
    if ("蒲公英" in combined or "合作" in combined) and not _has_effect(
        effect_set, "commercial_disclosure"
    ):
        issues.append(
            CompletionIssue(
                "realization",
                "body",
                "commercial_disclosure",
                "commercial_note_without_disclosure_effect",
            )
        )
    return CompletionGraphReport(issues=tuple(issues), blocked=bool(issues))


class SessionType(StrEnum):
    SCOUT = "scout"
    DRAFT_FORK = "draft_fork"
    POLISH = "polish"
    SNAPSHOT_EVAL = "snapshot_eval"


@dataclass(frozen=True)
class SessionStats:
    mean: float
    stddev: float
    samples: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "mean": _round(self.mean),
            "stddev": _round(self.stddev),
            "samples": self.samples,
        }


@dataclass(frozen=True)
class SessionProposal:
    session_type: SessionType
    expected_reward: float
    estimated_tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_type": self.session_type.value,
            "expected_reward": _round(self.expected_reward),
            "estimated_tokens": self.estimated_tokens,
        }


@dataclass(frozen=True)
class SessionDecision:
    spawn: bool
    normalized_advantage: float
    penalty: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "spawn": self.spawn,
            "normalized_advantage": _round(self.normalized_advantage),
            "penalty": _round(self.penalty),
            "reason": self.reason,
        }


class MosaicSessionScheduler:
    """Normalize per-session-type gains and penalize session-count inflation."""

    def __init__(
        self,
        stats: Mapping[SessionType | str, SessionStats | Mapping[str, Any]] | None = None,
        *,
        gamma: float = 0.85,
        spawn_threshold: float = 0.0,
        epsilon: float = 1e-6,
    ) -> None:
        self._gamma = _clip(gamma)
        self._threshold = _number(spawn_threshold)
        self._epsilon = max(1e-9, _number(epsilon, 1e-6))
        self._stats: dict[str, SessionStats] = {}
        for key, value in (stats or {}).items():
            name = key.value if isinstance(key, SessionType) else _as_text(key)
            if isinstance(value, SessionStats):
                stat = value
            else:
                data = _mapping(value)
                stat = SessionStats(
                    mean=_number(data.get("mean")),
                    stddev=_number(data.get("stddev")),
                    samples=int(_number(data.get("samples"))),
                )
            self._stats[name] = stat

    def evaluate(
        self,
        proposal: SessionProposal,
        *,
        current_session_count: int = 0,
    ) -> SessionDecision:
        stat = self._stats.get(proposal.session_type.value, SessionStats(mean=0.0, stddev=1.0))
        stddev = max(self._epsilon, abs(stat.stddev))
        normalized = (_number(proposal.expected_reward) - stat.mean) / stddev
        count = max(0, int(_number(current_session_count, 0.0)))
        penalty = self._gamma**count
        score = normalized * penalty
        spawn = normalized > self._threshold and score > 0.0
        if not spawn:
            reason = "negative_or_flat_normalized_gain"
        elif penalty < 0.5:
            reason = "penalized_by_session_count"
        else:
            reason = "positive_normalized_gain"
        return SessionDecision(
            spawn=spawn,
            normalized_advantage=normalized,
            penalty=penalty,
            reason=reason,
        )


@dataclass(frozen=True)
class ScopedRevisionResult:
    revision: Mapping[str, Any]
    locked_fields: tuple[str, ...]
    revised_fields: tuple[str, ...]
    rejected_fields: tuple[str, ...]
    missing_required_fields: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision": dict(self.revision),
            "locked_fields": list(self.locked_fields),
            "revised_fields": list(self.revised_fields),
            "rejected_fields": list(self.rejected_fields),
            "missing_required_fields": list(self.missing_required_fields),
        }


def scoped_revision(
    first_opinion: Mapping[str, Any] | None,
    memory: Mapping[str, Any] | None,
    *,
    required_fields: Iterable[str] = (),
    forbidden_values: Iterable[str] = (),
) -> ScopedRevisionResult:
    """Apply memory only where it does not overwrite a sound first opinion."""

    base = dict(_mapping(first_opinion))
    recalled = _mapping(memory)
    required = _texts(required_fields)
    forbidden = set(_texts(forbidden_values))
    locked: list[str] = []
    revised: list[str] = []
    rejected: list[str] = []
    revision = dict(base)
    for key, value in base.items():
        if _as_text(value):
            locked.append(key)
    for key in required:
        if key in base and _as_text(base[key]) and key not in locked:
            locked.append(key)
    for key, raw_value in recalled.items():
        value = _as_text(raw_value)
        if not value:
            continue
        if key in locked:
            if _as_text(base.get(key)) != value:
                rejected.append(key)
            continue
        if value in forbidden:
            rejected.append(key)
            continue
        current = _as_text(revision.get(key))
        if not current:
            revision[key] = raw_value
            revised.append(key)
        elif current != value:
            rejected.append(key)
    missing = tuple(key for key in required if key not in revision or not _as_text(revision[key]))
    return ScopedRevisionResult(
        revision=revision,
        locked_fields=tuple(locked),
        revised_fields=tuple(revised),
        rejected_fields=tuple(rejected),
        missing_required_fields=missing,
    )


@dataclass(frozen=True)
class CardSample:
    index: int
    entropy: float
    banned_hits: int = 0
    entity_complete: bool = True
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "entropy": _round(self.entropy),
            "banned_hits": self.banned_hits,
            "entity_complete": self.entity_complete,
        }


@dataclass(frozen=True)
class CardRewindPlan:
    action: str
    rewind_to: int | None
    reason: str
    suspicious_cards: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "rewind_to": self.rewind_to,
            "reason": self.reason,
            "suspicious_cards": list(self.suspicious_cards),
        }


def detect_card_rewind(
    cards: Iterable[CardSample | Mapping[str, Any]],
    *,
    baseline_mean: float | None = None,
    baseline_std: float | None = None,
    z_threshold: float = 2.0,
) -> CardRewindPlan:
    """Find the first card whose uncertainty or compliance jumps."""

    samples: list[CardSample] = []
    for item in cards:
        if isinstance(item, CardSample):
            samples.append(item)
        else:
            data = _mapping(item)
            samples.append(
                CardSample(
                    index=int(_number(data.get("index"), len(samples) + 1)),
                    entropy=_number(data.get("entropy")),
                    banned_hits=int(_number(data.get("banned_hits"))),
                    entity_complete=bool(data.get("entity_complete", True)),
                    text=_as_text(data.get("text")),
                )
            )
    if not samples:
        return CardRewindPlan("accept", None, "no_cards")
    entropies = [sample.entropy for sample in samples]
    mean = _number(baseline_mean, sum(entropies) / len(entropies))
    if baseline_std is not None:
        stddev = max(0.0, _number(baseline_std))
    elif len(entropies) > 1:
        variance = sum((value - mean) ** 2 for value in entropies) / len(entropies)
        stddev = math.sqrt(variance)
    else:
        stddev = 0.0
    threshold = mean + max(0.0, _number(z_threshold, 2.0)) * stddev
    suspicious: list[int] = []
    previous: int | None = None
    for sample in sorted(samples, key=lambda item: item.index):
        if sample.entropy > threshold or sample.banned_hits > 0 or not sample.entity_complete:
            suspicious.append(sample.index)
            return CardRewindPlan(
                action="rewind",
                rewind_to=previous,
                reason=f"card_{sample.index}_uncertain_or_invalid",
                suspicious_cards=tuple(suspicious),
            )
        previous = sample.index
    return CardRewindPlan("accept", None, "all_cards_stable")


@dataclass(frozen=True)
class MetricClaim:
    metric: str
    value: float
    note_id: str = ""
    window: str = ""
    claim_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": _round(self.value),
            "note_id": self.note_id,
            "window": self.window,
            "claim_id": self.claim_id,
        }


@dataclass(frozen=True)
class QueryBatch:
    key: str
    claim_ids: tuple[str, ...]
    query_hint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "claim_ids": list(self.claim_ids),
            "query_hint": self.query_hint,
        }


@dataclass(frozen=True)
class JointVerificationResult:
    ok: bool
    batch_count: int
    mismatches: tuple[str, ...]
    missing: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "batch_count": self.batch_count,
            "mismatches": list(self.mismatches),
            "missing": list(self.missing),
        }


def _claim_label(claim: MetricClaim, index: int) -> str:
    return claim.claim_id or f"claim-{index + 1}"


def build_bounded_query_batches(
    claims: Iterable[MetricClaim],
    *,
    max_batches: int = 3,
) -> tuple[QueryBatch, ...]:
    """Group related metric claims into a bounded number of query batches."""

    grouped: dict[str, list[MetricClaim]] = {}
    for claim in claims:
        key = claim.note_id or claim.window or claim.metric or "global"
        grouped.setdefault(key, []).append(claim)
    keys = list(grouped)
    limit = max(1, int(_number(max_batches, 3)))
    if len(keys) > limit:
        keep = keys[: limit - 1]
        merged: list[MetricClaim] = []
        for key in keys[limit - 1 :]:
            merged.extend(grouped[key])
        grouped = {key: grouped[key] for key in keep}
        grouped["merged"] = merged
        keys = keep + ["merged"]
    batches: list[QueryBatch] = []
    for key in keys:
        items = grouped[key]
        claim_ids = tuple(_claim_label(claim, index) for index, claim in enumerate(items))
        batches.append(
            QueryBatch(
                key=key,
                claim_ids=claim_ids,
                query_hint=f"bounded_lookup:{key}",
            )
        )
    return tuple(batches)


def _ledger_value(
    ledger: Mapping[str, Any],
    claim: MetricClaim,
) -> float | None:
    candidates = (
        claim.claim_id,
        f"{claim.note_id}:{claim.metric}" if claim.note_id else "",
        f"{claim.window}:{claim.metric}" if claim.window else "",
        claim.metric,
    )
    for key in candidates:
        if not key or key not in ledger:
            continue
        value = ledger[key]
        if isinstance(value, Mapping):
            found = value.get("value")
            if found is not None:
                return _number(found)
        elif isinstance(value, (list, tuple)):
            for entry in value:
                data = _mapping(entry)
                if claim.note_id and _as_text(data.get("note_id")) not in {"", claim.note_id}:
                    continue
                if claim.metric and _as_text(data.get("metric")) not in {"", claim.metric}:
                    continue
                return _number(data.get("value"), math.nan)
        else:
            return _number(value, math.nan)
    return None


def verify_metric_claims(
    claims: Iterable[MetricClaim],
    ledger: Mapping[str, Any],
    *,
    tolerance: float = 1e-4,
) -> JointVerificationResult:
    """Compare report numbers with the database ledger without an LLM."""

    claim_list = list(claims)
    mismatches: list[str] = []
    missing: list[str] = []
    for index, claim in enumerate(claim_list):
        label = _claim_label(claim, index)
        expected = _ledger_value(ledger, claim)
        if expected is None or not math.isfinite(expected):
            missing.append(label)
            continue
        if abs(expected - _number(claim.value)) > max(0.0, _number(tolerance, 1e-4)):
            mismatches.append(label)
    batches = build_bounded_query_batches(claim_list)
    return JointVerificationResult(
        ok=not mismatches and not missing,
        batch_count=len(batches),
        mismatches=tuple(mismatches),
        missing=tuple(missing),
    )
