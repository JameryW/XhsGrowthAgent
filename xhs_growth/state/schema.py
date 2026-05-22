from enum import Enum
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages
from typing_extensions import NotRequired


# ── Enums ──────────────────────────────────────────────────────────────────


class WorkflowPhase(str, Enum):
    IDLE = "idle"
    SCOUTING = "scouting"
    PLANNING = "planning"
    CREATING = "creating"
    REVIEWING = "reviewing"
    PUBLISHING = "publishing"
    ANALYZING = "analyzing"
    ENGAGING = "engaging"
    COMPLETED = "completed"
    ERROR = "error"


class ContentStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    FAILED = "failed"


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    TRENDING = "trending"


class ContentType(str, Enum):
    NOTE = "note"          # 图文笔记
    VIDEO = "video"        # 视频笔记
    CAROUSEL = "carousel"  # 轮播图


# ── Sub-state models ───────────────────────────────────────────────────────


class TrendData(TypedDict, total=False):
    """趋势侦察结果"""
    hot_topics: list[dict[str, Any]]       # [{topic, heat_score, growth_rate, related_keywords}]
    trending_keywords: list[str]
    competitor_posts: list[dict[str, Any]]  # [{title, likes, comments, author}]
    niche_opportunities: list[dict[str, Any]]
    timestamp: str


class ContentPlan(TypedDict, total=False):
    """内容策略计划"""
    selected_topic: str
    content_angle: str
    content_type: ContentType
    target_audience: str
    key_points: list[str]
    suggested_timing: str
    reference_posts: list[dict[str, Any]]
    hashtags: list[str]
    urgency: Urgency


class CopyContent(TypedDict, total=False):
    """文案内容"""
    title_candidates: list[str]   # 3-5 个标题候选
    selected_title: str
    body_text: str
    hashtags: list[str]
    cta: str                      # call-to-action
    emoji_usage: list[str]
    tone: str                     # 语气风格


class VisualPlan(TypedDict, total=False):
    """视觉设计方案"""
    cover_prompt: str             # 封面图生成提示
    image_count: int
    image_prompts: list[str]      # 每张图的提示
    layout_style: str
    color_palette: list[str]
    font_suggestion: str
    brand_elements: list[str]


class PublishResult(TypedDict, total=False):
    """发布结果"""
    post_id: str
    post_url: str
    published_at: str
    ab_variant: str | None        # A/B 测试变体标记
    status: ContentStatus


class AnalyticsSnapshot(TypedDict, total=False):
    """数据分析快照"""
    post_id: str
    views: int
    likes: int
    collects: int
    comments: int
    shares: int
    engagement_rate: float
    reach_rate: float
    timestamp: str
    insights: list[str]           # 分析洞察
    recommendations: list[str]    # 优化建议


class EngagementAction(TypedDict, total=False):
    """互动操作"""
    action_type: str              # reply_comment, reply_dm, follow_back
    target_id: str
    content: str
    timestamp: str


class HumanFeedback(TypedDict, total=False):
    """人工审核反馈"""
    decision: ContentStatus       # approved / rejected
    comments: str
    revisions: list[str]          # 修改要求
    reviewer: str


class RipplePrediction(TypedDict, total=False):
    """Ripple CAS 传播预测结果"""
    job_id: str
    estimated_reach: int
    estimated_engagement: int
    viral_probability: float
    phase: str                    # 种子期/增长/爆发/衰退
    confidence: float
    key_influencers: list[dict]
    spread_path: list[dict]


class RipplePMFResult(TypedDict, total=False):
    """Ripple PMF 验证结果"""
    job_id: str
    pmf_score: float
    risk_factors: list[str]
    improvement_strategies: list[str]
    market_segment: dict
    confidence: float


# ── Main state ─────────────────────────────────────────────────────────────


def _merge_dict(left: dict, right: dict) -> dict:
    """Reducer: 合并字典，right 覆盖 left"""
    return {**left, **right}


def _append_list(left: list, right: list) -> list:
    """Reducer: 追加列表"""
    return left + right


class XHSGrowthState(TypedDict, total=False):
    """小红书增长引擎全局状态"""

    # 工作流控制
    phase: WorkflowPhase
    current_agent: str
    error: str | None
    retry_count: int

    # 消息历史 (LangGraph 内置 reducer)
    messages: Annotated[list, add_messages]

    # 各阶段数据
    trend_data: TrendData
    content_plan: ContentPlan
    copy_content: CopyContent
    visual_plan: VisualPlan
    publish_result: PublishResult
    analytics: AnalyticsSnapshot
    engagement_actions: Annotated[list[EngagementAction], _append_list]

    # 人工审核
    human_feedback: HumanFeedback

    # Ripple CAS 引擎
    ripple_prediction: RipplePrediction
    ripple_pmf: RipplePMFResult
    ripple_job_ids: Annotated[list[str], _append_list]

    # 历史记录
    content_history: Annotated[list[dict], _append_list]
    performance_log: Annotated[list[dict], _append_list]

    # 元数据
    account_id: str
    session_id: str
    created_at: str
    updated_at: str
