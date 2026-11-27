"""Publish preflight: the coupling and realization edges a note must satisfy.

Ledger scheme #62 (Interlock typed completion graph) says a long-horizon run can
be locally correct and still globally incomplete: the copywriter writes
"实测对比表见图 2" while the visual plan only carries one cover card, or the body
promises "置顶评论领路书" while nothing in the publish path ever schedules that
comment.  :func:`backend.services.verification_contracts.assert_typed_completion`
can already decide those edges; this module is the production seam that feeds it
from workflow state and decides whether the publish gate should refuse.

Opt-in by design: :data:`PREFLIGHT_ENV` unset means
:func:`run_preflight` returns an unchecked report without touching state, so the
default publish path stays byte-identical (no new keys in the node result and no
new key in the interrupt payload).

The check is deterministic — no LLM, no network, no database.  It only reads the
state the publish gate already holds.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.services.verification_contracts import (
    CompletionIssue,
    assert_typed_completion,
)
from backend.state.modes import stored_mode

logger = logging.getLogger("xhs_growth.services.publish_preflight")

__all__ = [
    "PREFLIGHT_ENV",
    "PublishPreflightReport",
    "build_preflight",
    "collect_effects",
    "issue_summary",
    "preflight_enabled",
    "run_preflight",
]

#: Opt-in switch.  Unset/empty = the preflight is not run at all.
PREFLIGHT_ENV = "XHS_INTERLOCK_PREFLIGHT"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: Report order for derived effects — fixed so logs and tests read the same.
_EFFECT_ORDER = ("commercial_disclosure", "pinned_comment", "ab_test", "schedule")

#: Markers that mean "this engagement action pins a comment".
_PINNED_HINTS = ("置顶", "pinned", "pin_comment", "pin-comment", "pincomment")


def preflight_enabled() -> bool:
    """Is the pre-publish interlock check switched on?"""
    return os.environ.get(PREFLIGHT_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class PublishPreflightReport:
    """Outcome of one pre-publish interlock check.

    ``checked`` is separate from ``blocked`` on purpose: "not run" and "ran, all
    edges present" must not be the same answer, or turning the switch off would
    look like a pass in the telemetry.
    """

    checked: bool
    blocked: bool
    issues: tuple[CompletionIssue, ...] = ()
    effects: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "blocked": self.blocked,
            "issues": [issue.as_dict() for issue in self.issues],
            "effects": list(self.effects),
        }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _texts(value: Any) -> tuple[str, ...]:
    """Non-blank strings from a list-ish field, order preserved."""
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(text for text in (_as_text(item) for item in value) if text)


def _has_pinned_action(actions: Any) -> bool:
    if not isinstance(actions, (list, tuple)):
        return False
    for action in actions:
        if isinstance(action, Mapping):
            kind = _as_text(action.get("action_type") or action.get("type") or action.get("action"))
            content = _as_text(action.get("content"))
        else:
            kind, content = _as_text(action), ""
        haystack = f"{kind} {content}".lower()
        if kind.lower() in _PINNED_HINTS or any(hint in haystack for hint in _PINNED_HINTS):
            return True
    return False


def collect_effects(state: Mapping[str, Any]) -> tuple[str, ...]:
    """Downstream effects this run has actually scheduled, in a fixed order.

    Only statements the run already made count.  A body that *mentions* 蒲公英
    does not schedule a disclosure; ``publish_options.disclosure_confirmed`` or a
    commercial brief does.
    """
    found: set[str] = set()
    options = _as_mapping(state.get("publish_options"))
    copy = _as_mapping(state.get("copy_content"))

    if stored_mode(state) == "brief" or _as_mapping(state.get("brief_content")):
        found.add("commercial_disclosure")
    if options.get("disclosure_confirmed") is True or state.get("disclosure_confirmed") is True:
        found.add("commercial_disclosure")

    if (
        _as_text(copy.get("pinned_comment"))
        or _as_text(copy.get("seed_comment"))
        or options.get("pinned_comment") is True
        or _has_pinned_action(state.get("engagement_actions"))
    ):
        found.add("pinned_comment")

    versions = state.get("content_versions")
    if options.get("ab_test") is True or (
        isinstance(versions, (list, tuple)) and len(versions) >= 2
    ):
        found.add("ab_test")

    if _as_text(options.get("schedule_time")) or _as_text(options.get("scheduled_at")):
        found.add("schedule")

    return tuple(name for name in _EFFECT_ORDER if name in found)


def build_preflight(state: Mapping[str, Any]) -> PublishPreflightReport:
    """Run the typed-completion check against one workflow state."""
    copy = _as_mapping(state.get("copy_content"))
    visual = _as_mapping(state.get("visual_plan"))
    title = _as_text(copy.get("selected_title") or copy.get("title"))
    body = "\n".join(
        part
        for part in (
            _as_text(copy.get("body_text") or copy.get("body")),
            _as_text(copy.get("cta")),
        )
        if part
    )
    carousel = _texts(visual.get("image_prompts")) or _texts(visual.get("image_paths"))
    effects = collect_effects(state)
    report = assert_typed_completion(
        title=title,
        body=body,
        carousel=carousel,
        hashtags=_texts(copy.get("hashtags")),
        effects=effects,
    )
    return PublishPreflightReport(
        checked=True,
        blocked=report.blocked,
        issues=report.issues,
        effects=effects,
    )


def run_preflight(state: Mapping[str, Any]) -> PublishPreflightReport:
    """Run the check when switched on; otherwise return an unchecked report."""
    if not preflight_enabled():
        return PublishPreflightReport(checked=False, blocked=False)
    report = build_preflight(state)
    if report.blocked:
        logger.warning(
            "publish preflight: %d coupling/realization issue(s) block the publish",
            len(report.issues),
        )
    return report


def issue_summary(issues: tuple[CompletionIssue, ...], *, limit: int = 3) -> str:
    """One human-readable line for the refusal comment (first ``limit`` issues)."""
    parts = [
        f"{issue.edge}:{issue.source}->{issue.target} ({issue.reason})" for issue in issues[:limit]
    ]
    return "；".join(parts)
