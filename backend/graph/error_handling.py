"""Error handling — retry policies and error recovery."""

from __future__ import annotations

import logging

from langgraph.types import RetryPolicy

logger = logging.getLogger("xhs_growth.error_handling")

# ── 各节点的重试策略（P0-W3：穷举注册表）──
#
# 显式决策：图中每一个节点都必须出现在本注册表里（有策略或显式 None）。
# get_retry_policy 对未知节点 raise KeyError —— "有没有框架级重试"不允许
# dict.get 的静默 None 回退。tests/unit/graph/test_retry_registry.py 断言
# build_graph() 的全部节点都在此登记。
#
# 重要现状说明（保持不变）：BaseAgent.__call__ 吞掉 execute() 的一切异常并
# 返回错误状态（stateful retry，见 base.py docstring 与
# prd 07-07-remove-handle-agent-error-dead-code），因此下面的 RetryPolicy
# 实际只对节点 wrapper 层的 raise（如 _check_cancelled 之外的意外异常）生效，
# 多数 agent 的重试仍由业务路由的 retry_count 承担。统一 retry 引擎属 P1/P2。
RETRY_POLICIES: dict[str, RetryPolicy | None] = {
    # 高重试：外部 API 调用可能不稳定（纯读取，无外部副作用）
    "trend_scout": RetryPolicy(max_attempts=3),
    # 中重试：LLM 调用可能触发限速
    "copywriter": RetryPolicy(max_attempts=2),
    "visual_designer": RetryPolicy(max_attempts=2),
    "analyst": RetryPolicy(max_attempts=2),
    "content_strategist": RetryPolicy(max_attempts=2),
    # 低重试：确定性逻辑
    "orchestrator": RetryPolicy(max_attempts=1),
    "review_gate": RetryPolicy(max_attempts=1),
    # ── 显式无框架级重试 ──
    # P0-W3：publisher 是外部副作用节点（真实小红书发帖），禁止 generic
    # auto-retry —— 重复触发就是重复发帖。发布重试必须走 /publish-retry 的
    # 显式人工通道（幂等键 + unknown 对账保护，见 backend/agents/publisher.py）。
    "publisher": None,
    # 评估器自带降级 pass-through（吞异常），历史上隐式 None → 显式化。
    "evaluator_gate": None,
    # 以下节点历史上在 builder 里隐式拿 None（dict 无此键）或根本未传
    # retry 参数 —— 全部显式登记，防止"忘了配"与"故意不配"不可区分。
    "brief_analyzer": None,
    "shooting_planner": None,
    "revise_content": None,
    "ripple_gate": None,
    "ripple_finalize": None,
    "ripple_late_recheck": None,
    "draft_gate": None,
    "viral_matcher": None,
    "blogger_scout": None,
    "blogger_gate": None,
    "content_analyzer": None,
    "version_generator": None,
    "choice_gate": None,
    "brief_gate": None,
}


def get_retry_policy(node_name: str) -> RetryPolicy | None:
    """获取指定节点的重试策略。

    P0-W3：未知节点直接 raise KeyError（不再是 dict.get 的静默 None），
    让"该节点有没有框架级重试"成为编译期的显式决策。返回值可以为 None，
    但那必须是注册表里写明的 None 条目。
    """
    return RETRY_POLICIES[node_name]
