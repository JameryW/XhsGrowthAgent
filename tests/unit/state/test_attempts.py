"""Attempt identity library (票 5w) — pure, data-minimising, deterministic.

The entry shape is a reservation: a new field is a schema decision. These tests
pin the vocabulary, the id derivation (attempt number included — otherwise a
retry reuses the previous attempt's id), the strict validation of numbers and
text, and the fact that no content field exists at all.
"""

from __future__ import annotations

import math

import pytest

from backend.db.workflow_events import EVENT_KINDS
from backend.state.attempts import (
    ATTEMPT_EVENT_KIND,
    AttemptOutcome,
    attempt_entry,
    attempt_id,
)

_TEXT = "2026-10-22T12:00:00+00:00"


def _entry(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "agent": "structured_test",
        "task_type": "routing",
        "level": "prompted",
        "attempt_no": 1,
        "outcome": AttemptOutcome.SUCCEEDED,
        "duration_ms": 12.345,
        "started_at": _TEXT,
    }
    kwargs.update(overrides)
    return attempt_entry(**kwargs)  # type: ignore[arg-type]


def test_the_kind_is_registered_once() -> None:
    assert ATTEMPT_EVENT_KIND == "attempt"
    assert ATTEMPT_EVENT_KIND in EVENT_KINDS


def test_the_outcome_vocabulary_is_closed() -> None:
    assert {member.value for member in AttemptOutcome} == {
        "succeeded",
        "payload_rejected",
        "semantic_rejected",
        "unreachable",
    }


def test_the_entry_has_exactly_the_reserved_keys() -> None:
    entry = _entry()
    assert set(entry) == {
        "kind",
        "attempt_id",
        "agent",
        "task_type",
        "level",
        "attempt_no",
        "outcome",
        "duration_ms",
        "started_at",
        "error_class",
    }
    assert entry["kind"] == "attempt"
    assert entry["attempt_id"].startswith("att_")  # type: ignore[union-attr]
    assert entry["outcome"] == "succeeded"
    assert entry["duration_ms"] == 12.345
    assert entry["error_class"] == ""


def test_the_entry_carries_no_content() -> None:
    entry = _entry(error_class="ValueError")
    # Data minimisation is structural: there is no field a prompt, a model
    # output or an exception message could hide in.
    for forbidden in ("content", "prompt", "messages", "output", "error", "text"):
        assert forbidden not in entry
    assert all(isinstance(value, (str, int, float)) for value in entry.values())


def test_the_id_is_deterministic_and_number_aware() -> None:
    first = attempt_id("agent", level="prompted", attempt_no=1, started_at=_TEXT)
    assert first == attempt_id("agent", level="prompted", attempt_no=1, started_at=_TEXT)
    assert first != attempt_id("agent", level="prompted", attempt_no=2, started_at=_TEXT)
    assert first != attempt_id("agent", level="native_schema", attempt_no=1, started_at=_TEXT)
    assert first != attempt_id("other", level="prompted", attempt_no=1, started_at=_TEXT)
    assert first != attempt_id("agent", level="prompted", attempt_no=1, started_at="later")


def test_an_id_needs_text_and_a_positive_number() -> None:
    with pytest.raises(ValueError, match="agent"):
        attempt_id(" ", level="prompted", attempt_no=1, started_at=_TEXT)
    with pytest.raises(ValueError, match="level"):
        attempt_id("agent", level="", attempt_no=1, started_at=_TEXT)
    with pytest.raises(ValueError, match="started_at"):
        attempt_id("agent", level="prompted", attempt_no=1, started_at="  ")
    with pytest.raises(ValueError, match="attempt_no"):
        attempt_id("agent", level="prompted", attempt_no=0, started_at=_TEXT)


@pytest.mark.parametrize("bad_number", [True, 0, -1, 1.0, "1"])
def test_attempt_no_must_be_a_positive_int(bad_number: object) -> None:
    with pytest.raises(ValueError, match="attempt_no"):
        attempt_id("agent", level="prompted", attempt_no=bad_number, started_at=_TEXT)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_duration", [-1, -0.001, math.inf, math.nan, True, "12"])
def test_duration_must_be_a_finite_non_negative_number(bad_duration: object) -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        _entry(duration_ms=bad_duration)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("agent", "  "),
        ("task_type", ""),
        ("level", " "),
        ("started_at", ""),
        ("outcome", "succeeded"),
        ("error_class", 7),
    ],
)
def test_each_field_is_validated(field: str, bad: object) -> None:
    with pytest.raises(ValueError):
        _entry(**{field: bad})


def test_duration_is_rounded_to_milliseconds() -> None:
    rounded = _entry(duration_ms=1.23456789)
    assert rounded["duration_ms"] == 1.235
