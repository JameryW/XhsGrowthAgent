"""Deterministic token estimator (info.md D4').

CJK characters ≈ 1 token each; every other character ≈ 1/4 token, rounding
up so the estimate errs on the safe (larger) side under budget pressure.
Pure function, zero dependencies — an exact provider tokenizer (e.g.
tiktoken) can replace :func:`estimate_tokens` behind the same signature
later without touching callers.
"""

from __future__ import annotations

_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3000, 0x303F),  # CJK punctuation
    (0x3400, 0x4DBF),  # CJK unified ideographs extension A
    (0x4E00, 0x9FFF),  # CJK unified ideographs
    (0xF900, 0xFAFF),  # CJK compatibility ideographs
    (0xFF00, 0xFFEF),  # fullwidth forms
)


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return any(start <= code <= end for start, end in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` deterministically.

    The result depends only on the input (no locale, no tokenizer version),
    which is what makes budget trimming reproducible across runs.
    """
    if not text:
        return 0
    cjk = sum(1 for char in text if _is_cjk(char))
    other = len(text) - cjk
    return cjk + (other + 3) // 4
