"""Content hashtag research tool."""

from langchain_core.tools import tool


@tool
async def research_hashtags(topic: str, limit: int = 10) -> list[dict]:
    """深度研究标签 — 分析标签竞争度和流量"""
    return [{"tag": f"#{topic}", "competition": "medium", "traffic": "high"}]