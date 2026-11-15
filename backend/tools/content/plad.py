"""PLAD — psycholinguistic anti-homogeneity inspection for RedNote copy.

The RedNote-Vibe / PLAD line of work identifies 31 computable features across
four psychological dimensions that separate human-written notes from
LLM-polished ones.  This module implements the *deterministic* subset: it
never calls an LLM and never blocks on network access, so it can run before
every ``TaskType.POLISH`` invocation at zero token cost.

The output is advisory.  ``plad_constraints`` turns the largest deviations
into Chinese constraints that the polisher receives as revision hints; the
polisher remains free to rewrite.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

_GROUP_A = "情感与社会锚定"
_GROUP_B = "认知架构"
_GROUP_C = "词汇身份与风格签名"
_GROUP_D = "文本衔接流"

_FIRST_PERSON = ("我", "我们", "本人", "自己", "亲测", "自用")
_SECOND_PERSON = ("你", "你们", "大家", "姐妹们", "朋友们")
_EMOTION_WORDS = (
    "开心",
    "快乐",
    "喜欢",
    "爱",
    "治愈",
    "惊艳",
    "难过",
    "焦虑",
    "崩溃",
    "心动",
    "温柔",
    "感动",
    "惊喜",
    "失落",
)
_SOCIAL_PROOF = ("亲测", "实测", "万人", "好评", "回购", "朋友推荐", "大家都在", "爆款")
_CONNECTIVES = (
    "总而言之",
    "综上所述",
    "不仅如此",
    "此外",
    "与此同时",
    "值得注意的是",
    "首先",
    "其次",
    "最后",
    "然而",
    "因此",
    "从而",
    "在这个快节奏",
    "在当今",
    "随着",
)
_CAUSAL = ("因为", "所以", "因此", "导致", "从而", "由于", "使得")
_HEDGES = ("可能", "也许", "大概", "似乎", "或许", "应该", "据说")
_CLICHES = (
    "在这个快节奏的时代",
    "在当今社会",
    "不得不说",
    "绝绝子",
    "yyds",
    "狠狠拿捏",
    "宝藏",
    "分享给大家",
    "希望对大家有帮助",
    "总而言之",
    "综上所述",
    "赋能",
    "打造",
)

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.、)]|[①②③④⑤⑥⑦⑧⑨⑩])\s*", re.MULTILINE)
_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def _count(text: str, terms: tuple[str, ...]) -> int:
    return sum(text.count(term) for term in terms)


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.findall(text) if part.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]|[A-Za-z]+|\d+", text)


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


_GROUPS: dict[str, tuple[str, ...]] = {
    _GROUP_A: (
        "first_person_ratio",
        "second_person_ratio",
        "emotion_word_density",
        "emoji_density",
        "social_proof_density",
        "question_density",
        "exclamation_density",
        "sentiment_polarity_proxy",
    ),
    _GROUP_B: (
        "sentence_count",
        "avg_sentence_length",
        "burstiness",
        "clause_depth_proxy",
        "connective_density",
        "causal_connective_density",
        "hedge_density",
        "list_marker_count",
    ),
    _GROUP_C: (
        "lexical_diversity",
        "rare_char_ratio",
        "idiom_count",
        "cliche_phrase_count",
        "repeated_phrase_ratio",
        "hashtag_count",
        "latin_token_ratio",
        "punctuation_variety",
    ),
    _GROUP_D: (
        "paragraph_count",
        "avg_paragraph_length",
        "linebreak_ratio",
        "opening_repetition",
        "pronoun_continuity",
        "transition_density",
        "text_length",
    ),
}


def _feature_names() -> list[str]:
    return [name for names in _GROUPS.values() for name in names]


_FEATURE_COUNT = len(_feature_names())


@dataclass(frozen=True)
class PladFeature:
    name: str
    group: str
    value: float
    baseline: float
    direction: str  # "high" means unusually high vs human baseline

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "group": self.group,
            "value": round(self.value, 4),
            "baseline": self.baseline,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class PladReport:
    text_length: int
    features: tuple[PladFeature, ...]
    ai_likelihood: float
    burstiness: float
    connective_density: float
    first_person_scene_ratio: float
    emotion_volatility: float
    violations: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def feature_names(self) -> list[str]:
        return [item.name for item in self.features]

    def as_dict(self) -> dict[str, Any]:
        return {
            "text_length": self.text_length,
            "ai_likelihood": round(self.ai_likelihood, 4),
            "burstiness": round(self.burstiness, 4),
            "connective_density": round(self.connective_density, 4),
            "first_person_scene_ratio": round(self.first_person_scene_ratio, 4),
            "emotion_volatility": round(self.emotion_volatility, 4),
            "violations": list(self.violations),
            "features": [item.as_dict() for item in self.features],
            "feature_count": len(self.features),
        }


def _compute_raw(text: str) -> dict[str, float]:
    sentences = _sentences(text)
    words = _words(text)
    paragraphs = [part.strip() for part in _PARAGRAPH_RE.split(text) if part.strip()] or [
        text.strip()
    ]
    sentence_lengths = [len(sentence) for sentence in sentences] or [len(text)]
    lengths = [len(paragraph) for paragraph in paragraphs]
    unique_words = len(set(words))
    hashtags = re.findall(r"#([^\s#]+)", text)
    latin = re.findall(r"[A-Za-z]+", text)
    openings = [sentence[:4] for sentence in sentences if sentence]
    repeated_openings = _safe_ratio(len(openings) - len(set(openings)), len(openings))
    repeated_phrases = len(re.findall(r"(.{4,})\1+", text))

    emotion_hits = _count(text, _EMOTION_WORDS)
    emoji_hits = len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text))
    questions = text.count("？") + text.count("?")
    exclamations = text.count("！") + text.count("!")
    positive = sum(text.count(word) for word in ("好", "美", "赞", "喜欢", "开心", "爱", "推荐"))
    negative = sum(text.count(word) for word in ("差", "烂", "糟", "难过", "焦虑", "贵", "坑"))
    sentence_length_variance = _variance([float(length) for length in sentence_lengths])
    burstiness = math.sqrt(sentence_length_variance) / (
        sum(sentence_lengths) / len(sentence_lengths) or 1.0
    )
    emotion_density = _safe_ratio(emotion_hits, max(1, len(words)))
    # Approximate "volatility" as the coefficient of variation of emotion
    # word clusters across equal-sized thirds of the text.
    third = max(1, len(text) // 3)
    chunks = [text[:third], text[third : 2 * third], text[2 * third :]]
    chunk_hits = [float(_count(chunk, _EMOTION_WORDS)) for chunk in chunks]
    emotion_volatility = _variance(chunk_hits)

    return {
        "first_person_ratio": _safe_ratio(_count(text, _FIRST_PERSON), max(1, len(words))),
        "second_person_ratio": _safe_ratio(_count(text, _SECOND_PERSON), max(1, len(words))),
        "emotion_word_density": emotion_density,
        "emotion_volatility": emotion_volatility,
        "emoji_density": _safe_ratio(emoji_hits, max(1, len(words))),
        "social_proof_density": _safe_ratio(_count(text, _SOCIAL_PROOF), max(1, len(words))),
        "question_density": _safe_ratio(questions, max(1, len(sentences))),
        "exclamation_density": _safe_ratio(exclamations, max(1, len(sentences))),
        "sentiment_polarity_proxy": _safe_ratio(positive - negative, max(1, positive + negative)),
        "sentence_count": float(len(sentences)),
        "avg_sentence_length": sum(sentence_lengths) / len(sentence_lengths),
        "burstiness": burstiness,
        "clause_depth_proxy": _safe_ratio(
            text.count("，") + text.count(","), max(1, len(sentences))
        ),
        "connective_density": _safe_ratio(_count(text, _CONNECTIVES), max(1, len(sentences))),
        "causal_connective_density": _safe_ratio(_count(text, _CAUSAL), max(1, len(sentences))),
        "hedge_density": _safe_ratio(_count(text, _HEDGES), max(1, len(sentences))),
        "list_marker_count": float(len(_BULLET_RE.findall(text))),
        "lexical_diversity": _safe_ratio(unique_words, max(1, len(words))),
        "rare_char_ratio": _safe_ratio(
            len([word for word in words if len(word) >= 4]), max(1, len(words))
        ),
        "idiom_count": float(len(re.findall(r"[\u4e00-\u9fff]{4}(?=[，。！？\s])", text))),
        "cliche_phrase_count": float(_count(text, _CLICHES)),
        "repeated_phrase_ratio": _safe_ratio(repeated_phrases, max(1, len(sentences))),
        "hashtag_count": float(len(hashtags)),
        "latin_token_ratio": _safe_ratio(len(latin), max(1, len(words))),
        "punctuation_variety": float(len(set(re.findall(r"[，。！？、；：,.!?;:]", text)))),
        "paragraph_count": float(len(paragraphs)),
        "avg_paragraph_length": sum(lengths) / len(lengths),
        "linebreak_ratio": _safe_ratio(text.count("\n"), max(1, len(text))),
        "opening_repetition": repeated_openings,
        "pronoun_continuity": _safe_ratio(
            _count(text, _FIRST_PERSON + _SECOND_PERSON), max(1, len(sentences))
        ),
        "transition_density": _safe_ratio(_count(text, _CONNECTIVES), max(1, len(sentences))),
        "text_length": float(len(text)),
    }


_BASELINES: dict[str, tuple[float, str]] = {
    "first_person_ratio": (0.045, "low"),
    "second_person_ratio": (0.02, "low"),
    "emotion_word_density": (0.012, "low"),
    "emoji_density": (0.008, "low"),
    "social_proof_density": (0.004, "low"),
    "question_density": (0.25, "low"),
    "exclamation_density": (0.35, "low"),
    "sentiment_polarity_proxy": (0.35, "low"),
    "sentence_count": (12.0, "low"),
    "avg_sentence_length": (28.0, "low"),
    "burstiness": (0.55, "low"),
    "clause_depth_proxy": (1.2, "high"),
    "connective_density": (0.25, "high"),
    "causal_connective_density": (0.12, "high"),
    "hedge_density": (0.10, "high"),
    "list_marker_count": (2.0, "low"),
    "lexical_diversity": (0.62, "low"),
    "rare_char_ratio": (0.08, "low"),
    "idiom_count": (1.0, "low"),
    "cliche_phrase_count": (1.0, "high"),
    "repeated_phrase_ratio": (0.05, "high"),
    "hashtag_count": (5.0, "low"),
    "latin_token_ratio": (0.01, "low"),
    "punctuation_variety": (5.0, "low"),
    "paragraph_count": (4.0, "low"),
    "avg_paragraph_length": (90.0, "high"),
    "linebreak_ratio": (0.02, "low"),
    "opening_repetition": (0.10, "high"),
    "pronoun_continuity": (0.25, "low"),
    "transition_density": (0.25, "high"),
    "text_length": (350.0, "low"),
}


def inspect_text(text: str) -> PladReport:
    """Compute the 31-feature PLAD report for a note draft."""
    text = text or ""
    raw = _compute_raw(text)
    features: list[PladFeature] = []
    for group, names in _GROUPS.items():
        for name in names:
            baseline, direction = _BASELINES[name]
            features.append(
                PladFeature(
                    name=name,
                    group=group,
                    value=raw[name],
                    baseline=baseline,
                    direction=direction,
                )
            )

    def deviation(name: str) -> float:
        baseline, direction = _BASELINES[name]
        value = raw[name]
        if direction == "high":
            return max(0.0, (value - baseline) / max(abs(baseline), 1e-6))
        return max(0.0, (baseline - value) / max(abs(baseline), 1e-6))

    # AI-ish signals: uniform sentences, high connectives, low first-person
    # anchoring, low emotion volatility, cliché density.
    ai_score = (
        0.24 * min(1.0, deviation("burstiness"))
        + 0.22 * min(1.0, deviation("connective_density"))
        + 0.16 * min(1.0, deviation("first_person_ratio"))
        + 0.14 * min(1.0, deviation("emotion_word_density"))
        + 0.12 * min(1.0, deviation("cliche_phrase_count"))
        + 0.12 * min(1.0, deviation("opening_repetition"))
    )
    ai_likelihood = 1.0 / (1.0 + math.exp(-(ai_score - 0.55) * 4.0))

    violations: list[dict[str, Any]] = []
    checks = (
        ("burstiness", "句长方差过低，句式过于整齐", 0.30),
        ("connective_density", "AI 连接词密度过高", 0.25),
        ("first_person_ratio", "缺少第一人称具体场景锚定", 0.30),
        ("emotion_word_density", "情绪词密度偏低，语气过于中性", 0.35),
        ("cliche_phrase_count", "模板化套话过多", 0.20),
        ("opening_repetition", "句子开头重复度过高", 0.25),
    )
    for name, message, threshold in checks:
        if deviation(name) >= threshold:
            violations.append(
                {
                    "feature": name,
                    "message": message,
                    "value": round(raw[name], 4),
                    "baseline": _BASELINES[name][0],
                    "severity": round(min(1.0, deviation(name) / 2.0), 3),
                }
            )
    violations.sort(key=lambda item: item["severity"], reverse=True)
    return PladReport(
        text_length=len(text),
        features=tuple(features),
        ai_likelihood=_clamp01(ai_likelihood),
        burstiness=raw["burstiness"],
        connective_density=raw["connective_density"],
        first_person_scene_ratio=raw["first_person_ratio"],
        emotion_volatility=emotion_volatility_proxy(raw),
        violations=tuple(violations),
    )


def emotion_volatility_proxy(raw: dict[str, float]) -> float:
    """A 0-1 proxy combining emotion density and punctuation energy."""
    return _clamp01(
        min(1.0, raw["emotion_word_density"] / 0.05) * 0.6
        + min(1.0, raw["exclamation_density"] / 1.0) * 0.4
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def plad_constraints(report: PladReport | dict[str, Any], *, limit: int = 5) -> str:
    """Render violations as a compact constraint block for ``TaskType.POLISH``."""
    if isinstance(report, dict):
        violations = list(report.get("violations") or [])
    else:
        violations = list(report.violations)
    if not violations:
        return "PLAD 体检通过：保持现有具体场景与句式节奏，勿引入模板化连接词。"
    lines = ["PLAD 去同质化约束（必须逐条落实）："]
    for item in violations[:limit]:
        lines.append(
            f"- {item.get('message', item.get('feature'))}（当前 {item.get('value')}，"
            f"基线 {item.get('baseline')}）"
        )
    lines.append("- 保留第一人称亲历细节，打破对称排比；句长要有明显长短差。")
    return "\n".join(lines)


__all__ = [
    "PladFeature",
    "PladReport",
    "inspect_text",
    "plad_constraints",
    "_FEATURE_COUNT",
]
