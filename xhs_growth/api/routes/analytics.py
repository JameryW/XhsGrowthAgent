"""Analytics API routes — growth reports and performance data."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/report/{account_id}")
async def get_growth_report(account_id: str, period: str = "weekly"):
    """获取增长报告"""
    # TODO: 从长期记忆中读取
    return {"account_id": account_id, "period": period, "report": "暂无数据"}


@router.get("/performance/{account_id}")
async def get_performance(account_id: str, limit: int = 20):
    """获取最近帖子表现数据"""
    return {"account_id": account_id, "posts": []}


@router.get("/costs")
async def get_costs():
    """获取 LLM 调用成本"""
    from xhs_growth.models.cost_tracker import CostTracker

    # TODO: 从全局 tracker 获取
    return {"total_cost_usd": 0, "today_cost_usd": 0, "circuit_open": False}