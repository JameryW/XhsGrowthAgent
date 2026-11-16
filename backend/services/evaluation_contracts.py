"""Phase-5 evaluation and generation contracts (ledger schemes 25-30)."""

from __future__ import annotations

import io
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from backend.context.estimator import estimate_tokens
from backend.context.models import CompiledPrompt

__all__ = [
    "CandidateScore",
    "CoverCritique",
    "RenderedCoverCritique",
    "GroupwiseReport",
    "ModelRouteDecision",
    "PolicyAnchor",
    "PolicyResetDecision",
    "SpanRevision",
    "build_swa_sandwich",
    "classify_workload",
    "evaluate_cover_layout",
    "evaluate_groupwise",
    "policy_reset_decision",
    "ptgs_temperature",
    "route_model_capability",
    "shannon_entropy",
]


class Workload(StrEnum):
    """Coarse capability bucket for model routing."""

    PREFILL_HEAVY = "prefill_heavy"
    CREATIVE = "creative"
    VISION = "vision"
    BALANCED = "balanced"


@dataclass(frozen=True)
class ModelRouteDecision:
    workload: str
    model_id: str
    reason: str
    capability_routing: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "workload": self.workload,
            "model_id": self.model_id,
            "reason": self.reason,
            "capability_routing": self.capability_routing,
        }


_DEFAULT_MODEL = "magpie-deepseek-v4.1-flash"
_PREFILL_MODEL = "deepseek-v4.1"
_CREATIVE_MODEL = "mimo-v2.6-flash"


def classify_workload(task_type: str, input_tokens: int = 0, has_vision: bool = False) -> Workload:
    """Classify a request into a capability bucket without changing routing."""

    if has_vision:
        return Workload.VISION
    kind = (task_type or "").casefold()
    if any(token in kind for token in ("copy", "write", "polish", "version", "creative", "brief")):
        return Workload.CREATIVE
    if input_tokens >= 6000 or any(token in kind for token in ("analysis", "evaluation", "scout")):
        return Workload.PREFILL_HEAVY
    return Workload.BALANCED


def route_model_capability(
    task_type: str,
    *,
    input_tokens: int = 0,
    has_vision: bool = False,
    capability_routing: bool | None = None,
) -> ModelRouteDecision:
    """Recommend a capability-based route while defaulting to the existing route.

    The project currently routes every task through the magpie gateway.  This
    function is an opt-in policy layer: with ``capability_routing=False`` (the
    default unless explicitly enabled) it returns the same magpie model as the
    production router.
    """

    enabled = bool(capability_routing)
    workload = classify_workload(task_type, input_tokens=input_tokens, has_vision=has_vision)
    if not enabled:
        return ModelRouteDecision(
            workload.value,
            _DEFAULT_MODEL,
            "capability routing disabled; preserve existing magpie route",
            False,
        )
    if workload is Workload.VISION or workload is Workload.PREFILL_HEAVY:
        return ModelRouteDecision(workload.value, _PREFILL_MODEL, "prefill/vision workload", True)
    if workload is Workload.CREATIVE:
        return ModelRouteDecision(workload.value, _CREATIVE_MODEL, "creative generation", True)
    return ModelRouteDecision(workload.value, _DEFAULT_MODEL, "balanced workload", True)


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    scores: dict[str, float] = field(default_factory=dict)

    def average(self) -> float:
        return sum(self.scores.values()) / max(1, len(self.scores))


@dataclass(frozen=True)
class GroupwiseReport:
    leader: str
    ranking: tuple[dict[str, Any], ...]
    group_mean: float
    group_std: float
    method: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "leader": self.leader,
            "ranking": list(self.ranking),
            "group_mean": round(self.group_mean, 4),
            "group_std": round(self.group_std, 4),
            "method": self.method,
        }


