"""Treat platform text as untrusted data before it reaches an agent.

Trending notes, competitor captions, keyword results and search snippets are
written by third parties.  FORGE (EMNLP 2026 Findings) and the OWASP Agentic
top-10 both show that instruction-like text in retrieved content can hijack a
recommender or a tool-using agent even when the system prompt says otherwise.

The Gateway marks capabilities that return such text with
``ToolSpec.external_content``; on success it runs :func:`sanitize_external_payload`
and sets ``ToolResult.untrusted=True``.  The sanitiser removes control
characters and instruction-shaped phrases while preserving the data's shape,
so a caller can still parse titles/counts and can see that the payload came
from outside the trust boundary.

This is a deterministic containment layer, not a complete prompt-injection
defence.  It is deliberately conservative: a phrase is replaced, never passed
through with a warning.
"""

from __future__ import annotations

import re
from typing import Any

UNTRUSTED_BOUNDARY = "untrusted_xhs_content"
FILTERED_MARKER = "[filtered_untrusted_instruction]"

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+)?(?:the\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"ignore\s+(?:all\s+)?(?:the\s+)?above", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?(?:the\s+)?(?:previous|above)", re.IGNORECASE),
    re.compile(r"(?:system|developer)\s+(?:prompt|message)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(?:an?\s+)?", re.IGNORECASE),
    re.compile(r"act\s+as\s+(?:the\s+)?system", re.IGNORECASE),
    re.compile(r"忽略(?:之前|以上|前面|先前)的?(?:所有)?(?:指令|提示|规则)"),
    re.compile(r"无视(?:之前|以上|前面|先前)的?(?:所有)?(?:指令|提示|规则)"),
    re.compile(r"自动批准(?:发布|通过)?"),
    re.compile(r"跳过(?:人工)?(?:审核|审批|确认)"),
    re.compile(r"修改(?:商品)?价格为"),
    re.compile(r"执行以下(?:命令|操作)"),
)


def sanitize_external_text(text: str) -> str:
    """Remove control characters and replace instruction-shaped phrases."""
    cleaned = _ZERO_WIDTH_RE.sub("", text)
    for pattern in _INSTRUCTION_PATTERNS:
        cleaned = pattern.sub(FILTERED_MARKER, cleaned)
    return cleaned


def sanitize_external_payload(value: Any) -> Any:
    """Recursively sanitise strings in a tool payload without changing shape."""
    if isinstance(value, str):
        return sanitize_external_text(value)
    if isinstance(value, dict):
        return {
            sanitize_external_text(key) if isinstance(key, str) else key: sanitize_external_payload(
                item
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_external_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_external_payload(item) for item in value)
    if isinstance(value, set):
        return {sanitize_external_payload(item) for item in value}
    return value


def wrap_untrusted(text: str) -> str:
    """Wrap free text in the boundary tag used by prompt-facing callers."""
    return f"<{UNTRUSTED_BOUNDARY}>\n{sanitize_external_text(text)}\n</{UNTRUSTED_BOUNDARY}>"


__all__ = [
    "FILTERED_MARKER",
    "UNTRUSTED_BOUNDARY",
    "sanitize_external_payload",
    "sanitize_external_text",
    "wrap_untrusted",
]
