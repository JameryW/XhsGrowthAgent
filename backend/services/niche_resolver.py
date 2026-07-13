"""Account niche (赛道) resolution: infer from historical notes or accept manual override.

Pure inference is I/O-free so fixture note titles/tags exercise the real transform.
Manual niche always wins when non-empty — inference never silently replaces it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

logger = logging.getLogger("xhs_growth.niche_resolver")

# Product niche labels (aligned with WorkflowStartForm frontend niches)
KNOWN_NICHES: tuple[str, ...] = (
    "母婴",
    "美妆",
    "穿搭",
    "美食",
    "家居",
    "健身",
    "旅行",
    "数码",
    "宠物",
    "知识",
)

NicheSource = Literal["manual", "inferred", "account_bound", "cold_start"]

# Keyword → niche heuristics (title/tags/body text-contains, case-insensitive for ASCII)
_NICHE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "母婴": (
        "母婴",
        "宝宝",
        "婴儿",
        "辅食",
        "育儿",
        "奶粉",
        "月子",
        "孕",
        "宝妈",
        "亲子",
        "童装",
        "尿布",
        "睡袋",
        "夜醒",
    ),
    "美妆": (
        "美妆",
        "护肤",
        "化妆",
        "口红",
        "面膜",
        "粉底",
        "眼影",
        "防晒",
        "精华",
        "底妆",
        "彩妆",
    ),
    "穿搭": ("穿搭", "ootd", "OOTD", "时装", "衣服", "搭配", "鞋", "包", "潮流", "look"),
    "美食": ("美食", "探店", "餐厅", "食谱", "做饭", "烘焙", "小吃", "菜", "甜品", "火锅"),
    "家居": ("家居", "装修", "收纳", "家具", "软装", "室内", "客厅", "卧室", "布置"),
    "健身": ("健身", "运动", "瑜伽", "减脂", "增肌", "跑步", "训练", "塑形", "拉伸"),
    "旅行": ("旅行", "旅游", "攻略", "景点", "出行", "机票", "酒店", "打卡", "周末游"),
    "数码": (
        "数码",
        "手机",
        "电脑",
        "相机",
        "耳机",
        "评测",
        "开箱",
        "科技",
        "平板",
        "智能",
        "ai",
        "人工智能",
        "大模型",
        "模型",
        "claude",
        "codex",
        "chatgpt",
        "gpt",
        "gemini",
        "openai",
        "deepseek",
        "glm",
        "编程",
        "代码",
        "开发",
    ),
    "宠物": ("宠物", "猫", "狗", "铲屎", "萌宠", "猫咪", "狗狗", "养宠", "猫粮", "狗粮"),
    "知识": ("知识", "干货", "学习", "读书", "职场", "技能", "科普", "教程", "成长", "方法论"),
}


@dataclass
class NicheResolution:
    """Result of niche resolution for an account / workflow run."""

    niche: str
    source: NicheSource
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    cold_start: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _text_blob(note: dict[str, Any] | Any) -> str:
    if hasattr(note, "to_dict"):
        d = note.to_dict()
    elif isinstance(note, dict):
        d = note
    else:
        return str(note)
    parts: list[str] = []
    for key in ("title", "body", "body_text", "content", "display_title"):
        v = d.get(key)
        if v:
            parts.append(str(v))
    tags = d.get("tags") or d.get("hashtags") or []
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags if t)
    elif tags:
        parts.append(str(tags))
    return " ".join(parts)


def score_niches_from_text(text: str) -> dict[str, int]:
    """Return hit counts per known niche for a free-text blob."""
    scores: dict[str, int] = {n: 0 for n in KNOWN_NICHES}
    if not text:
        return scores
    lower = text.lower()
    for niche, keywords in _NICHE_KEYWORDS.items():
        for kw in keywords:
            if kw.isascii():
                normalized_kw = kw.lower()
                # ``ai`` is a useful signal in Chinese titles such as
                # ``AI模型`` but is too short to substring-match safely:
                # ``Daily`` would otherwise infer the 数码 niche. Chinese
                # characters count as valid token boundaries here.
                if normalized_kw == "ai":
                    matched = re.search(r"(?<![a-z0-9])ai(?![a-z0-9])", lower) is not None
                else:
                    matched = normalized_kw in lower
                if matched:
                    scores[niche] += 1
            elif kw in text:
                scores[niche] += 1
    return scores


def infer_niche_from_notes(
    notes: list[dict[str, Any] | Any],
    *,
    min_hits: int = 1,
) -> NicheResolution:
    """Pure: historical notes → niche label (or cold_start when no signal).

    Uses keyword hits on titles/tags/body. Deterministic; no LLM.
    """
    if not notes:
        return NicheResolution(
            niche="",
            source="cold_start",
            confidence=0.0,
            evidence=["no_historical_notes"],
            cold_start=True,
        )

    totals: dict[str, int] = {n: 0 for n in KNOWN_NICHES}
    evidence_hits: list[str] = []
    for note in notes:
        blob = _text_blob(note)
        if not blob.strip():
            continue
        scores = score_niches_from_text(blob)
        for niche, hits in scores.items():
            if hits:
                totals[niche] += hits
                if len(evidence_hits) < 8 and hits:
                    title = ""
                    if isinstance(note, dict):
                        title = str(note.get("title") or "")[:40]
                    elif hasattr(note, "title"):
                        title = str(getattr(note, "title", ""))[:40]
                    evidence_hits.append(f"{niche}+{hits}:{title}")

    ranked = sorted(
        ((n, c) for n, c in totals.items() if c >= min_hits),
        key=lambda x: (-x[1], x[0]),
    )
    candidates = [{"niche": n, "hits": c} for n, c in ranked[:5]]
    if not ranked:
        return NicheResolution(
            niche="",
            source="cold_start",
            confidence=0.0,
            evidence=["notes_present_but_no_keyword_match"],
            candidates=candidates,
            cold_start=True,
        )

    best_niche, best_hits = ranked[0]
    total_hits = sum(c for _, c in ranked) or 1
    boost = 1.0 if best_hits >= 2 else 0.6
    confidence = round(min(1.0, best_hits / max(total_hits, 1) * boost), 3)
    return NicheResolution(
        niche=best_niche,
        source="inferred",
        confidence=confidence,
        evidence=evidence_hits[:5] or [f"hits={best_hits}"],
        candidates=candidates,
        cold_start=False,
    )


def resolve_niche(
    *,
    manual_niche: str | None = None,
    notes: list[dict[str, Any] | Any] | None = None,
    account_bound_niche: str | None = None,
    cold_start_default: str = "",
) -> NicheResolution:
    """Resolve niche with explicit priority: manual > inferred > account_bound > cold_start.

    Manual non-empty always wins so deliberate UI choices are never overwritten
    by inference in the same resolve call.
    """
    manual = (manual_niche or "").strip()
    if manual:
        return NicheResolution(
            niche=manual,
            source="manual",
            confidence=1.0,
            evidence=["user_provided_manual_niche"],
            cold_start=False,
        )

    inferred = infer_niche_from_notes(notes or [])
    if inferred.niche and not inferred.cold_start:
        return inferred

    bound = (account_bound_niche or "").strip()
    if bound:
        return NicheResolution(
            niche=bound,
            source="account_bound",
            confidence=0.5,
            evidence=["account.niche_bound"],
            candidates=inferred.candidates,
            cold_start=False,
        )

    default = (cold_start_default or "").strip()
    return NicheResolution(
        niche=default,
        source="cold_start",
        confidence=0.0,
        evidence=inferred.evidence or ["no_notes_no_manual"],
        candidates=inferred.candidates,
        cold_start=True,
    )


async def load_notes_for_account(account_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Load note-like dicts from imported creator stats (and optional future sources)."""
    notes: list[dict[str, Any]] = []
    try:
        from backend.db import creator_stats as stats_db

        rows = await stats_db.list_note_stats(account_id, limit=limit)
        for r in rows:
            notes.append(r.to_dict())
    except Exception as e:
        logger.debug("load creator_note_stats for niche failed: %s", e)
    return notes


