"""Tests for prompt token estimation and context capping."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from backend.models.context_cap import cap_context, estimate_tokens


def test_estimate_tokens_string_and_messages():
    assert estimate_tokens("hello world") > 0
    msgs = [SystemMessage(content="system prompt"), HumanMessage(content="user text")]
    assert estimate_tokens(msgs) > estimate_tokens("system prompt")


def test_estimate_tokens_non_list_returns_zero():
    assert estimate_tokens(12345) == 0  # type: ignore[arg-type]
    assert estimate_tokens(None) == 0  # type: ignore[arg-type]


def test_under_limit_returned_unchanged():
    msgs = [SystemMessage(content="s"), HumanMessage(content="u")]
    result = cap_context(msgs, max_tokens=1_000_000)
    assert result == msgs
    assert result is not msgs  # new list, input not mutated


def test_trims_oldest_non_system_messages():
    big = "x " * 5000  # comfortably over a small cap
    msgs = [
        SystemMessage(content="keep me"),
        HumanMessage(content=big),
        HumanMessage(content=big),
        HumanMessage(content="recent"),
    ]
    result = cap_context(msgs, max_tokens=200)

    # System message always preserved
    contents = [m.content for m in result]
    assert "keep me" in contents
    # Most recent non-system message preserved
    assert "recent" in contents
    # Oldest big messages dropped to fit
    assert big not in contents
    assert estimate_tokens(result) <= 200


def test_only_system_messages_preserved_when_over_limit():
    big = "y " * 5000
    msgs = [SystemMessage(content=big), SystemMessage(content=big)]
    result = cap_context(msgs, max_tokens=100)
    # All system messages kept even if over (nothing safe to drop)
    assert len(result) == 2


def test_dict_messages_supported():
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "x " * 3000},
        {"role": "user", "content": "last"},
    ]
    result = cap_context(msgs, max_tokens=200)
    roles = [m["role"] for m in result]
    assert roles[0] == "system"
    assert result[-1]["content"] == "last"


def test_default_threshold_env(monkeypatch):
    monkeypatch.setenv("XHS_LLM_MAX_INPUT_TOKENS", "5")
    msgs = [HumanMessage(content="this is a reasonably long message")]
    result = cap_context(msgs)  # uses env default = 5
    assert estimate_tokens(result) <= 5 or result == []
