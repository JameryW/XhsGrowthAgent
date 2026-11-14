"""§4 numeric gates for Adaptive Harness A/B runs (P3/E3/E4).

``docs/adaptive-harness-eval-plan.md`` §4 fixes the numbers a variant must clear
before it may be called "not worse than the baseline":

* **cost** — token and model-call drift ``<= 5%`` versus the baseline;
* **latency** — p50 / p95 degradation ``<= 10%``;
* **quality** — judge (or rubric) agreement ``>= 0.8``, when a judge was enabled.

This module turns one metrics snapshot into per-dimension rows a gate can report
on.  It is deliberately offline and dependency-free (stdlib only): the live L3
run that *produces* the numbers is external-only, while deciding pass/fail from
them should be deterministic and reviewable in this repository.

Percentiles are **nearest-rank**: sort the samples ascending, take the 1-based
rank ``ceil(percentile / 100 * n)``, clamp it to ``[1, n]``, and return that
observed sample.  No interpolation, so a p95 is always a latency that actually
happened.  Example: ``[10, 20, 30, 40]`` -> p50 = 20, p95 = 40.

Three absences are handled differently on purpose:

* a missing quality verdict is a **SKIP** row, not a red — §4 enables the judge
  conditionally ("若启用 judge"), and inventing a failure from "no judge data"
  would red every run that did not use one;
* a zero baseline is a **SKIP** dimension — drift is undefined, and the gate must
  not invent a percentage from ``x / 0``;
* a *missing path* (``None``) is an explicit **SKIP** report, while a path that
  was provided but cannot be read or parsed raises ``ValueError`` so the gate can
  turn it red.  A typo in ``--metrics`` must not look like "no data today".
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Float-boundary tolerance: ``(current - baseline) * 100 / baseline`` is exact
# for integer inputs, but a metrics producer may hand us decimal floats whose
# representation sits a few ulps above the limit.  A value that is the limit for
# every practical purpose must pass (§4 says "≤", not "<").
_FLOAT_EPS = 1e-9

_CONFIG_FIELDS = (
    "cost_drift_pct",
    "latency_p50_degradation_pct",
    "latency_p95_degradation_pct",
    "quality_min_agreement",
)
_RUN_FIELDS = frozenset({"tokens", "calls", "latency_ms"})
_METRICS_FIELDS = frozenset({"baseline", "current", "quality", "label"})
_QUALITY_FIELDS = frozenset({"agreement", "samples"})


def _is_number(value: object) -> bool:
    """True for finite ints/floats; ``bool`` is not a number here."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _require_number(
    value: object,
    field_name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if not _is_number(value):
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"{field_name} must be >= {minimum:g}, got {number:g}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field_name} must be <= {maximum:g}, got {number:g}")
    return number


