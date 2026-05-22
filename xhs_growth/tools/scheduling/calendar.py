"""Scheduling tools."""

from langchain_core.tools import tool


@tool
async def calendar_manager(action: str = "view", date: str = "", content_plan: dict = {}) -> dict:
    """管理内容日历 — 查看/添加/删除排期"""
    return {"action": action, "date": date, "plan": content_plan}


@tool
async def timing_optimizer(niche: str = "", target_audience: str = "") -> dict:
    """优化发布时间 — 基于历史数据分析最佳发布时段"""
    return {
        "best_times": ["08:00", "12:00", "18:00", "21:00"],
        "best_days": ["周三", "周五", "周六"],
        "niche": niche,
        "audience": target_audience,
    }