def _normalise_candidates(
    candidates: Iterable[CandidateScore | Mapping[str, Any]],
) -> list[CandidateScore]:
    result: list[CandidateScore] = []
    for candidate in candidates:
        if isinstance(candidate, CandidateScore):
            result.append(candidate)
            continue
        if isinstance(candidate, Mapping):
            result.append(
                CandidateScore(
                    str(candidate.get("candidate_id", candidate.get("id", ""))),
                    {
                        str(key): float(value)
                        for key, value in (candidate.get("scores") or {}).items()
                    },
                )
            )
    return result


def evaluate_groupwise(
    candidates: Iterable[CandidateScore | Mapping[str, Any]],
    *,
    method: str = "grs",
) -> GroupwiseReport:
    """GRS-style group-relative scoring plus a deterministic ranking.

    GRS subtracts the group mean from each candidate's average score.  GAR is
    represented by the mean rank across dimensions, which is more robust to a
    single inflated dimension.
    """

    rows = _normalise_candidates(candidates)
    if not rows:
        return GroupwiseReport("", (), 0.0, 0.0, method)
    averages = [row.average() for row in rows]
    mean = statistics.fmean(averages)
    std = statistics.pstdev(averages) if len(averages) > 1 else 0.0
    dimensions = sorted({key for row in rows for key in row.scores})
    ranks_by_dimension: dict[str, dict[str, float]] = {}
    for dimension in dimensions:
        ordered = sorted(rows, key=lambda row: (-row.scores.get(dimension, 0.0), row.candidate_id))
        ranks_by_dimension[dimension] = {
            row.candidate_id: float(index + 1) for index, row in enumerate(ordered)
        }
    ranking: list[dict[str, Any]] = []
    for row, average in zip(rows, averages, strict=False):
        if method == "gar":
            rank_values = [ranks_by_dimension[dim][row.candidate_id] for dim in dimensions]
            score = statistics.fmean(rank_values) if rank_values else 0.0
            relative = -score
        else:
            score = average
            relative = average - mean
        ranking.append(
            {
                "candidate_id": row.candidate_id,
                "average": round(average, 4),
                "relative": round(relative, 4),
                "score": round(score, 4),
            }
        )
    ranking.sort(key=lambda item: (-item["relative"], item["candidate_id"]))
    return GroupwiseReport(
        leader=ranking[0]["candidate_id"],
        ranking=tuple(ranking),
        group_mean=mean,
        group_std=std,
        method=method,
    )


def ptgs_temperature(s_max: float, r_plad: float) -> float:
    """Compute the PTGS dynamic temperature in the published range."""

    value = 0.65 + 0.35 * max(0.0, (s_max - 0.65) / 0.35) + 0.15 * max(0.0, r_plad - 0.50)
    return max(0.65, min(1.05, value))


@dataclass(frozen=True)
class PolicyAnchor:
    created_at: datetime
    note_count: int
    reference_version: str = "v1"

    def as_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at.isoformat(),
            "note_count": self.note_count,
            "reference_version": self.reference_version,
        }


@dataclass(frozen=True)
class PolicyResetDecision:
    should_reset: bool
    reason: str
    entropy: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "should_reset": self.should_reset,
            "reason": self.reason,
            "entropy": None if self.entropy is None else round(self.entropy, 4),
        }


def shannon_entropy(counts: Sequence[int | float]) -> float:
    """Shannon entropy in nats; zero for empty/degenerate distributions."""

    values = [float(value) for value in counts if float(value) > 0]
    total = sum(values)
    if total <= 0:
        return 0.0
    return -sum((value / total) * math.log(value / total) for value in values)


def policy_reset_decision(
    anchor: PolicyAnchor | None,
    *,
    now: datetime | None = None,
    note_count: int = 0,
    category_counts: Sequence[int] | None = None,
    min_entropy: float = 1.0,
) -> PolicyResetDecision:
    """APMD reset check for age, note count and track entropy."""

    current = now or datetime.now(UTC)
    if anchor is None:
        return PolicyResetDecision(True, "no_anchor")
    if current - anchor.created_at >= timedelta(weeks=4):
        return PolicyResetDecision(True, "age_reset")
    if note_count - anchor.note_count >= 12:
        return PolicyResetDecision(True, "note_count_reset")
    entropy = shannon_entropy(category_counts or [])
    if category_counts and entropy < min_entropy:
        return PolicyResetDecision(True, "low_track_entropy", entropy)
    return PolicyResetDecision(False, "anchor_valid", entropy if category_counts else None)