def _require_int(value: object, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer, got {value!r}")
    if value < minimum:
        raise ValueError(f"{field_name} must be >= {minimum}, got {value}")
    return value


def _reject_unknown(
    payload: Mapping[str, Any], allowed: frozenset[str] | tuple[str, ...], where: str
) -> None:
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise ValueError(f"{where} has unknown key(s): {', '.join(unknown)}")


@dataclass(frozen=True)
class ThresholdConfig:
    """The §4 limits; defaults are the plan's suggested gate values."""

    cost_drift_pct: float = 5.0
    latency_p50_degradation_pct: float = 10.0
    latency_p95_degradation_pct: float = 10.0
    quality_min_agreement: float = 0.8

    def __post_init__(self) -> None:
        _require_number(self.cost_drift_pct, "cost_drift_pct", minimum=0)
        _require_number(self.latency_p50_degradation_pct, "latency_p50_degradation_pct", minimum=0)
        _require_number(self.latency_p95_degradation_pct, "latency_p95_degradation_pct", minimum=0)
        _require_number(self.quality_min_agreement, "quality_min_agreement", minimum=0, maximum=1)

    def to_dict(self) -> dict[str, float]:
        return {
            "cost_drift_pct": float(self.cost_drift_pct),
            "latency_p50_degradation_pct": float(self.latency_p50_degradation_pct),
            "latency_p95_degradation_pct": float(self.latency_p95_degradation_pct),
            "quality_min_agreement": float(self.quality_min_agreement),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ThresholdConfig:
        if not isinstance(payload, Mapping):
            raise ValueError(f"threshold config must be a mapping, got {type(payload).__name__}")
        _reject_unknown(payload, _CONFIG_FIELDS, "threshold config")
        missing = sorted(set(_CONFIG_FIELDS) - set(payload))
        if missing:
            raise ValueError(f"threshold config is missing key(s): {', '.join(missing)}")
        return cls(**dict(payload))


@dataclass(frozen=True)
class RunMetrics:
    """One side of an A/B comparison: cost counters plus latency samples."""

    tokens: int
    calls: int
    latency_ms: tuple[float, ...]

    def __post_init__(self) -> None:
        _require_int(self.tokens, "tokens")
        _require_int(self.calls, "calls")
        latencies = self.latency_ms
        if isinstance(latencies, (str, bytes)) or not isinstance(latencies, Sequence):
            raise ValueError(
                f"latency_ms must be a sequence of numbers, got {type(latencies).__name__}"
            )
        if not latencies:
            raise ValueError("latency_ms must not be empty")
        parsed: list[float] = []
        for position, value in enumerate(latencies):
            if not _is_number(value) or value <= 0:
                raise ValueError(f"latency_ms[{position}] must be a positive number, got {value!r}")
            parsed.append(float(value))
        # Normalise to a tuple so the frozen record is actually immutable.
        object.__setattr__(self, "latency_ms", tuple(parsed))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "calls": self.calls,
            "latency_ms": list(self.latency_ms),
        }


@dataclass(frozen=True)
class QualityMetrics:
    """A judge/rubric agreement verdict: agreement is a 0..1 proportion."""

    agreement: float
    samples: int

    def __post_init__(self) -> None:
        agreement = _require_number(self.agreement, "agreement", minimum=0, maximum=1)
        _require_int(self.samples, "samples")
        object.__setattr__(self, "agreement", agreement)

    def to_dict(self) -> dict[str, Any]:
        return {"agreement": self.agreement, "samples": self.samples}


@dataclass(frozen=True)
class MetricsRecord:
    """The loaded metrics file: baseline, current, optional quality, optional label."""

    baseline: RunMetrics
    current: RunMetrics
    quality: QualityMetrics | None = None
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "current": self.current.to_dict(),
            "quality": None if self.quality is None else self.quality.to_dict(),
            "label": self.label,
        }


def _parse_run(payload: Any, where: str) -> RunMetrics:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{where} must be an object, got {type(payload).__name__}")
    _reject_unknown(payload, _RUN_FIELDS, where)
    missing = sorted(_RUN_FIELDS - set(payload))
    if missing:
        raise ValueError(f"{where} is missing required key(s): {', '.join(missing)}")
    latencies = payload["latency_ms"]
    if not isinstance(latencies, list):
        raise ValueError(f"{where}.latency_ms must be a list, got {type(latencies).__name__}")
    if not latencies:
        raise ValueError(f"{where}.latency_ms must not be empty")
    parsed: list[float] = []
    for position, value in enumerate(latencies):
        if not _is_number(value) or value <= 0:
            raise ValueError(
                f"{where}.latency_ms[{position}] must be a positive number, got {value!r}"
            )
        parsed.append(float(value))
    return RunMetrics(
        tokens=_require_int(payload["tokens"], f"{where}.tokens"),
        calls=_require_int(payload["calls"], f"{where}.calls"),
        latency_ms=tuple(parsed),
    )


def _parse_quality(payload: Any, where: str) -> QualityMetrics:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{where} must be an object or null, got {type(payload).__name__}")
    _reject_unknown(payload, _QUALITY_FIELDS, where)
    missing = sorted(_QUALITY_FIELDS - set(payload))
    if missing:
        raise ValueError(f"{where} is missing required key(s): {', '.join(missing)}")
    return QualityMetrics(
        agreement=_require_number(payload["agreement"], f"{where}.agreement", minimum=0, maximum=1),
        samples=_require_int(payload["samples"], f"{where}.samples"),
    )


