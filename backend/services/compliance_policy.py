"""Shared compliance / automation safety gates (P0 baseline).

Centralises dual-auto rejection, high-risk niche vetoes, and commercial
disclosure markers so API, CLI, review_gate, and publish_gate stay aligned.
"""

from __future__ import annotations

import os
from typing import Any

# High-risk niches never qualify for auto_low_risk approval (review_gate).
HIGH_RISK_NICHES: frozenset[str] = frozenset(
    {
        "医疗",
        "金融",
        "药品",
        "保健",
        "投资",
    }
)

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


def state_is_commercial(state: dict[str, Any] | None) -> bool:
    """True when the run is a commercial brief or explicitly flagged."""
    if not state:
        return False
    if state.get("is_commercial") is True:
        return True
    mode = state.get("workflow_mode")
    mode_text = str(getattr(mode, "value", mode) or "").strip().lower()
    return mode_text == "brief"


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
    "assert_not_dual_auto",
    "auto_approve_low_risk_enabled",
    "commercial_disclosure_ok",
    "is_high_risk_niche",
    "state_is_blocking",
    "state_is_commercial",
    "text_has_disclosure",
]
