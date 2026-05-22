"""XHS publisher tool."""

from langchain_core.tools import tool


@tool
async def xhs_publisher(title: str, body: str, hashtags: list[str], image_paths: list[str] = []) -> dict:
    """发布小红书笔记"""
    return {"post_id": "mock_id", "status": "published", "title": title}


@tool
async def ab_test_manager(post_id: str, variant_titles: list[str], duration_hours: int = 4) -> dict:
    """管理 A/B 测试 — 对比不同标题/封面的表现"""
    return {"test_id": "mock_test", "variants": variant_titles, "duration": duration_hours}


@tool
async def post_scheduler(post_id: str, publish_time: str) -> dict:
    """调度帖子在最佳时间发布"""
    return {"scheduled": True, "post_id": post_id, "publish_time": publish_time}