"""Per-judge z-score calibration for cross-model RQGM comparability."""

from __future__ import annotations

from backend.services.judge_calibration import (
    JudgeSample,
    calibrated_score,
    fit_judge_calibration,
)


def test_calibration_moves_a_judge_mean_toward_the_shared_target() -> None:
    samples = [JudgeSample("judge-a", 60.0 + (index % 5)) for index in range(20)]

    calibration = fit_judge_calibration(samples, "judge-a")

    assert calibration is not None
    assert calibration.sample_size == 20
    assert calibration.mean > 60
    assert calibration.calibrate(calibration.mean) == 70.0


def test_calibration_uses_only_the_requested_model_and_window() -> None:
    samples = [JudgeSample("judge-a", 40.0 + index) for index in range(5)]
    samples.extend(JudgeSample("judge-b", 90.0 + index) for index in range(5))

    calibration = fit_judge_calibration(samples, "judge-b")

    assert calibration is not None
    assert calibration.mean == 92.0
    assert calibration.sample_size == 5
    assert calibrated_score(92.0, samples, "judge-b") == 70.0


def test_unknown_or_singleton_model_returns_none() -> None:
    assert fit_judge_calibration([], "judge-a") is None
    assert calibrated_score(80.0, [JudgeSample("other", 80.0)], "judge-a") is None
