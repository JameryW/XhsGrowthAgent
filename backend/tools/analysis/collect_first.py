"""Collect-First engagement forecasting and Hawkes diffusion.

Implements the OranSim-style prediction contract used by the growth workflow:

* four independent ``log1p`` heads — reads / likes / collects / comments;
* an optional account-level calibration fitted from ``content_history``
  outcomes, so the prior is corrected toward what this account actually gets;
* a compact, deterministic 64-dim text representation (no embedding API
  dependency, so the forecast is reproducible in CI);
* Collect-First ranking with a 14-day cumulative simulated response mass as
  the tie-breaker;
* an exponential-kernel Hawkes fit from the ``/analytics <id>`` snapshot
  series, plus a deterministic 14-day diffusion curve;
* paired feature substitution with a fixed seed for low-variance
  counterfactual comparisons.

The module is deliberately pure Python: no network, no model calls, no
clock besides parameters passed in.  That keeps it usable from the
``content_strategist`` node and from offline evaluation scripts.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_HEAD_NAMES = ("read", "like", "collect", "comment")
_DEFAULT_HORIZON_DAYS = 14
_TEXT_DIMS = 64

# Utility-oriented vocabulary from the RedNote note corpus.  Weights are
# deliberately small: the forecast is a ranking signal, not a promise.
_UTILITY_TERMS = (
    "干货",
    "教程",
    "攻略",
    "清单",
    "步骤",
    "收藏",
    "必备",
    "避坑",
    "测评",
    "模板",
    "公式",
    "指南",
    "方法",
    "技巧",
)
_EMOTION_TERMS = ("绝了", "太爱", "治愈", "惊艳", "快乐", "难过", "焦虑", "温柔", "心动", "崩溃")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _tokenize(text: str) -> list[str]:
    """Character bigrams plus latin words — a cheap deterministic tokenizer."""
    text = (text or "").lower()
    tokens: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            tokens.append("".join(buffer))
            buffer.clear()

    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            flush()
            tokens.append(ch)
        elif ch.isalnum():
            buffer.append(ch)
        else:
            flush()
    flush()

    grams = ["".join(tokens[i : i + 2]) for i in range(max(0, len(tokens) - 1))]
    return grams or tokens


def text_signature(text: str, dims: int = _TEXT_DIMS) -> list[float]:
    """Hash character bigrams into a fixed-size signed vector and L2-normalise."""
    vector = [0.0] * dims
    for token in _tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dims
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0:
        vector = [v / norm for v in vector]
    return vector


def _count_terms(text: str, terms: Sequence[str]) -> int:
    return sum(1 for term in terms if term in text)


@dataclass(frozen=True)
class PostFeatures:
    """Pre-publish note features available to the forecast model."""

    title: str = ""
    body: str = ""
    tags: tuple[str, ...] = ()
    media_type: str = "image"
    follower_count: int = 0
    age_days: float = 0.0
    posted_hour: int = 12

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> PostFeatures:
        tags = payload.get("tags") or payload.get("hashtags") or ()
        if isinstance(tags, str):
            tags = tuple(
                part.strip() for part in tags.replace("，", ",").split(",") if part.strip()
            )
        return cls(
            title=str(payload.get("title") or ""),
            body=str(payload.get("body") or payload.get("body_text") or ""),
            tags=tuple(str(tag) for tag in tags),
            media_type=str(payload.get("media_type") or "image"),
            follower_count=max(0, int(_safe_float(payload.get("follower_count"), 0))),
            age_days=max(0.0, _safe_float(payload.get("age_days"), 0.0)),
            posted_hour=int(_safe_float(payload.get("posted_hour"), 12)) % 24,
        )


@dataclass(frozen=True)
class EngagementForecast:
    """Four-head forecast in both log and raw space."""

    read: float
    like: float
    collect: float
    comment: float
    log_scores: dict[str, float] = field(default_factory=dict)
    representation: tuple[float, ...] = ()
    features: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "predicted_read": round(self.read, 2),
            "predicted_like": round(self.like, 2),
            "predicted_collect": round(self.collect, 2),
            "predicted_comment": round(self.comment, 2),
            "log_scores": {key: round(value, 6) for key, value in self.log_scores.items()},
            "features": {key: round(value, 6) for key, value in self.features.items()},
        }


@dataclass(frozen=True)
class CalibrationHead:
    """One log-space correction fitted from an account's own outcomes."""

    slope: float
    intercept: float
    sample_size: int
    r2_log: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "slope": round(self.slope, 4),
            "intercept": round(self.intercept, 4),
            "sample_size": self.sample_size,
            "r2_log": round(self.r2_log, 4),
        }