@dataclass(frozen=True)
class SpanRevision:
    old: str
    new: str
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"old": self.old, "new": self.new, "reason": self.reason}


@dataclass(frozen=True)
class CoverCritique:
    score: float
    issues: tuple[str, ...] = field(default_factory=tuple)
    safe_area_ok: bool = True
    contrast_ok: bool = True
    thumbnail_ok: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "issues": list(self.issues),
            "safe_area_ok": self.safe_area_ok,
            "contrast_ok": self.contrast_ok,
            "thumbnail_ok": self.thumbnail_ok,
        }


def evaluate_cover_layout(
    text: str,
    *,
    text_box: Mapping[str, float],
    canvas: tuple[int, int] = (1242, 1660),
    thumbnail: tuple[int, int] = (180, 240),
    safe_margin: float = 0.08,
    contrast_ratio: float = 4.5,
    min_thumbnail_text_px: float = 10.0,
) -> CoverCritique:
    """Check a rendered cover's safe area, contrast and thumbnail legibility."""

    width, height = canvas
    x = float(text_box.get("x", 0))
    y = float(text_box.get("y", 0))
    box_width = float(text_box.get("w", text_box.get("width", 0)))
    box_height = float(text_box.get("h", text_box.get("height", 0)))
    margin_x = width * safe_margin
    margin_y = height * safe_margin
    safe_area_ok = (
        x >= margin_x
        and y >= margin_y
        and x + box_width <= width - margin_x
        and y + box_height <= height - margin_y
    )
    contrast_ok = contrast_ratio >= 4.5
    thumbnail_text_px = box_height * (thumbnail[1] / max(1, height))
    thumbnail_ok = thumbnail_text_px >= min_thumbnail_text_px
    issues: list[str] = []
    if not safe_area_ok:
        issues.append("text_outside_safe_area")
    if not contrast_ok:
        issues.append("contrast_below_4_5")
    if not thumbnail_ok:
        issues.append("text_too_small_in_thumbnail")
    if len(text.strip()) > 60:
        issues.append("cover_copy_too_long")
    score = 100.0 - 25.0 * len(issues)
    return CoverCritique(score, tuple(issues), safe_area_ok, contrast_ok, thumbnail_ok)


@dataclass(frozen=True)
class RenderedCoverCritique(CoverCritique):
    """Cover critique backed by actual rendered pixels.

    ``contrast_ratio`` compares the text box's mean relative luminance with the
    surrounding frame; callers that already have a text mask should pass the
    measured ratio to :func:`evaluate_cover_layout` instead.
    """

    width: int = 0
    height: int = 0
    contrast_ratio: float = 0.0
    thumbnail_text_px: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data.update(
            {
                "width": self.width,
                "height": self.height,
                "contrast_ratio": round(self.contrast_ratio, 2),
                "thumbnail_text_px": round(self.thumbnail_text_px, 2),
            }
        )
        return data


def _relative_luminance(rgb: Sequence[float]) -> float:
    channels = []
    for value in rgb[:3]:
        c = max(0.0, min(1.0, float(value) / 255.0))
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _percentile_luminance(image: Any, fraction: float) -> float:
    """Return the luminance at ``fraction`` of the pixel histogram (0-1)."""

    histogram = image.convert("L").histogram()
    total = max(1, sum(histogram))
    target = total * max(0.0, min(1.0, fraction))
    seen = 0
    for value, count in enumerate(histogram):
        seen += count
        if seen >= target:
            return _relative_luminance((value, value, value))
    return _relative_luminance((255, 255, 255))


def _text_contrast_ratio(image: Any) -> float:
    """Measure the spread between dark glyph pixels and light background pixels."""

    dark = _percentile_luminance(image, 0.0005)
    light = _percentile_luminance(image, 0.9995)
    lighter = max(dark, light)
    darker = min(dark, light)
    return (lighter + 0.05) / (darker + 0.05)


