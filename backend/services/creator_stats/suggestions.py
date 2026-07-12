"""Creative suggestions for all workflow modes: trend | brief | free.

Shared recall surface — modes do not keep separate suggestion silos.
"""

from __future__ import annotations

from typing import Any

from langgraph.store.base import BaseStore

from backend.memory.creative import CreativeMemory
from backend.services.creator_stats.types import (
    AnalysisResult,
    CreativeMode,
    CreativeSuggestion,
    NoteStats,
    StyleFinding,
)

_MODES: tuple[CreativeMode, ...] = ("trend", "brief", "free")


def _normalize_mode(mode: str | None) -> CreativeMode:
    """Coerce unknown modes to ``trend`` so cold-start never KeyErrors.

    Case/whitespace insensitive: ``FREE`` / `` Brief `` → free / brief.
    """
    if mode is None:
        return "trend"
    m = str(mode).strip().lower()
    if m in _MODES:
        return m
    return "trend"


def _cold_start_suggestions(mode: CreativeMode) -> list[CreativeSuggestion]:
    """Defined empty/cold-start result when no imported data exists."""
    mode = _normalize_mode(mode)
    base = CreativeSuggestion(
        mode=mode,
        category="cold_start",
        title="暂无创作中心数据",
        advice=(
            "尚未导入创作者中心统计数据。请先同步 "
            "creator.xiaohongshu.com/statistics/account/v2 的账户/笔记数据，"
            "再获取基于真实表现的创作建议。"
        ),
        priority=0,
        evidence="no_imported_stats",
    )
    mode_hint: dict[CreativeMode, CreativeSuggestion] = {
        "trend": CreativeSuggestion(
            mode="trend",
            category="cold_start",
            title="趋势模式冷启动",
            advice="趋势模式下可先用赛道默认热词选题；导入数据后会叠加高互动话题偏好。",
            priority=1,
            evidence="cold_start",
        ),
        "brief": CreativeSuggestion(
            mode="brief",
            category="cold_start",
            title="Brief 模式冷启动",
            advice="Brief 模式下先对齐品牌卖点与受众；导入数据后会推荐历史高转化语气与标题公式。",
            priority=1,
            evidence="cold_start",
        ),
        "free": CreativeSuggestion(
            mode="free",
            category="cold_start",
            title="自由创作冷启动",
            advice="自由创作可先按默认风格起草；导入数据后会注入账户专属风格指纹与爆款标题参考。",
            priority=1,
            evidence="cold_start",
        ),
    }
    return [base, mode_hint[mode]]


def _finding_map(findings: list[StyleFinding]) -> dict[str, StyleFinding]:
    return {f.finding_type: f for f in findings}


def suggestions_from_analysis(
    analysis: AnalysisResult,
    notes: list[NoteStats] | None = None,
    *,
    mode: CreativeMode | None = None,
) -> dict[str, list[CreativeSuggestion]]:
    """Build structured suggestions for one or all modes from analysis findings."""
    if mode is not None:
        modes: tuple[CreativeMode, ...] = (_normalize_mode(mode),)
    else:
        modes = _MODES
    if analysis.cold_start or analysis.note_count == 0:
        return {m: _cold_start_suggestions(m) for m in modes}

    fm = _finding_map(analysis.findings)
    top_notes = notes or []
    ranked = sorted(top_notes, key=lambda x: x.engagement_rate, reverse=True)[:3]
    best_titles = [n.title for n in ranked if n.title]
    if not best_titles and fm.get("best_note"):
        best_titles = [fm["best_note"].label]

    out: dict[str, list[CreativeSuggestion]] = {}
    for m in modes:
        items: list[CreativeSuggestion] = []

        if "tone" in fm:
            f = fm["tone"]
            items.append(
                CreativeSuggestion(
                    mode=m,
                    category="style",
                    title=f"沿用高互动语气「{f.label}」",
                    advice=(f"基于导入笔记表现，优先使用「{f.label}」文风。{f.evidence}"),
                    priority=1,
                    evidence=f.evidence,
                    related_note_ids=list(f.note_ids),
                )
            )

        if "topic" in fm:
            f = fm["topic"]
            if m == "trend":
                advice = (
                    f"趋势选题优先贴近高表现话题「{f.label}」，并与当前热搜交叉验证。{f.evidence}"
                )
            elif m == "brief":
                advice = (
                    f"Brief 内容方向尽量挂靠历史高表现话题「{f.label}」，"
                    f"将品牌卖点包装进该话题语境。{f.evidence}"
                )
            else:
                advice = (
                    f"自由创作可从话题「{f.label}」切入，该话题在你账号上互动更稳。{f.evidence}"
                )
            items.append(
                CreativeSuggestion(
                    mode=m,
                    category="topic",
                    title=f"话题偏好：{f.label}",
                    advice=advice,
                    priority=2,
                    evidence=f.evidence,
                    related_note_ids=list(f.note_ids),
                )
            )

        if "format" in fm:
            f = fm["format"]
            items.append(
                CreativeSuggestion(
                    mode=m,
                    category="format",
                    title=f"优先内容形态：{f.label}",
                    advice=f"历史数据表明「{f.label}」形态平均互动更高。{f.evidence}",
                    priority=3,
                    evidence=f.evidence,
                    related_note_ids=list(f.note_ids),
                )
            )

        if "title_formula" in fm:
            f = fm["title_formula"]
            items.append(
                CreativeSuggestion(
                    mode=m,
                    category="style",
                    title=f"标题公式：{f.label}",
                    advice=(
                        f"高互动标题多用「{f.label}」。"
                        + (f" 参考：{' / '.join(best_titles[:2])}" if best_titles else "")
                    ),
                    priority=2,
                    evidence=f.evidence,
                    related_note_ids=list(f.note_ids),
                )
            )

        if "best_note" in fm:
            f = fm["best_note"]
            items.append(
                CreativeSuggestion(
                    mode=m,
                    category="style",
                    title="复用最佳笔记结构",
                    advice=f"{f.evidence}。创作时可模仿其标题钩子与信息密度。",
                    priority=4,
                    evidence=f.evidence,
                    related_note_ids=list(f.note_ids),
                )
            )

        # Mode-specific closing tip with real metrics (never dummy 示例 only)
        items.append(
            CreativeSuggestion(
                mode=m,
                category="timing",
                title=f"{m} 模式数据摘要",
                advice=(
                    f"账户 {analysis.account_id} 已分析 {analysis.note_count} 篇导入笔记，"
                    f"平均互动率 {analysis.avg_engagement_rate:.2%}。"
                    + (
                        f" Top 笔记：{', '.join(analysis.top_note_ids[:3])}。"
                        if analysis.top_note_ids
                        else ""
                    )
                ),
                priority=5,
                evidence=f"notes={analysis.note_count};avg_er={analysis.avg_engagement_rate}",
                related_note_ids=list(analysis.top_note_ids[:5]),
            )
        )

        out[m] = items
    return out


