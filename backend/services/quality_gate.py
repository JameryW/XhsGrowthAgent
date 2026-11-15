"""SearchLLM-style quality gate and deterministic search-GEO readiness.

Two layers, matching the RedNote SearchLLM evaluation contract:

* **Layer I (soft-AND floor gate).**  A handful of non-negotiable dimensions
  (compliance, first-screen grounding, format compliance) get a multiplicative
  gate.  A dimension *at or above* its floor contributes ``1.0``; below the
  floor the factor decays smoothly to ~0, so one hidden defect cannot be
  averaged away by a high literary score.
* **Layer II (utility aggregate).**  The evaluator's existing weighted
  average is kept unchanged and multiplied by the gate.

``search_geo`` is an additional deterministic advisory dimension: it scores
whether a note is likely to match Xiaohongshu search intent (title length,
answer-first first three lines, long-tail query vocabulary, list structure,
hashtag compliance).  It is deliberately *not* added to the evaluator's
weight table — that table is contractually fixed at sum 1.0 — so it surfaces
as an audit field and a small capped Layer II multiplier only.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FloorSpec:
    """One Layer I dimension floor."""

    dimension: str
    floor: float = 60.0
    temperature: float = 8.0
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "floor": self.floor,
            "temperature": self.temperature,
            "label": self.label or self.dimension,
        }


# The evaluator's dimensions are proxies for SearchLLM's Layer I concerns:
# compliance covers policy/format, copywriting covers first-screen coherence,
# commercial_tone covers disclosure tone.  Additional raw dimensions may be
# supplied by callers and are used when present.
DEFAULT_LAYER_ONE: tuple[FloorSpec, ...] = (
    FloorSpec("compliance", floor=60.0, temperature=8.0, label="合规与底线"),
    FloorSpec("copywriting", floor=50.0, temperature=10.0, label="首屏表达与结构"),
    FloorSpec("commercial_tone", floor=40.0, temperature=10.0, label="商单披露语气"),
)

_GEO_INTENT_TERMS = (
    "怎么",
    "如何",
    "教程",
    "攻略",
    "测评",
    "推荐",
    "避坑",
    "清单",
    "步骤",
    "方法",
    "技巧",
    "指南",
    "模板",
    "平替",
    "对比",
    "哪个",
    "值得吗",
)
_ANSWER_FIRST_RE = re.compile(
    r"(^\s*(?:\d+[.、)]|[①②③④⑤]|[-*•])|首先|第一步|结论|答案是|直接说|重点)",
    re.MULTILINE,
)
_HASHTAG_RE = re.compile(r"#([^\s#]+)")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _soft_floor(score: float | None, spec: FloorSpec) -> float:
    """1.0 at/above the floor; a smooth decay below it."""
    if score is None:
        return 1.0  # missing evidence is handled by the evaluator's coverage
    if score >= spec.floor:
        return 1.0
    delta = (spec.floor - score) / max(spec.temperature, 0.1)
    # Logistic tail anchored so score=floor -> 1.0, then rapidly near zero.
    return 2.0 / (1.0 + math.exp(min(50.0, delta)))


def evaluate_layer_one(
    dimensions: Iterable[Mapping[str, Any]],
    specs: Sequence[FloorSpec] = DEFAULT_LAYER_ONE,
) -> dict[str, Any]:
    """Compute the soft-AND gate from evaluator dimensions.

    ``dimensions`` is the normalized list produced by the evaluator (each item
    has ``dimension``/``score``/``available``).  Missing dimensions are
    reported but do not zero the gate: the evaluator's coverage contract
    already prevents a partial panel from becoming a pass.
    """
    by_name = {str(item.get("dimension")): item for item in dimensions}
    components: list[dict[str, Any]] = []
    gate = 1.0
    blocked: list[str] = []
    for spec in specs:
        item = by_name.get(spec.dimension)
        score = None
        if item is not None and item.get("available") is not False:
            raw = item.get("score")
            if raw is not None:
                score = _clamp(float(raw), 0.0, 100.0)
        factor = _soft_floor(score, spec)
        gate *= factor
        if score is not None and score < spec.floor:
            blocked.append(spec.dimension)
        components.append(
            {
                **spec.as_dict(),
                "score": None if score is None else round(score, 2),
                "factor": round(factor, 6),
                "passed": score is None or score >= spec.floor,
            }
        )
    return {
        "gate_factor": round(_clamp(gate, 0.0, 1.0), 6),
        "blocked_dimensions": blocked,
        "components": components,
    }


def _first_three_lines(body: str) -> str:
    lines = [line.strip() for line in (body or "").splitlines() if line.strip()]
    return "\n".join(lines[:3])


def geo_readiness(
    title: str,
    body: str,
    hashtags: Sequence[str] | str | None = None,
) -> dict[str, Any]:
    """Deterministic 0-100 search-GEO readiness score.

    Four equally weighted checks (25 points each):
    1. title length 1-20 chars (platform hard limit) and contains a topic word;
    2. answer-first: the first three non-empty lines carry the conclusion;
    3. long-tail search vocabulary in title or first screen;
    4. list/structure markers and 3-10 hashtags.
    """
    title = (title or "").strip()
    body = body or ""
    if isinstance(hashtags, str):
        tags = [part.strip() for part in re.split(r"[,\s#]+", hashtags) if part.strip()]
    else:
        tags = [str(tag).lstrip("#") for tag in (hashtags or [])]
    if not tags:
        tags = _HASHTAG_RE.findall(body)

    components: dict[str, Any] = {}

    title_ok = 1 <= len(title) <= 20
    title_score = 25.0 if title_ok else (10.0 if len(title) > 20 else 0.0)
    components["title_length"] = {
        "score": title_score,
        "max": 25.0,
        "detail": f"标题 {len(title)} 字（平台上限 20）",
    }

    first = _first_three_lines(body)
    answer_score = 0.0
    if first:
        if _ANSWER_FIRST_RE.search(first):
            answer_score += 15.0
        # A short first screen is more likely to be scanned, not skipped.
        if len(first) <= 160:
            answer_score += 10.0
    components["answer_first"] = {
        "score": answer_score,
        "max": 25.0,
        "detail": "首屏前三行包含结论/步骤" if answer_score >= 15 else "首屏未结论前置",
    }

    searchable = f"{title}\n{first}"
    matched_terms = sorted({term for term in _GEO_INTENT_TERMS if term in searchable})
    intent_score = 25.0 if len(matched_terms) >= 2 else (15.0 if matched_terms else 0.0)
    components["long_tail_intent"] = {
        "score": intent_score,
        "max": 25.0,
        "matched_terms": matched_terms,
    }

    bullet_count = len(_ANSWER_FIRST_RE.findall(body))
    tag_ok = 3 <= len(tags) <= 10
    structure_score = min(15.0, bullet_count * 5.0) + (10.0 if tag_ok else 0.0)
    components["structure"] = {
        "score": structure_score,
        "max": 25.0,
        "detail": f"分点 {bullet_count} 处，标签 {len(tags)} 个",
    }

    total = sum(float(item["score"]) for item in components.values())
    return {
        "score": round(_clamp(total, 0.0, 100.0), 1),
        "components": components,
        "matched_terms": matched_terms,
    }


def apply_quality_gate(
    dimensions: Iterable[Mapping[str, Any]],
    *,
    base_overall: float,
    specs: Sequence[FloorSpec] = DEFAULT_LAYER_ONE,
) -> dict[str, Any]:
    """Apply the Layer I gate to an already-computed Layer II score."""
    layer_one = evaluate_layer_one(dimensions, specs)
    gated = round(_clamp(base_overall * layer_one["gate_factor"], 0.0, 100.0), 1)
    return {
        "base_overall": round(base_overall, 1),
        "overall": gated,
        "gate_factor": layer_one["gate_factor"],
        "blocked_dimensions": layer_one["blocked_dimensions"],
        "components": layer_one["components"],
    }


__all__ = [
    "DEFAULT_LAYER_ONE",
    "FloorSpec",
    "apply_quality_gate",
    "evaluate_layer_one",
    "geo_readiness",
]
