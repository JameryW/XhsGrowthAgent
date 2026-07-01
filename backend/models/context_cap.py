"""Context-window cap — estimate prompt tokens and trim history when over.

Coarse estimate via tiktoken cl100k_base (already a dependency). Not exact for
Anthropic/Qwen encodings, but the 500k threshold leaves ample headroom; this
only needs to decide "is this so big it'll blow the window". Drops oldest
non-system messages first, preserving system + most recent.
"""

from __future__ import annotations

import os
from typing import Any

try:
    import tiktoken

    _ENCODER: Any = tiktoken.get_encoding("cl100k_base")

    def _encode_len(text: str) -> int:
        return len(_ENCODER.encode(text))
except Exception:  # pragma: no cover - tiktoken always present in this repo
    _ENCODER = None

    def _encode_len(text: str) -> int:
        # ponytail: char/4 fallback — rough but fine for the over-limit check.
        return len(text) // 4


_DEFAULT_MAX_INPUT_TOKENS = 500_000
# Per-message overhead (role tags, separators) — OpenAI cookbook heuristic.
_PER_MESSAGE_OVERHEAD = 3


def _default_max_tokens() -> int:
    return int(os.environ.get("XHS_LLM_MAX_INPUT_TOKENS", str(_DEFAULT_MAX_INPUT_TOKENS)))


def _message_content(message: Any) -> str:
    """Pull a stringish content out of a langchain Message or dict."""

    if isinstance(message, str):
        return message
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, str):
        return content
    # langchain message with list-of-blocks content — concatenate text blocks
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _is_system(message: Any) -> bool:
    role = getattr(message, "type", None) or getattr(message, "role", None)
    if role is None and isinstance(message, dict):
        role = message.get("role") or message.get("type")
    return role in ("system", "SystemMessage")


def estimate_tokens(messages: Any) -> int:
    """Estimate total prompt tokens for a list of messages."""

    if isinstance(messages, str):
        return _encode_len(messages)
    if not isinstance(messages, list):
        return 0
    total = 0
    for message in messages:
        total += _encode_len(_message_content(message)) + _PER_MESSAGE_OVERHEAD
    return total


def cap_context(messages: list[Any], max_tokens: int | None = None) -> list[Any]:
    """Trim oldest non-system messages until estimated tokens fit.

    Preserves all system messages and the most recent non-system messages.
    Returns a new list; never mutates the input. If already under the cap or
    only system messages are present, returns the input unchanged.
    """

    limit = max_tokens if max_tokens is not None else _default_max_tokens()
    if estimate_tokens(messages) <= limit:
        return list(messages)

    system_msgs = [m for m in messages if _is_system(m)]
    non_system = [m for m in messages if not _is_system(m)]

    # Keep newest non-system messages; drop oldest until we fit.
    kept = list(non_system)
    while kept and estimate_tokens(system_msgs + kept) > limit:
        kept.pop(0)

    return system_msgs + kept
