"""Creative analysis over persisted note stats → style DNA / memory deposits.

Pure analysis helpers are I/O-free; deposit_from_notes talks to CreativeMemory.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter

from langgraph.store.base import BaseStore

from backend.memory.creative import CreativeMemory
from backend.memory.types import ConversionPlay, MaterialEntry, StyleDNA
from backend.services.creator_stats.types import (
    AnalysisResult,
    NoteStats,
    StyleFinding,
)

logger = logging.getLogger("xhs_growth.creator_stats.analyze")

# Lightweight title/tone heuristics — no LLM required for fixture-driven path
_TONE_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("治愈", re.compile(r"治愈|温暖|慢慢|安心|陪伴|温柔"), "温暖治愈"),
    ("活泼", re.compile(r"绝绝子|姐妹|哈哈|冲|快乐|宝藏|必入"), "活力青春"),
    ("专业", re.compile(r"方法|步骤|测评|对比|指南|干货|清单"), "现代简约"),
    ("犀利", re.compile(r"避雷|踩坑|别买|真相|内幕|割韭菜"), "高冷高级"),
]

# Prefer specific hooks — bare "一" alone matches almost every Chinese title.
_TITLE_HOOK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("数字+痛点", re.compile(r"\d+\s*[个条步点种]|[二三四五六七八九十]个")),
    ("疑问钩子", re.compile(r"[？?]|为什么|怎么|如何|有没有")),
    ("对比反差", re.compile(r"vs|对比|前后|之前|之后|从.+到")),
    ("清单干货", re.compile(r"清单|合集|推荐|种草|避雷|干货")),
]


def _infer_tone(text: str) -> tuple[str, str]:
    for tone, pattern, visual in _TONE_PATTERNS:
        if pattern.search(text or ""):
            return tone, visual
    return "治愈", "温暖治愈"


def _infer_title_formula(text: str) -> str:
    for label, pattern in _TITLE_HOOK_PATTERNS:
        if pattern.search(text or ""):
            return label
    return "叙事种草"


def _infer_tone_from_note(note: NoteStats) -> tuple[str, str]:
    """Title patterns win; if title has no signal, fall back to body_text."""
    title = (note.title or "").strip()
    for tone, pattern, visual in _TONE_PATTERNS:
        if pattern.search(title):
            return tone, visual
    body = (getattr(note, "body_text", None) or "").strip()
    if body:
        for tone, pattern, visual in _TONE_PATTERNS:
            if pattern.search(body):
                return tone, visual
    return "治愈", "温暖治愈"


def _infer_title_formula_from_note(note: NoteStats) -> str:
    title = (note.title or "").strip()
    for label, pattern in _TITLE_HOOK_PATTERNS:
        if pattern.search(title):
            return label
    body = (getattr(note, "body_text", None) or "").strip()
    if body:
        for label, pattern in _TITLE_HOOK_PATTERNS:
            if pattern.search(body):
                return label
    return "叙事种草"


def _top_tags(notes: list[NoteStats], limit: int = 5) -> list[tuple[str, int]]:
    """Count notes that carry each tag (not raw tag-list multiplicity).

    Per-note tag de-dupe avoids API payloads like ``["母婴","母婴","母婴"]``
    inflating frequency and crowding out real topics.
    """
    counter: Counter[str] = Counter()
    for n in notes:
        seen: set[str] = set()
        for t in n.tags or []:
            if not t or t in seen:
                continue
            seen.add(t)
            counter[t] += 1
    return counter.most_common(limit)


def _content_type_dist(notes: list[NoteStats]) -> Counter[str]:
    return Counter(n.content_type or "note" for n in notes)


def as_fraction_engagement_rate(rate: float | int | None) -> float:
    """Normalize engagement to 0–1 fraction.

    Import path recompute yields fractions (e.g. 0.1571). Legacy / hand-built
    rows may store percent-scale values (e.g. 15.71). Rates ``> 1`` are treated
    as percent and divided by 100 so averages and ``:.2%`` formatting stay sane.
    """
    if rate is None:
        return 0.0
    try:
        r = float(rate)
    except (TypeError, ValueError):
        return 0.0
    if r < 0:
        return 0.0
    if r > 1.0:
        return round(min(r / 100.0, 1.0), 4)
    return round(r, 4)


def _normalize_note_rates(notes: list[NoteStats]) -> list[NoteStats]:
    """Return notes with engagement_rate coerced to 0–1 (mutates copies lightly)."""
    out: list[NoteStats] = []
    for n in notes:
        frac = as_fraction_engagement_rate(n.engagement_rate)
        if frac != n.engagement_rate:
            n.engagement_rate = frac
        out.append(n)
    return out


def analyze_notes(notes: list[NoteStats], account_id: str) -> AnalysisResult:
    """Produce data-backed style findings from note stats (pure function)."""
    if not notes:
        return AnalysisResult(account_id=account_id, cold_start=True, note_count=0)

    notes = _normalize_note_rates(list(notes))
    sorted_notes = sorted(notes, key=lambda n: n.engagement_rate, reverse=True)
    rates = [n.engagement_rate for n in notes]
    avg_rate = round(sum(rates) / len(rates), 4) if rates else 0.0
    top = sorted_notes[: min(5, len(sorted_notes))]
    top_ids = [n.note_id for n in top]

    findings: list[StyleFinding] = []

    # Tone pattern from high performers
    tone_counter: Counter[str] = Counter()
    tone_evidence: dict[str, list[str]] = {}
    for n in top:
        tone, _ = _infer_tone_from_note(n)
        tone_counter[tone] += 1
        tone_evidence.setdefault(tone, []).append(n.note_id)
    if tone_counter:
        best_tone, count = tone_counter.most_common(1)[0]
        top_with_tone = [n for n in top if _infer_tone_from_note(n)[0] == best_tone]
        avg_top = (
            round(sum(n.engagement_rate for n in top_with_tone) / len(top_with_tone), 4)
            if top_with_tone
            else avg_rate
        )
        findings.append(
            StyleFinding(
                finding_type="tone",
                label=best_tone,
                evidence=(
                    f"高互动笔记中「{best_tone}」语气出现 {count} 次，平均互动率 {avg_top:.2%}"
                ),
                score=avg_top,
                sample_count=count,
                note_ids=tone_evidence.get(best_tone, [])[:5],
            )
        )

    # Topic/tag patterns — pick highest avg engagement (not merely most frequent)
    tag_counts = _top_tags(notes, limit=10)
    if tag_counts:
        best_tag = ""
        best_tag_rate = -1.0
        best_tag_notes: list[NoteStats] = []
        for tag, _cnt in tag_counts:
            tag_notes = [n for n in notes if tag in (n.tags or [])]
            if not tag_notes:
                continue
            tag_rate = round(sum(n.engagement_rate for n in tag_notes) / len(tag_notes), 4)
            # Prefer higher rate; break ties by sample count
            if tag_rate > best_tag_rate or (
                tag_rate == best_tag_rate and len(tag_notes) > len(best_tag_notes)
            ):
                best_tag, best_tag_rate, best_tag_notes = tag, tag_rate, tag_notes
        if best_tag:
            findings.append(
                StyleFinding(
                    finding_type="topic",
                    label=best_tag,
                    evidence=(
                        f"话题「{best_tag}」覆盖 {len(best_tag_notes)} 篇笔记，"
                        f"平均互动率 {best_tag_rate:.2%}"
                    ),
                    score=best_tag_rate,
                    sample_count=len(best_tag_notes),
                    note_ids=[n.note_id for n in best_tag_notes[:5]],
                )
            )

    # Format / content type — prefer form with best avg engagement
    type_dist = _content_type_dist(notes)
    if type_dist:
        best_ctype = ""
        best_type_rate = -1.0
        best_type_notes: list[NoteStats] = []
        for ctype in type_dist:
            type_notes = [n for n in notes if (n.content_type or "note") == ctype]
            if not type_notes:
                continue
            type_rate = round(sum(n.engagement_rate for n in type_notes) / len(type_notes), 4)
            if type_rate > best_type_rate or (
                type_rate == best_type_rate and len(type_notes) > len(best_type_notes)
            ):
                best_ctype, best_type_rate, best_type_notes = ctype, type_rate, type_notes
        if best_ctype:
            findings.append(
                StyleFinding(
                    finding_type="format",
                    label=best_ctype,
                    evidence=(
                        f"内容形态「{best_ctype}」共 {len(best_type_notes)} 篇，"
                        f"平均互动率 {best_type_rate:.2%}"
                    ),
                    score=best_type_rate,
                    sample_count=len(best_type_notes),
                    note_ids=[n.note_id for n in best_type_notes[:5]],
                )
            )

    # Title formula among top performers (title first, body fallback)
    formula_counter: Counter[str] = Counter()
    for n in top:
        formula_counter[_infer_title_formula_from_note(n)] += 1
    if formula_counter:
        formula, cnt = formula_counter.most_common(1)[0]
        findings.append(
            StyleFinding(
                finding_type="title_formula",
                label=formula,
                evidence=f"高互动标题多用「{formula}」模式（{cnt}/{len(top)}）",
                score=top[0].engagement_rate if top else 0.0,
                sample_count=cnt,
                note_ids=top_ids[:3],
            )
        )

    # Best single note highlight (title or body snippet — never empty 「」)
    if top:
        best = top[0]
        best_label = _note_content_snippet(best, limit=80) or best.note_id
        findings.append(
            StyleFinding(
                finding_type="best_note",
                label=best_label,
                evidence=(
                    f"最佳笔记「{best_label}」互动率 {best.engagement_rate:.2%} "
                    f"(浏览{best.views}/赞{best.likes}/藏{best.collects}/评{best.comments})"
                ),
                score=best.engagement_rate,
                sample_count=1,
                note_ids=[best.note_id],
            )
        )

    return AnalysisResult(
        account_id=account_id,
        findings=findings,
        note_count=len(notes),
        avg_engagement_rate=avg_rate,
        top_note_ids=top_ids,
        cold_start=False,
    )


def _visual_for_tone(tone: str) -> str:
    for t, _p, visual in _TONE_PATTERNS:
        if t == tone:
            return visual
    return "温暖治愈"


def _note_content_snippet(note: NoteStats, *, limit: int = 120) -> str:
    """Prefer title; fall back to body_text so empty-title notes still deposit materials."""
    title = (note.title or "").strip()
    if title:
        return title
    body = (getattr(note, "body_text", None) or "").strip()
    if not body:
        return ""
    return body if len(body) <= limit else body[:limit]


def _style_from_finding(
    tone_finding: StyleFinding | None,
    avg_rate: float,
    top_titles: list[str],
) -> StyleDNA:
    tone = tone_finding.label if tone_finding else "治愈"
    visual = _visual_for_tone(tone)
    voice = [tt for tt in top_titles if tt][:3] or ["今天分享..."]
    return StyleDNA(
        style_id=f"creator_stats_{tone}",
        tone=tone,
        voice_patterns=voice,
        visual_style=visual,
        color_palette=[],
        layout_preference="拼贴" if tone == "治愈" else "网格",
        emoji_usage="克制",
        hashtag_style="精准少而美",
        engagement_rate=tone_finding.score if tone_finding else avg_rate,
        sample_count=tone_finding.sample_count if tone_finding else 1,
        last_used="",
    )


def _avg_save_rate(notes: list[NoteStats]) -> float:
    views = sum(n.views for n in notes)
    if views <= 0:
        return 0.0
    return round(sum(n.collects for n in notes) / views, 4)


async def deposit_from_analysis(
    analysis: AnalysisResult,
    notes: list[NoteStats],
    store: BaseStore | None,
    *,
    account_niche: str = "",
) -> AnalysisResult:
    """Write durable style DNA / materials / plays into CreativeMemory.

    CreativeMemory persists to DB (Postgres or in-memory fallback) even when
    ``store`` is None — so CLI / dry-run without a graph store still deposits
    styles for the next creation recall.

    ``account_niche`` is the product 赛道 (母婴/美妆/…), NOT a topic tag.
    Topic tags go into ``trigger_condition`` so agent ``recall_plays(niche=赛道)``
    still returns universal / matching plays.
    """
    if analysis.cold_start or not notes:
        analysis.cold_start = True
        analysis.styles_deposited = 0
        analysis.materials_deposited = 0
        analysis.plays_deposited = 0
        return analysis

    cm = CreativeMemory(analysis.account_id, store=store)
    styles = 0
    materials = 0
    plays = 0
    coros = []

    tone_finding = next((f for f in analysis.findings if f.finding_type == "tone"), None)
    top = sorted(notes, key=lambda n: n.engagement_rate, reverse=True)[:5]
    # Title or body snippet — empty-title notes still contribute voice/hooks/materials
    top_snippets = [s for n in top if (s := _note_content_snippet(n))]

    style = _style_from_finding(tone_finding, analysis.avg_engagement_rate, top_snippets)
    coros.append(cm.deposit_style(style))
    styles = 1

    formula_finding = next(
        (f for f in analysis.findings if f.finding_type == "title_formula"), None
    )
    topic_finding = next((f for f in analysis.findings if f.finding_type == "topic"), None)
    format_finding = next((f for f in analysis.findings if f.finding_type == "format"), None)

    # Product niche (赛道) for playbook recall — never put free-form topic tags here
    # or content_strategist recall_plays(niche="母婴") will miss the row.
    product_niche = (account_niche or "").strip()
    topic_label = topic_finding.label if topic_finding else ""
    trigger = "creator_stats_high_performer"
    if topic_label:
        trigger = f"{trigger}:{topic_label}"

    play = ConversionPlay(
        play_id=f"creator_stats_play_{analysis.account_id}",
        trigger_condition=trigger,
        title_formula=formula_finding.label if formula_finding else "叙事种草",
        opening_hook=top_snippets[0] if top_snippets else "",
        cta_pattern="收藏+关注",
        best_posting_hour=0,
        avg_engagement_rate=analysis.avg_engagement_rate,
        avg_save_rate=_avg_save_rate(top),
        content_type=format_finding.label if format_finding else "note",
        niche=product_niche,
        proven_count=len(top),
        last_proven="",
    )
    coros.append(cm.deposit_play(play))
    plays = 1

    for n in top:
        snippet = _note_content_snippet(n)
        if not snippet:
            continue
        rate = as_fraction_engagement_rate(n.engagement_rate)
        title = (n.title or "").strip()
        if title:
            entry = MaterialEntry(
                material_id=f"creator_title_{n.note_id}",
                category="标题模板",
                content=title,
                source_post_id=n.note_id,
                source_engagement_rate=rate,
                tags=["高转化", "creator_stats", "爆款标题"],
                reuse_count=0,
                effectiveness=min(1.0, rate * 10) if rate else 0.5,
                weight=1.0 + rate,
                created_at=n.synced_at or "",
            )
            coros.append(cm.deposit_material(entry))
            materials += 1

        # 文案片段: title or body_text (covers empty-title notes)
        body_entry = MaterialEntry(
            material_id=f"creator_hook_{n.note_id}",
            category="文案片段",
            content=snippet,
            source_post_id=n.note_id,
            source_engagement_rate=rate,
            tags=["高转化", "creator_stats", "开头"],
            effectiveness=min(1.0, rate * 10) if rate else 0.5,
            weight=1.0 + rate,
            created_at=n.synced_at or "",
        )
        coros.append(cm.deposit_material(body_entry))
        materials += 1

    # deposit_style/play/material each self-isolate (try/except → logger.warning,
    # return None), so bare coros in gather — no _safe_* wrapper needed. Writes are
    # independent upsert-by-key with no cross-write read dependency (gather-safe).
    await asyncio.gather(*coros)

    analysis.styles_deposited = styles
    analysis.materials_deposited = materials
    analysis.plays_deposited = plays
    return analysis


async def run_analysis(
    notes: list[NoteStats],
    account_id: str,
    store: BaseStore | None = None,
    *,
    account_niche: str = "",
) -> AnalysisResult:
    """Analyze notes and deposit durable creative memory."""
    analysis = analyze_notes(notes, account_id)
    # Prefer explicit niche; else best-effort from account row (manual/inferred bind)
    niche = (account_niche or "").strip()
    if not niche:
        try:
            from backend.db.accounts import get_account

            acc = await get_account(account_id)
            if acc is not None:
                niche = (getattr(acc, "niche", None) or "").strip()
        except Exception:
            niche = ""
    return await deposit_from_analysis(analysis, notes, store, account_niche=niche)
