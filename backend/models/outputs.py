"""What the model is asked to return, and how it becomes state.

P1d. These models are deliberately **not** the contracts in
``backend/api/generated/models.py``. That module is generated from the OpenAPI
schema and its fields are tuned for validating a response produced by our own
code: ``AwareDatetime``, a hex ``pattern``, ``StrictStr`` everywhere. A model
that answers "明天下午三点" for a timestamp, ``#fff`` for a colour, or a number
where a string was expected has produced something a human would read without
blinking and this codebase can normalise — failing the call there would trade a
usable sentence for a retry.

Two responsibilities, kept apart on purpose:

* the **model** decides which input *shapes* are acceptable — a field declared
  ``list[str]`` takes ``[{"point": "…"}]`` and a bare ``"…"`` and stringifies
  what it can. Shape leniency has to live here or it does not exist: a ``str``
  field rejects a ``datetime`` during validation, so a normaliser downstream
  never gets the chance to handle it.
* **``normalize_*``** decides which *values* leave: canonical contract values
  for the enum-ish fields, ``#`` stripped to exactly one per tag, timestamps in
  ISO 8601. Whatever the model said, what leaves this module satisfies the
  state contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "BloggerCandidateOutput",
    "BloggerScoutOutput",
    "ContentPlanOutput",
    "HotTopicItemOutput",
    "TrendScoutOutput",
    "normalize_blogger_candidates",
    "normalize_content_plan",
    "normalize_trend_data",
]


def _as_list(value: Any) -> list[Any]:
    """A list from whatever the model wrote where a list was expected.

    A bare string becomes a one-item list rather than being iterated: a model
    that answers ``"要点一、要点二"`` for ``key_points`` must not be answered
    with a list of its characters, which is the failure that looks like success.
    """
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        return [value]
    if isinstance(value, Sequence):
        return list(value)
    return [value]


def _list_items_as_text(value: Any) -> list[str]:
    """Loose items → text, keeping order and blanks for ``normalize_*`` to trim."""
    items: list[str] = []
    for item in _as_list(value):
        if isinstance(item, Mapping):
            items.append(next((str(v) for v in item.values() if isinstance(v, str)), ""))
        else:
            items.append(str(item))
    return items


def _as_float(value: Any) -> float:
    """A float from what a model writes for a score (``90``, ``"90"``, ``"90%"``).

    The percent sign is dropped, not rescaled: whether a score is 0-1 or 0-100
    is a semantic question this function cannot answer, and guessing would turn
    a readable number into a wrong one.
    """
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(",", "").replace("，", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


_COUNT_SUFFIXES: Mapping[str, int] = {
    "万": 10_000,
    "w": 10_000,
    "k": 1_000,
    "千": 1_000,
    "亿": 100_000_000,
}


def _as_int(value: Any) -> int:
    """An int from what a model writes for a count (``"5万"``, ``"1.2w"``, ``5e4``).

    Chinese models answer follower counts in units far more often than in raw
    digits, and each unparsed one used to buy a whole retry over a suffix.
    Unreadable input becomes 0 rather than an error: these counts are decorative
    on a *generated* candidate, so a zero is harmless where a failed batch is
    not.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().replace(",", "").replace("，", "")
    if not text:
        return 0
    multiplier = 1
    lowered = text.lower()
    for suffix, factor in _COUNT_SUFFIXES.items():
        if lowered.endswith(suffix):
            multiplier = factor
            text = text[: -len(suffix)].strip()
            break
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


_TOPIC_ALIASES: tuple[str, ...] = ("topic", "title", "name", "keyword", "话题", "话题名称")


