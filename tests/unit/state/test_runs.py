"""Run identity library (票 5x) — pure, data-minimising, deterministic.

The entry shape is a reservation: a new field is a schema decision. These tests
pin the vocabulary, the id derivation (run_seq included — otherwise a terminal
restart reuses the previous run's id), the fact that resume/recover cannot mint
an entry, and the fact that no content field exists at all.
"""

from __future__ import annotations

import pytest

from backend.db.workflow_events import EVENT_KINDS
from backend.state.runs import (
    RUN_EVENT_KIND,
    RunCause,
    mint_run_stamp,
    next_run_seq,
    run_entry,
    run_id,
    run_identity_view,
)

_TEXT = "2026-10-29T12:00:00+00:00"
_THREAD = "xhs_acc1_deadbeef"


def _entry(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "thread_id": _THREAD,
        "run_seq": 1,
        "cause": RunCause.START,
        "started_at": _TEXT,
    }
    kwargs.update(overrides)
    return run_entry(**kwargs)  # type: ignore[arg-type]


def test_the_kind_is_registered_once() -> None:
    assert RUN_EVENT_KIND == "run"
    assert RUN_EVENT_KIND in EVENT_KINDS


def test_the_cause_vocabulary_is_closed() -> None:
    assert {member.value for member in RunCause} == {
        "start",
        "resume",
        "rerun",
        "recover",
    }


def test_the_entry_has_exactly_the_reserved_keys() -> None:
    entry = _entry()
    assert set(entry) == {
        "kind",
        "run_id",
        "thread_id",
        "run_seq",
        "cause",
        "started_at",
    }
    assert entry["kind"] == "run"
    assert entry["run_id"].startswith("run_")  # type: ignore[union-attr]
    assert entry["cause"] == "start"
    assert entry["run_seq"] == 1


def test_the_entry_carries_no_content() -> None:
    entry = _entry()
    for forbidden in ("content", "goal", "brief", "prompt", "messages", "output", "error"):
        assert forbidden not in entry


def test_id_is_deterministic_and_includes_seq() -> None:
    a = run_id(_THREAD, run_seq=1, started_at=_TEXT)
    b = run_id(_THREAD, run_seq=1, started_at=_TEXT)
    c = run_id(_THREAD, run_seq=2, started_at=_TEXT)
    assert a == b
    assert a != c
    assert a.startswith("run_")


def test_resume_and_recover_cannot_mint_an_entry() -> None:
    with pytest.raises(ValueError, match="start or rerun"):
        run_entry(thread_id=_THREAD, run_seq=1, cause=RunCause.RESUME, started_at=_TEXT)
    with pytest.raises(ValueError, match="start or rerun"):
        run_entry(thread_id=_THREAD, run_seq=1, cause=RunCause.RECOVER, started_at=_TEXT)


def test_next_run_seq_from_missing_or_invalid_is_one() -> None:
    assert next_run_seq(None) == 1
    assert next_run_seq(0) == 1
    assert next_run_seq(-1) == 1
    assert next_run_seq("2") == 1
    assert next_run_seq(True) == 1


def test_next_run_seq_increments() -> None:
    assert next_run_seq(1) == 2
    assert next_run_seq(7) == 8


def test_mint_run_stamp_start_is_seq_one() -> None:
    stamped = mint_run_stamp(_THREAD, cause=RunCause.START, started_at=_TEXT, prior_seq=99)
    assert stamped["state"]["run_seq"] == 1
    assert stamped["state"]["run_cause"] == "start"
    assert stamped["entry"]["run_id"] == stamped["state"]["run_id"]


def test_mint_run_stamp_rerun_increments_prior() -> None:
    stamped = mint_run_stamp(_THREAD, cause=RunCause.RERUN, started_at=_TEXT, prior_seq=1)
    assert stamped["state"]["run_seq"] == 2
    assert stamped["state"]["run_cause"] == "rerun"
    first = run_id(_THREAD, run_seq=1, started_at=_TEXT)
    assert stamped["state"]["run_id"] != first


def test_mint_rejects_reuse_causes() -> None:
    with pytest.raises(ValueError, match="start or rerun"):
        mint_run_stamp(_THREAD, cause=RunCause.RESUME, started_at=_TEXT)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"thread_id": "", "run_seq": 1, "started_at": _TEXT}, "thread_id"),
        ({"thread_id": _THREAD, "run_seq": 0, "started_at": _TEXT}, "run_seq"),
        ({"thread_id": _THREAD, "run_seq": 1, "started_at": ""}, "started_at"),
    ],
)
def test_run_id_rejects_bad_inputs(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        run_id(**kwargs)  # type: ignore[arg-type]


def test_run_identity_view_nulls_legacy_and_rejects_bool_seq() -> None:
    assert run_identity_view(None) == {
        "run_id": None,
        "run_seq": None,
        "run_cause": None,
    }
    assert run_identity_view({})["run_id"] is None
    # bool is a subclass of int — must not leak True as run_seq.
    assert run_identity_view({"run_seq": True})["run_seq"] is None
    assert run_identity_view({"run_id": "run_abc", "run_seq": 2, "run_cause": "rerun"}) == {
        "run_id": "run_abc",
        "run_seq": 2,
        "run_cause": "rerun",
    }
