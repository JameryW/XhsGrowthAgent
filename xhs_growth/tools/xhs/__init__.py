"""小红书平台工具模块 — 平台交互.

Tools:
- xhs_trending: 热门话题获取
- keyword_monitor: 关键词监控
- competitor_analyzer: 竞品分析
- xhs_publisher: 发布笔记
- ab_test_manager: A/B 测试管理
- post_scheduler: 发布调度
- analytics_reader: 数据读取
- pattern_detector: 模式检测
- comment_replier: 评论回复
- dm_handler: 私信处理
- escalation_flagger: 风险标记
- fetch_pending_comments: 获取待回复评论
"""

from xhs_growth.tools.xhs.trending import (
    xhs_trending,
    keyword_monitor,
    competitor_analyzer,
)
from xhs_growth.tools.xhs.publisher import (
    xhs_publisher,
    ab_test_manager,
    post_scheduler,
)
from xhs_growth.tools.xhs.analytics import analytics_reader, pattern_detector
from xhs_growth.tools.xhs.engagement import (
    comment_replier,
    dm_handler,
    escalation_flagger,
    fetch_pending_comments,
)

__all__ = [
    "xhs_trending",
    "keyword_monitor",
    "competitor_analyzer",
    "xhs_publisher",
    "ab_test_manager",
    "post_scheduler",
    "analytics_reader",
    "pattern_detector",
    "comment_replier",
    "dm_handler",
    "escalation_flagger",
    "fetch_pending_comments",
]