def parse_metrics(payload: Any, *, source: str = "<memory>") -> MetricsRecord:
    """Validate an already-decoded metrics object (the shape ``load_metrics`` reads).

    Strict on purpose: unknown keys are rejected so a metrics producer cannot add
    a field the gate silently ignores, and ``bool`` is never accepted where a
    count is expected (``True`` is not a token count).
    """
    if not isinstance(payload, Mapping):
        raise ValueError(f"{source}: metrics must be a JSON object, got {type(payload).__name__}")
    _reject_unknown(payload, _METRICS_FIELDS, source)
    missing = sorted({"baseline", "current"} - set(payload))
    if missing:
        raise ValueError(f"{source} is missing required key(s): {', '.join(missing)}")
    quality_payload = payload.get("quality")
    quality = (
        None if quality_payload is None else _parse_quality(quality_payload, f"{source}.quality")
    )
    label = payload.get("label", "")
    if not isinstance(label, str):
        raise ValueError(f"{source}.label must be a string, got {type(label).__name__}")
    return MetricsRecord(
        baseline=_parse_run(payload["baseline"], f"{source}.baseline"),
        current=_parse_run(payload["current"], f"{source}.current"),
        quality=quality,
        label=label,
    )


def load_metrics(path: str | Path) -> MetricsRecord:
    """Read and validate a metrics JSON file; any failure is a clear ``ValueError``.

    A missing or unreadable file is *not* skipped here: the caller explicitly
    named the path, so the gate must be able to red a typo instead of reporting
    "no metrics today".  Only ``run_thresholds(None)`` is a skip.
    """
    metrics_path = Path(path)
    try:
        raw = metrics_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"metrics file {metrics_path} could not be read: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"metrics file {metrics_path} is not valid JSON: {exc}") from exc
    return parse_metrics(payload, source=str(metrics_path))


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    """Nearest-rank percentile: the ``ceil(p/100 * n)``-th smallest sample (1-based).

    See the module docstring for the exact rule; with ``[10, 20, 30, 40]``,
    p50 = 20 and p95 = 40.  The rank is clamped to ``[1, n]`` so tiny samples
    still answer (a single sample is its own p50 and p95).
    """
    if not values:
        raise ValueError("percentile needs at least one latency sample")
    if not _is_number(percentile) or not 0 <= percentile <= 100:
        raise ValueError(f"percentile must be between 0 and 100, got {percentile!r}")
    ordered = sorted(values)
    rank = math.ceil(percentile / 100.0 * len(ordered))
    index = min(max(rank - 1, 0), len(ordered) - 1)
    return float(ordered[index])


def compute_latency(record: RunMetrics) -> tuple[float, float]:
    """Return ``(p50, p95)`` for one run, using the documented nearest-rank rule."""
    return (
        nearest_rank_percentile(record.latency_ms, 50),
        nearest_rank_percentile(record.latency_ms, 95),
    )


@dataclass(frozen=True)
class ThresholdDimension:
    """One row of the §4 table: what was measured, the limit, and the verdict."""

    name: str
    baseline: int | float | None
    current: int | float | None
    threshold: float
    ok: bool
    change_pct: float | None = None
    value: float | None = None
    skipped: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "baseline": self.baseline,
            "current": self.current,
            "change_pct": self.change_pct,
            "value": self.value,
            "threshold": self.threshold,
            "ok": self.ok,
            "skipped": self.skipped,
            "note": self.note,
        }


@dataclass(frozen=True)
class ThresholdReport:
    """All §4 rows plus the aggregate verdict (``ok`` ignores skipped rows)."""

    dimensions: tuple[ThresholdDimension, ...]
    config: ThresholdConfig = field(default_factory=ThresholdConfig)
    label: str = ""

    @property
    def ok(self) -> bool:
        """True when every *measured* dimension is within its limit."""
        return all(dimension.ok for dimension in self.dimensions if not dimension.skipped)

    @property
    def status(self) -> str:
        return "PASS" if self.ok else "FAIL"

    @property
    def failed(self) -> tuple[ThresholdDimension, ...]:
        return tuple(
            dimension for dimension in self.dimensions if not dimension.skipped and not dimension.ok
        )

    @property
    def skipped(self) -> tuple[ThresholdDimension, ...]:
        return tuple(dimension for dimension in self.dimensions if dimension.skipped)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "label": self.label,
            "config": self.config.to_dict(),
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
        }

    def summary(self) -> str:
        header = f"thresholds: {self.status}"
        if self.label:
            header += f" ({self.label})"
        lines = [header]
        lines.extend(
            f"  {dimension.name}: {_dimension_summary(dimension)}" for dimension in self.dimensions
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class SkipReport:
    """The explicit "no metrics were supplied" outcome (never a pass)."""

    detail: str

    @property
    def status(self) -> str:
        return "SKIP"

    @property
    def ok(self) -> bool:
        """A skip is not a pass; callers must branch on ``status``."""
        return False

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "detail": self.detail}

    def summary(self) -> str:
        return f"thresholds: SKIP ({self.detail})"


