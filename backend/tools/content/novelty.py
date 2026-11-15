"""Account-history novelty scoring for topic/copy deduplication.

AutoViralAI's three-signal ranking includes a novelty term computed as the
maximum cosine similarity against the account's recent published notes.  This
module implements the same contract with a deterministic character n-gram
TF-IDF representation, so it works without an embedding service (and costs no
tokens).  The default threshold is ``0.82`` as specified in the 2026-11
architecture review.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

DEFAULT_NOVELTY_THRESHOLD = 0.82
DEFAULT_NOVELTY_PENALTY = 8.0


def _tokens(text: str) -> list[str]:
    text = (text or "").lower()
    chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff" or ch.isalnum()]
    grams = [chars[i] + chars[i + 1] for i in range(max(0, len(chars) - 1))]
    latin = re.findall(r"[a-z]+|\d+", text)
    return grams + latin


def cosine_similarity(left: str, right: str) -> float:
    """Cosine similarity between two documents' n-gram count vectors."""
    left_counts = Counter(_tokens(left))
    right_counts = Counter(_tokens(right))
    if not left_counts or not right_counts:
        return 0.0
    common = set(left_counts) & set(right_counts)
    dot = sum(left_counts[token] * right_counts[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left_counts.values()))
    right_norm = math.sqrt(sum(value * value for value in right_counts.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass(frozen=True)
class NoveltyResult:
    max_similarity: float
    most_similar_index: int | None
    threshold: float
    penalty: float
    is_duplicate_risk: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_similarity": round(self.max_similarity, 4),
            "most_similar_index": self.most_similar_index,
            "threshold": self.threshold,
            "penalty": round(self.penalty, 2),
            "is_duplicate_risk": self.is_duplicate_risk,
        }


def max_history_similarity(candidate: str, history: Sequence[str]) -> tuple[float, int | None]:
    """Return ``(max cosine, index)`` against the history texts."""
    best = 0.0
    best_index: int | None = None
    for index, text in enumerate(history):
        similarity = cosine_similarity(candidate, text)
        if similarity > best:
            best = similarity
            best_index = index
    return best, best_index


def novelty_penalty(
    candidate: str,
    history: Iterable[str],
    *,
    threshold: float = DEFAULT_NOVELTY_THRESHOLD,
    penalty: float = DEFAULT_NOVELTY_PENALTY,
) -> NoveltyResult:
    """Score a candidate against the account's recent note texts.

    The penalty is applied only above the threshold and scales linearly with
    the excess similarity, capped at ``penalty`` points.  A duplicate-risk
    candidate should also be asked for a different angle by the caller.
    """
    texts = [str(text) for text in history if str(text).strip()]
    similarity, index = max_history_similarity(candidate, texts)
    risk = similarity > threshold
    applied = 0.0
    if risk:
        applied = min(penalty, penalty * (similarity - threshold) / max(1e-6, 1.0 - threshold))
    return NoveltyResult(
        max_similarity=similarity,
        most_similar_index=index,
        threshold=threshold,
        penalty=applied,
        is_duplicate_risk=risk,
    )


def adjusted_topic_score(base_score: float, novelty: NoveltyResult) -> float:
    """Subtract the novelty penalty and clamp to the 0-100 scoring scale."""
    return round(max(0.0, min(100.0, base_score - novelty.penalty)), 2)


__all__ = [
    "DEFAULT_NOVELTY_PENALTY",
    "DEFAULT_NOVELTY_THRESHOLD",
    "NoveltyResult",
    "adjusted_topic_score",
    "cosine_similarity",
    "max_history_similarity",
    "novelty_penalty",
]
