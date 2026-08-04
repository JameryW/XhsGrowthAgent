"""智能体模块 — 各阶段 Agent 实现.

Agents:
- OrchestratorAgent: 编排器，路由决策
- TrendScoutAgent: 趋势侦察
- ContentStrategistAgent: 内容策略
- CopywriterAgent: 文案创作
- VisualDesignerAgent: 视觉设计
- PublisherAgent: 发布执行
- AnalystAgent: 数据分析
- ViralMatcherAgent: 爆款匹配 (发布前优化)
- ContentAnalyzerAgent: 对比分析 (发布前优化)
- VersionGeneratorAgent: 版本生成 (发布前优化)
- BloggerScoutAgent: 博主发现 (热门博主参考)
- EvaluatorAgent: 创作质量评估 (RQGM agent-as-a-judge 面板, 发布前 AI 质量关卡)

All re-exports are lazy via ``__getattr__`` (PEP 562). Each agent class pulls in
the model router (langchain_openai), tools, and langgraph — eagerly importing
them here made every ``from backend.agents.nodes import X`` (which runs this
package __init__ first) pay ~2.4s. Callers now pay that only on first
attribute access. ``from backend.agents import OrchestratorAgent`` etc. still
work via __getattr__; ``from backend.agents import *`` works via __dir__.
"""

from typing import Any

# Map of re-exported names to the submodule that provides them.
# Resolved on first access via ``__getattr__`` (PEP 562).
_LAZY_EXPORTS = {
    "BaseAgent": ("backend.agents.base", "BaseAgent"),
    "OrchestratorAgent": ("backend.agents.orchestrator", "OrchestratorAgent"),
    "TrendScoutAgent": ("backend.agents.trend_scout", "TrendScoutAgent"),
    "ContentStrategistAgent": ("backend.agents.content_strategist", "ContentStrategistAgent"),
    "CopywriterAgent": ("backend.agents.copywriter", "CopywriterAgent"),
    "VisualDesignerAgent": ("backend.agents.visual_designer", "VisualDesignerAgent"),
    "PublisherAgent": ("backend.agents.publisher", "PublisherAgent"),
    "AnalystAgent": ("backend.agents.analyst", "AnalystAgent"),
    "ViralMatcherAgent": ("backend.agents.viral_matcher", "ViralMatcherAgent"),
    "ContentAnalyzerAgent": ("backend.agents.content_analyzer", "ContentAnalyzerAgent"),
    "VersionGeneratorAgent": ("backend.agents.version_generator", "VersionGeneratorAgent"),
    "BriefAnalyzerAgent": ("backend.agents.brief_analyzer", "BriefAnalyzerAgent"),
    "ShootingPlannerAgent": ("backend.agents.shooting_planner", "ShootingPlannerAgent"),
    "BloggerScoutAgent": ("backend.agents.blogger_scout", "BloggerScoutAgent"),
    "EvaluatorAgent": ("backend.agents.evaluator", "EvaluatorAgent"),
}

__all__ = [
    "BaseAgent",
    "OrchestratorAgent",
    "TrendScoutAgent",
    "ContentStrategistAgent",
    "CopywriterAgent",
    "VisualDesignerAgent",
    "PublisherAgent",
    "AnalystAgent",
    "ViralMatcherAgent",
    "ContentAnalyzerAgent",
    "VersionGeneratorAgent",
    "BriefAnalyzerAgent",
    "ShootingPlannerAgent",
    "BloggerScoutAgent",
    "EvaluatorAgent",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.agents' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
