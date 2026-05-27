"""Graph node functions — wraps agent calls into LangGraph nodes."""

from xhs_growth.agents.nodes._base import NodeContext, NodeResult
from xhs_growth.agents.nodes.orchestrator import orchestrator_node
from xhs_growth.agents.nodes.trend_scout import trend_scout_node
from xhs_growth.agents.nodes.content_strategist import content_strategist_node
from xhs_growth.agents.nodes.copywriter import copywriter_node
from xhs_growth.agents.nodes.visual_designer import visual_designer_node
from xhs_growth.agents.nodes.publisher import publisher_node
from xhs_growth.agents.nodes.analyst import analyst_node
from xhs_growth.agents.nodes.engagement import engagement_node
from xhs_growth.agents.nodes.review_gate import review_gate_node
from xhs_growth.agents.nodes.revise_content import revise_content_node

# Optimization nodes
from xhs_growth.agents.nodes.optimization import (
    viral_matcher_node,
    content_analyzer_node,
    version_generator_node,
    choice_gate_node,
)

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