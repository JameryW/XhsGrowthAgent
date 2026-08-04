"""小红书增长引擎 — Multi-agent system for XHS content growth.

核心模块:
- graph: LangGraph 工作流构建
- agents: 各阶段智能体实现
- state: 全局状态定义
- tools: LangChain 工具集

The graph builder and state schema are re-exported lazily via ``__getattr__``
so that importing a submodule (``from backend.db import X``,
``from backend.services import Y``) does not trigger the full LangGraph +
langchain_core import chain (~2.5s). Callers that actually need
``build_graph`` / ``compile_graph_*`` / ``XHSGrowthState`` pay that cost on
first attribute access instead of on every ``backend`` package import.
"""

from typing import Any

# Lightweight enums are safe to import eagerly — ``state.enums`` is stdlib-only.
from backend.state.enums import ContentStatus, WorkflowPhase

__all__ = [
    "compile_graph_dev",
    "compile_graph_prod",
    "build_graph",
    "XHSGrowthState",
    "WorkflowPhase",
    "ContentStatus",
]

# Map of re-exported names to the submodule + attribute that provides them.
# Resolved on first access via ``__getattr__`` (PEP 562), avoiding the heavy
# graph-builder import at package-import time.
_LAZY_EXPORTS = {
    "build_graph": ("backend.graph.builder", "build_graph"),
    "compile_graph_dev": ("backend.graph.builder", "compile_graph_dev"),
    "compile_graph_prod": ("backend.graph.builder", "compile_graph_prod"),
    "XHSGrowthState": ("backend.state.schema", "XHSGrowthState"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
