"""De-AI-taste (humanize) tool — strip template-y AI copy for Xiaohongshu notes.

Used by CopywriterAgent as a post-generation polish pass and registered as a
LangChain tool for copywriter / omp callers. LLM rewrite with an algorithmic
fallback so the pipeline never fails hard on model errors.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, cast

import yaml
from langchain_core.tools import tool

from backend.config.models import TaskType
from backend.services.llm_enrichment import get_llm_service

logger = logging.getLogger("xhs_growth.tools.de_ai_taste")

# Common Chinese LLM / marketing clichés → lighter spoken substitutes.
# Order matters for overlapping patterns; applied case-sensitively on raw text.
_CLICHE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"在当今(?:这个)?(?:社会|时代|互联网时代)[，,]?"), ""),
    (re.compile(r"随着(?:社会|科技|时代)的(?:发展|进步)[，,]?"), ""),
    (re.compile(r"值得一提的是[，,]?"), "另外，"),
    (re.compile(r"综上所述[，,]?"), "简单说，"),
    (re.compile(r"总而言之[，,]?"), "总之，"),
    (re.compile(r"毋庸置疑[，,]?"), "说实话，"),
    (re.compile(r"不可否认的是[，,]?"), "确实，"),
    (re.compile(r"让我们一起"), "我们一起"),
    (re.compile(r"赋能"), "帮到"),
    (re.compile(r"助力"), "帮"),
    (re.compile(r"打造(?:一个|专属)?"), "做出"),
    (re.compile(r"深度(?:赋能|链接|融合)"), "好好结合"),
    (re.compile(r"全方位"), "各方面"),
    (re.compile(r"一站式"), "省事的"),
    (re.compile(r"沉浸式体验"), "亲身体验"),
    (re.compile(r"家人们[!！]?"), ""),
    (re.compile(r"宝子们[!！]?"), ""),
    (re.compile(r"绝绝子"), "真的不错"),
    (re.compile(r"yyds", re.IGNORECASE), "真的很能打"),
    (re.compile(r"不仅(?:仅)?是[，,]?更是"), "更像是"),
    (re.compile(r"在这个.{0,12}的时代[，,]?"), ""),
    (re.compile(r"作为一个.{0,16}[，,]?我想说[，,]?"), "我自己用下来，"),
    (re.compile(r"相信很多人(?:都)?"), "不少人"),
    (re.compile(r"希望这篇文章对你有所帮助[。.!！]?"), "有用的话收藏一下。"),
    (re.compile(r"欢迎在评论区留言交流[。.!！]?"), "评论区聊聊你的用法。"),
    (re.compile(r"请(?:不吝|多多)(?:点赞|关注|转发|收藏)"), "觉得有用就收藏"),
)

_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_MULTI_NL = re.compile(r"\n{3,}")


def _load_prompt() -> dict[str, Any]:
    """Load tool prompt; prefer package-relative path (backend layout)."""
    candidates = [
        Path(__file__).resolve().parents[2] / "config" / "prompts" / "tools" / "de_ai_taste.yaml",
        Path("backend/config/prompts/tools/de_ai_taste.yaml"),
        Path("xhs_growth/config/prompts/tools/de_ai_taste.yaml"),
    ]
    for path in candidates:
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                data: Any = yaml.safe_load(f)
            return cast(dict[str, Any], data or {})
    raise FileNotFoundError("de_ai_taste.yaml not found")


def _clean_whitespace(text: str) -> str:
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    # Fix leftover punctuation after phrase deletion, e.g. "，，" or leading commas.
    text = re.sub(r"^[，,、\s]+", "", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"。{2,}", "。", text)
    return text.strip()


def algorithmic_de_ai(data: dict[str, Any]) -> dict[str, Any]:
    """Deterministic cliché scrub — never raises; keeps meaning best-effort."""
    title = str(data.get("selected_title") or data.get("title") or "")
    body = str(data.get("body_text") or data.get("body") or "")
    cta = str(data.get("cta") or "")
    tone = str(data.get("tone") or "")
    changes: list[str] = []
    signals: list[str] = []

    def _apply(field: str, value: str) -> str:
        out = value
        for pattern, repl in _CLICHE_REPLACEMENTS:
            if pattern.search(out):
                signals.append(pattern.pattern[:40])
                new_out = pattern.sub(repl, out)
                if new_out != out:
                    changes.append(f"{field}: scrubbed AI cliché")
                    out = new_out
        return _clean_whitespace(out)

    new_title = _apply("title", title) if title else title
    new_body = _apply("body", body) if body else body
    new_cta = _apply("cta", cta) if cta else cta

    # Mild structural nudge: break ultra-long paragraphs into shorter breaths.
    if new_body and "\n" not in new_body and len(new_body) > 180:
        chunks = re.split(r"(?<=[。！？!?])", new_body)
        rebuilt: list[str] = []
        buf = ""
        for chunk in chunks:
            if not chunk:
                continue
            buf += chunk
            if len(buf) >= 60:
                rebuilt.append(buf.strip())
                buf = ""
        if buf.strip():
            rebuilt.append(buf.strip())
        if len(rebuilt) >= 2:
            new_body = "\n".join(rebuilt)
            changes.append("body: split long paragraph for spoken rhythm")

    polished = bool(changes) and (new_title != title or new_body != body or new_cta != cta)
    # Dedupe change labels while preserving order
    seen: set[str] = set()
    uniq_changes: list[str] = []
    for c in changes:
        if c not in seen:
            seen.add(c)
            uniq_changes.append(c)

    return {
        "selected_title": new_title or title,
        "body_text": new_body or body,
        "cta": new_cta or cta,
        "tone": tone or "亲切口语",
        "changes": uniq_changes,
        "ai_signals_found": list(dict.fromkeys(signals))[:12],
        "polished": polished,
        "method": "algorithmic",
    }


def _normalize_result(raw: dict[str, Any] | list[Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, list):
        raw = raw[0] if raw and isinstance(raw[0], dict) else {}
    if not isinstance(raw, dict):
        return fallback

    title = str(raw.get("selected_title") or raw.get("title") or fallback["selected_title"])
    body = str(raw.get("body_text") or raw.get("body") or fallback["body_text"])
    # Never return empty body when input had content.
    if not body.strip() and fallback.get("body_text"):
        body = str(fallback["body_text"])
    if not title.strip() and fallback.get("selected_title"):
        title = str(fallback["selected_title"])

    changes = raw.get("changes") or []
    if not isinstance(changes, list):
        changes = [str(changes)]
    signals = raw.get("ai_signals_found") or raw.get("ai_signals") or []
    if not isinstance(signals, list):
        signals = [str(signals)]

    return {
        "selected_title": title,
        "body_text": body,
        "cta": str(raw.get("cta") if raw.get("cta") is not None else fallback.get("cta") or ""),
        "tone": str(raw.get("tone") or fallback.get("tone") or "亲切口语"),
        "changes": [str(c) for c in changes if c][:20],
        "ai_signals_found": [str(s) for s in signals if s][:20],
        "polished": bool(raw.get("polished", True)),
        "method": "llm",
    }


async def polish_copy(
    *,
    selected_title: str = "",
    body_text: str = "",
    cta: str = "",
    tone: str = "",
    niche: str = "",
    revision_hints: list[str] | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    """Polish title/body to reduce AI taste. Safe to call from agents.

    Always falls back to algorithmic scrubbing when the LLM path fails or
    ``use_llm=False`` (e.g. style-variant batch to control cost).
    """
    input_data = {
        "selected_title": selected_title or "",
        "body_text": body_text or "",
        "cta": cta or "",
        "tone": tone or "",
        "niche": niche or "通用",
        "revision_hints": (
            "；".join(str(h) for h in (revision_hints or []) if h) or "无额外修订要求"
        ),
    }
    fallback = algorithmic_de_ai(input_data)
    if not (input_data["body_text"].strip() or input_data["selected_title"].strip()):
        return {**fallback, "polished": False, "changes": [], "method": "skip"}

    if not use_llm:
        return fallback

    try:
        prompt_template = _load_prompt()
        service = get_llm_service()
        result = await service.enrich_with_llm(
            task_type=TaskType.WRITING,
            prompt_template=prompt_template,
            input_data=input_data,
            fallback_fn=algorithmic_de_ai,
        )
        if isinstance(result, dict) and result.get("method") == "algorithmic":
            return result
        return _normalize_result(result, fallback)
    except Exception as e:
        logger.warning("polish_copy LLM path failed, using algorithmic fallback: %s", e)
        return fallback


@tool
async def de_ai_taste(
    body_text: str,
    selected_title: str = "",
    cta: str = "",
    tone: str = "",
    niche: str = "",
    revision_hints: str = "",
) -> dict[str, Any]:
    """去除小红书文案 AI 味 — 把模板化/空泛表达改成真人分享感.

    Args:
        body_text: 正文
        selected_title: 标题
        cta: 互动号召
        tone: 原语气
        niche: 垂类赛道
        revision_hints: 额外修订要求（可含 RQGM ai_taste 反馈）

    Returns:
        润色结果 dict：selected_title / body_text / cta / tone / changes /
        ai_signals_found / polished / method
    """
    hints = [h.strip() for h in re.split(r"[;\n；|]", revision_hints or "") if h.strip()]
    return await polish_copy(
        selected_title=selected_title,
        body_text=body_text,
        cta=cta,
        tone=tone,
        niche=niche,
        revision_hints=hints,
        use_llm=True,
    )


__all__ = ["de_ai_taste", "polish_copy", "algorithmic_de_ai"]