async def resolve_account_niche(
    account_id: str,
    *,
    manual_niche: str | None = None,
    notes: list[dict[str, Any] | Any] | None = None,
    cold_start_default: str = "",
    persist: bool = False,
) -> NicheResolution:
    """Full resolve path used by workflow start / free draft / API / post-import.

    Priority: request manual > account manual binding > inferred > other bound >
    cold_start. Deliberate ``niche_source=manual`` on the account is never
    overwritten by inference in this call.

    When ``persist`` and source is inferred/manual (not cold_start), writes
    niche onto the account row (best-effort when DB available).
    """
    bound = ""
    bound_source = ""
    try:
        from backend.db.accounts import get_account

        acc = await get_account(account_id)
        if acc is not None:
            bound = getattr(acc, "niche", "") or ""
            bound_source = getattr(acc, "niche_source", "") or ""
    except Exception as e:
        logger.debug("get_account for niche bind failed: %s", e)

    if notes is None:
        notes = await load_notes_for_account(account_id)

    manual = (manual_niche or "").strip()
    if manual:
        result = NicheResolution(
            niche=manual,
            source="manual",
            confidence=1.0,
            evidence=["user_provided_manual_niche"],
            cold_start=False,
        )
    elif bound_source == "manual" and bound.strip():
        # Protect deliberate account-level manual assignment from auto-infer
        result = NicheResolution(
            niche=bound.strip(),
            source="account_bound",
            confidence=1.0,
            evidence=["account.niche_source=manual"],
            cold_start=False,
        )
    else:
        result = resolve_niche(
            manual_niche="",
            notes=notes,
            account_bound_niche=bound,
            cold_start_default=cold_start_default,
        )

    if persist and result.niche and result.source in ("manual", "inferred"):
        try:
            from backend.db.accounts import update_account

            await update_account(
                account_id,
                niche=result.niche,
                niche_source=result.source,
            )
        except Exception as e:
            logger.debug("persist niche to account failed: %s", e)

    return result
