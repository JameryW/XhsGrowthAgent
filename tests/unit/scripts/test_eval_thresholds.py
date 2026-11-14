"""§4 threshold gate: cost drift, latency degradation, judge agreement.

``docs/adaptive-harness-eval-plan.md`` §4 is a numeric table, so these tests pin
the numbers and the absences: which dimension goes red, where the "≤" / ">="
boundary sits, and why missing judge data or a zero baseline is a SKIP rather
than a failure.  Everything is local JSON; no network, keys or environment.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / "scripts" / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import thresholds as th  # noqa: E402  (sibling module after sys.path setup)

BASE_LATENCY = (100.0, 200.0, 300.0, 400.0)  # p50 = 200, p95 = 400
DIMENSION_NAMES = [
    "cost.tokens_drift",
    "cost.calls_drift",
    "latency.p50_degradation",
    "latency.p95_degradation",
    "quality.agreement",
]


def _run(
    *,
    tokens: int = 1000,
    calls: int = 100,
    latency: tuple[float, ...] = BASE_LATENCY,
) -> th.RunMetrics:
    return th.RunMetrics(tokens=tokens, calls=calls, latency_ms=latency)


def _run_payload(
    *,
    tokens: int = 1000,
    calls: int = 100,
    latency: tuple[float, ...] = BASE_LATENCY,
) -> dict:
    return {"tokens": tokens, "calls": calls, "latency_ms": list(latency)}


def _payload(
    *,
    current_tokens: int = 1000,
    current_calls: int = 100,
    current_latency: tuple[float, ...] = BASE_LATENCY,
    quality: dict | None = None,
    label: str = "",
    baseline: dict | None = None,
) -> dict:
    return {
        "baseline": baseline if baseline is not None else _run_payload(),
        "current": _run_payload(
            tokens=current_tokens, calls=current_calls, latency=current_latency
        ),
        "quality": quality,
        "label": label,
    }


def _variant(payload: dict, **changes) -> dict:
    return {**payload, **changes}


def _without(payload: dict, *keys: str) -> dict:
    return {key: value for key, value in payload.items() if key not in keys}


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _dims(report: th.ThresholdReport) -> dict[str, th.ThresholdDimension]:
    return {dimension.name: dimension for dimension in report.dimensions}


def test_a_clean_run_passes_every_dimension():
    report = th.evaluate_thresholds(
        _run(),
        _run(tokens=1030, calls=104, latency=(105.0, 210.0, 315.0, 420.0)),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.9, samples=20),
    )

    assert report.status == "PASS"
    assert report.ok
    assert [dimension.name for dimension in report.dimensions] == DIMENSION_NAMES
    assert all(dimension.ok and not dimension.skipped for dimension in report.dimensions)
    assert report.failed == ()
    assert report.skipped == ()


def test_token_drift_over_five_percent_is_red():
    report = th.evaluate_thresholds(
        _run(),
        _run(tokens=1060),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.9, samples=10),
    )

    assert report.status == "FAIL"
    tokens = _dims(report)["cost.tokens_drift"]
    assert not tokens.ok
    assert tokens.change_pct == pytest.approx(6.0)
    assert [dimension.name for dimension in report.failed] == ["cost.tokens_drift"]


def test_call_drift_over_five_percent_is_red():
    report = th.evaluate_thresholds(
        _run(),
        _run(calls=106),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.9, samples=10),
    )

    assert report.status == "FAIL"
    calls = _dims(report)["cost.calls_drift"]
    assert not calls.ok
    assert calls.change_pct == pytest.approx(6.0)
    assert [dimension.name for dimension in report.failed] == ["cost.calls_drift"]


def test_p50_degradation_over_ten_percent_is_red():
    # p50 200 -> 230 (+15%), p95 400 -> 400 (unchanged).
    report = th.evaluate_thresholds(
        _run(),
        _run(latency=(100.0, 230.0, 300.0, 400.0)),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.9, samples=10),
    )

    assert report.status == "FAIL"
    p50 = _dims(report)["latency.p50_degradation"]
    assert not p50.ok
    assert p50.change_pct == pytest.approx(15.0)
    assert [dimension.name for dimension in report.failed] == ["latency.p50_degradation"]


def test_p95_degradation_over_ten_percent_is_red():
    # p50 200 -> 200 (unchanged), p95 400 -> 460 (+15%).
    report = th.evaluate_thresholds(
        _run(),
        _run(latency=(100.0, 200.0, 300.0, 460.0)),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.9, samples=10),
    )

    assert report.status == "FAIL"
    p95 = _dims(report)["latency.p95_degradation"]
    assert not p95.ok
    assert p95.change_pct == pytest.approx(15.0)
    assert [dimension.name for dimension in report.failed] == ["latency.p95_degradation"]


def test_quality_agreement_below_eight_tenths_is_red():
    report = th.evaluate_thresholds(
        _run(),
        _run(),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.79, samples=10),
    )

    assert report.status == "FAIL"
    quality = _dims(report)["quality.agreement"]
    assert not quality.ok
    assert quality.value == pytest.approx(0.79)
    assert quality.threshold == 0.8
    assert [dimension.name for dimension in report.failed] == ["quality.agreement"]


def test_absent_quality_is_skipped_not_red():
    report = th.evaluate_thresholds(_run(), _run(), th.ThresholdConfig())

    quality = _dims(report)["quality.agreement"]
    assert quality.skipped
    assert quality.ok
    assert quality.note == "quality: no judge data"
    assert quality in report.skipped
    assert report.status == "PASS"


def test_the_boundary_equality_passes_and_a_hair_over_fails():
    # Exactly 5% cost drift and exactly 10% p50/p95 degradation; agreement 0.8.
    at_limit = th.evaluate_thresholds(
        _run(),
        _run(tokens=1050, calls=105, latency=(110.0, 220.0, 330.0, 440.0)),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.8, samples=10),
    )
    assert at_limit.status == "PASS"
    dims = _dims(at_limit)
    assert dims["cost.tokens_drift"].change_pct == 5.0
    assert dims["cost.calls_drift"].change_pct == 5.0
    assert dims["latency.p50_degradation"].change_pct == 10.0
    assert dims["latency.p95_degradation"].change_pct == 10.0

    over = th.evaluate_thresholds(
        _run(),
        _run(tokens=1051),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.8, samples=10),
    )
    assert over.status == "FAIL"


def test_a_zero_baseline_skips_that_cost_dimension():
    report = th.evaluate_thresholds(
        _run(tokens=0, calls=0),
        _run(tokens=50, calls=10),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.9, samples=5),
    )
    dims = _dims(report)
    for name in ("cost.tokens_drift", "cost.calls_drift"):
        assert dims[name].skipped
        assert dims[name].ok
        assert "drift cannot be computed" in dims[name].note
    assert report.status == "PASS"

    # One zero baseline only skips that dimension; the other is still measured.
    one_sided = th.evaluate_thresholds(
        _run(tokens=0, calls=100),
        _run(tokens=5, calls=100),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.9, samples=5),
    )
    dims = _dims(one_sided)
    assert dims["cost.tokens_drift"].skipped
    assert not dims["cost.calls_drift"].skipped
    assert dims["cost.calls_drift"].change_pct == 0.0


def test_nearest_rank_percentiles_are_observed_values():
    four = th.RunMetrics(tokens=1, calls=1, latency_ms=(10.0, 20.0, 30.0, 40.0))
    assert th.compute_latency(four) == (20.0, 40.0)
    single = th.RunMetrics(tokens=1, calls=1, latency_ms=(7.0,))
    assert th.compute_latency(single) == (7.0, 7.0)
    # 95th nearest rank of 1..20 is the 19th sample, not 19.05 (no interpolation).
    assert th.nearest_rank_percentile(tuple(range(1, 21)), 95) == 19.0
    assert th.nearest_rank_percentile((10.0, 20.0, 30.0), 50) == 20.0

    with pytest.raises(ValueError, match="at least one"):
        th.nearest_rank_percentile((), 50)
    with pytest.raises(ValueError, match="between 0 and 100"):
        th.nearest_rank_percentile((1.0,), 101)


def test_load_metrics_reads_the_documented_shape(tmp_path):
    payload = _payload(
        current_tokens=1010,
        quality={"agreement": 0.85, "samples": 12},
        label="nightly",
    )

    record = th.load_metrics(_write(tmp_path, payload))

    assert record.baseline == _run()
    assert record.current == _run(tokens=1010)
    assert record.quality == th.QualityMetrics(agreement=0.85, samples=12)
    assert record.label == "nightly"
    json.dumps(record.to_dict())


def test_a_malformed_or_missing_file_is_a_value_error(tmp_path):
    malformed = tmp_path / "bad.json"
    malformed.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        th.load_metrics(malformed)
    with pytest.raises(ValueError, match="could not be read"):
        th.load_metrics(tmp_path / "absent.json")


_SCHEMA_CASES = [
    (_without(_payload(), "current"), "missing required key"),
    (_variant(_payload(), extra=True), "unknown key"),
    (_variant(_payload(), baseline=_run_payload(tokens=-1)), "tokens must be >= 0"),
    (_variant(_payload(), baseline=_run_payload(tokens=True)), "must be an integer"),
    (_variant(_payload(), baseline=_run_payload(tokens=10.5)), "must be an integer"),
    (_variant(_payload(), baseline=_run_payload(calls=-1)), "calls must be >= 0"),
    (_variant(_payload(), baseline=_run_payload(latency=())), "must not be empty"),
    (_variant(_payload(), baseline=_run_payload(latency=(0.0,))), "positive number"),
    (
        _variant(_payload(), baseline=_run_payload(latency=(1.0, True))),
        "positive number",
    ),
    (_variant(_payload(), quality={"agreement": 1.1, "samples": 1}), "agreement"),
    (
        _variant(_payload(), quality={"agreement": 0.5, "samples": -1}),
        "samples must be >= 0",
    ),
    (_variant(_payload(), quality={"agreement": 0.5}), "missing required key"),
    (
        _variant(_payload(), quality={"agreement": 0.5, "samples": 1, "extra": 2}),
        "unknown key",
    ),
    (_variant(_payload(), label=3), "label must be a string"),
    (_variant(_payload(), baseline=5), "must be an object"),
]


@pytest.mark.parametrize(("payload", "match"), _SCHEMA_CASES)
def test_load_metrics_rejects_schema_violations(tmp_path, payload, match):
    with pytest.raises(ValueError, match=match):
        th.load_metrics(_write(tmp_path, payload))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"cost_drift_pct": -1.0}, "cost_drift_pct"),
        ({"latency_p50_degradation_pct": -0.1}, "latency_p50_degradation_pct"),
        ({"latency_p95_degradation_pct": -10.0}, "latency_p95_degradation_pct"),
        ({"quality_min_agreement": -0.01}, "quality_min_agreement"),
        ({"quality_min_agreement": 1.01}, "quality_min_agreement"),
        ({"cost_drift_pct": True}, "finite number"),
    ],
)
def test_threshold_config_is_validated(kwargs, match):
    with pytest.raises(ValueError, match=match):
        th.ThresholdConfig(**kwargs)


def test_threshold_config_allows_zero_limits_and_is_frozen():
    config = th.ThresholdConfig(cost_drift_pct=0, quality_min_agreement=0)

    assert config.cost_drift_pct == 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.cost_drift_pct = 1  # type: ignore[misc]


def test_threshold_config_round_trips_to_and_from_dict():
    config = th.ThresholdConfig(
        cost_drift_pct=6,
        latency_p50_degradation_pct=12,
        latency_p95_degradation_pct=14,
        quality_min_agreement=0.75,
    )

    assert th.ThresholdConfig.from_dict(config.to_dict()) == config
    with pytest.raises(ValueError, match="unknown key"):
        th.ThresholdConfig.from_dict({"cost_drift_pct": 5.0, "bogus": 1})
    with pytest.raises(ValueError, match="missing key"):
        th.ThresholdConfig.from_dict({"cost_drift_pct": 5.0})


def test_the_report_to_dict_and_summary_are_json_able():
    report = th.evaluate_thresholds(
        _run(),
        _run(tokens=1060),
        th.ThresholdConfig(),
        quality=th.QualityMetrics(agreement=0.9, samples=5),
        label="run-1",
    )

    payload = report.to_dict()
    json.dumps(payload)
    assert payload["status"] == "FAIL"
    assert payload["label"] == "run-1"
    assert [dimension["name"] for dimension in payload["dimensions"]] == DIMENSION_NAMES
    summary = report.summary()
    assert summary.startswith("thresholds: FAIL (run-1)")
    assert "cost.tokens_drift: FAIL" in summary


def test_run_thresholds_without_a_path_is_an_explicit_skip():
    report = th.run_thresholds(None)

    assert isinstance(report, th.SkipReport)
    assert report.status == "SKIP"
    assert not report.ok
    assert "no --metrics provided" in report.detail
    assert report.to_dict() == {
        "status": "SKIP",
        "detail": "thresholds: no --metrics provided",
    }
    assert "SKIP" in report.summary()


def test_run_thresholds_raises_for_a_provided_but_missing_path(tmp_path):
    with pytest.raises(ValueError, match="could not be read"):
        th.run_thresholds(tmp_path / "absent.json")


def test_run_thresholds_evaluates_the_loaded_record(tmp_path):
    payload = _payload(
        current_tokens=1060,
        quality={"agreement": 0.9, "samples": 20},
        label="nightly",
    )

    report = th.run_thresholds(_write(tmp_path, payload), th.ThresholdConfig())

    assert isinstance(report, th.ThresholdReport)
    assert report.label == "nightly"
    assert report.status == "FAIL"
    assert [dimension.name for dimension in report.failed] == ["cost.tokens_drift"]


def test_a_null_quality_verdict_is_a_skip_not_a_red(tmp_path):
    report = th.run_thresholds(_write(tmp_path, _payload(quality=None)))

    assert isinstance(report, th.ThresholdReport)
    quality = _dims(report)["quality.agreement"]
    assert quality.skipped and quality.ok
    assert quality.note == "quality: no judge data"
    assert report.status == "PASS"
