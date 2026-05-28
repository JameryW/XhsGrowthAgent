"""Analytics API routes — growth reports and performance data."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from fastapi import APIRouter

from backend.api.responses import success

router = APIRouter()


# Mock data generators for demo
def _generate_mock_posts(count: int = 10) -> list[dict]:
    """Generate mock post performance data."""
    posts = []
    base_time = datetime.now() - timedelta(days=7)

    topics = [
        "春日穿搭分享｜清新简约风格",
        "美食探店｜城中热门餐厅打卡",
        "旅行攻略｜周末小众景点推荐",
        "护肤心得｜敏感肌护理秘籍",
        "健身打卡｜一周运动记录",
    ]

    for i in range(count):
        published_at = base_time + timedelta(days=i, hours=random.randint(8, 20))
        likes = random.randint(50, 500)
        comments = random.randint(5, 50)
        collects = random.randint(10, 100)
        shares = random.randint(2, 20)
        views = random.randint(500, 5000)

        posts.append({
            "id": f"post_{i}",
            "title": topics[i % len(topics)],
            "likes": likes,
            "comments": comments,
            "collects": collects,
            "shares": shares,
            "views": views,
            "engagement_rate": round((likes + comments + collects + shares) / views * 100, 2),
            "published_at": published_at.strftime("%Y-%m-%d %H:%M"),
        })

    return posts


def _generate_mock_metrics(period: str) -> dict:
    """Generate mock growth metrics."""
    if period == "daily":
        return {
            "total_posts": 1,
            "total_engagement": random.randint(100, 300),
            "avg_engagement_rate": random.uniform(2.5, 5.0),
            "best_post_title": "今日热门内容",
            "trend_topics": ["穿搭", "美食"],
        }
    elif period == "weekly":
        return {
            "total_posts": 7,
            "total_engagement": random.randint(1000, 3000),
            "avg_engagement_rate": random.uniform(3.0, 6.0),
            "best_post_title": "春日穿搭分享",
            "trend_topics": ["穿搭", "美食", "旅行"],
        }
    else:  # monthly
        return {
            "total_posts": 30,
            "total_engagement": random.randint(5000, 15000),
            "avg_engagement_rate": random.uniform(3.5, 7.0),
            "best_post_title": "月度最佳内容",
            "trend_topics": ["穿搭", "美食", "旅行", "护肤", "健身"],
        }


@router.get("/report/{account_id}")
async def get_growth_report(account_id: str, period: str = "weekly"):
    """获取增长报告"""
    metrics = _generate_mock_metrics(period)
    insights = [
        {"type": "trend", "message": "穿搭类内容互动率持续上升"},
        {"type": "opportunity", "message": "建议增加美食探店频次"},
        {"type": "warning", "message": "周末发布效果优于工作日"},
    ]

    return success(data={
        "account_id": account_id,
        "period": period,
        "metrics": metrics,
        "insights": insights,
        "generated_at": datetime.now().isoformat(),
    })


@router.get("/performance/{account_id}")
async def get_performance(account_id: str, limit: int = 20):
    """获取最近帖子表现数据"""
    posts = _generate_mock_posts(min(limit, 20))

    return success(data={
        "account_id": account_id,
        "posts": posts,
        "total": len(posts),
        "fetched_at": datetime.now().isoformat(),
    })


@router.get("/costs")
async def get_costs():
    """获取 LLM 调用成本"""
    # Mock cost data for demo
    return success(data={
        "total_cost_usd": random.uniform(1.0, 5.0),
        "today_cost_usd": random.uniform(0.1, 0.5),
        "by_model": {
            "claude-sonnet": random.uniform(0.5, 2.0),
            "gpt-4o": random.uniform(0.3, 1.5),
            "deepseek-chat": random.uniform(0.05, 0.3),
        },
        "circuit_open": False,
        "budget_remaining_usd": 8.5,
        "updated_at": datetime.now().isoformat(),
    })