@dataclass(frozen=True)
class EngagementCalibration:
    """Account-level correction applied to the four prior log scores.

    ``content_history`` stores only a title, hashtags, publish time and the
    eventual counters — no body, follower count or media type.  Refitting all
    feature coefficients from that would mostly fit missing inputs, so the
    calibration stays one-dimensional per head: ``y_log ≈ slope * prior_log +
    intercept``.  It is deliberately modest and reports its own R²; callers
    should treat a low/negative R² as "not enough signal", not as a promise.
    """

    heads: dict[str, CalibrationHead] = field(default_factory=dict)
    sample_size: int = 0

    def apply(self, log_scores: Mapping[str, float]) -> dict[str, float]:
        adjusted: dict[str, float] = {}
        for name, value in log_scores.items():
            head = self.heads.get(name)
            if head is None:
                adjusted[name] = value
            else:
                adjusted[name] = head.slope * value + head.intercept
        return adjusted

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_size": self.sample_size,
            "heads": {name: head.as_dict() for name, head in sorted(self.heads.items())},
        }


@dataclass(frozen=True)
class HawkesParams:
    """Exponential-kernel Hawkes parameters."""

    mu: float
    alpha: float
    beta: float
    horizon_days: int = _DEFAULT_HORIZON_DAYS
    fitted_from: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "mu": round(self.mu, 6),
            "alpha": round(self.alpha, 6),
            "beta": round(self.beta, 6),
            "horizon_days": self.horizon_days,
            "fitted_from": self.fitted_from,
        }


@dataclass(frozen=True)
class CounterfactualResult:
    variant: str
    forecast: EngagementForecast
    delta_collect: float
    rank: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "delta_collect": round(self.delta_collect, 2),
            "rank": self.rank,
            **self.forecast.as_dict(),
        }


def _feature_dict(features: PostFeatures) -> dict[str, float]:
    text = f"{features.title}\n{features.body}"
    followers = math.log1p(features.follower_count) / 10.0
    tag_signal = min(len(features.tags), 10) / 10.0
    utility = _count_terms(text, _UTILITY_TERMS) / 5.0
    emotion = _count_terms(text, _EMOTION_TERMS) / 5.0
    length = max(1, len(text))
    density = min(1.0, len(features.body) / 800.0)
    media = 1.0 if features.media_type in {"video", "视频"} else 0.0
    hour = features.posted_hour
    prime_time = 1.0 if 11 <= hour <= 14 or 19 <= hour <= 23 else 0.0
    age = _clamp(features.age_days / 180.0, 0.0, 1.0)
    return {
        "followers": followers,
        "tag_signal": tag_signal,
        "utility_signal": min(1.0, utility),
        "emotion_signal": min(1.0, emotion),
        "media_type": media,
        "prime_time": prime_time,
        "age_ratio": age,
        "body_density": density,
        "text_length": min(1.0, length / 1200.0),
    }


def predict_engagement(
    features: PostFeatures | Mapping[str, Any],
    *,
    calibration: EngagementCalibration | None = None,
) -> EngagementForecast:
    """Predict the four heads with a deterministic OranSim-shaped model.

    The coefficients are an explicit prior (no training happens here).  They
    encode the three regularities the OranSim paper validates: collect intent
    is utility-driven, reads are follower/media driven, and age depresses all
    heads.  ``log1p`` outputs keep the heavy tail well behaved.

    ``calibration`` is optional and only rescales each prior log score; the
    feature weights themselves stay fixed.  Fit it with :func:`fit_calibration`
    when the account has enough measured outcomes.
    """
    if not isinstance(features, PostFeatures):
        features = PostFeatures.from_mapping(features)
    f = _feature_dict(features)
    text = f"{features.title}\n{features.body}"
    signature = text_signature(text)

    # A stable content-quality projection from the 64-dim signature.  It is
    # intentionally tiny: the signature captures surface novelty, not truth.
    novelty_projection = sum(signature[i] * ((i % 7) - 3) for i in range(len(signature))) / 64.0

    common = (
        0.42 * f["followers"]
        + 0.18 * f["tag_signal"]
        + 0.12 * f["media_type"]
        + 0.08 * f["prime_time"]
        - 0.35 * f["age_ratio"]
        + 0.10 * novelty_projection
    )
    log_scores = {
        "read": common + 0.20 * f["utility_signal"] + 0.10 * f["body_density"],
        "like": common * 0.85 + 0.28 * f["emotion_signal"] + 0.08 * f["utility_signal"],
        # Collect-First: utility is the dominant signal for saves.
        "collect": common * 0.90
        + 0.55 * f["utility_signal"]
        + 0.20 * f["tag_signal"]
        + 0.10 * f["body_density"],
        "comment": common * 0.70 + 0.22 * f["emotion_signal"] + 0.08 * f["tag_signal"],
    }
    if calibration is not None:
        log_scores = calibration.apply(log_scores)
    raw = {
        name: max(0.0, math.expm1(max(-6.0, min(8.0, value)))) for name, value in log_scores.items()
    }
    return EngagementForecast(
        read=raw["read"],
        like=raw["like"],
        collect=raw["collect"],
        comment=raw["comment"],
        log_scores=log_scores,
        representation=tuple(signature),
        features=f,
    )


