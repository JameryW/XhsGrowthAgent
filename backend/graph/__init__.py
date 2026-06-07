"""工作流图模块 — LangGraph 状态图构建.

Components:
- builder: StateGraph 构建与编译
- routers: 条件路由函数
- error_handling: 错误处理与重试策略

Note: Node functions are now in xhs_growth.agents.nodes
"""

# Node functions are now imported from agents.nodes
from backend.agents.nodes import (
    analyst_node,
    blogger_gate_node,
    blogger_scout_node,
    choice_gate_node,
    content_analyzer_node,
    content_strategist_node,
    copywriter_node,
    engagement_node,
    orchestrator_node,
    publisher_node,
    review_gate_node,
    revise_content_node,
    trend_scout_node,
    version_generator_node,
    # 发布前优化节点
    viral_matcher_node,
    visual_designer_node,
)
from backend.graph.builder import build_graph, compile_graph_dev, compile_graph_prod

__all__ = [
    "build_graph",
    "compile_graph_dev",
    "compile_graph_prod",
    # Node functions (re-exported from agents.nodes for backward compatibility)
    "orchestrator_node",
    "trend_scout_node",
    "content_strategist_node",
    "copywriter_node",
    "visual_designer_node",
    "review_gate_node",
    "publisher_node",
    "analyst_node",
    "engagement_node",
    "revise_content_node",
    "viral_matcher_node",
    "content_analyzer_node",
    "version_generator_node",
    "choice_gate_node",
    "blogger_scout_node",
    "blogger_gate_node",
]