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

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "AnalyticsOutput",
    "BloggerCandidateOutput",
    "BloggerScoutOutput",
    "BriefAnalysisOutput",
    "BriefClarificationOutput",
    "ClarificationQuestionOutput",
    "ContentAnalysisOutput",
    "ContentPlanOutput",
    "ContentVersionOutput",
    "ContentVersionsOutput",
    "CopyContentOutput",
    "EvaluationDimensionOutput",
    "EvaluationPanelOutput",
    "GapItemOutput",
    "HotTopicItemOutput",
    "ShootingAngleOutput",
    "ShootingPlanOutput",
    "StyleVariantOutput",
    "StyleVariantsOutput",
    "SuggestionItemOutput",
    "TrendScoutOutput",
    "ViralPostsOutput",
    "VisualPlanOutput",
    "normalize_analytics",
    "normalize_blogger_candidates",
    "normalize_brief_analysis",
    "normalize_brief_clarification",
    "normalize_content_plan",
    "normalize_content_versions",
    "normalize_copy_content",
    "normalize_evaluation_panel",
    "normalize_optimization_analysis",
    "normalize_shooting_plan",
    "normalize_style_variants",
    "normalize_trend_data",
    "normalize_viral_posts",
    "normalize_visual_plan",
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


def _as_text(value: Any) -> str:
    """Text from whatever the model wrote where a sentence was expected.

    ``None`` becomes ``""`` rather than the literal ``"None"``. The pre-migration
    readers were ``str(raw.get(key, ""))``, which is fine for a missing key and
    writes the four characters ``None`` for an explicit ``null`` — straight into
    a rationale or a summary a human reads. An empty string says "said nothing";
    ``"None"`` says something false.
    """
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _number_or_none(value: Any) -> float | None:
    """A number from a score-ish field, or ``None`` when there is not one.

    Same arithmetic as the pre-migration ``_to_float(value, nan)``; only the
    sentinel differs, and it differs deliberately. Downstream reads the score
    with ``_to_float(score, nan)`` and turns a nan into "this dimension is
    unavailable", so ``None`` and "unparseable" are one thing to it. Folding
    here keeps an unreadable score from failing the whole panel: a missing score
    is a normal input on this path, and a retry spent on one buys nothing.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_TRUE_WORDS = frozenset({"true", "yes", "1", "on"})
_FALSE_WORDS = frozenset({"false", "no", "0", "off"})


def _flag_or_none(value: Any) -> bool | None:
    """A three-state flag → ``bool`` or ``None``; an unreadable spelling reads as
    "not stated".

    The pre-migration readers were ``bool(raw.get(key, default))``, so a missing
    key took the default, an explicit ``null`` fell to ``False``, and a string
    was whatever ``bool()`` says about a non-empty string — which is ``True`` for
    ``"false"``. The bug is not reproduced: a model that writes ``"false"`` meant
    ``False``. ``None`` is *kept* rather than flattened because the flattening
    already has an owner, the ``bool(...)`` inside the evaluator's result
    builder, and doing it here would erase a distinction that owner uses.
    """
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


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


def _non_blank(raw: Sequence[str]) -> list[str]:
    """Text trimmed, blanks dropped, order kept.

    The one leniency every text list in this module finishes with, so that
    "what leaves here" is stated once instead of re-derived by each normaliser.
    """
    return [text for item in raw if (text := item.strip())]


def _normalize_key_points(raw: Sequence[str]) -> list[str]:
    """Blanks dropped, order kept."""
    return _non_blank(raw)


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


# ── 商单 brief 解析（brief_analyzer） ──


class BriefAnalysisOutput(BaseModel):
    """商单 brief 的结构化解析 —— 模型面向的宽松版本。

    只声明**从 brief 文本里读出来**的 13 个字段。``raw_text`` / ``source_type``
    不在其中：那是调用方的事实（原文是什么、来自文本还是 PDF），模型无从陈述，
    因此由调用方在合并时保留。与 ``TrendScoutOutput`` 不含 ``data_source`` 是同一条
    纪律 —— 让模型能声明一个它没有的事实，就是让它能谎报它。
    """

    model_config = ConfigDict(extra="ignore")

    brand_name: str = Field(default="", description="品牌名称")
    product_name: str = Field(default="", description="产品名称")
    product_specs: list[str] = Field(default_factory=list, description="产品规格列表")
    selling_points: list[str] = Field(default_factory=list, description="必提卖点列表")
    required_keywords: list[str] = Field(default_factory=list, description="必含关键词列表")
    required_hashtags: list[str] = Field(default_factory=list, description="必带话题列表")
    optional_hashtags: list[str] = Field(default_factory=list, description="选带话题列表")
    content_direction: str = Field(default="", description="内容方向")
    target_audience: str = Field(default="", description="目标受众")
    style_requirements: str = Field(default="", description="风格/视觉要求")
    shooting_requirements: str = Field(default="", description="拍摄要求")
    notes: list[str] = Field(default_factory=list, description="特殊注意事项列表")
    confidence: float = Field(default=0.5, description="解析置信度 0-1，信息越模糊越低")

    @field_validator(
        "product_specs",
        "selling_points",
        "required_keywords",
        "required_hashtags",
        "optional_hashtags",
        "notes",
        mode="before",
    )
    @classmethod
    def _loose_text_lists(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence_as_number(cls, value: Any) -> Any:
        """数字化**不做换算**，理由见 ``_as_float``。

        两个默认值不同，都是有意的：**缺失**（模型没提置信度）保留调用点原来的
        ``0.5``；**读不懂**（写了 ``"高"``）落到 ``0.0`` —— 模型确实表达了一个我们
        读不出来的判断，对它最保守的读法就是"最没把握"，而最没把握会把这条 brief
        送去问用户，这是这里唯一安全的错法。
        """
        return _as_float(value)


def normalize_brief_analysis(output: BriefAnalysisOutput) -> dict[str, Any]:
    """state 形状的 brief 解析结果。

    话题标签**原样保留**（只去首尾空白与空项），不加 ``#``：商单必带/选带话题是
    **品牌方的原文**，"带不带 #"是品牌的写法，不是模型的口误。``normalize_content_plan``
    里的 ``hashtags`` 不同 —— 那些是模型自己生成的推荐标签，``#`` 前缀是我们向它
    要求的格式。两处看起来在做同一件事，判据（谁写的内容）不一样。
    """
    return {
        "brand_name": output.brand_name.strip(),
        "product_name": output.product_name.strip(),
        "product_specs": _non_blank(output.product_specs),
        "selling_points": _non_blank(output.selling_points),
        "required_keywords": _non_blank(output.required_keywords),
        "required_hashtags": _non_blank(output.required_hashtags),
        "optional_hashtags": _non_blank(output.optional_hashtags),
        "content_direction": output.content_direction.strip(),
        "target_audience": output.target_audience.strip(),
        "style_requirements": output.style_requirements.strip(),
        "shooting_requirements": output.shooting_requirements.strip(),
        "notes": _non_blank(output.notes),
        "confidence": output.confidence,
    }


class ClarificationQuestionOutput(BaseModel):
    """一条澄清问题。

    ``extra="allow"``，与这个文件里其它模型都不同，理由是契约不同：
    ``BriefClarification.questions`` 声明为 ``list[dict[str, Any]]``，**故意不设形状**，
    因为它直接进 UI 让用户作答。在一个不设形状的契约上丢掉未建模的键，是这次迁移
    唯一会静默少送字段到前端的动作。对照 ``TrendScoutOutput``：那里的契约是
    TypedDict，丢掉未声明的键正是"能进 state 的键都在这里声明过"的兑现。
    """

    model_config = ConfigDict(extra="allow")

    field: str = Field(default="", description="需要澄清的字段名")
    question: str = Field(default="", description="向用户提出的问题")
    options: list[str] = Field(default_factory=list, description="建议选项列表")
    inferred_value: Any = Field(default=None, description="模型推断的默认值")

    @field_validator("options", mode="before")
    @classmethod
    def _loose_options(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)


class BriefClarificationOutput(BaseModel):
    """澄清问题列表 —— 顶层可能是**裸数组**。

    模型两种写法都出现过（``[{...}]`` 与 ``{"questions": [{...}]}``），旧调用点两种
    都收：``parsed if isinstance(parsed, list) else parsed.get("questions", [])``。
    实测 ``_parse_json_response`` 对两种写法分别返回 list 与 dict，所以这不是死代码。
    数组的语义从字段名就唯一确定（问题列表），因此直接声明 ``accepts_bare_list``，
    而不是让链条先拒一次再纠正 —— 那一拒在旧实现里根本不存在。
    """

    model_config = ConfigDict(extra="ignore")

    accepts_bare_list: ClassVar[bool] = True

    questions: list[ClarificationQuestionOutput] = Field(
        default_factory=list, description="澄清问题列表"
    )

    @model_validator(mode="before")
    @classmethod
    def _a_bare_array_is_the_question_list(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"questions": data}
        return data


def normalize_brief_clarification(output: BriefClarificationOutput) -> list[dict[str, Any]]:
    """问题列表，原样交给前端（每个问题收敛成一个 dict）。"""
    return [question.model_dump() for question in output.questions]


# ── 数据分析（analyst） ──


class AnalyticsOutput(BaseModel):
    """帖子的分析报告 —— 模型面向的宽松版本。

    键来自两处证据：``analyst.yaml`` 向模型要的 7 个，加上
    ``api/routes/analytics.py::_extract_post_data`` 真的会去读的计数字段。后者值得
    单说：那 5 个计数不在提示词里，模型是从同一提示词里的"帖子数据"抄回来的，
    抄回来它们就进 state、进报表；不抄则缺失。声明它们让"缺失"变成一个有默认值的
    字段，而不是一个看运气是否存在的键。

    契约里的 ``post_id`` / ``timestamp`` 刻意不建模：它们不是模型能陈述的事实。
    ``analyst`` 是 ``state["analytics"]`` 的唯一写入者（``routes/free.py`` 那条
    自由创作路径也返回一个同名快照，但它不进 state）。
    """

    model_config = ConfigDict(extra="ignore")

    insights: list[str] = Field(default_factory=list, description="数据洞察")
    recommendations: list[str] = Field(default_factory=list, description="优化建议")
    engagement_rate: float = Field(default=0.0, description="互动率（占比，不是百分数）")
    reach_rate: float = Field(default=0.0, description="触达率（占比）")
    views: int = Field(default=0, description="浏览量")
    likes: int = Field(default=0, description="点赞数")
    collects: int = Field(default=0, description="收藏数")
    comments: int = Field(default=0, description="评论数")
    shares: int = Field(default=0, description="分享数")
    best_performing_type: str = Field(default="", description="表现最好的内容类型")
    best_performing_time: str = Field(default="", description="表现最好的发布时段")
    top_hashtags: list[str] = Field(default_factory=list, description="表现最好的话题标签")

    @field_validator("insights", "recommendations", "top_hashtags", mode="before")
    @classmethod
    def _loose_text_lists(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)

    @field_validator("engagement_rate", "reach_rate", mode="before")
    @classmethod
    def _rate_as_number(cls, value: Any) -> Any:
        return _as_float(value)

    @field_validator("views", "likes", "collects", "comments", "shares", mode="before")
    @classmethod
    def _count_as_number(cls, value: Any) -> Any:
        return _as_int(value)


def normalize_analytics(output: AnalyticsOutput) -> dict[str, Any]:
    """state 形状的分析报告。

    ``ripple_comparison`` 不在这里：它是调用方把预测与实际比出来的结论，写在一个
    模型不可能知道的位置上（见 ``analyst.execute``）。
    """
    return {
        "insights": _non_blank(output.insights),
        "recommendations": _non_blank(output.recommendations),
        "engagement_rate": output.engagement_rate,
        "reach_rate": output.reach_rate,
        "views": output.views,
        "likes": output.likes,
        "collects": output.collects,
        "comments": output.comments,
        "shares": output.shares,
        "best_performing_type": output.best_performing_type.strip(),
        "best_performing_time": output.best_performing_time.strip(),
        "top_hashtags": _non_blank(output.top_hashtags),
    }


# ── 草稿与爆款的差距分析（content_analyzer） ──


class GapItemOutput(BaseModel):
    """一个差距项。字段对齐 ``state.substates.GapItem``。"""

    model_config = ConfigDict(extra="ignore")

    dimension: str = Field(default="", description="差距维度")
    description: str = Field(default="", description="具体描述")
    severity: str = Field(default="", description="严重程度：high / medium / low")


class SuggestionItemOutput(BaseModel):
    """一条优化建议。

    ``priority`` 在 ``SuggestionItem`` 契约里，也在 ``content_analyzer.yaml``
    的示例里（``"priority": 1``），而且真被读：``version_generator`` 两处都按
    ``s.get('priority', 3)`` 把它渲染进下一个提示词。所以它是一个**有消费者**的
    字段，默认值取消费者自己兜的那个 3，而不是另发明一个。
    """

    model_config = ConfigDict(extra="ignore")

    dimension: str = Field(default="", description="建议维度")
    action: str = Field(default="", description="具体行动")
    reasoning: str = Field(default="", description="理由")
    priority: int = Field(default=3, description="优先级 1-5，1 最高")

    @field_validator("priority", mode="before")
    @classmethod
    def _priority_as_number(cls, value: Any) -> Any:
        return _as_int(value)


class OptimizationAnalysisOutput(BaseModel):
    """差距 / 建议 / 爆款模式三件套。字段对齐 ``state.substates.OptimizationAnalysis``。"""

    model_config = ConfigDict(extra="ignore")

    gaps: list[GapItemOutput] = Field(default_factory=list, description="差距项列表")
    suggestions: list[SuggestionItemOutput] = Field(
        default_factory=list, description="优化建议列表"
    )
    viral_patterns: list[str] = Field(default_factory=list, description="爆款模式总结")

    @field_validator("viral_patterns", mode="before")
    @classmethod
    def _loose_patterns(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)


class ContentAnalysisOutput(BaseModel):
    """``{"optimization_analysis": {...}}`` —— 外层是模型给的信封。

    信封刻意保留：调用点拿到的是它，而重写成"模型直接给内层对象"会把提示词一起
    改掉（红线：prompt 字节不变）。
    """

    model_config = ConfigDict(extra="ignore")

    optimization_analysis: OptimizationAnalysisOutput = Field(
        default_factory=OptimizationAnalysisOutput
    )


def normalize_optimization_analysis(output: ContentAnalysisOutput) -> dict[str, Any]:
    """state 形状的优化分析。

    三个键**总是**在，空的部分是空列表。旧调用点缺键时另手写了一份一模一样的空
    结构，于是"空分析长什么样"有两个来源；这里让它只剩一个。
    """
    inner = output.optimization_analysis
    return {
        "gaps": [gap.model_dump() for gap in inner.gaps],
        "suggestions": [suggestion.model_dump() for suggestion in inner.suggestions],
        "viral_patterns": _non_blank(inner.viral_patterns),
    }


# ── 爆款参考（viral_matcher） ──


class ViralPostOutput(BaseModel):
    """一条爆款参考笔记。字段对齐 ``state.substates.ViralPost``。"""

    model_config = ConfigDict(extra="ignore")

    note_id: str = Field(default="", description="笔记 ID")
    title: str = Field(default="", description="标题")
    body: str = Field(default="", description="正文")
    hashtags: list[str] = Field(default_factory=list, description="话题标签")
    cover_url: str = Field(default="", description="封面地址")
    image_urls: list[str] = Field(default_factory=list, description="图片地址列表")
    likes: int = Field(default=0, description="点赞数")
    collects: int = Field(default=0, description="收藏数")
    comments: int = Field(default=0, description="评论数")
    engagement_rate: float = Field(default=0.0, description="互动率")
    visual_style: str = Field(default="", description="视觉风格分类")
    color_palette: dict[str, str] = Field(default_factory=dict, description="颜色主调")

    @field_validator("hashtags", "image_urls", mode="before")
    @classmethod
    def _loose_text_lists(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)

    @field_validator("likes", "collects", "comments", mode="before")
    @classmethod
    def _count_as_number(cls, value: Any) -> Any:
        return _as_int(value)

    @field_validator("engagement_rate", mode="before")
    @classmethod
    def _rate_as_number(cls, value: Any) -> Any:
        return _as_float(value)

    @field_validator("color_palette", mode="before")
    @classmethod
    def _palette_as_mapping(cls, value: Any) -> Any:
        """非映射的调色板落到 ``{}`` 而不是让整批爆款失败。

        它是渲染进下一个提示词的一行装饰（``content_analyzer._build_viral_summary``
        原样透传），而它所在的条目是那批参考笔记本身 —— 拿整批笔记换一个色卡是
        明显划不来的交易。
        """
        return value if isinstance(value, Mapping) else {}


class ViralPostsOutput(BaseModel):
    """``{"viral_posts": [...]}``，也接受裸数组（数组的语义由字段名唯一确定）。

    ``search_keywords_used`` 是提示词会附带产出的键，刻意不建模：旧调用点本来
    就只取 ``result.get("viral_posts", [])``，所以丢掉它不是这次迁移引入的变化。
    """

    model_config = ConfigDict(extra="ignore")

    accepts_bare_list: ClassVar[bool] = True

    viral_posts: list[ViralPostOutput] = Field(default_factory=list, description="爆款参考笔记")

    @model_validator(mode="before")
    @classmethod
    def _a_bare_array_is_the_post_list(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"viral_posts": data}
        return data


def normalize_viral_posts(output: ViralPostsOutput) -> list[dict[str, Any]]:
    """爆款参考列表，``ViralPost`` 形状。"""
    return [post.model_dump() for post in output.viral_posts]


# ── 创作质量评估面板（evaluator） ──


class EvaluationDimensionOutput(BaseModel):
    """The panel's answer for one dimension.

    This declares **the half a model can state** — scores, reasons, problems, a
    blocking flag. ``overall_score`` and ``decision`` are deliberately absent,
    and not by omission: ``evaluator._build_evaluation_result`` recomputes both
    from fixed rules (RQGM's verifiable-metric + judge-signal split), precisely
    so a judge panel's own verdict is not trusted. Modelling them as model
    fields would hand that rule straight back to the model. The prompt's example
    asks for them anyway; ``extra="ignore"`` is what makes that harmless.

    ``available`` is an *internal* concept — the prompt's example does not carry
    it, and the pre-migration reader defaulted it to ``True`` and then ANDed it
    with "the score parsed". It stays modelled because a model that writes it
    means it, and reading ``false`` as ``true`` would invent usable evidence.
    """

    model_config = ConfigDict(extra="ignore")

    dimension: str = Field(default="", description="维度名，如 copywriting/compliance/altruism")
    score: float | None = Field(default=None, description="该维度得分 0-100；无法评分时省略")
    available: bool | None = Field(default=True, description="该维度是否给出了可用的分数")
    rationale: str = Field(default="", description="评分理由")
    issues: list[str] = Field(default_factory=list, description="该维度发现的问题")
    is_blocking: bool | None = Field(default=False, description="是否阻塞发布（合规硬伤）")
    bias_severity: float | None = Field(
        default=None, description="bias_check 专用：检测到的偏倚严重度 0-100"
    )

    @field_validator("dimension", "rationale", mode="before")
    @classmethod
    def _text_fields(cls, value: Any) -> str:
        return _as_text(value)

    @field_validator("score", "bias_severity", mode="before")
    @classmethod
    def _number_fields(cls, value: Any) -> float | None:
        return _number_or_none(value)

    @field_validator("available", "is_blocking", mode="before")
    @classmethod
    def _flag_fields(cls, value: Any) -> bool | None:
        return _flag_or_none(value)

    @field_validator("issues", mode="before")
    @classmethod
    def _loose_issues(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)


class EvaluationPanelOutput(BaseModel):
    """The judge panel's answer: dimensions, hints, a summary.

    The evaluator's deterministic rebuild consumes exactly these keys off the raw
    payload, so nothing here is decoration — ``bias_warning`` is read only on the
    historical-note path (the workflow path computes its own from the
    ``bias_check`` dimension).
    """

    model_config = ConfigDict(extra="ignore")

    dimensions: list[EvaluationDimensionOutput] = Field(
        default_factory=list, description="各维度评分面板"
    )
    revision_hints: list[str] = Field(default_factory=list, description="具体可执行的修订指令")
    summary: str = Field(default="", description="一句话总评")
    bias_warning: str = Field(default="", description="面板偏倚警告")

    @field_validator("revision_hints", mode="before")
    @classmethod
    def _loose_hints(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)

    @field_validator("summary", "bias_warning", mode="before")
    @classmethod
    def _text_fields(cls, value: Any) -> str:
        return _as_text(value)


def normalize_evaluation_panel(output: EvaluationPanelOutput) -> dict[str, Any]:
    """The raw-payload shape ``_build_evaluation_result`` reads.

    A dict rather than the model, because that builder is the other half of this
    design: it owns the recomputation, the coverage arithmetic and the
    never-invent-a-neutral-score补齐. Handing it a typed object would put the
    two halves of one calculation in two modules; handing it this dict keeps the
    migration to "how the payload is obtained and checked".

    ``available``/``is_blocking``/``bias_severity`` are emitted even when unset —
    the builder reads them with ``.get(key, default)`` and ``_to_float(None,
    -1.0)``, where an absent key and an explicit ``None`` are the same input.
    """
    dimensions: list[dict[str, Any]] = [
        {
            "dimension": dim.dimension,
            "score": dim.score,
            "available": dim.available,
            "rationale": dim.rationale,
            "issues": dim.issues,
            "is_blocking": dim.is_blocking,
            "bias_severity": dim.bias_severity,
        }
        for dim in output.dimensions
    ]
    return {
        "dimensions": dimensions,
        "revision_hints": _non_blank(output.revision_hints),
        "summary": output.summary,
        "bias_warning": output.bias_warning,
    }


# ── 文案与版本（copywriter / version_generator） ──


def _version_id_or_new(value: str) -> str:
    """A version id, minted when the model left one out.

    Both pre-migration call sites assigned ``str(uuid.uuid4())[:8]`` to a parsed
    variant *after* parsing and before returning it, so the id belongs to "what
    leaves", not to "what the model said" — settled here rather than at the two
    call sites that would otherwise each need to remember.
    """
    return value.strip() or str(uuid.uuid4())[:8]


class CopyContentOutput(BaseModel):
    """``copywriter`` 的正文产物，字段对齐 ``state.substates.CopyContent``。

    The prompt's seven keys are the contract's seven keys, so nothing is left
    out or invented. ``copywriter._apply_de_ai_taste`` later adds ``de_ai_*``
    keys to the normalised dict — those are the *outcome* of a polish call, not
    part of what the model answered, which is why they are not modelled here.

    ``selected_title``/``body_text`` also answer to ``title``/``body``: the
    variant prompt in the same module asks for those names, the model crosses
    them over often enough that ``_apply_de_ai_taste`` grew a manual
    ``.get("selected_title") or .get("title")`` fallback for it, and a retry
    spent on a field the model *did* answer would be buying nothing.
    """

    model_config = ConfigDict(extra="ignore")

    title_candidates: list[str] = Field(default_factory=list, description="标题候选")
    selected_title: str = Field(
        default="",
        validation_alias=AliasChoices("selected_title", "title"),
        description="从候选中选定的标题",
    )
    body_text: str = Field(
        default="",
        validation_alias=AliasChoices("body_text", "body"),
        description="正文内容",
    )
    hashtags: list[str] = Field(default_factory=list, description="话题标签")
    cta: str = Field(default="", description="互动号召语")
    emoji_usage: list[str] = Field(default_factory=list, description="使用的 emoji")
    tone: str = Field(default="", description="语气：亲切/专业/幽默")

    @field_validator("title_candidates", "hashtags", "emoji_usage", mode="before")
    @classmethod
    def _loose_text_lists(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)

    @field_validator("selected_title", "body_text", "cta", "tone", mode="before")
    @classmethod
    def _text_fields(cls, value: Any) -> str:
        return _as_text(value)


def normalize_copy_content(output: CopyContentOutput) -> dict[str, Any]:
    """``CopyContent`` 形状。

    ``hashtags`` goes through ``_non_blank`` rather than
    ``_normalize_hashtags``: the downstream reader is
    ``publisher._as_str_list``, which passes tags through untouched, so the
    tags that leave here are the tags the model wrote.
    """
    return {
        "title_candidates": _non_blank(output.title_candidates),
        "selected_title": output.selected_title,
        "body_text": output.body_text,
        "hashtags": _non_blank(output.hashtags),
        "cta": output.cta,
        "emoji_usage": _non_blank(output.emoji_usage),
        "tone": output.tone,
    }


class _ContentVersionFields(BaseModel):
    """``content_versions`` 元素在两个来源之间共享的 11 个字段。

    ``copywriter`` 的多风格变体与 ``version_generator`` 的 A/B/C 版本写进**同
    一个** state 键，下游读者（``choice_gate``、``state.artifacts``、OMP 的
    ``review_versions``、前端 ``optimization.ts``）不区分来源 —— 所以两个输出
    模型的字段集必须同构，一个基类是让「同构」只有一个归属地的方式。

    这也是这里字段比提示词多三个的原因：``image_prompts`` /
    ``changes_summary`` / ``predicted_score`` 不在任何一条提示词里，但它们是
    ``state.substates.ContentVersion`` 的成员且有真实读者。提示词是给模型的
    **指示**，契约是可接受的**答案空间**；把契约里的键拒掉，等于把一个模型
    自发补上的字段从 state 里删掉。
    """

    model_config = ConfigDict(extra="ignore")

    version_id: str = Field(default="", description="版本 ID")
    title: str = Field(default="", description="标题（含 emoji）")
    body: str = Field(default="", description="正文内容")
    hashtags: list[str] = Field(default_factory=list, description="话题标签")
    image_prompts: list[str] = Field(default_factory=list, description="配图提示词")
    style_suggestion: str = Field(default="", description="视觉风格建议")
    changes_summary: str = Field(default="", description="本版改了什么")
    predicted_score: float = Field(default=0.0, description="预测得分")
    tone: str = Field(default="", description="语气描述")
    visual_style: str = Field(default="", description="视觉风格关键词")
    color_palette: dict[str, str] = Field(default_factory=dict, description="配色方案")

    @field_validator("hashtags", "image_prompts", mode="before")
    @classmethod
    def _loose_text_lists(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)

    @field_validator("color_palette", mode="before")
    @classmethod
    def _palette_or_empty(cls, value: Any) -> Any:
        """非映射的配色落到 ``{}``，而不是拿三个版本换一个色卡。

        Both prompts ask for a mapping here
        (``primary``/``secondary``/``accent``) — the opposite of the visual
        plan's bare list. Shape follows each prompt, not the word "palette".
        """
        return value if isinstance(value, Mapping) else {}

    @field_validator("predicted_score", mode="before")
    @classmethod
    def _score_as_number(cls, value: Any) -> Any:
        return _as_float(value)

    @field_validator(
        "version_id",
        "title",
        "body",
        "style_suggestion",
        "changes_summary",
        "tone",
        "visual_style",
        mode="before",
    )
    @classmethod
    def _text_fields(cls, value: Any) -> str:
        return _as_text(value)

    def _shared_payload(self) -> dict[str, Any]:
        """归一化后的共享键。

        The three contract-only keys leave **only when the model wrote them**.
        Their absence carries meaning downstream — ``omp_bridge`` does
        ``v.get("changes_summary", "draft")`` and ``artifacts`` does
        ``version.get("predicted_score", 0.0)`` — so emitting a default for a
        key the model never wrote would turn "said nothing" into "said it is
        empty" and quietly delete the placeholder every existing version was
        falling back to.
        """
        payload: dict[str, Any] = {
            "version_id": _version_id_or_new(self.version_id),
            "title": self.title,
            "body": self.body,
            "hashtags": _non_blank(self.hashtags),
            "style_suggestion": self.style_suggestion,
            "tone": self.tone,
            "visual_style": self.visual_style,
            "color_palette": dict(self.color_palette),
        }
        if "image_prompts" in self.model_fields_set:
            payload["image_prompts"] = _non_blank(self.image_prompts)
        if "changes_summary" in self.model_fields_set:
            payload["changes_summary"] = self.changes_summary
        if "predicted_score" in self.model_fields_set:
            payload["predicted_score"] = self.predicted_score
        return payload


class StyleVariantOutput(_ContentVersionFields):
    """``copywriter`` 多风格生成里的一个版本：共享字段 + ``style_name``。"""

    style_name: str = Field(default="", description="风格名称")

    @field_validator("style_name", mode="before")
    @classmethod
    def _style_name_as_text(cls, value: Any) -> str:
        return _as_text(value)

    def as_payload(self) -> dict[str, Any]:
        return {"style_name": self.style_name, **self._shared_payload()}


class StyleVariantsOutput(BaseModel):
    """``{"variants": [...]}``.

    No ``accepts_bare_list``: the pre-migration reader was
    ``parsed.get("variants", [])``, which *fails* on a bare array. Declaring
    one here would be a widening smuggled into a migration — leaving it out
    means a bare array takes the correction path instead, which is strictly
    better than the crash it used to get.
    """

    model_config = ConfigDict(extra="ignore")

    variants: list[StyleVariantOutput] = Field(default_factory=list, description="风格版本列表")


def normalize_style_variants(output: StyleVariantsOutput) -> list[dict[str, Any]]:
    """风格版本列表，``ContentVersion`` 形状（每个都带 ``version_id``）。"""
    return [variant.as_payload() for variant in output.variants]


class ContentVersionOutput(_ContentVersionFields):
    """``version_generator`` 的 A/B/C 版本之一：共享字段 + ``version_type``。"""

    version_type: str = Field(default="", description="版本类型：conservative/balanced/aggressive")

    @field_validator("version_type", mode="before")
    @classmethod
    def _version_type_as_text(cls, value: Any) -> str:
        return _as_text(value)

    def as_payload(self) -> dict[str, Any]:
        return {"version_type": self.version_type, **self._shared_payload()}


class ContentVersionsOutput(BaseModel):
    """``{"versions": [...]}``；裸数组的处理同 :class:`StyleVariantsOutput`。"""

    model_config = ConfigDict(extra="ignore")

    versions: list[ContentVersionOutput] = Field(default_factory=list, description="A/B/C 版本列表")


def normalize_content_versions(output: ContentVersionsOutput) -> list[dict[str, Any]]:
    """``ContentVersion`` 形状的版本列表（每个都带 ``version_id``）。

    与 :func:`normalize_style_variants` 的全部差别就是那个判别键：两个来源写
    进同一个 state 键，所以元素形状由 :class:`_ContentVersionFields` 统一决定。
    """
    return [version.as_payload() for version in output.versions]


# ── 视觉计划（visual_designer） ──


class VisualPlanOutput(BaseModel):
    """``visual_designer`` 的视觉计划，字段对齐提示词的输出规范。

    ``color_palette`` here is a **bare list of colours**, not the mapping
    ``ViralPostOutput`` carries: the consumers are
    ``StyleDNA.color_palette: list[str]`` and ``publisher._as_str_list``.
    Copying the mapping shape over would drop a ``{}`` into an ``f"{a}{b}"``
    and render ``"{}{}"`` into a downstream prompt.

    ``image_count`` goes through ``_as_int`` because the prompt writes it as
    ``N`` and Chinese models answer "3" or "3张" — the suffix table already
    handles the units this field sees.
    """

    model_config = ConfigDict(extra="ignore")

    cover_prompt: str = Field(default="", description="封面 AI 绘画提示词")
    image_count: int = Field(default=0, description="图片数量")
    image_prompts: list[str] = Field(default_factory=list, description="各图提示词")
    visual_style: str = Field(default="", description="视觉风格：ins风/极简/复古/温暖治愈等")
    layout_preference: str = Field(default="", description="排版偏好：九宫格/四宫格/单图")
    color_palette: list[str] = Field(default_factory=list, description="配色方案（色值列表）")
    font_suggestion: str = Field(default="", description="字体建议")
    brand_elements: list[str] = Field(default_factory=list, description="品牌元素")

    @field_validator("image_prompts", "color_palette", "brand_elements", mode="before")
    @classmethod
    def _loose_text_lists(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)

    @field_validator("image_count", mode="before")
    @classmethod
    def _count_as_number(cls, value: Any) -> Any:
        return _as_int(value)

    @field_validator(
        "cover_prompt",
        "visual_style",
        "layout_preference",
        "font_suggestion",
        mode="before",
    )
    @classmethod
    def _text_fields(cls, value: Any) -> str:
        return _as_text(value)


def normalize_visual_plan(output: VisualPlanOutput) -> dict[str, Any]:
    """``VisualPlan`` 形状 —— 键集**刻意**与提示词一致。

    ``evaluator``/``public_showcase``/``review`` read ``layout_style``, a key
    the prompt and the old parse result never carried: they have always fallen
    back to their own defaults. Adding it here would change what a reader that
    was never fed the key now sees, which is a behaviour change wearing a
    migration's clothes.

    ``style_id`` is *not* emitted: the call site writes it back after
    ``deposit_style`` when creative memory returns one.
    """
    return {
        "cover_prompt": output.cover_prompt,
        "image_count": output.image_count,
        "image_prompts": _non_blank(output.image_prompts),
        "visual_style": output.visual_style,
        "layout_preference": output.layout_preference,
        "color_palette": _non_blank(output.color_palette),
        "font_suggestion": output.font_suggestion,
        "brand_elements": _non_blank(output.brand_elements),
    }


# ── 拍摄计划（shooting_planner） ──


class ShootingAngleOutput(BaseModel):
    """一个拍摄角度 —— ``state.substates.ShootingPlan.shooting_angles`` 的项。"""

    model_config = ConfigDict(extra="ignore")

    description: str = Field(default="", description="角度描述")
    reference_image: str = Field(default="", description="参考图")

    @field_validator("description", "reference_image", mode="before")
    @classmethod
    def _text_fields(cls, value: Any) -> str:
        return _as_text(value)


class ShootingPlanOutput(BaseModel):
    """商单拍摄计划，16 个字段与 ``state.substates.ShootingPlan`` 逐一对齐。

    ``outfits`` is the one nested mapping here — ``{角色: [服装选项]}``.
    """

    model_config = ConfigDict(extra="ignore")

    creator_nickname: str = Field(default="", description="达人昵称")
    content_direction: str = Field(default="", description="内容方向")
    content_type_label: str = Field(default="", description="图文内容标签")
    profile_link: str = Field(default="", description="主页链接")
    creator_level: str = Field(default="", description="达人量级")
    planned_publish_date: str = Field(default="", description="预计发布日期")
    product_specification: str = Field(default="", description="产品规格描述")
    draft_requirements: list[str] = Field(default_factory=list, description="初稿要求")
    draft_notes: list[str] = Field(default_factory=list, description="初稿注意事项")
    title_candidates: list[str] = Field(default_factory=list, description="标题备选")
    body_copy: str = Field(default="", description="文案（含必提卖点与必含关键词）")
    required_hashtags: list[str] = Field(default_factory=list, description="必带话题")
    optional_hashtags: list[str] = Field(default_factory=list, description="选带话题")
    suggested_hashtags: list[str] = Field(default_factory=list, description="建议的热门话题")
    outfits: dict[str, list[str]] = Field(default_factory=dict, description="{角色: [服装选项]}")
    shooting_angles: list[ShootingAngleOutput] = Field(
        default_factory=list, description="拍摄角度建议"
    )

    @field_validator(
        "draft_requirements",
        "draft_notes",
        "title_candidates",
        "required_hashtags",
        "optional_hashtags",
        "suggested_hashtags",
        mode="before",
    )
    @classmethod
    def _loose_text_lists(cls, value: Any) -> list[str]:
        return _list_items_as_text(value)

    @field_validator("outfits", mode="before")
    @classmethod
    def _outfits_as_mapping(cls, value: Any) -> Any:
        """非映射的服装建议落到 ``{}``，值统一成字符串列表。

        ``{角色: [服装选项]}`` is this template's own shape. A model that
        answers ``[{角色, 服装}]`` has answered a different question, and
        guessing which field is the role would invent a costume for a person
        nobody named.
        """
        if not isinstance(value, Mapping):
            return {}
        return {str(role): _list_items_as_text(items) for role, items in value.items()}

    @field_validator("shooting_angles", mode="before")
    @classmethod
    def _angles_as_descriptions(cls, value: Any) -> Any:
        """A bare sentence where the list belongs becomes one angle, not its characters.

        The prompt asks for ``[{description: …}]``, so a model that answers
        ``"低角度仰拍"`` has described exactly one angle. Letting Pydantic
        reject it would spend a retry on a field the model did answer, and
        ``_as_list`` is what keeps the string whole instead of iterating it.
        An entry that is neither a mapping nor text is dropped: it described
        no angle.
        """
        angles: list[Any] = []
        for item in _as_list(value):
            if isinstance(item, Mapping):
                angles.append(item)
            elif item is not None and str(item).strip():
                angles.append({"description": str(item)})
        return angles

    @field_validator(
        "creator_nickname",
        "content_direction",
        "content_type_label",
        "profile_link",
        "creator_level",
        "planned_publish_date",
        "product_specification",
        "body_copy",
        mode="before",
    )
    @classmethod
    def _text_fields(cls, value: Any) -> str:
        return _as_text(value)


def normalize_shooting_plan(output: ShootingPlanOutput) -> dict[str, Any]:
    """``ShootingPlan`` 形状（16 个契约键）。

    A whole document rather than a projection: the call site stops this object
    into state as-is, and every key here is one the template renders.
    """
    return {
        "creator_nickname": output.creator_nickname,
        "content_direction": output.content_direction,
        "content_type_label": output.content_type_label,
        "profile_link": output.profile_link,
        "creator_level": output.creator_level,
        "planned_publish_date": output.planned_publish_date,
        "product_specification": output.product_specification,
        "draft_requirements": _non_blank(output.draft_requirements),
        "draft_notes": _non_blank(output.draft_notes),
        "title_candidates": _non_blank(output.title_candidates),
        "body_copy": output.body_copy,
        "required_hashtags": _non_blank(output.required_hashtags),
        "optional_hashtags": _non_blank(output.optional_hashtags),
        "suggested_hashtags": _non_blank(output.suggested_hashtags),
        "outfits": {role: _non_blank(items) for role, items in output.outfits.items()},
        "shooting_angles": [angle.model_dump() for angle in output.shooting_angles],
    }
