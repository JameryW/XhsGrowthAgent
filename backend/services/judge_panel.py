"""Heterogeneous judge panel aggregation.

The evaluator historically asked one judge prompt for the whole RQGM panel.
This module adds a small, deterministic aggregation layer for an optional
multi-lens panel: each lens sees the same content from a different review
stance, then the scores are combined dimension by dimension.

The lenses are not different provider models in this deployment (all model
calls go through the magpie gateway). They are deliberately different judge
instructions, and each vote records the concrete model id that produced it.
That keeps the contract honest: the panel is heterogeneous in review stance,
not a claim of cross-provider judging. The aggregation itself is pure so the
evaluator can keep its deterministic overall-score rebuild unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

JUDGE_PANEL_ENV = "XHS_HETEROGENEOUS_JUDGE"
MIN_PANEL_AGREEMENT = 0.65
DISSENT_DIMENSION_SPREAD = 20.0


@dataclass(frozen=True)
class JudgeLens:
    """One review stance in the panel."""

    judge_id: str
    instruction: str
    weight: float = 1.0


DEFAULT_JUDGE_LENSES: tuple[JudgeLens, ...] = (
    JudgeLens(
        "strict",
        "以最严格的合规与事实审稿人视角评分：优先发现夸大、无证据承诺和合规风险。",
    ),
    JudgeLens(
        "audience",
        "以目标受众视角评分：判断开头是否抓人、信息是否可执行、是否值得收藏。",
    ),
    JudgeLens(
        "commercial",
        "以商业转化与品牌安全视角评分：判断卖点是否清楚、披露是否充分、语气是否可信。",
    ),
)


def judge_panel_enabled() -> bool:
    """Whether the optional multi-lens evaluator path is enabled."""
    return os.environ.get(JUDGE_PANEL_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class JudgeVote:
    judge_id: str
    model_id: str
    dimensions: dict[str, float]
    overall: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "judge_id": self.judge_id,
            "model_id": self.model_id,
            "dimensions": dict(self.dimensions),
            "overall": self.overall,
        }


@dataclass(frozen=True)
class JudgePanelConsensus:
    votes: tuple[JudgeVote, ...]
    dimensions: list[dict[str, Any]]
    revision_hints: list[str]
    summary: str
    bias_warning: str
    agreement: float
    dissent: list[str]

    def payload(self) -> dict[str, Any]:
        """The raw panel shape consumed by ``_build_evaluation_result``."""
        return {
            "dimensions": self.dimensions,
            "revision_hints": self.revision_hints,
            "summary": self.summary,
            "bias_warning": self.bias_warning,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "panel_size": len(self.votes),
            "judge_ids": [vote.judge_id for vote in self.votes],
            "model_ids": sorted({vote.model_id for vote in self.votes}),
            "agreement": round(self.agreement, 4),
            "dissent": list(self.dissent),
            "votes": [vote.as_dict() for vote in self.votes],
        }


def _as_dimensions(panel: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = panel.get("dimensions")
    entries: Iterable[Any]
    if isinstance(raw, Mapping):
        entries = raw.values()
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        entries = raw
    else:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("dimension") or "").strip()
        if name:
            result[name] = dict(entry)
    return result


def _score(entry: Mapping[str, Any]) -> float | None:
    value = entry.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value)))


def aggregate_judge_panels(
    panels: Sequence[Mapping[str, Any]],
    *,
    judge_ids: Sequence[str] | None = None,
    model_ids: Sequence[str] | None = None,
    weights: Sequence[float] | None = None,
) -> JudgePanelConsensus:
    """Combine normalized ``EvaluationPanelOutput`` payloads.

    Every panel contributes its available dimension scores. The consensus score
    is the weighted mean; a dimension is only emitted when at least one judge
    supplied a numeric score. Blocking flags are OR-ed because a single judge
    finding a hard compliance issue must not be averaged away.
    """
    if not panels:
        raise ValueError("judge panel requires at least one panel")

    ids = list(judge_ids or [f"judge-{index + 1}" for index in range(len(panels))])
    models = list(model_ids or ["unknown"] * len(panels))
    if len(ids) != len(panels) or len(models) != len(panels):
        raise ValueError("judge_ids/model_ids must match the number of panels")

    panel_weights = list(weights or [1.0] * len(panels))
    if len(panel_weights) != len(panels):
        raise ValueError("weights must match the number of panels")

    dimension_values: dict[str, list[tuple[float, float]]] = {}
    dimension_entries: dict[str, list[dict[str, Any]]] = {}
    panel_overalls: list[float] = []
    votes: list[JudgeVote] = []

    for panel, judge_id, model_id, weight in zip(panels, ids, models, panel_weights, strict=True):
        dimensions = _as_dimensions(panel)
        scores: dict[str, float] = {}
        for name, entry in dimensions.items():
            score = _score(entry)
            if score is None:
                continue
            scores[name] = score
            dimension_values.setdefault(name, []).append((score, max(0.0, weight)))
            dimension_entries.setdefault(name, []).append(entry)
        overall = round(sum(scores.values()) / len(scores), 2) if scores else None
        if overall is not None:
            panel_overalls.append(overall)
        votes.append(
            JudgeVote(
                judge_id=judge_id,
                model_id=model_id,
                dimensions=scores,
                overall=overall,
            )
        )

    consensus_dimensions: list[dict[str, Any]] = []
    dissent: list[str] = []
    for name, values in dimension_values.items():
        weighted_total = sum(score * weight for score, weight in values)
        weight_total = sum(weight for _, weight in values)
        score = round(weighted_total / weight_total, 2) if weight_total else None
        spread = max(value for value, _ in values) - min(value for value, _ in values)
        if spread >= DISSENT_DIMENSION_SPREAD:
            dissent.append(name)
        entries = dimension_entries[name]
        issues: list[str] = []
        rationales: list[str] = []
        for entry in entries:
            raw_issues = entry.get("issues")
            if isinstance(raw_issues, list):
                issues.extend(str(item) for item in raw_issues if str(item).strip())
            rationale = str(entry.get("rationale") or "").strip()
            if rationale:
                rationales.append(rationale)
        bias_values = [
            float(entry["bias_severity"])
            for entry in entries
            if isinstance(entry.get("bias_severity"), (int, float))
            and not isinstance(entry.get("bias_severity"), bool)
        ]
        consensus_dimensions.append(
            {
                "dimension": name,
                "score": score,
                "available": score is not None,
                "rationale": " | ".join(dict.fromkeys(rationales)),
                "issues": list(dict.fromkeys(issues)),
                "is_blocking": any(bool(entry.get("is_blocking")) for entry in entries),
                "bias_severity": (
                    round(sum(bias_values) / len(bias_values), 2) if bias_values else None
                ),
            }
        )

    hints: list[str] = []
    summaries: list[str] = []
    warnings: list[str] = []
    for panel in panels:
        for hint in panel.get("revision_hints") or ():
            text = str(hint).strip()
            if text:
                hints.append(text)
        summary = str(panel.get("summary") or "").strip()
        if summary:
            summaries.append(summary)
        warning = str(panel.get("bias_warning") or "").strip()
        if warning:
            warnings.append(warning)

    agreement = 1.0 - (max(panel_overalls) - min(panel_overalls)) / 100.0 if panel_overalls else 1.0
    return JudgePanelConsensus(
        votes=tuple(votes),
        dimensions=consensus_dimensions,
        revision_hints=list(dict.fromkeys(hints)),
        summary="；".join(dict.fromkeys(summaries)),
        bias_warning="；".join(dict.fromkeys(warnings)),
        agreement=max(0.0, min(1.0, agreement)),
        dissent=dissent,
    )


__all__ = [
    "DEFAULT_JUDGE_LENSES",
    "DISSENT_DIMENSION_SPREAD",
    "JUDGE_PANEL_ENV",
    "MIN_PANEL_AGREEMENT",
    "JudgeLens",
    "JudgePanelConsensus",
    "JudgeVote",
    "aggregate_judge_panels",
    "judge_panel_enabled",
]
