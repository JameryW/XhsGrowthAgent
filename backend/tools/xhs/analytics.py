"""XHS analytics tools — prefer imported creator-center stats when available."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


@tool
async def analytics_reader(post_id: str, account_id: str = "default") -> dict[str, Any]:
    """读取小红书帖子数据分析（优先本地导入的创作者中心笔记统计）"""
    from backend.db import creator_stats as stats_db

    note = await stats_db.get_note_stats(account_id, post_id)
    if note is not None:
        return {
            "post_id": note.note_id,
            "title": note.title,
            "views": note.views,
            "likes": note.likes,
            "collects": note.collects,
            "comments": note.comments,
            "shares": note.shares,
            "engagement_rate": note.engagement_rate,
            "published_at": note.published_at,
            "source": note.source,
        }
    return {
        "post_id": post_id,
        "views": 0,
        "likes": 0,
        "collects": 0,
        "comments": 0,
        "shares": 0,
        "engagement_rate": 0.0,
        "source": "unavailable",
    }


@tool
async def pattern_detector(
    time_range: str = "7d", account_id: str = "default"
) -> list[dict[str, Any]]:
    """检测内容表现模式 — 基于导入的创作者中心笔记统计"""
    from backend.db import creator_stats as stats_db
    from backend.services.creator_stats.analyze import analyze_notes

    notes = await stats_db.list_note_stats(account_id, limit=100)
    if not notes:
        return [
            {
                "pattern": "暂无导入数据",
                "confidence": 0.0,
                "time_range": time_range,
                "account_id": account_id,
            }
        ]
    analysis = analyze_notes(notes, account_id)
    return [
        {
            "pattern": f"{f.finding_type}:{f.label}",
            # Confidence from sample_count (not engagement*10 which saturates at 0.1)
            "confidence": round(
                min(1.0, max(0.1, (f.sample_count or 1) / max(analysis.note_count, 1))),
                3,
            ),
            "evidence": f.evidence,
            "sample_count": f.sample_count,
            "score": f.score,
            "time_range": time_range,
            "account_id": account_id,
        }
        for f in analysis.findings
    ]


@tool
async def report_generator(account_id: str, period: str = "weekly") -> str:
    """生成增长报告（含导入统计与创作建议摘要）"""
    from backend.db import creator_stats as stats_db
    from backend.services.creator_stats.analyze import analyze_notes

    account = await stats_db.get_account_stats(account_id)
    notes = await stats_db.list_note_stats(account_id, limit=50)
    if not notes and account is None:
        return f"增长报告: account={account_id}, period={period}, 暂无导入的创作者中心数据"
    analysis = analyze_notes(notes, account_id)
    lines = [
        f"增长报告: account={account_id}, period={period}",
        f"导入笔记: {analysis.note_count} 篇, 平均互动率 {analysis.avg_engagement_rate:.2%}",
    ]
    if account:
        lines.append(
            f"账户汇总: 浏览{account.views}/赞{account.likes}/"
            f"藏{account.collects}/评{account.comments}"
        )
    # Surface bound niche when available (post-import resolve)
    try:
        from backend.db.accounts import get_account

        acc = await get_account(account_id)
        if acc is not None and acc.niche:
            lines.append(f"赛道绑定: {acc.niche} (source={acc.niche_source or 'unknown'})")
    except Exception:
        pass
    for f in analysis.findings[:5]:
        lines.append(f"- {f.finding_type}/{f.label}: {f.evidence}")
    # Surface durable style DNA when present (next-creation recall surface)
    try:
        from backend.memory.creative import CreativeMemory

        cm = CreativeMemory(account_id, store=None)
        styles = await cm.recall_style(query="growth report style", limit=2)
        real = [s for s in styles if not str(s.get("style_id", "")).startswith("default_")]
        if real:
            s0 = real[0]
            lines.append(
                f"风格DNA: 文风={s0.get('tone')} 视觉={s0.get('visual_style')} "
                f"互动率={s0.get('engagement_rate')} 采样={s0.get('sample_count')}"
            )
    except Exception:
        pass
    return "\n".join(lines)