_METRIC_FIELDS: dict[str, tuple[str, ...]] = {
    "read": ("views", "reads", "read"),
    "like": ("likes", "like"),
    "collect": ("collects", "collect", "bookmarks"),
    "comment": ("comments", "comment"),
}


def _metric_target(record: Mapping[str, Any], head: str) -> float | None:
    """Return ``log1p(metric)`` for the first present counter, else ``None``."""
    for field_name in _METRIC_FIELDS[head]:
        if field_name not in record:
            continue
        raw = record.get(field_name)
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        return math.log1p(value)
    return None


def _posted_hour(record: Mapping[str, Any]) -> int:
    raw_hour = record.get("posted_hour")
    try:
        return int(float(raw_hour)) % 24  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pass
    stamp = record.get("published_at")
    if isinstance(stamp, (int, float)) and math.isfinite(float(stamp)):
        value = float(stamp)
        seconds = value / 1000.0 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC).hour
        except (OverflowError, OSError, ValueError):
            return 12
    if isinstance(stamp, str) and stamp.strip():
        text = stamp.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).hour
        except ValueError:
            return 12
    return 12


def _history_features(record: Mapping[str, Any]) -> PostFeatures:
    """Rebuild the predict-time features that content_history actually stores."""
    payload: dict[str, Any] = dict(record)
    content_type = str(record.get("content_type") or "").lower()
    if "media_type" not in payload:
        payload["media_type"] = "video" if content_type in {"video", "视频"} else "image"
    payload["posted_hour"] = _posted_hour(record)
    # Age at measurement is unknown; the account-level intercept absorbs the
    # average delay rather than pretending every note was scored at publish time.
    payload["age_days"] = 0.0
    return PostFeatures.from_mapping(payload)


def _fit_calibration_head(
    prior_logs: Sequence[float],
    targets: Sequence[float],
    *,
    min_samples: int,
) -> CalibrationHead | None:
    count = min(len(prior_logs), len(targets))
    if count < min_samples:
        return None
    xs = list(prior_logs[:count])
    ys = list(targets[:count])
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x < 1e-12:
        slope = 1.0
    else:
        covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
        slope = _clamp(covariance / var_x, 0.25, 3.0)
    intercept = _clamp(mean_y - slope * mean_x, -8.0, 8.0)
    predictions = [slope * x + intercept for x in xs]
    ss_res = sum((y - pred) ** 2 for y, pred in zip(ys, predictions, strict=True))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return CalibrationHead(
        slope=slope,
        intercept=intercept,
        sample_size=count,
        r2_log=r2,
    )


def fit_calibration(
    records: Sequence[Mapping[str, Any]],
    *,
    min_samples: int = 8,
) -> EngagementCalibration | None:
    """Fit a per-head log-space correction from ``content_history`` records.

    Returns ``None`` when no head has ``min_samples`` complete outcomes.  The
    four heads are fitted independently: a note may have views but no collect
    counter, and that should not throw the read calibration away.
    """
    usable: list[tuple[PostFeatures, EngagementForecast, Mapping[str, Any]]] = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if not any(_metric_target(record, head) is not None for head in _HEAD_NAMES):
            continue
        features = _history_features(record)
        usable.append((features, predict_engagement(features), record))
    if not usable:
        return None

    heads: dict[str, CalibrationHead] = {}
    for head in _HEAD_NAMES:
        pairs = [
            (forecast.log_scores[head], target)
            for _features, forecast, record in usable
            if (target := _metric_target(record, head)) is not None
        ]
        if len(pairs) < min_samples:
            continue
        fitted = _fit_calibration_head(
            [pair[0] for pair in pairs],
            [pair[1] for pair in pairs],
            min_samples=min_samples,
        )
        if fitted is not None:
            heads[head] = fitted
    if not heads:
        return None
    return EngagementCalibration(heads=heads, sample_size=len(usable))


