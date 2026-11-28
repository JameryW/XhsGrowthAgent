"""Account-level visual memory contracts (ledger scheme #45).

The ledger's #45 asks for a *persistent* visual memory: an account should keep a
recognisable "visual hammer" (colour palette, title weight, recurring subject)
across weeks, while the per-scene layout preference should move with real
feedback instead of being regenerated from scratch every run.

:class:`backend.services.interaction_contracts.SceneVisualMemoryBank` already
models the two layers — an immutable :class:`VisualDna` plus feedback-revisable
:class:`SceneVisualProfile` entries. This module gives that bank a durable home
in the LangGraph ``BaseStore`` and the deterministic glue the workflow needs:

- ``build_directive`` reads the bank and composes the designer directive;
- ``apply_directive`` fills the gaps in a generated plan and reports drift, but
  never silently rewrites a designer's choice;
- ``ensure_dna`` freezes the anchors on the first run and never overwrites them;
- ``record_scene_feedback`` moves one scene weight only when a real outcome
  carries a baseline and enough samples.

Everything here is deterministic — no LLM call, no embedding, no network. The
switch ``XHS_VISUAL_MEMORY`` is opt-in; when it is off the call sites must
produce byte-identical output to before (no new plan keys, no store traffic).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from backend.services.interaction_contracts import (
    SceneVisualMemoryBank,
    SceneVisualProfile,
    VisualDna,
    build_visual_directive,
)

logger = logging.getLogger("xhs_growth.services.visual_memory")

__all__ = [
    "VISUAL_MEMORY_ENV",
    "apply_directive",
    "build_directive",
    "directive_prompt",
    "ensure_dna",
    "feedback_score",
    "load_bank",
    "load_dna",
    "load_scenes",
    "record_scene_feedback",
    "record_scene_feedback_if_enabled",
    "save_dna",
    "save_scenes",
    "scene_for",
    "visual_memory_enabled",
]

VISUAL_MEMORY_ENV = "XHS_VISUAL_MEMORY"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_NAMESPACE_SUFFIX = "visual_memory"
_DNA_KEY = "dna"
_SCENES_KEY = "scenes"
#: One or two notes are noise; a scene weight only moves with a real baseline.
_MIN_FEEDBACK_SAMPLES = 3
#: ``title_weight_ratio`` tolerance before a plan counts as drifting from DNA.
_TITLE_WEIGHT_TOLERANCE = 0.3
_COLLECT_WEIGHT = 0.7
_VIEW_WEIGHT = 0.3

#: First matching scene wins; keys mirror ``DEFAULT_SCENE_LAYOUTS`` exactly.
_SCENE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("food", ("美食", "餐厅", "探店", "食谱", "烘焙", "咖啡", "小吃", "火锅")),
    (
        "travel",
        ("旅行", "旅游", "自驾", "攻略", "川西", "新疆", "路线", "酒店", "民宿", "露营", "门票"),
    ),
    ("outfit", ("穿搭", "服装", "时尚", "ootd", "配饰", "鞋", "包")),
    ("beauty", ("美妆", "护肤", "化妆", "口红", "面膜", "发型", "底妆")),
    ("fitness", ("健身", "运动", "减脂", "瑜伽", "训练", "跑步", "增肌")),
    ("home", ("家居", "装修", "收纳", "租房", "房间", "软装", "改造")),
    ("lifestyle", ("生活", "日常", "vlog", "效率", "学习", "情绪", "好物")),
)


def visual_memory_enabled() -> bool:
    """Whether the opt-in visual-memory wiring is active."""
    return os.environ.get(VISUAL_MEMORY_ENV, "").strip().lower() in _TRUTHY


def scene_for(*, niche: str = "", content_type: str = "") -> str:
    """Map a Chinese niche/content type onto one ``DEFAULT_SCENE_LAYOUTS`` key."""
    haystack = f"{niche} {content_type}".strip().lower()
    for scene, keywords in _SCENE_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return scene
    # ``lifestyle`` is the bank's own fallback key, so an unknown niche still
    # reads and writes the same scene on both sides.
    return "lifestyle"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Sequence):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _clip_unit(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _namespace(account_id: str) -> tuple[str, str, str]:
    return ("accounts", _text(account_id) or "default", _NAMESPACE_SUFFIX)


def _dna_from_mapping(value: Any, account_id: str) -> VisualDna | None:
    if not isinstance(value, Mapping):
        return None
    return VisualDna(
        account_id=_text(value.get("account_id")) or _text(account_id) or "default",
        primary_color=_text(value.get("primary_color")) or "#FFFFFF",
        secondary_color=_text(value.get("secondary_color")) or "#111111",
        accent_color=_text(value.get("accent_color")) or "#FF4D4F",
        title_weight_ratio=_number(value.get("title_weight_ratio"), 1.6),
        subject_tokens=tuple(_strings(value.get("subject_tokens"))),
        negative_tokens=tuple(_strings(value.get("negative_tokens"))),
    )


def _profile_from_mapping(value: Any) -> SceneVisualProfile | None:
    if not isinstance(value, Mapping):
        return None
    scene = _text(value.get("scene")).lower()
    if not scene:
        return None
    return SceneVisualProfile(
        scene=scene,
        preferred_layouts=tuple(_strings(value.get("preferred_layouts"))),
        weight=_number(value.get("weight"), 1.0),
    )


async def _read(store: Any, account_id: str, key: str) -> Any:
    """Best-effort single-key read; a missing store/record reads as ``None``."""
    if store is None:
        return None
    try:
        item = await store.aget(_namespace(account_id), key)
    except Exception as exc:  # pragma: no cover - defensive store boundary
        logger.debug("visual memory read skipped (%s): %s", key, exc)
        return None
    return getattr(item, "value", None) if item is not None else None


async def _write(store: Any, account_id: str, key: str, value: dict[str, Any]) -> None:
    """Persist one key; failures surface to the caller."""
    if store is None:
        return
    try:
        await store.aput(_namespace(account_id), key, value)
    except Exception as exc:  # pragma: no cover - defensive store boundary
        logger.debug("visual memory write skipped (%s): %s", key, exc)
        raise


async def load_dna(store: Any, account_id: str) -> VisualDna | None:
    """Read the immutable brand DNA, or ``None`` on the first run."""
    value = await _read(store, account_id, _DNA_KEY)
    if isinstance(value, Mapping):
        payload = value.get(_DNA_KEY) if _DNA_KEY in value else value
        return _dna_from_mapping(payload, account_id)
    return None


async def save_dna(store: Any, account_id: str, dna: VisualDna) -> None:
    """Persist the brand DNA."""
    await _write(store, account_id, _DNA_KEY, {_DNA_KEY: dna.as_dict()})


async def load_scenes(store: Any, account_id: str) -> dict[str, SceneVisualProfile]:
    """Read the feedback-revisable scene layer."""
    value = await _read(store, account_id, _SCENES_KEY)
    if not isinstance(value, Mapping):
        return {}
    raw = value.get(_SCENES_KEY) if isinstance(value.get(_SCENES_KEY), Mapping) else value
    scenes: dict[str, SceneVisualProfile] = {}
    if isinstance(raw, Mapping):
        for scene, payload in raw.items():
            profile = _profile_from_mapping({**payload, "scene": scene})
            if profile is not None:
                scenes[profile.scene] = profile
    return scenes


async def save_scenes(
    store: Any, account_id: str, scenes: Mapping[str, SceneVisualProfile]
) -> None:
    """Persist the scene layer."""
    payload = {scene: profile.as_dict() for scene, profile in scenes.items()}
    await _write(store, account_id, _SCENES_KEY, {_SCENES_KEY: payload})


async def load_bank(store: Any, account_id: str) -> SceneVisualMemoryBank:
    """Hydrate a bank from the store (empty on the first run)."""
    dna = await load_dna(store, account_id)
    scenes = await load_scenes(store, account_id)
    key = _text(account_id) or "default"
    return SceneVisualMemoryBank(
        dna_by_account={key: dna} if dna is not None else None,
        scene_profiles=scenes,
    )


async def ensure_dna(
    store: Any,
    account_id: str,
    *,
    palette: Sequence[str] = (),
    title_weight_ratio: float | None = None,
    subject_tokens: Sequence[str] = (),
    negative_tokens: Sequence[str] = (),
) -> tuple[VisualDna, bool]:
    """Freeze the brand DNA once; always return the existing anchors afterwards."""
    existing = await load_dna(store, account_id)
    if existing is not None:
        return existing, False
    colors = _strings(palette)
    dna = VisualDna(
        account_id=_text(account_id) or "default",
        primary_color=colors[0] if len(colors) > 0 else "#FFFFFF",
        secondary_color=colors[1] if len(colors) > 1 else "#111111",
        accent_color=colors[2] if len(colors) > 2 else "#FF4D4F",
        title_weight_ratio=_number(title_weight_ratio, 1.6) if title_weight_ratio else 1.6,
        subject_tokens=tuple(_strings(subject_tokens)),
        negative_tokens=tuple(_strings(negative_tokens)),
    )
    await save_dna(store, account_id, dna)
    return dna, True


async def build_directive(store: Any, account_id: str, scene: str) -> dict[str, Any]:
    """Compose the visual directive for one account/scene."""
    dna = await load_dna(store, account_id)
    scenes = await load_scenes(store, account_id)
    key = _text(account_id) or "default"
    bank = SceneVisualMemoryBank(
        dna_by_account={key: dna} if dna is not None else None,
        scene_profiles=scenes,
    )
    directive = build_visual_directive(bank, account_id, scene)
    # A first run has no anchors yet: the prompt must ask the designer to
    # establish them instead of naming the defaults (which would leak a colour
    # scheme the account never chose).
    directive["bootstrapped"] = dna is not None
    return directive


def directive_prompt(directive: Mapping[str, Any]) -> str:
    """Render the directive as a compact Chinese prompt block."""
    palette = directive.get("palette")
    colors = palette if isinstance(palette, Mapping) else {}
    scene = _text(directive.get("scene")) or "lifestyle"
    layouts = "、".join(_strings(directive.get("preferred_layouts")))
    subject_tokens = "、".join(_strings(directive.get("subject_tokens")))
    negative_tokens = "、".join(_strings(directive.get("negative_tokens")))
    ratio = _number(directive.get("title_weight_ratio"), 1.6)
    lines = ["## 账号视觉记忆（品牌 DNA 锚点）"]
    if not directive.get("bootstrapped"):
        lines.append(
            "这是该账号的首篇视觉方案：请确立一套可长期复用的视觉锚点"
            "（主色/辅色/强调色、主标题与副标题的字重比、固定主视觉主体），"
            "并在方案中写明，后续所有笔记都会沿用。"
        )
    else:
        lines.append(
            "主色 {primary}、辅色 {secondary}、强调色 {accent}；"
            "主标题字重约为副标题的 {ratio} 倍。".format(
                primary=_text(colors.get("primary")) or "#FFFFFF",
                secondary=_text(colors.get("secondary")) or "#111111",
                accent=_text(colors.get("accent")) or "#FF4D4F",
                ratio=f"{ratio:g}",
            )
        )
        if subject_tokens:
            lines.append(f"固定主视觉主体：{subject_tokens}。")
        if negative_tokens:
            lines.append(f"禁用视觉元素：{negative_tokens}。")
    if layouts:
        lines.append(f"本场景（{scene}）偏好版式：{layouts}。")
    lines.append("硬性要求：不得更改上述色板与字重比；若与本篇内容冲突，先复用锚点再调整构图。")
    return "\n".join(lines)


def _palette_colors(raw: Any) -> list[str]:
    colors: list[str] = []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, Sequence):
        for item in raw:
            if isinstance(item, str) and item.strip():
                colors.append(item.strip())
            elif isinstance(item, Mapping):
                for key in ("hex", "color", "name", "value"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        colors.append(value.strip())
                        break
    return colors


def apply_directive(plan: dict[str, Any], directive: Mapping[str, Any]) -> dict[str, Any]:
    """Fill plan gaps from the anchors and report drift; never rewrite choices.

    Only *missing* fields are filled. A plan whose own palette/title weight
    disagrees with the frozen anchors keeps its values and gets a ``drift``
    entry instead, so a deliberate new look is surfaced for human review rather
    than silently normalised away.
    """
    palette = directive.get("palette")
    colors = palette if isinstance(palette, Mapping) else {}
    bootstrapped = bool(directive.get("bootstrapped"))
    anchors = [
        _text(colors.get("primary")),
        _text(colors.get("secondary")),
        _text(colors.get("accent")),
    ]
    anchors = [color for color in anchors if color]
    filled: list[str] = []
    drift: list[str] = []

    # A first run has no frozen anchors yet, so there is nothing to fill from
    # and nothing to drift from — the designer is establishing the DNA and the
    # caller freezes it afterwards.
    anchor_ratio = _number(directive.get("title_weight_ratio"), 1.6)
    if bootstrapped:
        existing_palette = _palette_colors(plan.get("color_palette"))
        if anchors and not existing_palette:
            plan["color_palette"] = list(anchors)
            filled.append("color_palette")
        elif anchors and existing_palette:
            normalized = {color.lower() for color in existing_palette}
            shared = [color for color in anchors if color.lower() in normalized]
            if not shared:
                drift.append("palette_off_anchor")
            elif len(shared) < len(anchors):
                drift.append("palette_partial")

        plan_ratio = plan.get("title_weight_ratio")
        if plan_ratio is None:
            plan["title_weight_ratio"] = anchor_ratio
            filled.append("title_weight_ratio")
        elif abs(_number(plan_ratio, anchor_ratio) - anchor_ratio) > _TITLE_WEIGHT_TOLERANCE:
            drift.append("title_weight_off_anchor")

    layouts = _strings(directive.get("preferred_layouts"))
    if (
        bootstrapped
        and layouts
        and not (_text(plan.get("layout_preference")) or _text(plan.get("layout_type")))
    ):
        plan["layout_preference"] = layouts[0]
        filled.append("layout_preference")

    report: dict[str, Any] = {
        "scene": _text(directive.get("scene")) or "lifestyle",
        "scene_weight": _number(directive.get("scene_weight"), 1.0),
        "bootstrapped": bootstrapped,
        "palette": dict(colors),
        "title_weight_ratio": anchor_ratio,
        "preferred_layouts": layouts,
        "subject_tokens": _strings(directive.get("subject_tokens")),
        "negative_tokens": _strings(directive.get("negative_tokens")),
        "filled": filled,
        "drift": drift,
    }
    plan["visual_memory"] = report
    return report


def feedback_score(*, collect_ratio: float | None, view_ratio: float | None) -> float:
    """Baseline-relative outcome in ``[-1, 1]`` (0 when no baseline exists)."""
    parts: list[tuple[float, float]] = []
    if collect_ratio is not None:
        parts.append((_COLLECT_WEIGHT, _clip_unit(collect_ratio - 1.0)))
    if view_ratio is not None:
        parts.append((_VIEW_WEIGHT, _clip_unit(view_ratio - 1.0)))
    if not parts:
        return 0.0
    total = sum(weight for weight, _ in parts)
    return round(sum(weight * value for weight, value in parts) / total, 6)


async def record_scene_feedback(
    store: Any,
    account_id: str,
    scene: str,
    *,
    collect_ratio: float | None = None,
    view_ratio: float | None = None,
    sample_size: int = 0,
) -> SceneVisualProfile | None:
    """Nudge one scene weight with a baseline-relative outcome.

    Returns ``None`` (and writes nothing) when there is no baseline or too few
    samples: a cold-start account should not teach its visual memory from noise.
    """
    if collect_ratio is None and view_ratio is None:
        return None
    if sample_size < _MIN_FEEDBACK_SAMPLES:
        return None
    score = feedback_score(collect_ratio=collect_ratio, view_ratio=view_ratio)
    scenes = await load_scenes(store, account_id)
    bank = SceneVisualMemoryBank(scene_profiles=scenes)
    profile = bank.adapt_scene(scene, feedback_score=score)
    scenes[profile.scene] = profile
    await save_scenes(store, account_id, scenes)
    logger.info(
        "visual memory scene updated: account=%s scene=%s weight=%.3f score=%.3f",
        _text(account_id) or "default",
        profile.scene,
        profile.weight,
        score,
    )
    return profile


async def record_scene_feedback_if_enabled(
    store: Any,
    account_id: str,
    scene: str,
    *,
    collect_ratio: float | None = None,
    view_ratio: float | None = None,
    sample_size: int = 0,
) -> SceneVisualProfile | None:
    """Switch-guarded :func:`record_scene_feedback`."""
    if not visual_memory_enabled():
        return None
    return await record_scene_feedback(
        store,
        account_id,
        scene,
        collect_ratio=collect_ratio,
        view_ratio=view_ratio,
        sample_size=sample_size,
    )