def _drift_pct(baseline: int | float, current: int | float) -> float:
    """Relative change in percent; multiply before dividing to keep 5%/10% exact."""
    return (current - baseline) * 100.0 / baseline


def _drift_dimension(
    name: str,
    baseline: int | float,
    current: int | float,
    threshold: float,
) -> ThresholdDimension:
    if baseline == 0:
        return ThresholdDimension(
            name=name,
            baseline=baseline,
            current=current,
            threshold=threshold,
            ok=True,
            skipped=True,
            note="baseline is 0: drift cannot be computed",
        )
    change_pct = _drift_pct(baseline, current)
    ok = change_pct <= threshold + _FLOAT_EPS
    return ThresholdDimension(
        name=name,
        baseline=baseline,
        current=current,
        threshold=threshold,
        ok=ok,
        change_pct=change_pct,
        note="" if ok else "change exceeds the threshold",
    )


def _quality_dimension(quality: QualityMetrics | None, threshold: float) -> ThresholdDimension:
    if quality is None:
        return ThresholdDimension(
            name="quality.agreement",
            baseline=None,
            current=None,
            threshold=threshold,
            ok=True,
            skipped=True,
            note="quality: no judge data",
        )
    return ThresholdDimension(
        name="quality.agreement",
        baseline=None,
        current=None,
        threshold=threshold,
        ok=quality.agreement >= threshold,
        value=quality.agreement,
    )


def _dimension_summary(dimension: ThresholdDimension) -> str:
    if dimension.skipped:
        return f"SKIP ({dimension.note})"
    verdict = "PASS" if dimension.ok else "FAIL"
    if dimension.value is not None:
        return f"{verdict} ({dimension.value:.3f} vs min {dimension.threshold:.3f})"
    change = dimension.change_pct if dimension.change_pct is not None else 0.0
    return (
        f"{verdict} ({dimension.baseline} -> {dimension.current}, "
        f"change {change:+.2f}% vs limit {dimension.threshold:.2f}%)"
    )


def evaluate_thresholds(
    baseline: RunMetrics,
    current: RunMetrics,
    config: ThresholdConfig,
    *,
    quality: QualityMetrics | None = None,
    label: str = "",
) -> ThresholdReport:
    """Apply the §4 gates to one baseline/current pair.

    Cost produces two rows (tokens, calls), latency two rows (p50, p95), quality
    one row.  A row is red only when the corresponding §4 number is exceeded; the
    aggregate ``ok`` is true when every non-skipped row is green (§4 says a
    variant must not be *worse*: improvements are negative drift and pass).
    """
    baseline_p50, baseline_p95 = compute_latency(baseline)
    current_p50, current_p95 = compute_latency(current)
    dimensions = (
        _drift_dimension(
            "cost.tokens_drift", baseline.tokens, current.tokens, config.cost_drift_pct
        ),
        _drift_dimension("cost.calls_drift", baseline.calls, current.calls, config.cost_drift_pct),
        _drift_dimension(
            "latency.p50_degradation",
            baseline_p50,
            current_p50,
            config.latency_p50_degradation_pct,
        ),
        _drift_dimension(
            "latency.p95_degradation",
            baseline_p95,
            current_p95,
            config.latency_p95_degradation_pct,
        ),
        _quality_dimension(quality, config.quality_min_agreement),
    )
    return ThresholdReport(dimensions=dimensions, config=config, label=label)


def run_thresholds(
    metrics_path: str | Path | None,
    config: ThresholdConfig | None = None,
) -> ThresholdReport | SkipReport:
    """Load a metrics file and evaluate it; ``None`` path is an explicit skip.

    A path that was supplied but is missing, unreadable or malformed raises
    ``ValueError`` (via ``load_metrics``) so a gate can report red.  Only "the
    operator did not pass ``--metrics``" is a skip.
    """
    if metrics_path is None:
        return SkipReport("thresholds: no --metrics provided")
    record = load_metrics(metrics_path)
    effective_config = config if config is not None else ThresholdConfig()
    return evaluate_thresholds(
        record.baseline,
        record.current,
        effective_config,
        quality=record.quality,
        label=record.label,
    )