def response_mass(forecast: EngagementForecast, horizon_days: int = _DEFAULT_HORIZON_DAYS) -> float:
    """Cumulative simulated response mass over the horizon.

    Uses a simple geometric decay (per-day retention 0.82) rather than the
    Hawkes model because a cold-start note has no event history.  The result
    is monotone in every head and is used only as the Collect-First tie-break.
    """
    daily = (
        forecast.read + 2.0 * forecast.like + 4.0 * forecast.collect + 3.0 * forecast.comment
    ) / 10.0
    retention = 0.82
    total = 0.0
    weight = 1.0
    for _ in range(max(1, horizon_days)):
        total += daily * weight
        weight *= retention
    return total


def rank_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    horizon_days: int = _DEFAULT_HORIZON_DAYS,
) -> list[dict[str, Any]]:
    """Rank candidate notes by Collect-First, then response mass.

    Each candidate must carry an identifier (``id`` or ``variant``) plus the
    fields accepted by :class:`PostFeatures`.  Results are new dicts; input
    order is preserved only as the final deterministic tie-break.
    """
    scored: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        forecast = predict_engagement(candidate)
        scored.append(
            {
                "variant": str(
                    candidate.get("variant") or candidate.get("id") or f"candidate-{index}"
                ),
                "index": index,
                "forecast": forecast,
                "collect": forecast.collect,
                "response_mass": response_mass(forecast, horizon_days),
            }
        )
    scored.sort(key=lambda item: (-item["collect"], -item["response_mass"], item["index"]))
    for rank, item in enumerate(scored, start=1):
        item["rank"] = rank
    return scored


def paired_feature_substitution(
    base: PostFeatures | Mapping[str, Any],
    variants: Sequence[Mapping[str, Any]],
    *,
    seed: int = 42,
) -> list[CounterfactualResult]:
    """Score variants against a shared baseline with common random numbers.

    Each variant is a partial feature override (title / cover / hour / tags).
    The seed only drives a tiny symmetric jitter applied identically to the
    baseline score of every variant, so the *delta* is low-variance.
    """
    if not isinstance(base, PostFeatures):
        base = PostFeatures.from_mapping(base)
    base_forecast = predict_engagement(base)
    rng = random.Random(seed)
    baseline_jitter = (rng.random() - 0.5) * 0.02
    results: list[CounterfactualResult] = []
    for index, override in enumerate(variants):
        payload = {
            "title": base.title,
            "body": base.body,
            "tags": base.tags,
            "media_type": base.media_type,
            "follower_count": base.follower_count,
            "age_days": base.age_days,
            "posted_hour": base.posted_hour,
            **dict(override),
        }
        forecast = predict_engagement(payload)
        delta = forecast.collect - base_forecast.collect
        jitter = baseline_jitter * (1.0 if index % 2 == 0 else -1.0)
        results.append(
            CounterfactualResult(
                variant=str(override.get("variant") or override.get("id") or f"variant-{index}"),
                forecast=forecast,
                delta_collect=delta * (1.0 + jitter),
                rank=0,
            )
        )
    results.sort(key=lambda item: item.delta_collect, reverse=True)
    return [
        CounterfactualResult(
            variant=item.variant,
            forecast=item.forecast,
            delta_collect=item.delta_collect,
            rank=rank,
        )
        for rank, item in enumerate(results, start=1)
    ]


def _snapshot_datetime(snapshot: Mapping[str, Any]) -> datetime | None:
    raw = snapshot.get("fetched_at") or snapshot.get("timestamp")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _snapshot_total(snapshot: Mapping[str, Any]) -> float:
    return sum(
        _safe_float(snapshot.get(name), 0.0)
        for name in ("views", "likes", "collects", "comments", "shares")
    )


