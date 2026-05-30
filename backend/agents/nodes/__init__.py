"""Graph node functions — wraps agent calls into LangGraph nodes."""

from backend.agents.nodes._base import NodeContext, NodeResult
from backend.agents.nodes.analyst import analyst_node
from backend.agents.nodes.content_strategist import content_strategist_node
from backend.agents.nodes.copywriter import copywriter_node
from backend.agents.nodes.engagement import engagement_node

# Optimization nodes
from backend.agents.nodes.optimization import (
    choice_gate_node,
    content_analyzer_node,
    version_generator_node,
    viral_matcher_node,
)
from backend.agents.nodes.orchestrator import orchestrator_node
from backend.agents.nodes.publisher import publisher_node
from backend.agents.nodes.review_gate import review_gate_node
from backend.agents.nodes.revise_content import revise_content_node
from backend.agents.nodes.trend_scout import trend_scout_node
from backend.agents.nodes.visual_designer import visual_designer_node

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
    "engagement_node",
    "review_gate_node",
    "revise_content_node",
    # Optimization nodes
    "viral_matcher_node",
    "content_analyzer_node",
    "version_generator_node",
    "choice_gate_node",
]