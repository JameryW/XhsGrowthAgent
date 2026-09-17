"""``WorkflowRow`` decoding carries the mode (P2c-S3a).

The DB column is ``TEXT NOT NULL DEFAULT 'trend'`` and predates the request
boundary, so a row may hold anything an old client sent -- including a value no
``WorkflowMode`` member matches. Decoding must pass it through rather than
normalise it: the row is the only record of how that thread was created.
"""

from __future__ import annotations

from typing import Any

from backend.db.workflows import WorkflowRow, _row_from_dict
from backend.state.enums import WorkflowMode
from backend.state.modes import DEFAULT_WORKFLOW_MODE


def _row(**overrides: Any) -> dict[str, Any]:
    return {"thread_id": "t1", **overrides}


def test_the_stored_mode_is_carried_over() -> None:
    assert _row_from_dict(_row(workflow_mode="brief")).workflow_mode == "brief"


def test_an_unrecognised_stored_mode_is_not_normalised() -> None:
    assert _row_from_dict(_row(workflow_mode="brand_campaign")).workflow_mode == "brand_campaign"


def test_a_row_without_a_mode_falls_back_to_the_declared_default() -> None:
    assert _row_from_dict(_row()).workflow_mode == DEFAULT_WORKFLOW_MODE.value


def test_the_row_model_defaults_to_the_declared_default() -> None:
    assert WorkflowRow(thread_id="t1").workflow_mode == DEFAULT_WORKFLOW_MODE.value


def test_the_declared_default_is_trend() -> None:
    assert DEFAULT_WORKFLOW_MODE is WorkflowMode.TREND
