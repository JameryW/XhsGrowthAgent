# backend/services/polish_gate.py

"""Risk-aware polish gate for ``TaskType.POLISH`` (ledger scheme #56).

Unconditional two-stage self-revision is not free: ``arXiv:2609.35832v1`` shows
a net ``C -> W`` harmful-flip rate of up to 19.1% even when polishing helps on
average, because a model asked to polish an already human-sounding draft tends
to flatten its voice.  This module turns the polish step into a gated decision:

* stage-0 assessment scores the draft with the deterministic PLAD inspector
  (no API cost) and counts banned words;
* ``decide_before_polish`` skips the LLM polish entirely when the draft is
  already human-like and clean;
* ``decide_after_polish`` accepts the polished draft only when it is a Pareto
  improvement (``+0.03`` human probability and no lost semantic IDs),
  otherwise the caller keeps stage 0.

Opt-in: with ``XHS_POLISH_GATE`` unset the copywriter keeps its previous
unconditional behaviour.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from backend.services.decision_contracts import (
    PolishDecision,
    evaluate_polish_acceptance,
    risk_aware_polish_gate,
)
from backend.tools.content.plad import inspect_text

__all__ = [
    "POLISH_GATE_ENV",
    "StageAssessment",
    "assess_stage",
    "decide_after_polish",
    "decide_before_polish",
    "polish_decision_fields",
    "polish_gate_enabled",
]

POLISH_GATE_ENV: Final = "XHS_POLISH_GATE"
_TRUTHY: Final = frozenset({"1", "true", "yes", "on"})
_HUMAN_SKIP_THRESHOLD: Final = 0.82


def polish_gate_enabled() -> bool:
    """Return True when the opt-in risk-aware polish gate is switched on."""

    return os.environ.get(POLISH_GATE_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class StageAssessment:
    """Deterministic PLAD assessment of one draft stage."""

    title: str
    body: str
    human_prob: float
    ai_likelihood: float
    banned_word_count: int = 0

    def as_stage(self) -> dict[str, Any]:
        """Shape consumed by the decision contracts."""

        return {"title": self.title, "body": self.body}

    def as_dict(self) -> dict[str, Any]:
        return {
            "human_prob": round(self.human_prob, 4),
            "ai_likelihood": round(self.ai_likelihood, 4),
            "banned_word_count": self.banned_word_count,
            "title_chars": len(self.title),
            "body_chars": len(self.body),
        }


def assess_stage(
    title: str,
    body: str,
    *,
    banned_word_count: int = 0,
) -> StageAssessment:
    """Score a draft stage with the zero-cost PLAD inspector."""

    text = f"{title}\n{body}".strip()
    report = inspect_text(text)
    ai_likelihood = max(0.0, min(1.0, float(report.ai_likelihood)))
    return StageAssessment(
        title=title,
        body=body,
        human_prob=1.0 - ai_likelihood,
        ai_likelihood=ai_likelihood,
        banned_word_count=max(0, int(banned_word_count)),
    )


def decide_before_polish(
    stage0: StageAssessment,
    *,
    required_sections: Sequence[str] = (),
) -> PolishDecision:
    """Decide whether the stage-0 draft still needs an LLM polish pass."""

    return risk_aware_polish_gate(
        stage0.as_stage(),
        plad_human_prob=stage0.human_prob,
        banned_word_count=stage0.banned_word_count,
        required_sections=required_sections,
    )


def decide_after_polish(
    stage0: StageAssessment,
    stage1: StageAssessment,
    *,
    stage0_semantic_ids: Iterable[str] | None = None,
    stage1_semantic_ids: Iterable[str] | None = None,
    min_gain: float = 0.03,
) -> PolishDecision:
    """Accept a polished draft only when it does not regress the draft."""

    return evaluate_polish_acceptance(
        stage0.as_stage(),
        stage1.as_stage(),
        stage0_human_prob=stage0.human_prob,
        stage1_human_prob=stage1.human_prob,
        stage0_semantic_ids=stage0_semantic_ids,
        stage1_semantic_ids=stage1_semantic_ids,
        min_gain=min_gain,
    )


def polish_decision_fields(decision: PolishDecision) -> Mapping[str, Any]:
    """Observability payload written next to the copywriter output."""

    return {"de_ai_polish_gate": decision.as_dict()}