async def get_suggestions_for_mode(
    account_id: str,
    mode: CreativeMode,
    *,
    store: BaseStore | None = None,
    notes: list[NoteStats] | None = None,
    analysis: AnalysisResult | None = None,
) -> list[CreativeSuggestion]:
    """Entry used by agents/API: account-scoped advice for one creative mode."""
    from backend.db import creator_stats as stats_db
    from backend.services.creator_stats.analyze import analyze_notes

    mode = _normalize_mode(mode)

    if analysis is None:
        loaded = notes
        if loaded is None:
            loaded = await stats_db.list_note_stats(account_id, limit=100)
        analysis = analyze_notes(loaded, account_id)
        notes = loaded

    result = suggestions_from_analysis(analysis, notes, mode=mode)
    suggestions = result.get(mode, [])

    # Enrich with CreativeMemory (durable DB always; store optional for semantic)
    if not analysis.cold_start:
        try:
            cm = CreativeMemory(account_id, store=store)
            styles = await cm.recall_style(query="creator stats style", limit=2)
            non_default = [
                s for s in styles if not str(s.get("style_id", "")).startswith("default_")
            ]
            if non_default:
                s0 = non_default[0]
                suggestions.insert(
                    0,
                    CreativeSuggestion(
                        mode=mode,
                        category="style",
                        title=f"记忆中的风格指纹：{s0.get('tone', '')}",
                        advice=(
                            f"召回账户风格 DNA：文风={s0.get('tone')} "
                            f"视觉={s0.get('visual_style')} "
                            f"互动率={s0.get('engagement_rate', 0)} "
                            f"采样={s0.get('sample_count', 0)}"
                        ),
                        priority=0,
                        evidence=f"style_id={s0.get('style_id')}",
                    ),
                )
        except Exception:
            pass
    return suggestions


def format_suggestions_context(suggestions: list[CreativeSuggestion]) -> str:
    """Render suggestions as LLM-consumable context text."""
    if not suggestions:
        return ""
    lines = ["创作数据建议（来自创作者中心导入分析）："]
    for s in suggestions[:6]:
        lines.append(f"- [{s.category}] {s.title}: {s.advice}")
    return "\n".join(lines)


async def build_mode_creative_context(
    account_id: str,
    mode: CreativeMode,
    store: BaseStore | None = None,
) -> str:
    """Shared entry for trend/brief/free to inject creator-stats advice into prompts."""
    suggestions = await get_suggestions_for_mode(account_id, mode, store=store)
    return format_suggestions_context(suggestions)


def suggestions_to_dicts(
    suggestions: dict[str, list[CreativeSuggestion]] | list[CreativeSuggestion],
) -> Any:
    if isinstance(suggestions, list):
        return [s.to_dict() for s in suggestions]
    return {k: [s.to_dict() for s in v] for k, v in suggestions.items()}
