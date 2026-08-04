"""工作流图模块 — LangGraph 状态图构建.

Components:
- builder: StateGraph 构建与编译
- routers: 条件路由函数
- error_handling: 错误处理与重试策略

Note: Node functions are now in xhs_growth.agents.nodes

All re-exports are lazy via ``__getattr__`` (PEP 562). The node-function
re-exports (re-exported from ``backend.agents.nodes`` for backward
compatibility) each trigger agent instantiation at import time (model
router + langchain_openai + langgraph); the builder symbols pull the
full graph topology. Eagerly importing them here made ``import
backend.graph`` pay ~2.5s. Callers now pay that only on first attribute
access. ``from backend.graph import build_graph`` etc. still work via
__getattr__; ``from backend.graph import builder as b`` resolves
normally (submodule); ``import *`` works via __dir__.
"""

from typing import Any

# Map of re-exported names to the submodule that provides them.
# Node functions resolve via the agents.nodes lazy namespace; builder
# symbols via the builder submodule. Resolved on first access via
# ``__getattr__`` (PEP 562).
_LAZY_EXPORTS = {
    # Builder symbols
    "build_graph": ("backend.graph.builder", "build_graph"),
    "close_dev_graph": ("backend.graph.builder", "close_dev_graph"),
    "compile_graph_dev": ("backend.graph.builder", "compile_graph_dev"),
    "compile_graph_prod": ("backend.graph.builder", "compile_graph_prod"),
    "dev_graph": ("backend.graph.builder", "dev_graph"),
    # Node functions (re-exported from agents.nodes for backward compatibility)
    "analyst_node": ("backend.agents.nodes", "analyst_node"),
    "blogger_gate_node": ("backend.agents.nodes", "blogger_gate_node"),
    "blogger_scout_node": ("backend.agents.nodes", "blogger_scout_node"),
    "choice_gate_node": ("backend.agents.nodes", "choice_gate_node"),
    "content_analyzer_node": ("backend.agents.nodes", "content_analyzer_node"),
    "content_strategist_node": ("backend.agents.nodes", "content_strategist_node"),
    "copywriter_node": ("backend.agents.nodes", "copywriter_node"),
    "orchestrator_node": ("backend.agents.nodes", "orchestrator_node"),
    "publisher_node": ("backend.agents.nodes", "publisher_node"),
    "review_gate_node": ("backend.agents.nodes", "review_gate_node"),
    "revise_content_node": ("backend.agents.nodes", "revise_content_node"),
    "trend_scout_node": ("backend.agents.nodes", "trend_scout_node"),
    "version_generator_node": ("backend.agents.nodes", "version_generator_node"),
    "viral_matcher_node": ("backend.agents.nodes", "viral_matcher_node"),
    "visual_designer_node": ("backend.agents.nodes", "visual_designer_node"),
}

__all__ = [
    "build_graph",
    "close_dev_graph",
    "compile_graph_dev",
    "compile_graph_prod",
    "dev_graph",
    # Node functions (re-exported from agents.nodes for backward compatibility)
    "orchestrator_node",
    "trend_scout_node",
    "content_strategist_node",
    "copywriter_node",
    "visual_designer_node",
    "review_gate_node",
    "publisher_node",
    "analyst_node",
    "revise_content_node",
    "viral_matcher_node",
    "content_analyzer_node",
    "version_generator_node",
    "choice_gate_node",
    "blogger_scout_node",
    "blogger_gate_node",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.graph' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