def fit_hawkes(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    horizon_days: int = _DEFAULT_HORIZON_DAYS,
) -> HawkesParams:
    """Fit an exponential-kernel Hawkes prior from cumulative snapshots.

    The analytics series is cumulative, so successive differences are the
    event counts in each interval.  We estimate:

    * ``mu`` — the mean arrival rate in quiet intervals (first half);
    * ``beta`` — ``-ln(decay_ratio) / dt`` from the second-half / first-half
      rate ratio;
    * ``alpha`` — the self-excitation budget implied by the observed burst
      ratio, clipped to a stable sub-critical range.

    Fewer than two usable points yields a conservative default.  The fit is
    intentionally robust rather than a full MLE: it must never raise inside
    the analyst node.
    """
    points: list[tuple[datetime, float]] = []
    for snapshot in snapshots:
        stamp = _snapshot_datetime(snapshot)
        if stamp is not None:
            points.append((stamp, _snapshot_total(snapshot)))
    points.sort(key=lambda item: item[0])
    if len(points) < 2:
        return HawkesParams(
            mu=0.5, alpha=0.15, beta=0.35, horizon_days=horizon_days, fitted_from=len(points)
        )

    increments: list[tuple[float, float]] = []
    for (prev_t, prev_total), (curr_t, curr_total) in zip(points, points[1:], strict=False):
        dt_hours = max((curr_t - prev_t).total_seconds() / 3600.0, 0.25)
        increments.append((dt_hours, max(0.0, curr_total - prev_total)))
    rates = [count / dt for dt, count in increments]
    midpoint = max(1, len(rates) // 2)
    early = sum(rates[:midpoint]) / midpoint
    late = sum(rates[midpoint:]) / max(1, len(rates) - midpoint)
    avg_dt = sum(dt for dt, _ in increments) / len(increments)

    decay_ratio = late / early if early > 0 else 1.0
    beta = -math.log(_clamp(decay_ratio, 0.05, 1.0)) / max(avg_dt, 0.25)
    beta = _clamp(beta, 0.02, 2.0)
    mu = _clamp(min(early, late) if late > 0 else early, 0.01, 1000.0)
    burst = max(early, late) / max(min(early, late), 1e-6)
    alpha = _clamp((burst - 1.0) * 0.25, 0.0, 0.75 * beta * 10.0)
    return HawkesParams(
        mu=mu,
        alpha=alpha,
        beta=beta,
        horizon_days=horizon_days,
        fitted_from=len(points),
    )


def diffusion_curve(
    params: HawkesParams | Mapping[str, Any],
    *,
    initial_events: float = 0.0,
    horizon_days: int | None = None,
) -> list[dict[str, float]]:
    """Deterministic hourly Euler integration, aggregated into daily rows.

    ``fit_hawkes`` estimates ``mu``/``beta`` in *per-hour* units, so the
    integrator steps hourly and sums each day.  A daily step would silently
    reinterpret ``beta`` (an hourly decay) as a daily one and flatten every
    burst.  Returns one row per day with ``day``, ``intensity`` (end of day),
    ``daily_events`` and ``cumulative``.  Cost is O(days × 24).
    """
    if not isinstance(params, HawkesParams):
        params = HawkesParams(
            mu=_safe_float(params.get("mu"), 0.5),
            alpha=_safe_float(params.get("alpha"), 0.15),
            beta=_safe_float(params.get("beta"), 0.35),
            horizon_days=int(_safe_float(params.get("horizon_days"), _DEFAULT_HORIZON_DAYS)),
        )
    days = max(1, int(horizon_days or params.horizon_days))
    mu = max(1e-6, params.mu)
    alpha = max(0.0, params.alpha)
    beta = max(1e-6, params.beta)
    # Keep the per-hour branching ratio sub-critical; otherwise the series explodes.
    alpha = min(alpha, 0.95)
    memory = max(0.0, initial_events)
    cumulative = 0.0
    rows: list[dict[str, float]] = []
    decay = math.exp(-beta)
    for day in range(1, days + 1):
        day_events = 0.0
        intensity = mu
        for _ in range(24):
            intensity = mu + alpha * memory
            events = max(0.0, intensity)
            day_events += events
            cumulative += events
            memory = memory * decay + events
        rows.append(
            {
                "day": float(day),
                "intensity": round(intensity, 6),
                "daily_events": round(day_events, 6),
                "cumulative": round(cumulative, 6),
            }
        )
    return rows


def forecast_payload(
    features: PostFeatures | Mapping[str, Any],
    *,
    snapshots: Sequence[Mapping[str, Any]] | None = None,
    calibration: EngagementCalibration | None = None,
) -> dict[str, Any]:
    """Bundle the forecast, Hawkes curve, and Collect-First score for tools."""
    forecast = predict_engagement(features, calibration=calibration)
    params = fit_hawkes(snapshots or [])
    curve = diffusion_curve(params, initial_events=0.0)
    return {
        **forecast.as_dict(),
        "collect_first_score": round(forecast.collect, 2),
        "response_mass_14d": round(response_mass(forecast), 2),
        "hawkes": params.as_dict(),
        "diffusion_curve": curve,
        "calibration": calibration.as_dict() if calibration is not None else None,
    }
