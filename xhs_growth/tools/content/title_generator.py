"""Content creation tools."""

from langchain_core.tools import tool


@tool
async def hashtag_researcher(keyword: str, limit: int = 10) -> list[dict]:
    """研究小红书标签 — 查找热门标签和相关标签"""
    return [{"hashtag": f"#{keyword}", "posts": 0, "heat": 0}]


@tool
async def title_generator(topic: str, style: str = "attractive", count: int = 5) -> list[str]:
    """生成小红书标题候选"""
    return [f"标题候选{i+1}: {topic}" for i in range(count)]