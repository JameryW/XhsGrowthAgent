"""GEO-CiteScore signals for topic scoring (ledger scheme #37).

The ledger asks for one thing from a topic: besides "is it hot", *is there still
a blank in AI search that a structured note could occupy?*  The contract lives in
:mod:`backend.services.visibility_contracts` (``geo_cite_score`` /
``rank_geo_keywords``); this module is the adapter that turns data the caller has
**already fetched** into the four signals it wants.

Why adapter instead of a richer fetcher:

1. ``topic_scorer`` already holds 50 search hits and one keyword-heat row per
   keyword.  Asking the platform again to answer "who else wrote this" would buy
   nothing and cost another read.
2. The score must be reproducible: it is written into a prompt and re-read in
   reviews.  A number that moves between two identical calls is worse than no
   number, so nothing here samples, retries, or calls a model.
3. An unreadable platform is handled upstream (``topic_scorer`` refuses to score
   a guess).  This module never invents a measurement: with no likes it reports
   zero supply / zero dispersion rather than a plausible-looking midpoint.

Signals, all in ``0..1`` unless noted:

- ``intent_specificity`` — how long-tail / question-shaped the keyword is.
  Broad head terms ("露营") score low, "国庆川西7天租车多少钱含押金" scores high.
- ``supply_density`` — share of hits already virally strong: likes at or above
  both the batch median and an absolute 1k bar.  High = the term is already
  written, hard to outrank.  The absolute bar matters: a batch where *every*
  note has 5k likes is saturated even though no note is 2× the median.
- ``evidence_dispersion`` — ``1 - top3/total_likes``: high when the existing
  notes are fragmented weak posts instead of one authority, which is exactly the
  shape a list/table note can capture.
- ``search_demand`` — raw magnitude (hits + likes/20); the contract applies
  ``log1p`` itself.

The switch (``XHS_GEO_SCORING``) is checked by ``maybe_geo_report`` only; the
pure helpers are always callable and are what the tests pin.
"""

from __future__ import annotations

import math
import os
import statistics
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from backend.services.visibility_contracts import GeoKeywordScore, rank_geo_keywords

GEO_SCORING_ENV = "XHS_GEO_SCORING"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Markers of a specific, answerable question rather than a broad head term.
# Two characters or longer on purpose: single characters ("带", "去") fire from
# ordinary words and would flatten the ranking.
_SPECIFIC_MARKERS: tuple[str, ...] = (
    "怎么",
    "多少",
    "几天",
    "几月",
    "哪个",
    "哪些",
    "哪里",
    "对比",
    "区别",
    "避坑",
    "清单",
    "攻略",
    "价格",
    "费用",
    "押金",
    "预算",
    "推荐",
    "适合",
    "需要",
    "注意",
    "流程",
    "时间",
    "怎么选",
)

_STRONG_SUPPLY_FLOOR = 1000.0
_RECOMMEND_BLANK = 0.60
_RECOMMEND_GAP = 0.30
_RECOMMEND_DEMAND_FLOOR = 5.0
_RECOMMEND_DENSE = 0.50
_DISPERSION_HINT = 0.60


def geo_scoring_enabled() -> bool:
    """Whether ``topic_scorer`` should attach the ``geo`` block."""
    return os.environ.get(GEO_SCORING_ENV, "").strip().lower() in _TRUTHY


