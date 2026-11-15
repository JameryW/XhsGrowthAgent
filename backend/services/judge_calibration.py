"""Cross-model judge score calibration.

RQGM scores are not comparable across judge models: a stricter model can shift
the whole trend line without any change in content quality.  The evaluator now
records the actual ``judge_model_id`` with every result; this module provides
the read-side normalisation the evaluation dashboard needs.

All functions are pure and operate on (model_id, score) samples, so they can
be tested without a database.  The caller is responsible for selecting the
window (the route uses the last 50 scores per model).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

DEFAULT_WINDOW = 50
TARGET_MEAN = 70.0
TARGET_STD = 10.0


@dataclass(frozen=True)
class JudgeSample:
    model_id: str
    score: float


@dataclass(frozen=True)
class JudgeCalibration:
    model_id: str
    sample_size: int
    mean: float
    std: float
    target_mean: float = TARGET_MEAN
    target_std: float = TARGET_STD

    def calibrate(self, score: float) -> float:
        if self.sample_size < 2 or self.std <= 0:
            return round(score, 2)
        z = (score - self.mean) / self.std
        return round(self.target_mean + z * self.target_std, 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "sample_size": self.sample_size,
            "mean": round(self.mean, 4),
            "std": round(self.std, 4),
            "target_mean": self.target_mean,
            "target_std": self.target_std,
        }


def fit_judge_calibration(
    samples: list[JudgeSample] | tuple[JudgeSample, ...],
    model_id: str,
    *,
    window: int = DEFAULT_WINDOW,
) -> JudgeCalibration | None:
    """Fit mean/std over the most recent samples from one judge model.

    Returns ``None`` when this model has no scores in the window: a fabricated
    mean of 0 would look like a real (and catastrophically strict) judge.
    """
    scores = [sample.score for sample in samples if sample.model_id == model_id]
    scores = scores[-max(1, window) :]
    if not scores:
        return None
    mean = sum(scores) / len(scores)
    variance = sum((score - mean) ** 2 for score in scores) / len(scores)
    return JudgeCalibration(
        model_id=model_id,
        sample_size=len(scores),
        mean=mean,
        std=math.sqrt(variance),
    )


def calibrated_score(
    score: float,
    samples: list[JudgeSample] | tuple[JudgeSample, ...],
    model_id: str,
    *,
    window: int = DEFAULT_WINDOW,
) -> float | None:
    """Return the score mapped to the shared target distribution."""
    calibration = fit_judge_calibration(samples, model_id, window=window)
    return None if calibration is None else calibration.calibrate(score)


__all__ = [
    "DEFAULT_WINDOW",
    "TARGET_MEAN",
    "TARGET_STD",
    "JudgeCalibration",
    "JudgeSample",
    "calibrated_score",
    "fit_judge_calibration",
]
