"""Deterministic, read-only creative-quality analysis for imported history.

This is deliberately separate from style-DNA analysis and workflow RQGM
evaluation.  It scores only durable Creator Center note statistics already
persisted for an account; it does not call a browser, LLM, or database writer.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from backend.services.creator_stats.analyze import as_fraction_engagement_rate
from backend.services.creator_stats.types import (
    CreatorQualityReport,
    NoteStats,
    QualityConfidence,
    QualityDimension,
    QualityDimensionKey,
    QualityGrade,
    QualityInsight,
    QualityRecommendation,
)

MIN_NOTES_FOR_OVERALL_SCORE = 3
SCOPE_ALL_IMPORTED_HISTORY = "all_imported_history"
SCOPE_SINGLE_IMPORTED_NOTE = "single_imported_note"
QualityReportLocale = Literal["zh-CN", "en"]

# Product heuristics for a transparent 0--100 signal.  They are not platform
# benchmarks; insight evidence always reports the account's observed values.
_ENGAGEMENT_SCORE_TARGET = 0.12
_SAVE_VALUE_SCORE_TARGET = 0.04
_DIMENSION_WEIGHTS: dict[QualityDimensionKey, float] = {
    "engagement": 0.35,
    "save_value": 0.25,
    "title_craft": 0.20,
    "consistency": 0.20,
}
_DIMENSION_ORDER: tuple[QualityDimensionKey, ...] = (
    "engagement",
    "save_value",
    "title_craft",
    "consistency",
)


def _normalize_locale(value: str | None) -> QualityReportLocale:
    """Keep the public report bilingual with a safe Chinese fallback."""
    return "en" if str(value or "").lower().startswith("en") else "zh-CN"


def _copy(locale: QualityReportLocale, chinese: str, english: str) -> str:
    return english if locale == "en" else chinese


# Keep title assessment title-only.  Missing ``body_text`` is an import-data
# limitation and must never be converted into a negative copywriting signal.
_TITLE_HOOK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\d+\s*(?:个|条|步|点|种|招|款)"),
    re.compile(r"[？?]|为什么|怎么|如何|有没有"),
    re.compile(r"\bvs\b|对比|前后|之前|之后|从.+到", re.IGNORECASE),
    re.compile(r"清单|合集|推荐|种草|避雷|干货|指南"),
)


@dataclass(frozen=True)
class _RateSample:
    note: NoteStats
    engagement_rate: float
    views: int
    collects: int


@dataclass(frozen=True)
class _DimensionMetrics:
    score: float
    evidence: str
    top_note_ids: tuple[str, ...] = ()
    bottom_note_ids: tuple[str, ...] = ()
    available: bool = True


def _nonnegative_int(value: Any) -> int:
    """Coerce malformed persisted counters without letting a bad row crash a report."""
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _clamp_score(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(max(0.0, min(100.0, value)), 1)


def _normalized_note_rate(note: NoteStats) -> float:
    """Normalize legacy percent/fraction rates without changing the input note.

    Most imported rows have a metrics-derived fraction.  Hand-built or legacy
    rows may retain a percent-scale ``engagement_rate``; the existing shared
    normalizer handles both.  If that field is absent/zero but counters are
    present, use the counters as a safe fallback rather than erasing a real
    interaction signal.
    """
    normalized = as_fraction_engagement_rate(getattr(note, "engagement_rate", 0.0))
    if not math.isfinite(normalized):
        normalized = 0.0
    views = _nonnegative_int(getattr(note, "views", 0))
    interactions = sum(
        _nonnegative_int(getattr(note, field, 0))
        for field in ("likes", "comments", "collects", "shares")
    )
    metric_rate = min(interactions / views, 1.0) if views else 0.0
    if normalized <= 0.0 and metric_rate > 0.0:
        return metric_rate
    return min(max(normalized, 0.0), 1.0)


def _rate_samples(notes: Iterable[NoteStats]) -> list[_RateSample]:
    return [
        _RateSample(
            note=note,
            engagement_rate=_normalized_note_rate(note),
            views=_nonnegative_int(getattr(note, "views", 0)),
            collects=_nonnegative_int(getattr(note, "collects", 0)),
        )
        for note in notes
    ]


def _format_percent(value: float) -> str:
    return f"{max(0.0, value) * 100:.2f}%"


def _top_note_ids(samples: list[_RateSample], *, limit: int = 3) -> tuple[str, ...]:
    ordered = sorted(
        samples,
        key=lambda sample: (
            -sample.engagement_rate,
            -sample.views,
            str(getattr(sample.note, "note_id", "")),
        ),
    )
    return tuple(
        str(sample.note.note_id)
        for sample in ordered[:limit]
        if str(getattr(sample.note, "note_id", "")).strip()
    )


def _bottom_note_ids(samples: list[_RateSample], *, limit: int = 3) -> tuple[str, ...]:
    ordered = sorted(
        samples,
        key=lambda sample: (
            sample.engagement_rate,
            sample.views,
            str(getattr(sample.note, "note_id", "")),
        ),
    )
    return tuple(
        str(sample.note.note_id)
        for sample in ordered[:limit]
        if str(getattr(sample.note, "note_id", "")).strip()
    )


def _title_text(note: NoteStats) -> str:
    return str(getattr(note, "title", "") or "").strip()


def _is_readable_title(title: str) -> bool:
    compact = re.sub(r"\s+", "", title)
    return 6 <= len(compact) <= 36


def _has_title_hook(title: str) -> bool:
    return any(pattern.search(title) for pattern in _TITLE_HOOK_PATTERNS)


def _engagement_dimension(
    samples: list[_RateSample], locale: QualityReportLocale
) -> _DimensionMetrics:
    if not samples:
        return _DimensionMetrics(
            score=0.0,
            evidence=_copy(
                locale,
                "尚无已导入笔记，无法计算互动信号。",
                "No imported notes are available to calculate engagement signals.",
            ),
            available=False,
        )

    total_views = sum(sample.views for sample in samples)
    if total_views:
        # Weight normalized per-note rates by each note's views so all imported
        # rows contribute to the account-level rate without averaging percent
        # and fraction scales incorrectly.
        engagement_rate = (
            sum(sample.engagement_rate * sample.views for sample in samples) / total_views
        )
    else:
        engagement_rate = sum(sample.engagement_rate for sample in samples) / len(samples)
    nonzero_count = sum(sample.engagement_rate > 0 for sample in samples)
    score = _clamp_score(engagement_rate / _ENGAGEMENT_SCORE_TARGET * 100)
    return _DimensionMetrics(
        score=score,
        evidence=_copy(
            locale,
            (
                f"全量 {len(samples)} 篇笔记的平均互动率为 {_format_percent(engagement_rate)}，"
                f"其中 {nonzero_count}/{len(samples)} 篇有非零互动。"
            ),
            (
                f"Across all {len(samples)} imported notes, the average engagement rate is "
                f"{_format_percent(engagement_rate)}; "
                f"{nonzero_count}/{len(samples)} have non-zero engagement."
            ),
        ),
        top_note_ids=_top_note_ids(samples),
        bottom_note_ids=_bottom_note_ids(samples),
    )


def _save_value_dimension(
    samples: list[_RateSample], locale: QualityReportLocale
) -> _DimensionMetrics:
    if not samples:
        return _DimensionMetrics(
            score=0.0,
            evidence=_copy(
                locale,
                "尚无已导入笔记，无法计算收藏价值。",
                "No imported notes are available to calculate save value.",
            ),
            available=False,
        )

    total_views = sum(sample.views for sample in samples)
    total_collects = sum(sample.collects for sample in samples)
    if not total_views:
        return _DimensionMetrics(
            score=0.0,
            evidence=_copy(
                locale,
                "已导入笔记均缺少可用浏览量，未对收藏价值作负面评分。",
                (
                    "Imported notes have no usable view counts, so save value was not scored "
                    "negatively."
                ),
            ),
            available=False,
        )
    save_rate = total_collects / total_views
    ranked = sorted(
        samples,
        key=lambda sample: (
            -(sample.collects / sample.views) if sample.views else 0.0,
            -sample.collects,
            str(getattr(sample.note, "note_id", "")),
        ),
    )
    top_ids = tuple(
        str(sample.note.note_id)
        for sample in ranked[:3]
        if str(getattr(sample.note, "note_id", "")).strip()
    )
    bottom_ranked = sorted(
        samples,
        key=lambda sample: (
            sample.collects / sample.views if sample.views else 0.0,
            sample.collects,
            str(getattr(sample.note, "note_id", "")),
        ),
    )
    bottom_ids = tuple(
        str(sample.note.note_id)
        for sample in bottom_ranked[:3]
        if str(getattr(sample.note, "note_id", "")).strip()
    )
    return _DimensionMetrics(
        score=_clamp_score(save_rate / _SAVE_VALUE_SCORE_TARGET * 100),
        evidence=_copy(
            locale,
            (
                f"全量历史累计 {total_collects} 次收藏、{total_views} 次浏览，"
                f"平均收藏率为 {_format_percent(save_rate)}。"
            ),
            (
                f"Across all imported history there are {total_collects} saves and "
                f"{total_views} views; "
                f"the average save rate is {_format_percent(save_rate)}."
            ),
        ),
        top_note_ids=top_ids,
        bottom_note_ids=bottom_ids,
    )


def _title_craft_dimension(
    samples: list[_RateSample], locale: QualityReportLocale
) -> _DimensionMetrics:
    title_samples = [sample for sample in samples if _title_text(sample.note)]
    if not samples:
        return _DimensionMetrics(
            score=0.0,
            evidence=_copy(
                locale,
                "尚无已导入笔记，无法计算标题表达信号。",
                "No imported notes are available to calculate title-craft signals.",
            ),
            available=False,
        )
    if not title_samples:
        return _DimensionMetrics(
            score=0.0,
            evidence=_copy(
                locale,
                "未导入可分析标题；未对标题或缺失的正文片段作负面评分。",
                (
                    "No analyzable titles were imported; missing titles or body snippets were "
                    "not scored negatively."
                ),
            ),
            available=False,
        )

    readable = [sample for sample in title_samples if _is_readable_title(_title_text(sample.note))]
    hooked = [sample for sample in title_samples if _has_title_hook(_title_text(sample.note))]
    readable_ratio = len(readable) / len(title_samples)
    hook_ratio = len(hooked) / len(title_samples)
    score = _clamp_score((readable_ratio * 0.55 + hook_ratio * 0.45) * 100)
    top_ids = tuple(
        sorted(
            str(sample.note.note_id)
            for sample in hooked
            if str(getattr(sample.note, "note_id", "")).strip()
        )[:3]
    )
    bottom_ids = tuple(
        sorted(
            str(sample.note.note_id)
            for sample in title_samples
            if not _has_title_hook(_title_text(sample.note))
            and str(getattr(sample.note, "note_id", "")).strip()
        )[:3]
    )
    return _DimensionMetrics(
        score=score,
        evidence=_copy(
            locale,
            (
                f"已导入标题覆盖 {len(title_samples)}/{len(samples)} 篇；其中 "
                f"{len(readable)}/{len(title_samples)} 篇长度可读，"
                f"{len(hooked)}/{len(title_samples)} 篇含可识别的标题钩子。"
            ),
            (
                f"Titles are available for {len(title_samples)}/{len(samples)} imported notes; "
                f"{len(readable)}/{len(title_samples)} have a readable length and "
                f"{len(hooked)}/{len(title_samples)} contain a recognizable title hook."
            ),
        ),
        top_note_ids=top_ids,
        bottom_note_ids=bottom_ids,
    )


def _consistency_dimension(
    samples: list[_RateSample], locale: QualityReportLocale
) -> _DimensionMetrics:
    if not samples:
        return _DimensionMetrics(
            score=0.0,
            evidence=_copy(
                locale,
                "尚无已导入笔记，无法计算表现稳定性。",
                "No imported notes are available to calculate performance consistency.",
            ),
            available=False,
        )
    if len(samples) < 2:
        return _DimensionMetrics(
            score=0.0,
            evidence=_copy(
                locale,
                "当前历史样本不足 2 篇，无法判断表现稳定性。",
                (
                    "Fewer than two historical notes are available, so performance consistency "
                    "cannot be assessed."
                ),
            ),
            available=False,
        )

    rates = [sample.engagement_rate for sample in samples]
    average = sum(rates) / len(rates)
    nonzero_count = sum(rate > 0 for rate in rates)
    if average <= 0:
        return _DimensionMetrics(
            score=0.0,
            evidence=_copy(
                locale,
                (f"{len(samples)} 篇历史笔记的互动率均为 0，目前没有可验证的稳定互动信号。"),
                (
                    f"All {len(samples)} imported historical notes have a 0 engagement rate; "
                    "there is no verified stable engagement signal yet."
                ),
            ),
            top_note_ids=_top_note_ids(samples),
            bottom_note_ids=_bottom_note_ids(samples),
        )

    variance = sum((rate - average) ** 2 for rate in rates) / len(rates)
    relative_spread = math.sqrt(variance) / average
    spread_score = max(0.0, 100.0 - min(100.0, relative_spread * 50.0))
    nonzero_score = nonzero_count / len(samples) * 100.0
    score = _clamp_score(spread_score * 0.65 + nonzero_score * 0.35)
    return _DimensionMetrics(
        score=score,
        evidence=_copy(
            locale,
            (
                f"全量历史平均互动率 {_format_percent(average)}，"
                f"非零互动覆盖 {nonzero_count}/{len(samples)} 篇，"
                f"相对波动为 {relative_spread:.2f}。"
            ),
            (
                "Across all imported history, the average engagement rate is "
                f"{_format_percent(average)}; non-zero engagement covers "
                f"{nonzero_count}/{len(samples)} notes, with relative variation "
                f"of {relative_spread:.2f}."
            ),
        ),
        top_note_ids=_top_note_ids(samples),
        bottom_note_ids=_bottom_note_ids(samples),
    )


def _dimension_metrics(
    samples: list[_RateSample], locale: QualityReportLocale
) -> dict[QualityDimensionKey, _DimensionMetrics]:
    return {
        "engagement": _engagement_dimension(samples, locale),
        "save_value": _save_value_dimension(samples, locale),
        "title_craft": _title_craft_dimension(samples, locale),
        "consistency": _consistency_dimension(samples, locale),
    }


def _as_dimensions(
    metrics: dict[QualityDimensionKey, _DimensionMetrics],
) -> list[QualityDimension]:
    return [
        QualityDimension(
            key=key,
            score=metrics[key].score,
            evidence=metrics[key].evidence,
            available=metrics[key].available,
        )
        for key in _DIMENSION_ORDER
    ]


def _overall_score(metrics: dict[QualityDimensionKey, _DimensionMetrics]) -> float:
    usable = [key for key in _DIMENSION_ORDER if metrics[key].available]
    if not usable:
        return 0.0
    weight_total = sum(_DIMENSION_WEIGHTS[key] for key in usable)
    weighted = sum(metrics[key].score * _DIMENSION_WEIGHTS[key] for key in usable)
    return _clamp_score(weighted / weight_total)


def _grade_for(score: float) -> QualityGrade:
    if score >= 70:
        return "strong"
    if score >= 45:
        return "developing"
    return "needs_attention"


def _confidence_for(note_count: int) -> QualityConfidence:
    if note_count >= 10:
        return "high"
    if note_count >= MIN_NOTES_FOR_OVERALL_SCORE:
        return "medium"
    return "low"


_STRENGTH_TITLES: dict[QualityDimensionKey, str] = {
    "engagement": "互动信号表现较好",
    "save_value": "收藏价值表现较好",
    "title_craft": "标题表达表现较好",
    "consistency": "表现稳定性较好",
}
_STRENGTH_TITLES_EN: dict[QualityDimensionKey, str] = {
    "engagement": "Engagement signals are relatively strong",
    "save_value": "Save value is relatively strong",
    "title_craft": "Title craft is relatively strong",
    "consistency": "Performance consistency is relatively strong",
}
_WEAKNESS_TITLES: dict[QualityDimensionKey, str] = {
    "engagement": "互动信号有提升空间",
    "save_value": "收藏价值有提升空间",
    "title_craft": "标题钩子覆盖有提升空间",
    "consistency": "表现稳定性有提升空间",
}
_WEAKNESS_TITLES_EN: dict[QualityDimensionKey, str] = {
    "engagement": "Engagement signals have room to improve",
    "save_value": "Save value has room to improve",
    "title_craft": "Title-hook coverage has room to improve",
    "consistency": "Performance consistency has room to improve",
}


def _strengths_and_weaknesses(
    metrics: dict[QualityDimensionKey, _DimensionMetrics],
    locale: QualityReportLocale,
) -> tuple[list[QualityInsight], list[QualityInsight]]:
    usable = [key for key in _DIMENSION_ORDER if metrics[key].available]
    ranked_high = sorted(usable, key=lambda key: (-metrics[key].score, key))
    ranked_low = sorted(usable, key=lambda key: (metrics[key].score, key))

    strength_keys = [key for key in ranked_high if metrics[key].score >= 65][:2]
    if not strength_keys and ranked_high and metrics[ranked_high[0]].score > 0:
        # Even a developing account benefits from seeing its strongest relative
        # signal, but do not invent a strength when every observed score is 0.
        strength_keys = ranked_high[:1]
    weakness_keys = [key for key in ranked_low if metrics[key].score < 55][:2]
    strength_titles = _STRENGTH_TITLES_EN if locale == "en" else _STRENGTH_TITLES
    weakness_titles = _WEAKNESS_TITLES_EN if locale == "en" else _WEAKNESS_TITLES

    strengths = [
        QualityInsight(
            dimension=key,
            title=strength_titles[key],
            evidence=metrics[key].evidence,
            related_note_ids=list(metrics[key].top_note_ids),
        )
        for key in strength_keys
    ]
    weaknesses = [
        QualityInsight(
            dimension=key,
            title=weakness_titles[key],
            evidence=metrics[key].evidence,
            related_note_ids=list(metrics[key].bottom_note_ids),
        )
        for key in weakness_keys
    ]
    return strengths, weaknesses


def _recommendation_for(
    key: QualityDimensionKey,
    metrics: _DimensionMetrics,
    priority: int,
    locale: QualityReportLocale,
) -> QualityRecommendation:
    if key == "engagement":
        return QualityRecommendation(
            priority=priority,
            dimension=key,
            title=_copy(
                locale,
                "提高首轮互动引导",
                "Strengthen first-round engagement prompts",
            ),
            advice=_copy(
                locale,
                "下一篇优先复用高互动历史笔记的选题或标题结构，并加入明确的评论互动引导。",
                (
                    "Reuse the topic or title structure of high-engagement historical notes in "
                    "the next post, and add a clear prompt for comments."
                ),
            ),
            evidence=metrics.evidence,
            related_note_ids=list(metrics.top_note_ids or metrics.bottom_note_ids),
        )
    if key == "save_value":
        return QualityRecommendation(
            priority=priority,
            dimension=key,
            title=_copy(
                locale,
                "增强可保存的信息密度",
                "Increase save-worthy information density",
            ),
            advice=_copy(
                locale,
                "将步骤、清单、对比或可复用结论前置，让读者有明确的收藏理由。",
                (
                    "Lead with steps, checklists, comparisons, or reusable conclusions so "
                    "readers have a clear reason to save the post."
                ),
            ),
            evidence=metrics.evidence,
            related_note_ids=list(metrics.top_note_ids or metrics.bottom_note_ids),
        )
    if key == "title_craft":
        return QualityRecommendation(
            priority=priority,
            dimension=key,
            title=_copy(
                locale,
                "提高标题钩子覆盖",
                "Increase title-hook coverage",
            ),
            advice=_copy(
                locale,
                "保持可读标题长度，并在下一篇尝试数字、问题、对比或清单中的一种明确钩子。",
                (
                    "Keep titles readable and try one clear hook in the next post: a number, "
                    "question, comparison, or checklist."
                ),
            ),
            evidence=metrics.evidence,
            related_note_ids=list(metrics.top_note_ids or metrics.bottom_note_ids),
        )
    return QualityRecommendation(
        priority=priority,
        dimension=key,
        title=_copy(locale, "收敛高低表现差异", "Reduce performance swings"),
        advice=_copy(
            locale,
            "以高互动历史笔记的选题和标题结构作为下一轮基线，减少同时改变多个创作变量。",
            (
                "Use the topic and title structure of high-engagement historical notes as the "
                "next baseline, changing fewer creative variables at once."
            ),
        ),
        evidence=metrics.evidence,
        related_note_ids=list(metrics.top_note_ids or metrics.bottom_note_ids),
    )


def _recommendations(
    metrics: dict[QualityDimensionKey, _DimensionMetrics],
    weaknesses: list[QualityInsight],
    locale: QualityReportLocale,
) -> list[QualityRecommendation]:
    keys: list[QualityDimensionKey] = []
    for insight in weaknesses:
        for key in _DIMENSION_ORDER:
            if insight.dimension == key and metrics[key].available:
                keys.append(key)
                break
    if not keys:
        # A strong report should still have a concrete next-post action.  Use
        # the lowest available signal without claiming it is a failure.
        keys = [
            key
            for key in sorted(
                (key for key in _DIMENSION_ORDER if metrics[key].available),
                key=lambda key: (metrics[key].score, key),
            )[:1]
        ]
    return [
        _recommendation_for(key, metrics[key], priority, locale)
        for priority, key in enumerate(keys[:3], start=1)
    ]


def _low_data_recommendation(note_count: int, locale: QualityReportLocale) -> QualityRecommendation:
    return QualityRecommendation(
        priority=1,
        dimension="data_collection",
        title=_copy(
            locale,
            "先积累可比较的历史样本",
            "Build a comparable historical sample first",
        ),
        advice=_copy(
            locale,
            "继续通过已绑定浏览器导入真实创作者中心历史笔记；积累至少 3 篇后再生成整体质量评分。",
            (
                "Continue importing real Creator Center history through the bound browser; "
                "collect at least three notes before generating an overall quality score."
            ),
        ),
        evidence=_copy(
            locale,
            f"当前仅有 {note_count} 篇已导入历史笔记，未达到整体评分所需的最小样本量。",
            (
                f"Only {note_count} imported historical notes are available, below the "
                "minimum sample size for an overall score."
            ),
        ),
    )


def _single_note_data_recommendation(
    note: NoteStats, locale: QualityReportLocale
) -> QualityRecommendation:
    """Explain why a single note has no scorable imported signal."""
    return QualityRecommendation(
        priority=1,
        dimension="data_collection",
        title=_copy(locale, "补充笔记表现数据", "Import more note-performance signals"),
        advice=_copy(
            locale,
            "该笔记缺少可用的浏览、互动或标题信号；请刷新创作者中心导入后再评估。",
            (
                "This note has no usable view, interaction, or title signal; refresh the "
                "Creator Center import before evaluating it again."
            ),
        ),
        evidence=_copy(
            locale,
            "当前没有足够的已导入字段生成单篇质量分。",
            "There are not enough imported fields to generate a single-note quality score.",
        ),
        related_note_ids=[note.note_id] if note.note_id else [],
    )


def analyze_historical_quality(
    notes: list[NoteStats], account_id: str, *, locale: str = "zh-CN"
) -> CreatorQualityReport:
    """Build one deterministic report from all supplied durable note rows.

    The function is intentionally I/O-free and never mutates ``notes``.  The
    route is responsible for passing the account's complete persisted history.
    """
    normalized_account_id = (account_id or "").strip()
    report_locale = _normalize_locale(locale)
    samples = _rate_samples(list(notes))
    note_count = len(samples)
    metrics = _dimension_metrics(samples, report_locale)
    dimensions = _as_dimensions(metrics)
    insufficient_data = note_count < MIN_NOTES_FOR_OVERALL_SCORE
    cold_start = note_count == 0

    if insufficient_data:
        if cold_start:
            summary = _copy(
                report_locale,
                "尚未检测到已导入的历史笔记。该报告只分析本地持久化的创作者中心数据；请先完成浏览器导入。",
                (
                    "No imported historical notes were found. This report only analyzes durable "
                    "local Creator Center data; complete a browser import first."
                ),
            )
        else:
            summary = _copy(
                report_locale,
                (
                    f"当前仅有 {note_count} 篇已导入历史笔记，样本不足以给出整体创作质量评分；"
                    "已保留全量历史范围，建议继续积累真实数据。"
                ),
                (
                    f"Only {note_count} imported historical notes are available, which is too "
                    "little for an overall creative-quality score. The full history remains in "
                    "scope; continue collecting real data."
                ),
            )
        return CreatorQualityReport(
            account_id=normalized_account_id,
            total_notes=note_count,
            notes_analyzed=note_count,
            scope=SCOPE_ALL_IMPORTED_HISTORY,
            overall_score=None,
            grade="insufficient_data",
            confidence="low",
            summary=summary,
            dimensions=dimensions,
            strengths=[],
            weaknesses=[],
            recommendations=[_low_data_recommendation(note_count, report_locale)],
            cold_start=cold_start,
            insufficient_data=True,
        )

    score = _overall_score(metrics)
    grade = _grade_for(score)
    confidence = _confidence_for(note_count)
    engagement_evidence = metrics["engagement"].evidence
    save_evidence = metrics["save_value"].evidence
    strengths, weaknesses = _strengths_and_weaknesses(metrics, report_locale)
    return CreatorQualityReport(
        account_id=normalized_account_id,
        total_notes=note_count,
        notes_analyzed=note_count,
        scope=SCOPE_ALL_IMPORTED_HISTORY,
        overall_score=score,
        grade=grade,
        confidence=confidence,
        summary=_copy(
            report_locale,
            (
                f"基于全部 {note_count} 篇已导入历史笔记，整体创作质量处于「{grade}」区间"
                f"（{score:.1f}/100，{confidence} 置信度）。{engagement_evidence}{save_evidence}"
                "评分仅覆盖互动、收藏、标题和表现稳定性，不评判未导入的视觉或正文质量。"
            ),
            (
                f"Based on all {note_count} imported historical notes, overall creative quality "
                f"is in the “{grade}” range ({score:.1f}/100, {confidence} confidence). "
                f"{engagement_evidence} {save_evidence} "
                "This score covers engagement, saves, titles, and performance consistency only; "
                "it does not judge visual or body quality that was not imported."
            ),
        ),
        dimensions=dimensions,
        strengths=strengths,
        weaknesses=weaknesses,
        recommendations=_recommendations(metrics, weaknesses, report_locale),
        cold_start=False,
        insufficient_data=False,
    )


def analyze_note_quality(
    note: NoteStats, account_id: str, *, locale: str = "zh-CN"
) -> CreatorQualityReport:
    """Build a transparent quality signal for one imported historical note.

    This deliberately reuses the historical analyzer's normalization,
    dimension heuristics, evidence, and recommendations.  Cross-note
    consistency is marked unavailable rather than inferred from one sample.
    The returned report is read-only and never mutates ``note``.
    """
    normalized_account_id = (account_id or note.account_id or "").strip()
    report_locale = _normalize_locale(locale)
    samples = _rate_samples([note])
    metrics = _dimension_metrics(samples, report_locale)
    dimensions = _as_dimensions(metrics)
    interactions = sum(
        _nonnegative_int(getattr(note, field, 0))
        for field in ("likes", "comments", "collects", "shares")
    )
    engagement_signal = bool(
        _nonnegative_int(getattr(note, "views", 0))
        or interactions
        or _normalized_note_rate(note) > 0
    )
    usable = [
        key
        for key in _DIMENSION_ORDER
        if metrics[key].available and (key != "engagement" or engagement_signal)
    ]
    note_id = str(note.note_id or "").strip()

    if not usable:
        return CreatorQualityReport(
            account_id=normalized_account_id,
            note_id=note_id,
            total_notes=1,
            notes_analyzed=1,
            scope=SCOPE_SINGLE_IMPORTED_NOTE,
            overall_score=None,
            grade="insufficient_data",
            confidence="low",
            summary=_copy(
                report_locale,
                "该篇历史笔记缺少可用的已导入指标，暂时无法生成质量分。",
                "This historical note has no usable imported signals for a quality score yet.",
            ),
            dimensions=dimensions,
            strengths=[],
            weaknesses=[],
            recommendations=[_single_note_data_recommendation(note, report_locale)],
            cold_start=False,
            insufficient_data=True,
        )

    score = _overall_score(metrics)
    strengths, weaknesses = _strengths_and_weaknesses(metrics, report_locale)
    title = (note.title or "").strip()
    note_label_zh = f"「{title}」" if title else f"（{note_id or '未命名笔记'}）"
    note_label_en = f'“{title}”' if title else f"({note_id or 'untitled note'})"
    score_summary = _copy(
        report_locale,
        (
            f"基于单篇已导入历史笔记{note_label_zh}"
            f"的可用信号，当前质量分为 {score:.1f}/100，置信度为 low。"
            "该结果只覆盖互动、收藏和标题信号；表现稳定性需要跨笔记样本。"
        ),
        (
            f"Based on the available signals for the single imported note "
            f"{note_label_en}, "
            f"the quality signal is {score:.1f}/100 with low confidence. "
            "It covers engagement, saves, and title signals only; consistency requires "
            "multiple notes."
        ),
    )
    return CreatorQualityReport(
        account_id=normalized_account_id,
        note_id=note_id,
        total_notes=1,
        notes_analyzed=1,
        scope=SCOPE_SINGLE_IMPORTED_NOTE,
        overall_score=score,
        grade=_grade_for(score),
        confidence="low",
        summary=score_summary,
        dimensions=dimensions,
        strengths=strengths,
        weaknesses=weaknesses,
        recommendations=_recommendations(metrics, weaknesses, report_locale),
        cold_start=False,
        insufficient_data=False,
    )
