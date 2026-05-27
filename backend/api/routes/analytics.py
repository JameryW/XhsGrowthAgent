"""Analytics API routes — growth reports and performance data."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.responses import success

router = APIRouter()


@router.get("/report/{account_id}")
async def get_growth_report(account_id: str, period: str = "weekly"):
    """获取增长报告"""
    # TODO: 从长期记忆中读取
    return success(data={"account_id": account_id, "period": period, "metrics": {}, "insights": []})


@router.get("/performance/{account_id}")
async def get_performance(account_id: str, limit: int = 20):
    """获取最近帖子表现数据"""
    return success(data={"account_id": account_id, "posts": []})


@router.get("/costs")
async def get_costs():
    """获取 LLM 调用成本"""
    from backend.models.cost_tracker import CostTracker

    # TODO: 从全局 tracker 获取
    return success(data={"total_cost_usd": 0, "today_cost_usd": 0, "by_model": {}, "circuit_open": False})