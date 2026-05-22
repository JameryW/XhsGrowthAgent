"""状态模块 — LangGraph 状态定义.

Components:
- schema: TypedDict 状态模型
- reducers: 状态更新器函数
"""

from xhs_growth.state.schema import (
    XHSGrowthState,
    WorkflowPhase,
    ContentStatus,
    ContentType,
    Urgency,
    TrendData,
    ContentPlan,
    CopyContent,
    VisualPlan,
    PublishResult,
    AnalyticsSnapshot,
    HumanFeedback,
)
from xhs_growth.state.reducers import merge_dict, append_list, replace, max_value

__all__ = [
    "XHSGrowthState",
    "WorkflowPhase",
    "ContentStatus",
    "ContentType",
    "Urgency",
    "TrendData",
    "ContentPlan",
    "CopyContent",
    "VisualPlan",
    "PublishResult",
    "AnalyticsSnapshot",
    "HumanFeedback",
    "merge_dict",
    "append_list",
    "replace",
    "max_value",
]