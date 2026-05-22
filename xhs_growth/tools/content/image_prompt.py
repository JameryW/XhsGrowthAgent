"""Image prompt generation tool."""

from langchain_core.tools import tool


@tool
async def image_prompt_generator(topic: str, style: str = "modern", count: int = 3) -> list[dict]:
    """生成小红书封面图和配图的 AI 绘画提示词"""
    return [
        {
            "prompt": f"A {style} style cover image about {topic}, suitable for Xiaohongshu",
            "type": "cover",
            "aspect_ratio": "3:4",
        }
        for _ in range(count)
    ]