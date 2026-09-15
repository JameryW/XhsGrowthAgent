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

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["ContentPlanOutput", "normalize_content_plan"]


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
