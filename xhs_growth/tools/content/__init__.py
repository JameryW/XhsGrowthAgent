"""内容工具模块 — 文案与视觉生成.

Tools:
- hashtag_researcher: 话题标签研究 (LLM 增强)
- title_generator: 标题生成 (LLM 增强)
- image_prompt_generator: 图片提示词生成
- layout_recommender: 排版布局推荐 (基于场景分析)
- style_library: 视觉风格库 (基于场景分析)

Helpers:
- get_default_layouts: 默认布局配置 (降级使用)
- get_default_styles: 默认风格配置 (降级使用)
"""

from xhs_growth.tools.content.hashtag_researcher import hashtag_researcher
from xhs_growth.tools.content.title_generator import title_generator
from xhs_growth.tools.content.image_prompt import image_prompt_generator
from xhs_growth.tools.content.layout import layout_recommender, get_default_layouts
from xhs_growth.tools.content.style import style_library, get_default_styles

# Alias for backward compatibility
research_hashtags = hashtag_researcher

__all__ = [
    "hashtag_researcher",
    "research_hashtags",
    "title_generator",
    "image_prompt_generator",
    "layout_recommender",
    "get_default_layouts",
    "style_library",
    "get_default_styles",
]