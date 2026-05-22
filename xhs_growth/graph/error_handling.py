"""Error handling — retry policies and error recovery."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import RetryPolicy

logger = logging.getLogger("xhs_growth.error_handling")

# ── 各 Agent 的重试策略 ──

RETRY_POLICIES: dict[str, RetryPolicy] = {
    # 高重试：外部 API 调用可能不稳定
    "trend_scout": RetryPolicy(max_attempts=3),
    "publisher": RetryPolicy(max_attempts=3),
    "engagement": RetryPolicy(max_attempts=3),
    # 中重试：LLM 调用可能触发限速
    "copywriter": RetryPolicy(max_attempts=2),
    "visual_designer": RetryPolicy(max_attempts=2),
    "analyst": RetryPolicy(max_attempts=2),
    "content_strategist": RetryPolicy(max_attempts=2),
    # 低重试：确定性逻辑
    "orchestrator": RetryPolicy(max_attempts=1),
    "review_gate": RetryPolicy(max_attempts=1),
}


def get_retry_policy(agent_name: str) -> RetryPolicy | None:
    """获取指定 Agent 的重试策略"""
    return RETRY_POLICIES.get(agent_name)