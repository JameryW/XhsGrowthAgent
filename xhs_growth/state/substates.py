"""Sub-state TypedDict definitions for modular state management."""
from typing import TypedDict, Any
from xhs_growth.state.enums import ContentType, Urgency, ContentStatus


class HotTopicItem(TypedDict, total=False):
    """Hot topic item."""
    topic: str
    heat_score: float
    growth_rate: float
    related_keywords: list[str]


class NicheOpportunity(TypedDict, total=False):
    """Niche opportunity."""
    topic: str
    potential_score: float
    audience_match: str
    entry_barrier: str


class CompetitorPost(TypedDict, total=False):
    """Competitor post."""
    title: str
    likes: int
    comments: int
    author: str


class TrendData(TypedDict, total=False):
    """Trend scouting result."""
    hot_topics: list[HotTopicItem]
    trending_keywords: list[str]
    competitor_posts: list[CompetitorPost]
    niche_opportunities: list[NicheOpportunity]
    timestamp: str


class ContentPlan(TypedDict, total=False):
    """Content strategy plan."""
    selected_topic: str
    content_angle: str
    content_type: ContentType
    target_audience: str
    key_points: list[str]
    suggested_timing: str
    hashtags: list[str]
    urgency: Urgency


class CopyContent(TypedDict, total=False):
    """Copy content."""
    title_candidates: list[str]
    selected_title: str
    body_text: str
    hashtags: list[str]
    cta: str
    emoji_usage: list[str]
    tone: str


class VisualPlan(TypedDict, total=False):
    """Visual design plan."""
    cover_prompt: str
    image_count: int
    image_prompts: list[str]
    layout_style: str
    color_palette: list[str]
    font_suggestion: str
    brand_elements: list[str]


class PublishResult(TypedDict, total=False):
    """Publish result."""
    post_id: str
    post_url: str
    published_at: str
    ab_variant: str | None
    status: ContentStatus


class AnalyticsSnapshot(TypedDict, total=False):
    """Analytics snapshot."""
    post_id: str
    views: int
    likes: int
    collects: int
    comments: int
    shares: int
    engagement_rate: float
    reach_rate: float
    timestamp: str
    insights: list[str]
    recommendations: list[str]


class HumanFeedback(TypedDict, total=False):
    """Human review feedback."""
    decision: ContentStatus
    comments: str
    revisions: list[str]
    reviewer: str


class EngagementAction(TypedDict, total=False):
    """Engagement action."""
    action_type: str
    target_id: str
    content: str
    timestamp: str


class RipplePrediction(TypedDict, total=False):
    """Ripple CAS prediction result."""
    job_id: str
    estimated_reach: int
    estimated_engagement: int
    viral_probability: float
    phase: str
    confidence: float
    key_influencers: list[dict[str, Any]]
    spread_path: list[dict[str, Any]]


class RipplePMFResult(TypedDict, total=False):
    """Ripple PMF validation result."""
    job_id: str
    pmf_score: float
    risk_factors: list[str]
    improvement_strategies: list[str]
    market_segment: dict[str, Any]
    confidence: float


# ── 发布前优化系统子状态 ──


class DraftContent(TypedDict, total=False):
    """用户原始草稿."""
    text: str
    images: list[str]
    title: str
    hashtags: list[str]
    provided_at: str


class ViralPost(TypedDict, total=False):
    """爆款参考笔记."""
    note_id: str
    title: str
    body: str
    hashtags: list[str]
    cover_url: str
    image_urls: list[str]
    likes: int
    collects: int
    comments: int
    engagement_rate: float
    visual_style: str
    color_palette: dict


class GapItem(TypedDict, total=False):
    """差距项."""
    dimension: str
    description: str
    severity: str


class SuggestionItem(TypedDict, total=False):
    """优化建议项."""
    dimension: str
    action: str
    reasoning: str
    priority: int


class OptimizationAnalysis(TypedDict, total=False):
    """优化分析报告."""
    gaps: list[GapItem]
    suggestions: list[SuggestionItem]
    viral_patterns: list[str]


class ContentVersion(TypedDict, total=False):
    """内容版本."""
    version_id: str
    title: str
    body: str
    hashtags: list[str]
    image_prompts: list[str]
    style_suggestion: str
    changes_summary: str
    predicted_score: float


__all__ = [
    "HotTopicItem", "NicheOpportunity", "CompetitorPost",
    "TrendData", "ContentPlan", "CopyContent", "VisualPlan",
    "PublishResult", "AnalyticsSnapshot", "HumanFeedback",
    "EngagementAction", "RipplePrediction", "RipplePMFResult",
    # 发布前优化
    "DraftContent", "ViralPost", "GapItem", "SuggestionItem",
    "OptimizationAnalysis", "ContentVersion",
]