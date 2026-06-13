"""TypedDict definitions for creative memory.

Style DNA, Conversion Playbook, Material Vault, Niche Benchmark.
"""

from __future__ import annotations

from typing import Any, TypedDict


class StyleDNA(TypedDict, total=False):
    """风格指纹 — 创作者的风格偏好画像"""

    style_id: str
    tone: str  # 文风: 活泼/专业/治愈/犀利
    voice_patterns: list[str]  # 常用句式/开头/结尾模板
    visual_style: str  # 视觉风格: 温暖治愈/高冷高级/...
    color_palette: list[str]  # 偏好色系
    layout_preference: str  # 偏好排版: 网格/拼贴/单焦点
    emoji_usage: str  # emoji 使用风格: 重度/克制/无
    hashtag_style: str  # 标签风格: 精准少而美/广撒网/蹭热点
    engagement_rate: float  # 该风格的历史互动率
    sample_count: int  # 采样次数
    last_used: str  # ISO timestamp


class ConversionPlay(TypedDict, total=False):
    """转化策略 — 经过验证的高转化内容模式"""

    play_id: str
    trigger_condition: str  # 什么时候用: "新品首发"/"教程干货"/"种草安利"
    title_formula: str  # 标题公式: "数字+痛点+解决方案"
    opening_hook: str  # 开头钩子模板
    cta_pattern: str  # 行动号召模式
    best_posting_hour: int  # 最佳发布时段
    avg_engagement_rate: float
    avg_save_rate: float  # 收藏率
    content_type: str  # note/video/carousel
    niche: str  # 适用赛道
    proven_count: int  # 验证次数
    last_proven: str  # 最近验证时间


class MaterialEntry(TypedDict, total=False):
    """优质素材 — 可复用的高效创作素材"""

    material_id: str
    category: str  # 封面/文案片段/标签组合/选题角度
    content: str  # 实际内容
    source_post_id: str  # 来源帖子
    source_engagement_rate: float
    tags: list[str]  # "高转化"/"爆款标题"/"引流开头"
    reuse_count: int  # 被复用次数
    effectiveness: float  # 复用后平均效果 (0-1)
    weight: float  # 权重（软降权用，初始 1.0）
    created_at: str


class NicheBenchmark(TypedDict, total=False):
    """行业基准 — 按赛道的聚合数据"""

    niche: str
    top_styles: list[dict[str, Any]]  # [{style_name, usage_rate, avg_engagement}]
    avg_engagement_by_angle: dict[str, float]  # {angle: avg_rate}
    trending_formulas: list[str]  # 当前赛道热门标题公式
    peak_posting_hours: list[int]  # 赛道整体高峰时段
    updated_at: str


class CalibrationPayload(TypedDict, total=False):
    """校准数据 — analyst 输出，由异步任务回写"""

    account_id: str
    niche: str
    style_id: str  # 要校准的 Style DNA ID
    actual_engagement_rate: float
    actual_save_rate: float
    play_id: str  # 要校准的 Conversion Play ID
    play_success: bool  # 本次是否验证成功
    material_ids: list[str]  # 要校准的素材 ID 列表
    material_effectiveness: dict[str, float]  # {material_id: effectiveness}
    post_id: str  # 本次发布的 post_id


__all__ = [
    "StyleDNA",
    "ConversionPlay",
    "MaterialEntry",
    "NicheBenchmark",
    "CalibrationPayload",
]