def _topic_text(item: Any) -> str:
    """The name of a topic-shaped item, whichever key or shape it arrived in.

    Both readers of ``hot_topics`` already accept a bare string or a dict with
    ``title`` or ``topic`` (``content_strategist._extract_candidate_topics``,
    ``blogger_scout._summarize_trend_data``), so the tolerant reading is settled
    here once instead of at each of them.
    """
    if isinstance(item, Mapping):
        for key in _TOPIC_ALIASES:
            text = str(item.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(item or "").strip()


class ContentPlanOutput(BaseModel):
    """The content plan as a model should write it — permissive, but not shapeless.

    Only ``selected_topic`` is required: it is the field the whole node exists
    to produce, and the one the semantic validator judges. Everything else has a
    default, because a model that omits ``content_angle`` has made a smaller
    mistake than the one a retry costs.
    """

    model_config = ConfigDict(extra="ignore")
    """Extra keys are dropped, not fatal.

    A model that adds ``reasoning``, or echoes a field from the prompt, has not
    made a mistake worth another request.
    """

    selected_topic: str = Field(description="选定的内容主题")
    content_angle: str = Field(default="", description="切入角度或视角")
    content_type: str = Field(default="", description="内容形式：note / video / carousel")
    target_audience: str = Field(default="", description="目标受众描述")
    key_points: list[str] = Field(default_factory=list, description="内容要点")
    suggested_timing: str = Field(
        default="", description="建议发布时间（ISO 8601，如 2026-09-16T19:00:00+08:00）"
    )
    hashtags: list[str] = Field(default_factory=list, description="推荐话题标签（含 # 前缀）")
    urgency: str = Field(default="", description="紧急度：low / medium / high / trending")

    @field_validator("key_points", "hashtags", mode="before")
    @classmethod
    def _accept_loose_items(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)

    @field_validator("suggested_timing", mode="before")
    @classmethod
    def _accept_a_datetime(cls, value: Any) -> Any:
        return value.isoformat() if isinstance(value, datetime) else value


_CONTENT_TYPE_ALIASES: Mapping[str, str] = {
    "note": "note",
    "图文": "note",
    "图文笔记": "note",
    "图片": "note",
    "image": "note",
    "images": "note",
    "post": "note",
    "video": "video",
    "视频": "video",
    "短视频": "video",
    "short_video": "video",
    "reel": "video",
    "carousel": "carousel",
    "轮播": "carousel",
    "轮播图": "carousel",
    "多图": "carousel",
    "slider": "carousel",
}

_URGENCY_ALIASES: Mapping[str, str] = {
    "low": "low",
    "低": "low",
    "不急": "low",
    "normal": "medium",
    "medium": "medium",
    "中": "medium",
    "中等": "medium",
    "high": "high",
    "高": "high",
    "urgent": "high",
    "紧急": "high",
    "trending": "trending",
    "hot": "trending",
    "热点": "trending",
    "热门": "trending",
}


def _canonical(value: Any, aliases: Mapping[str, str], fallback: str) -> str:
    """Map free text onto a contract value, falling back conservatively.

    An unrecognised word becomes ``fallback`` rather than passing through: the
    state contract types these fields as enums, and an unknown value would be
    rejected further downstream where the fix is no longer a one-word edit.
    """
    return aliases.get(str(value or "").strip().lower(), fallback)


def _normalize_hashtags(raw: Sequence[str]) -> list[str]:
    """Exactly one leading ``#`` per tag, blanks dropped, order kept.

    Shape leniency (a bare string, a number) already happened in the model; this
    only settles the contract value.
    """
    tags: list[str] = []
    for item in raw:
        text = item.strip().lstrip("#").strip()
        if text:
            tags.append(f"#{text}")
    return tags


def _normalize_key_points(raw: Sequence[str]) -> list[str]:
    """Blanks dropped, order kept."""
    points: list[str] = []
    for item in raw:
        text = item.strip()
        if text:
            points.append(text)
    return points


def _normalize_timing(raw: str) -> str:
    """ISO 8601 when the model gave something parseable, else its own words.

    Kept as a string either way: the state contract stores text, and a model
    that writes "本周五晚" is stating a real intent. Turning that into a wrong
    timestamp would be worse than keeping it as written.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return text


def normalize_content_plan(output: ContentPlanOutput) -> dict[str, Any]:
    """The state-shaped plan, with the model's slack taken out.

    This is where every leniency decision is settled, so the fields that leave
    here satisfy the state contract regardless of how the model phrased things.
    """
    return {
        "selected_topic": output.selected_topic.strip(),
        "content_angle": output.content_angle.strip(),
        "content_type": _canonical(output.content_type, _CONTENT_TYPE_ALIASES, "note"),
        "target_audience": output.target_audience.strip(),
        "key_points": _normalize_key_points(output.key_points),
        "suggested_timing": _normalize_timing(output.suggested_timing),
        "hashtags": _normalize_hashtags(output.hashtags),
        "urgency": _canonical(output.urgency, _URGENCY_ALIASES, "medium"),
    }


# ── 趋势侦察（trend_scout） ──
#
# 这些模型对齐 ``state/substates.py::TrendData``：那份 TypedDict 才是 state
# 契约，这里的模型只负责"模型怎么写"以及"怎么收敛到它"。
#
# 未建模的键会被 ``extra="ignore"`` 丢掉，这是有意的：能进 state 的键都在这里
# 声明过，模型于是无法定义 state 的形状。代价是模型的自由发挥会被丢 —— 但
# ``TrendData`` 的每个字段都是查过消费者才建的，不是照抄模型可能说的话。


class HotTopicItemOutput(BaseModel):
    """一条热点话题。

    ``topic`` 必填：下游按名字去重、拿去打分、渲染进 prompt，没名字的条目对谁
    都没用。其余全是可选 —— 一个只给出话题名的模型，给的是可用信息。
    """

    model_config = ConfigDict(extra="ignore")

    topic: str = Field(description="话题名称")
    heat_score: float = Field(default=0.0, description="热度分")
    growth_rate: float = Field(default=0.0, description="增长率")
    related_keywords: list[str] = Field(default_factory=list, description="相关关键词")

    @model_validator(mode="before")
    @classmethod
    def _accept_a_named_thing(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            payload = dict(data)
            if not str(payload.get("topic") or "").strip():
                payload["topic"] = _topic_text(payload)
            return payload
        return {"topic": _topic_text(data)}

    @field_validator("heat_score", "growth_rate", mode="before")
    @classmethod
    def _score_as_number(cls, value: Any) -> Any:
        return _as_float(value)


class CompetitorPostOutput(BaseModel):
    """一条竞品笔记。字段对齐 ``state.substates.CompetitorPost``。"""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(default="", description="笔记标题")
    likes: int = Field(default=0, description="点赞数")
    comments: int = Field(default=0, description="评论数")
    author: str = Field(default="", description="作者")

    @field_validator("likes", "comments", mode="before")
    @classmethod
    def _count_as_number(cls, value: Any) -> Any:
        return _as_int(value)


class NicheOpportunityOutput(BaseModel):
    """一个垂类机会。字段对齐 ``state.substates.NicheOpportunity``。"""

    model_config = ConfigDict(extra="ignore")

    topic: str = Field(default="", description="机会话题")
    potential_score: float = Field(default=0.0, description="潜力分")
    audience_match: str = Field(default="", description="受众匹配度")
    entry_barrier: str = Field(default="", description="进入门槛")

    @field_validator("potential_score", mode="before")
    @classmethod
    def _score_as_number(cls, value: Any) -> Any:
        return _as_float(value)


class TrendingNoteOutput(BaseModel):
    """一条热门笔记。

    ``blogger_scout._summarize_trend_data`` 读它的 ``title`` 拼趋势摘要 —— 这是
    一条以前只在模型碰巧输出该键时才有值的读取路径，现在它是声明过的字段。
    """

    model_config = ConfigDict(extra="ignore")

    title: str = Field(default="", description="笔记标题")


class TrendScoutOutput(BaseModel):
    """趋势报告，模型面向的宽松版本。

    刻意**不含** ``data_source``：那是运行时事实（平台可读 / 已降级），由调用方
    在归一化之后写入。让模型能声明它，就是让模型能谎报数据来源 —— 而"全零不是
    数据"这条结论，正是从一次假的 ``data_source="real"`` 里出来的。
    """

    model_config = ConfigDict(extra="ignore")

    hot_topics: list[HotTopicItemOutput] = Field(default_factory=list, description="热点话题")
    trending_keywords: list[str] = Field(default_factory=list, description="趋势关键词")
    trending_notes: list[TrendingNoteOutput] = Field(default_factory=list, description="热门笔记")
    competitor_posts: list[CompetitorPostOutput] = Field(
        default_factory=list, description="竞品笔记"
    )
    niche_opportunities: list[NicheOpportunityOutput] = Field(
        default_factory=list, description="垂类机会"
    )
    market_saturation: Any = Field(default=None, description="市场饱和度（原样透传给 Ripple）")

    @model_validator(mode="before")
    @classmethod
    def _hot_topics_from_its_older_names(cls, data: Any) -> Any:
        """``trending_topics`` / ``topics`` 是 ``hot_topics`` 的历史别名。

        调用点此前各自实现一遍这条别名链；"我怎么称呼这个字段"是模型自己知道的
        事，所以合并发生在这里。
        """
        if not isinstance(data, Mapping):
            return data
        payload = dict(data)
        if not payload.get("hot_topics"):
            for alias in ("trending_topics", "topics"):
                if payload.get(alias):
                    payload["hot_topics"] = payload[alias]
                    break
        return payload

    @field_validator("hot_topics", mode="before")
    @classmethod
    def _only_topics_that_have_a_name(cls, value: Any) -> list[Any]:
        """丢掉没有名字的条目，而不是让整份趋势报告失败。

        "列表里有一项没名字"与"模型没给出趋势"是两件事，前者不该升级成后者。
        """
        return [item for item in _as_list(value) if _topic_text(item)]

    @field_validator("trending_keywords", mode="before")
    @classmethod
    def _keywords_as_text(cls, value: Any) -> list[str]:
        return [text for item in _as_list(value) if (text := _topic_text(item))]


def normalize_trend_data(output: TrendScoutOutput) -> dict[str, Any]:
    """state 形状的趋势数据。

    ``data_source`` 刻意不在这里：调用方写完它，这份数据才算完整，也才不会有人
    误以为"模型产出的 trend_data"含有数据来源。
    """
    return {
        "hot_topics": [item.model_dump() for item in output.hot_topics],
        "trending_keywords": list(output.trending_keywords),
        "trending_notes": [item.model_dump() for item in output.trending_notes],
        "competitor_posts": [item.model_dump() for item in output.competitor_posts],
        "niche_opportunities": [item.model_dump() for item in output.niche_opportunities],
        "market_saturation": output.market_saturation,
    }


# ── 博主候选（blogger_scout） ──


class BloggerCandidateOutput(BaseModel):
    """一个虚拟博主候选。字段对齐 ``state.substates.BloggerProfile``。"""

    model_config = ConfigDict(extra="ignore")

    user_id: str = Field(default="", description="用户 ID")
    nickname: str = Field(default="", description="昵称")
    avatar_url: str = Field(default="", description="头像地址，没有就留空")
    follower_count: int = Field(default=0, description="粉丝数")
    note_count: int = Field(default=0, description="笔记数")
    total_engagement: int = Field(default=0, description="互动总量")
    top_note_title: str = Field(default="", description="代表作标题")

    @field_validator("follower_count", "note_count", "total_engagement", mode="before")
    @classmethod
    def _count_as_number(cls, value: Any) -> Any:
        return _as_int(value)


class BloggerScoutOutput(BaseModel):
    """虚拟博主候选列表。"""

    model_config = ConfigDict(extra="ignore")

    candidates: list[BloggerCandidateOutput] = Field(default_factory=list, description="博主候选")


def normalize_blogger_candidates(output: BloggerScoutOutput, *, limit: int) -> list[dict[str, Any]]:
    """候选列表：补 ``mock_`` 前缀、按 ``limit`` 截断。

    ``mock_`` 前缀是**契约不是装饰**：候选由模型虚构，``user_id`` 必须一眼看得出
    不是真实账号，否则会被当成真实数据用。此前两个调用点各写了一遍这段补齐，现在
    只有一处 —— 而"前缀只在一个地方加"正是它能被信任的原因。
    """
    candidates: list[dict[str, Any]] = []
    for candidate in output.candidates[:limit]:
        payload = candidate.model_dump()
        user_id = str(payload.get("user_id") or "")
        if not user_id.startswith("mock_"):
            payload["user_id"] = f"mock_{user_id or 'unknown'}"
        candidates.append(payload)
    return candidates