def intent_specificity(text: str) -> float:
    """How specific/long-tail a keyword is, in ``0..1``.

    Deterministic: length bands, question/qualifier markers and the presence of a
    digit.  Broad head terms land near 0.25 so a head term never beats a real
    long-tail query of the same demand.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return 0.0
    score = 0.25
    length = len(cleaned)
    if length >= 6:
        score += 0.10
    if length >= 10:
        score += 0.15
    if length >= 14:
        score += 0.10
    hits = sum(1 for marker in _SPECIFIC_MARKERS if marker in cleaned)
    score += min(0.35, 0.10 * hits)
    if any(char.isdigit() for char in cleaned):
        score += 0.15
    return round(min(1.0, score), 4)


def _clean_likes(likes: Iterable[float]) -> list[float]:
    """Finite, non-negative floats only — a bad value is dropped, not clamped to a guess."""
    cleaned: list[float] = []
    for value in likes:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            cleaned.append(max(0.0, number))
    return cleaned


def supply_density(likes: Iterable[float]) -> float:
    """Share of hits at or above both the batch median and the 1k virality bar."""
    values = _clean_likes(likes)
    if not values:
        return 0.0
    median = statistics.median(values)
    threshold = max(_STRONG_SUPPLY_FLOOR, median)
    strong = sum(1 for value in values if value >= threshold)
    return round(strong / len(values), 4)


def evidence_dispersion(likes: Iterable[float]) -> float:
    """``1 - top3/total``: how fragmented the current evidence is.

    Returns ``0.0`` for fewer than two hits or zero engagement: with nothing
    measurable the honest answer is "no evidence of fragmentation", not "wide
    open" — the demand side is already reported separately.
    """
    values = _clean_likes(likes)
    total = sum(values)
    if len(values) < 2 or total <= 0.0:
        return 0.0
    top_three = sum(sorted(values, reverse=True)[:3])
    return round(min(1.0, max(0.0, 1.0 - top_three / total)), 4)


def search_demand(
    *,
    post_count: int,
    average_likes: float,
    keyword_likes: float | None = None,
) -> float:
    """Raw demand magnitude; the contract takes ``log1p`` of it."""
    likes = average_likes if keyword_likes is None else keyword_likes
    try:
        likes_value = float(likes)
    except (TypeError, ValueError):
        likes_value = 0.0
    if not math.isfinite(likes_value):
        likes_value = 0.0
    demand = float(max(0, post_count)) + max(0.0, likes_value) / 20.0
    return round(demand, 4)


def _unique_keywords(*groups: Iterable[str], limit: int) -> list[str]:
    """First-seen order, trimmed, de-duplicated, capped."""
    seen: list[str] = []
    for group in groups:
        for item in group:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.append(text)
            if len(seen) >= limit:
                return seen
    return seen


def _recommendation(best: GeoKeywordScore | None, *, supply: float, dispersion: float) -> str:
    if best is None:
        return "无候选关键词，跳过 GEO 评分"
    if best.search_demand < _RECOMMEND_DEMAND_FLOOR:
        text = "需求过低：换更具体的场景/时间/预算词再试"
    elif supply >= _RECOMMEND_DENSE:
        text = "竞争饱和：加更具体的限定词（时间/预算/场景）再试"
    elif best.score >= _RECOMMEND_BLANK:
        text = "空白明显：用该长尾词做结构化实测帖，抢 AI 搜索引用"
    elif best.score >= _RECOMMEND_GAP:
        text = "有空隙：首段结论前置该长尾词，补足多维证据"
    else:
        text = "竞争饱和：加更具体的限定词（时间/预算/场景）再试"
    if dispersion >= _DISPERSION_HINT:
        text += "；现有笔记信息碎片化，列表化/表格化可提高被引用率"
    return text


def build_geo_report(
    *,
    topic: str,
    keywords: Sequence[str] = (),
    likes: Sequence[float] = (),
    keyword_likes: Mapping[str, float] | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Score the topic and its related keywords for AI-search blankness.

    Args:
        topic: The candidate topic (always the first keyword candidate).
        keywords: Related keywords; duplicates and empties are dropped.
        likes: Likes of the search hits already fetched for this topic.
        keyword_likes: Optional per-keyword average likes from the keyword read.
        limit: Maximum number of keyword candidates to rank.

    Returns:
        A JSON-ready report.  With no candidates it still returns the same shape
        (empty ``candidates``, empty ``best_keyword``) so callers never branch on
        ``None`` here.
    """
    limit = max(1, int(limit))
    head = str(topic or "").strip()
    candidates = _unique_keywords([head] if head else [], keywords, limit=limit)

    values = _clean_likes(likes)
    post_count = len(values)
    average_likes = sum(values) / post_count if post_count else 0.0
    density = supply_density(values)
    dispersion = evidence_dispersion(values)

    per_keyword: dict[str, float] = {}
    for key, value in (keyword_likes or {}).items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            per_keyword[str(key).strip()] = max(0.0, number)

    rows: list[dict[str, Any]] = []
    for keyword in candidates:
        rows.append(
            {
                "keyword": keyword,
                "intent_specificity": intent_specificity(keyword),
                "search_demand": search_demand(
                    post_count=post_count,
                    average_likes=average_likes,
                    keyword_likes=per_keyword.get(keyword),
                ),
                "high_density_supply_count": density,
                "evidence_dispersion_penalty": dispersion,
            }
        )
    ranked = rank_geo_keywords(rows, limit=limit)
    best = ranked[0] if ranked else None

    return {
        "enabled": True,
        "best_keyword": best.keyword if best is not None else "",
        "best_score": round(best.score, 6) if best is not None else 0.0,
        "signals": {
            "post_count": post_count,
            "average_likes": round(average_likes, 2),
            "supply_density": density,
            "evidence_dispersion": dispersion,
        },
        "candidates": [item.as_dict() for item in ranked],
        "recommendation": _recommendation(best, supply=density, dispersion=dispersion),
    }


def maybe_geo_report(**kwargs: Any) -> dict[str, Any] | None:
    """``build_geo_report`` behind the ``XHS_GEO_SCORING`` switch.

    Returns ``None`` when off, which is what keeps ``topic_scorer``'s payload
    byte-identical for deployments that never opt in.
    """
    if not geo_scoring_enabled():
        return None
    return build_geo_report(**kwargs)


__all__ = [
    "GEO_SCORING_ENV",
    "build_geo_report",
    "evidence_dispersion",
    "geo_scoring_enabled",
    "intent_specificity",
    "maybe_geo_report",
    "search_demand",
    "supply_density",
]
