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
"""

from backend.agents.analyst import AnalystAgent
from backend.agents.base import BaseAgent
from backend.agents.blogger_scout import BloggerScoutAgent
from backend.agents.brief_analyzer import BriefAnalyzerAgent
from backend.agents.content_analyzer import ContentAnalyzerAgent
from backend.agents.content_strategist import ContentStrategistAgent
from backend.agents.copywriter import CopywriterAgent
from backend.agents.evaluator import EvaluatorAgent
from backend.agents.orchestrator import OrchestratorAgent
from backend.agents.publisher import PublisherAgent
from backend.agents.shooting_planner import ShootingPlannerAgent
from backend.agents.trend_scout import TrendScoutAgent
from backend.agents.version_generator import VersionGeneratorAgent
from backend.agents.viral_matcher import ViralMatcherAgent
from backend.agents.visual_designer import VisualDesignerAgent

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
