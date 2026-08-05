"""Graph node functions — wraps agent calls into LangGraph nodes.

All node-function re-exports are lazy via ``__getattr__`` (PEP 562). Each node
module instantiates its agent class at import time, pulling in the model
router (langchain_openai), tools, and langgraph — eagerly importing them here
made every ``from backend.agents.nodes import X`` (e.g. the common
``from backend.agents.nodes import review_gate as rg``) pay ~2.9s. Callers now
pay that only on first attribute access. ``from backend.agents.nodes import
copywriter_node`` etc. still work via __getattr__; submodule imports
(``from backend.agents.nodes import review_gate as rg``) resolve normally
without touching __getattr__; ``import *`` works via __dir__.
"""

from typing import Any

# Map of re-exported names to the submodule that provides them.
# Resolved on first access via ``__getattr__`` (PEP 562).
_LAZY_EXPORTS = {
    "NodeContext": ("backend.agents.nodes._base", "NodeContext"),
    "NodeResult": ("backend.agents.nodes._base", "NodeResult"),
    "analyst_node": ("backend.agents.nodes.analyst", "analyst_node"),
    "blogger_gate_node": ("backend.agents.nodes.blogger_gate", "blogger_gate_node"),
    "blogger_scout_node": ("backend.agents.nodes.blogger_scout", "blogger_scout_node"),
    "brief_analyzer_node": ("backend.agents.nodes.brief_analyzer", "brief_analyzer_node"),
    "brief_gate_node": ("backend.agents.nodes.brief_gate", "brief_gate_node"),
    "content_strategist_node": (
        "backend.agents.nodes.content_strategist",
        "content_strategist_node",
    ),
    "copywriter_node": ("backend.agents.nodes.copywriter", "copywriter_node"),
    "evaluator_node": ("backend.agents.nodes.evaluator", "evaluator_node"),
    "choice_gate_node": ("backend.agents.nodes.optimization", "choice_gate_node"),
    "content_analyzer_node": ("backend.agents.nodes.optimization", "content_analyzer_node"),
    "draft_gate_node": ("backend.agents.nodes.optimization", "draft_gate_node"),
    "version_generator_node": ("backend.agents.nodes.optimization", "version_generator_node"),
    "viral_matcher_node": ("backend.agents.nodes.optimization", "viral_matcher_node"),
    "orchestrator_node": ("backend.agents.nodes.orchestrator", "orchestrator_node"),
    "publisher_node": ("backend.agents.nodes.publisher", "publisher_node"),
    "review_gate_node": ("backend.agents.nodes.review_gate", "review_gate_node"),
    "revise_content_node": ("backend.agents.nodes.revise_content", "revise_content_node"),
    "ripple_finalize_node": ("backend.agents.nodes.ripple_finalize", "ripple_finalize_node"),
    "ripple_gate_node": ("backend.agents.nodes.ripple_gate", "ripple_gate_node"),
    "ripple_late_recheck_node": (
        "backend.agents.nodes.ripple_late_recheck",
        "ripple_late_recheck_node",
    ),
    "shooting_planner_node": ("backend.agents.nodes.shooting_planner", "shooting_planner_node"),
    "trend_scout_node": ("backend.agents.nodes.trend_scout", "trend_scout_node"),
    "visual_designer_node": ("backend.agents.nodes.visual_designer", "visual_designer_node"),
}

__all__ = [
    # Base classes
    "NodeContext",
    "NodeResult",
    # Main workflow nodes
    "orchestrator_node",
    "trend_scout_node",
    "content_strategist_node",
    "copywriter_node",
    "visual_designer_node",
    "publisher_node",
    "analyst_node",
    "review_gate_node",
    "revise_content_node",
    "evaluator_node",
    # Ripple gate
    "ripple_gate_node",
    "ripple_finalize_node",
    "ripple_late_recheck_node",
    # Brief mode nodes
    "brief_analyzer_node",
    "brief_gate_node",
    "shooting_planner_node",
    # Blogger reference nodes
    "blogger_scout_node",
    "blogger_gate_node",
    # Optimization nodes
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
    raise AttributeError(f"module 'backend.agents.nodes' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
