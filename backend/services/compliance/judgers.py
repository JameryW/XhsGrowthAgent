"""Per-failure-mode publish eligibility judgers (deterministic + audit).

Publish permission is the conjunction of named judgers — not an LLM panel's
self-score. Each judger answers one failure mode; thresholds are tuned by
business cost (irreversible publish ⇒ stricter / blocking). The RQGM evaluator
may still produce quality revision hints; it must not alone grant a publish.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from backend.services.compliance.lexicon import scan_state_content
from backend.services.compliance_policy import (
    auto_approve_low_risk_enabled,
    commercial_disclosure_ok,
    is_high_risk_niche,
    state_is_blocking,
    state_is_commercial,
    text_has_disclosure,
)

__all__ = [
    "JudgerId",
    "JudgerThresholds",
    "JudgerVerdict",
    "PLAN_TIME_JUDGERS",
    "PublishEligibility",
    "decide_publish_eligibility",
    "judge_dual_auto",
    "judge_high_risk_auto",
    "load_thresholds",
]


class JudgerId(StrEnum):
    """One id per failure mode — keep stable for audit consumers."""

    LEXICON = "lexicon"
    COMMERCIAL_DISCLOSURE = "commercial_disclosure"
    BLOCKING_COMPLIANCE = "blocking_compliance"
    DUAL_AUTO = "dual_auto"
    HIGH_RISK_AUTO = "high_risk_auto"


@dataclass(frozen=True)
class JudgerThresholds:
    """Business-cost knobs. Higher cost ⇒ stricter / more likely blocking.

    Values are intentionally simple so operators can tune via env without
    redeploying LLM prompts. Lexicon / disclosure / dual-auto are binary
    gates (cost is encoded as ``blocking=True``); quality soft-scores stay
    out of this module by design.
    """

    # When True (default), a lexicon hit always forbids publish.
    lexicon_blocking: bool = True
    # When True (default), commercial copy without markers/checkbox forbids publish.
    disclosure_blocking: bool = True
    # When True (default), any prior is_blocking compliance mark forbids publish.
    compliance_blocking: bool = True
    # When True (default), AUTO_APPROVE_LOW_RISK ∩ auto_publish forbids publish.
    dual_auto_blocking: bool = True
    # When True (default), high-risk niche + auto_low_risk path forbids auto pass.
    high_risk_auto_blocking: bool = True


def load_thresholds() -> JudgerThresholds:
    """Read thresholds from env; missing/invalid → safe (blocking) defaults."""

    def _flag(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None or not str(raw).strip():
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    return JudgerThresholds(
        lexicon_blocking=_flag("XHS_JUDGER_LEXICON_BLOCKING", True),
        disclosure_blocking=_flag("XHS_JUDGER_DISCLOSURE_BLOCKING", True),
        compliance_blocking=_flag("XHS_JUDGER_COMPLIANCE_BLOCKING", True),
        dual_auto_blocking=_flag("XHS_JUDGER_DUAL_AUTO_BLOCKING", True),
        high_risk_auto_blocking=_flag("XHS_JUDGER_HIGH_RISK_AUTO_BLOCKING", True),
    )


@dataclass(frozen=True)
class JudgerVerdict:
    judger_id: JudgerId
    passed: bool
    blocking: bool
    reason_code: str
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    threshold: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "judger_id": str(self.judger_id),
            "passed": self.passed,
            "blocking": self.blocking,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }
        if self.threshold is not None:
            payload["threshold"] = dict(self.threshold)
        return payload


@dataclass(frozen=True)
class PublishEligibility:
    """Conjoined publish decision + audit record."""

    allowed: bool
    verdicts: tuple[JudgerVerdict, ...]
    decided_at: str
    policy_version: str = "publish_judgers_v1"

    @property
    def blocking_failures(self) -> tuple[JudgerVerdict, ...]:
        return tuple(v for v in self.verdicts if (not v.passed) and v.blocking)

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "allowed": self.allowed,
            "decided_at": self.decided_at,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "blocking_failures": [v.judger_id for v in self.blocking_failures],
        }


JudgerFn = Callable[[Mapping[str, Any], JudgerThresholds], JudgerVerdict]


def _auto_publish_requested(state: Mapping[str, Any]) -> bool:
    options = state.get("publish_options") or {}
    if isinstance(options, dict) and options.get("auto_publish") is True:
        return True
    return state.get("auto_publish") is True


def _auto_low_risk_source(state: Mapping[str, Any]) -> bool:
    """True when review already stamped an auto_low_risk approval."""
    feedback = state.get("human_feedback") or {}
    if isinstance(feedback, dict) and str(feedback.get("source") or "") == "auto_low_risk":
        return True
    confirmation = state.get("publish_confirmation") or {}
    return bool(
        isinstance(confirmation, dict) and str(confirmation.get("source") or "") == "auto_low_risk"
    )


_POLICY_DIMENSIONS = frozenset({"compliance", "policy"})


def judge_lexicon(state: Mapping[str, Any], thresholds: JudgerThresholds) -> JudgerVerdict:
    existing = state.get("compliance_scan") or {}
    evaluation = state.get("evaluation_result") or {}
    lex_from_eval = evaluation.get("lexicon_scan") if isinstance(evaluation, dict) else None
    if isinstance(lex_from_eval, dict) and lex_from_eval:
        payload: dict[str, Any] = dict(lex_from_eval)
    elif isinstance(existing, dict) and existing.get("hits") is not None:
        payload = dict(existing)
    else:
        payload = scan_state_content(dict(state)).to_dict()

    hits = list(payload.get("hits") or [])
    is_blocking = bool(payload.get("is_blocking"))
    failed = bool(hits) or is_blocking
    blocking = thresholds.lexicon_blocking and failed
    return JudgerVerdict(
        judger_id=JudgerId.LEXICON,
        passed=not failed,
        blocking=blocking if failed else False,
        reason_code="lexicon_clear" if not failed else "lexicon_hit",
        detail="违禁词库未命中" if not failed else f"违禁词命中 {len(hits)} 项",
        evidence={"hit_count": len(hits), "scan": payload},
        threshold={"lexicon_blocking": thresholds.lexicon_blocking},
    )


def judge_commercial_disclosure(
    state: Mapping[str, Any], thresholds: JudgerThresholds
) -> JudgerVerdict:
    commercial = state_is_commercial(dict(state))
    if not commercial:
        return JudgerVerdict(
            judger_id=JudgerId.COMMERCIAL_DISCLOSURE,
            passed=True,
            blocking=False,
            reason_code="not_commercial",
            detail="非商单，无需披露判定",
            evidence={"is_commercial": False},
            threshold={"disclosure_blocking": thresholds.disclosure_blocking},
        )

    copy = state.get("copy_content") or {}
    if not isinstance(copy, dict):
        copy = {}
    title = str(copy.get("selected_title") or "")
    body = str(copy.get("body_text") or "")
    has_markers = text_has_disclosure(f"{title}\n{body}")
    ok = commercial_disclosure_ok(dict(state))
    # At pre-publish-gate stages the checkbox may not exist yet; still require
    # in-copy markers. Full checkbox check applies once confirmation is present.
    confirmation = state.get("publish_confirmation") or {}
    options = state.get("publish_options") or {}
    checkbox_present = (
        (isinstance(confirmation, dict) and "disclosure_confirmed" in confirmation)
        or (isinstance(options, dict) and "disclosure_confirmed" in options)
        or ("disclosure_confirmed" in state)
    )
    if checkbox_present:
        failed = not ok
        reason = "disclosure_ok" if ok else "disclosure_incomplete"
        detail = "商单披露勾选与文案标注齐全" if ok else "商单缺少披露勾选或文案合作/广告标注"
    else:
        failed = not has_markers
        reason = "disclosure_markers_ok" if has_markers else "disclosure_markers_missing"
        detail = (
            "商单文案含合作/广告标注（勾选待发布确认）"
            if has_markers
            else "商单文案缺少合作/广告披露标注"
        )

    blocking = thresholds.disclosure_blocking and failed
    return JudgerVerdict(
        judger_id=JudgerId.COMMERCIAL_DISCLOSURE,
        passed=not failed,
        blocking=blocking if failed else False,
        reason_code=reason,
        detail=detail,
        evidence={
            "is_commercial": True,
            "has_markers": has_markers,
            "checkbox_present": checkbox_present,
            "commercial_disclosure_ok": ok,
        },
        threshold={"disclosure_blocking": thresholds.disclosure_blocking},
    )


def judge_blocking_compliance(
    state: Mapping[str, Any], thresholds: JudgerThresholds
) -> JudgerVerdict:
    """Hard policy flags on evaluation dimensions (not the lexicon judger).

    Lexicon hits are owned by :func:`judge_lexicon`. This judger only reads
    dimension-level ``is_blocking`` / ``failed_dimensions`` so each failure
    mode stays separately auditable.
    """
    # Only hard policy dimensions — quality failed_dimensions (copywriting etc.)
    # must not be treated as publish blockers (they own the revise loop).
    evaluation = state.get("evaluation_result") or {}
    blocking_dims: list[str] = []
    policy_failed: list[str] = []
    if isinstance(evaluation, dict):
        for dim in evaluation.get("dimensions") or []:
            if isinstance(dim, dict) and dim.get("is_blocking"):
                blocking_dims.append(str(dim.get("dimension") or "unknown"))
        policy_failed = [
            str(x)
            for x in (evaluation.get("failed_dimensions") or [])
            if str(x).strip() in _POLICY_DIMENSIONS
        ]
    failed = bool(blocking_dims) or bool(policy_failed)
    blocking = thresholds.compliance_blocking and failed
    return JudgerVerdict(
        judger_id=JudgerId.BLOCKING_COMPLIANCE,
        passed=not failed,
        blocking=blocking if failed else False,
        reason_code="compliance_clear" if not failed else "compliance_blocking",
        detail=(
            "无硬性合规阻断" if not failed else f"硬性合规阻断: {blocking_dims or policy_failed}"
        ),
        evidence={
            "blocking_dimensions": blocking_dims,
            "policy_failed_dimensions": policy_failed,
            # Observability only — not used as the pass/fail signal here.
            "state_is_blocking": state_is_blocking(dict(state)),
        },
        threshold={"compliance_blocking": thresholds.compliance_blocking},
    )


def judge_dual_auto(state: Mapping[str, Any], thresholds: JudgerThresholds) -> JudgerVerdict:
    dual = _auto_publish_requested(state) and auto_approve_low_risk_enabled()
    blocking = thresholds.dual_auto_blocking and dual
    return JudgerVerdict(
        judger_id=JudgerId.DUAL_AUTO,
        passed=not dual,
        blocking=blocking if dual else False,
        reason_code="dual_auto_clear" if not dual else "dual_auto_forbidden",
        detail=(
            "未同时开启 AUTO_APPROVE_LOW_RISK 与 auto_publish" if not dual else "双自动发布硬拒绝"
        ),
        evidence={
            "auto_publish": _auto_publish_requested(state),
            "auto_approve_low_risk": auto_approve_low_risk_enabled(),
        },
        threshold={"dual_auto_blocking": thresholds.dual_auto_blocking},
    )


def judge_high_risk_auto(state: Mapping[str, Any], thresholds: JudgerThresholds) -> JudgerVerdict:
    raw_plan = state.get("content_plan")
    plan: dict[str, Any] = raw_plan if isinstance(raw_plan, dict) else {}
    niche = str(state.get("niche") or plan.get("niche") or "")
    high = is_high_risk_niche(niche)
    # High-risk niches must never ride auto_low_risk or the dual-auto path.
    auto_low = _auto_low_risk_source(state) or (
        _auto_publish_requested(state) and auto_approve_low_risk_enabled()
    )
    failed = high and auto_low
    blocking = thresholds.high_risk_auto_blocking and failed
    return JudgerVerdict(
        judger_id=JudgerId.HIGH_RISK_AUTO,
        passed=not failed,
        blocking=blocking if failed else False,
        reason_code="high_risk_auto_clear" if not failed else "high_risk_auto_forbidden",
        detail=("高风险垂类未走自动放行" if not failed else f"高风险垂类 ({niche}) 禁止自动放行"),
        evidence={"niche": niche, "is_high_risk": high, "auto_low_risk_path": auto_low},
        threshold={"high_risk_auto_blocking": thresholds.high_risk_auto_blocking},
    )


_DEFAULT_JUDGERS: tuple[JudgerFn, ...] = (
    judge_lexicon,
    judge_commercial_disclosure,
    judge_blocking_compliance,
    judge_dual_auto,
    judge_high_risk_auto,
)

#: Action **plan** may answer only failure modes that need no artifact body.
#: Lexicon / disclosure / blocking_compliance re-run at execute after hash match.
PLAN_TIME_JUDGERS: tuple[JudgerFn, ...] = (
    judge_dual_auto,
    judge_high_risk_auto,
)


def decide_publish_eligibility(
    state: Mapping[str, Any],
    *,
    thresholds: JudgerThresholds | None = None,
    judgers: Sequence[JudgerFn] | None = None,
) -> PublishEligibility:
    """Run every failure-mode judger and conjoin into an audited decision."""
    thr = thresholds or load_thresholds()
    fns = tuple(judgers) if judgers is not None else _DEFAULT_JUDGERS
    verdicts = tuple(fn(state, thr) for fn in fns)
    allowed = not any((not v.passed) and v.blocking for v in verdicts)
    return PublishEligibility(
        allowed=allowed,
        verdicts=verdicts,
        decided_at=datetime.now(UTC).isoformat(),
    )
