"""Shared compliance / automation safety gates (P0 baseline).

Centralises dual-auto rejection, high-risk niche vetoes, and commercial
disclosure markers so API, CLI, review_gate, and publish_gate stay aligned.
"""

from __future__ import annotations

import os
from typing import Any

# High-risk niches never qualify for auto_low_risk approval (review_gate).
# Keep in sync with lexicon `_NICHE_OVERLAYS` and niche YAML overlays.
HIGH_RISK_NICHES: frozenset[str] = frozenset(
    {
        "医疗",
        "金融",
        "药品",
        "保健",
        "投资",
        "医美",
    }
)

# Required-qualification reminders when the operator selects a high-risk niche.
# Keys must be a subset of HIGH_RISK_NICHES (looked up after exact niche match).
NICHE_QUALIFICATION_HINTS: dict[str, str] = {
    "医疗": "医疗垂类需具备相应诊疗/科普资质；禁止功效承诺与处方暗示，文案须附免责声明。",
    "药品": "药品相关内容需具备药品信息发布资质；禁止疗效保证与未经批准的用药建议。",
    "保健": "保健品内容需真实资质与合规标识；禁止替代治疗或绝对化功效表述。",
    "医美": "医美垂类需具备医疗机构/执业资质公示；禁止「零风险」「一次永久」等夸大承诺。",
    "金融": "金融垂类需具备相应展业资质；禁止保本/稳赚话术，须提示投资风险。",
    "投资": "投资相关内容需风险揭示与资质合规；禁止收益承诺与诱导跟单。",
}

# Markers that count as commercial-collaboration disclosure in copy.
DISCLOSURE_MARKERS: tuple[str, ...] = (
    "合作",
    "广告",
    "品牌合作",
    "商业合作",
    "已报备",
    "已标注",
    "#广告",
    "#合作",
    "赞助",
    "推广",
    "含广告",
    "商业推广",
)


class DualAutoPublishError(ValueError):
    """Raised when AUTO_APPROVE_LOW_RISK and auto_publish are both enabled."""

    error_code = "dual_auto_publish_forbidden"

    def __init__(
        self,
        message: str = (
            "Cannot enable AUTO_APPROVE_LOW_RISK together with auto_publish "
            "(error_code=dual_auto_publish_forbidden). Disable one to keep a "
            "human gate on either review or publish."
        ),
    ) -> None:
        super().__init__(message)
        self.error_code = "dual_auto_publish_forbidden"


def auto_approve_low_risk_enabled() -> bool:
    """Read AUTO_APPROVE_LOW_RISK; default False (fail-safe)."""
    try:
        return os.environ.get("AUTO_APPROVE_LOW_RISK", "").strip().lower() in (
            "true",
            "1",
            "yes",
        )
    except Exception:
        return False


def assert_not_dual_auto(*, auto_publish: bool) -> None:
    """Hard-reject full unattended publish (API + CLI share this rule)."""
    if auto_publish and auto_approve_low_risk_enabled():
        raise DualAutoPublishError()


def is_high_risk_niche(niche: str | None) -> bool:
    return (niche or "").strip() in HIGH_RISK_NICHES


def niche_qualification_hint(niche: str | None) -> str | None:
    """Return the required-qualification hint for a high-risk niche, if any."""
    key = (niche or "").strip()
    if not key:
        return None
    return NICHE_QUALIFICATION_HINTS.get(key)


def get_niche_compliance_tier(niche: str | None) -> dict[str, Any]:
    """P2-2: compliance tier + lexicon/qualification notice for Start/Settings UI."""
    from backend.services.compliance.lexicon import NICHE_OVERLAYS

    key = (niche or "").strip()
    high = key in HIGH_RISK_NICHES
    return {
        "niche": key,
        "tier": "high" if high else "standard",
        "is_high_risk": high,
        "lexicon_stricter": high,
        "qualification_hint": NICHE_QUALIFICATION_HINTS.get(key) if high else None,
        "lexicon_overlay": NICHE_OVERLAYS.get(key),
    }


def state_is_commercial(state: dict[str, Any] | None) -> bool:
    """True when the run is a commercial brief or explicitly flagged."""
    if not state:
        return False
    if state.get("is_commercial") is True:
        return True
    # Read mode via the registry (modes.mode_spec) — never state.get("workflow_mode").
    from backend.state.enums import WorkflowMode
    from backend.state.modes import mode_spec

    return mode_spec(state).mode is WorkflowMode.BRIEF


def state_is_blocking(state: dict[str, Any] | None) -> bool:
    """True when compliance already marked the draft as blocking."""
    if not state:
        return False
    if state.get("is_blocking") is True:
        return True
    evaluation = state.get("evaluation_result") or {}
    if isinstance(evaluation, dict):
        for dim in evaluation.get("dimensions") or []:
            if isinstance(dim, dict) and dim.get("is_blocking"):
                return True
        lex = evaluation.get("lexicon_scan") or {}
        if isinstance(lex, dict) and lex.get("is_blocking"):
            return True
    compliance = state.get("compliance_scan") or {}
    return bool(isinstance(compliance, dict) and compliance.get("is_blocking"))


def text_has_disclosure(text: str) -> bool:
    blob = text or ""
    return any(marker in blob for marker in DISCLOSURE_MARKERS)


def commercial_disclosure_ok(state: dict[str, Any] | None) -> bool:
    """Commercial runs need disclosure markers in copy AND an explicit checkbox."""
    if not state_is_commercial(state):
        return True
    assert state is not None
    confirmation = state.get("publish_confirmation") or {}
    if not isinstance(confirmation, dict):
        confirmation = {}
    options = state.get("publish_options") or {}
    if not isinstance(options, dict):
        options = {}
    checked = (
        confirmation.get("disclosure_confirmed") is True
        or options.get("disclosure_confirmed") is True
        or state.get("disclosure_confirmed") is True
    )
    if not checked:
        return False
    copy = state.get("copy_content") or {}
    if not isinstance(copy, dict):
        copy = {}
    title = str(copy.get("selected_title") or "")
    body = str(copy.get("body_text") or "")
    return text_has_disclosure(f"{title}\n{body}")


__all__ = [
    "DISCLOSURE_MARKERS",
    "DualAutoPublishError",
    "HIGH_RISK_NICHES",
    "NICHE_QUALIFICATION_HINTS",
    "assert_not_dual_auto",
    "auto_approve_low_risk_enabled",
    "commercial_disclosure_ok",
    "get_niche_compliance_tier",
    "is_high_risk_niche",
    "niche_qualification_hint",
    "state_is_blocking",
    "state_is_commercial",
    "text_has_disclosure",
]
