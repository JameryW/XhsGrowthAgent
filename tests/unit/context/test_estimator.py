"""Deterministic estimator tests (info.md D4'): pure, input-only, CJK-aware."""

from backend.context.estimator import estimate_tokens


def test_empty_string_is_zero() -> None:
    assert estimate_tokens("") == 0


def test_ascii_counts_a_quarter_rounding_up() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2  # ceil(5 / 4)
    assert estimate_tokens("abcdefgh") == 2


def test_cjk_counts_one_per_char() -> None:
    assert estimate_tokens("趋势分析") == 4
    assert estimate_tokens("母婴") == 2


def test_cjk_punctuation_and_fullwidth_count_as_cjk() -> None:
    assert estimate_tokens("，。！") == 3
    assert estimate_tokens("ＡＢ") == 2  # fullwidth latin


def test_mixed_text() -> None:
    # 2 CJK + 2 ascii → 2 + ceil(2/4) = 3
    assert estimate_tokens("ab趋势") == 3
    # 2 CJK + 5 ascii → 2 + ceil(5/4) = 4
    assert estimate_tokens("abcde趋势") == 4


def test_deterministic_across_repeats() -> None:
    text = "睡眠倒退第 7 天 checkpoint benchmark"
    first = estimate_tokens(text)
    # Same char multiset in any order → identical estimate (input-only purity).
    assert first == estimate_tokens(text)
    assert first == estimate_tokens(text[::-1])
