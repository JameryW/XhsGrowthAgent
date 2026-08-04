"""Optimization workflow nodes.

All node-function re-exports are lazy via ``__getattr__`` (PEP 562). Each
node module instantiates its agent class at import (model router +
langchain_openai + langgraph); eagerly importing them here made every
``backend.agents.nodes.optimization.X`` import pay ~0.5s. Callers now pay
that only on first attribute access. Symbol imports (``from
backend.agents.nodes.optimization import viral_matcher_node``) resolve via
__getattr__; submodule imports (``... import choice_gate as
choice_gate_module``) resolve normally; ``import *`` works via __dir__.
"""

from typing import Any

_LAZY_EXPORTS = {
    "choice_gate_node": (
        "backend.agents.nodes.optimization.choice_gate",
        "choice_gate_node",
    ),
    "content_analyzer_node": (
        "backend.agents.nodes.optimization.content_analyzer",
        "content_analyzer_node",
    ),
    "draft_gate_node": (
        "backend.agents.nodes.optimization.draft_gate",
        "draft_gate_node",
    ),
    "version_generator_node": (
        "backend.agents.nodes.optimization.version_generator",
        "version_generator_node",
    ),
    "viral_matcher_node": (
        "backend.agents.nodes.optimization.viral_matcher",
        "viral_matcher_node",
    ),
}

__all__ = [
    "viral_matcher_node",
    "content_analyzer_node",
    "version_generator_node",
    "choice_gate_node",
    "draft_gate_node",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.agents.nodes.optimization' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
