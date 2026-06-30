"""分析工具模块 — 数据分析与报告生成.

Tools:
- detect_content_patterns: 内容模式检测
- generate_growth_report: 增长报告生成
- topic_scorer: 话题热度评分
"""

from backend.tools.analysis.report_generator import (
    detect_content_patterns,
    generate_growth_report,
)
from backend.tools.analysis.topic_scorer import topic_scorer

__all__ = ["detect_content_patterns", "generate_growth_report", "topic_scorer"]