def evaluate_rendered_cover(
    image: str | Path | bytes,
    *,
    text_box: Mapping[str, float],
    text_px_height: float | None = None,
    canvas: tuple[int, int] = (1242, 1660),
    thumbnail: tuple[int, int] = (180, 240),
    safe_margin: float = 0.08,
    min_contrast_ratio: float = 4.5,
    min_thumbnail_text_px: float = 10.0,
) -> RenderedCoverCritique:
    """Evaluate a rendered cover image (Pillow is an optional runtime dependency).

    Text boxes are expressed in the *canvas* coordinate space so callers can
    keep using the visual plan's layout numbers; the function scales them to the
    image's real dimensions.  Raises ``RuntimeError`` when Pillow is unavailable.
    """

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("evaluate_rendered_cover requires Pillow") from exc

    source = io.BytesIO(image) if isinstance(image, bytes) else Path(image)
    with Image.open(source) as opened:
        rendered = opened.convert("RGB")
    width, height = rendered.size
    scale_x = width / max(1, canvas[0])
    scale_y = height / max(1, canvas[1])
    x = float(text_box.get("x", 0)) * scale_x
    y = float(text_box.get("y", 0)) * scale_y
    box_width = float(text_box.get("w", text_box.get("width", 0))) * scale_x
    box_height = float(text_box.get("h", text_box.get("height", 0))) * scale_y
    left, top = max(0, int(x)), max(0, int(y))
    right, bottom = min(width, int(x + box_width)), min(height, int(y + box_height))
    if right <= left or bottom <= top:
        return RenderedCoverCritique(
            0.0,
            ("text_box_empty",),
            False,
            False,
            False,
            width=width,
            height=height,
        )

    margin_x = width * safe_margin
    margin_y = height * safe_margin
    safe_area_ok = (
        x >= margin_x
        and y >= margin_y
        and x + box_width <= width - margin_x
        and y + box_height <= height - margin_y
    )
    text_region = rendered.crop((left, top, right, bottom))
    contrast_ratio = _text_contrast_ratio(text_region)
    contrast_ok = contrast_ratio >= min_contrast_ratio

    effective_text_px = (
        float(text_px_height) if text_px_height is not None else max(1.0, box_height * 0.5)
    )
    thumbnail_text_px = effective_text_px * min(
        thumbnail[0] / max(1, width), thumbnail[1] / max(1, height)
    )
    thumbnail_ok = thumbnail_text_px >= min_thumbnail_text_px
    issues: list[str] = []
    if not safe_area_ok:
        issues.append("text_outside_safe_area")
    if not contrast_ok:
        issues.append("contrast_below_threshold")
    if not thumbnail_ok:
        issues.append("text_too_small_in_thumbnail")
    score = 100.0 - 25.0 * len(issues)
    return RenderedCoverCritique(
        score,
        tuple(issues),
        safe_area_ok,
        contrast_ok,
        thumbnail_ok,
        width=width,
        height=height,
        contrast_ratio=contrast_ratio,
        thumbnail_text_px=thumbnail_text_px,
    )


def build_swa_sandwich(
    compiled: CompiledPrompt,
    anchor: str,
    *,
    max_tokens: int = 160,
) -> dict[str, Any]:
    """Build a stable L0-L2 prefix plus a bounded L5 tail anchor.

    This helper is read-only with respect to ``CompiledPrompt``; callers that
    need the original prompt continue to call ``render()``.
    """

    bounded = (anchor or "").strip()
    while estimate_tokens(bounded) > max_tokens and bounded:
        bounded = bounded[:-1]
    prefix = compiled.cache_prefix
    tail = compiled.cache_tail
    sandwich = f"{prefix}\n\n{tail}"
    if bounded:
        sandwich = f"{sandwich}\n\n<swa_active_constraints>\n{bounded}\n</swa_active_constraints>"
    return {
        "prefix": prefix,
        "tail": tail,
        "anchor": bounded,
        "anchor_token_cost": estimate_tokens(bounded),
        "prompt": sandwich,
    }
