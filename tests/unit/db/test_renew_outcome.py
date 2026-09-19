"""A lost lease that says how it was lost (09-19-renew-loss-has-a-kind).

``renew`` answered a ``bool`` until now, and its ``False`` carried both "the row
stopped being ours" and "the store could not be asked".  The two are not
interchangeable, and the direction is the **opposite** of ``acquire``'s: a run
that starts without a lease risks doing nothing, while a run that keeps writing
without one risks two writers on one checkpoint.  So both non-answers stop the
run here -- that part is deliberately unchanged, and the six existing ``renew``
assertions in ``test_execution_leases.py`` are proof of it, still green and still
unmodified.

What this file pins, and why each needs a test rather than a sentence:

- the same scenario answers the **same member** on both backends.  The memory
  backend cannot fail, so its vocabulary has no ``UNKNOWN`` -- the asymmetry
  ``acquire`` has too, read out of the module rather than asserted in prose;
- ``renew`` is a **projection** -- one comparison over the outcome, not a second
  copy of the decision;
- an empty ``thread_id`` answers UNKNOWN **without asking the store**, which is
  what the bare ``False`` did;
- ``_heartbeat_until_cancelled`` **stops on either** non-answer and **hands the
  one it got back out of the task** -- the ruling and the reason, in one place.
  Without the second half the enum would have no reader, which is the same
  vacuity as a column with no writer.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.db import execution_leases as leases

_OTHER_OWNER = "other-host:4242:deadbeef"
_MODULE = Path(leases.__file__)


def _boom(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("lease store unavailable")


@pytest.fixture(autouse=True)
def _memory_backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The fallback explicitly, and a clean store on both sides of the test."""
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    leases._reset_memory_store()
    yield
    leases._reset_memory_store()


async def _held_by_a_foreign_owner(thread_id: str) -> None:
    """Plant a fresh foreign lease, then hand our own identity back.

    ``acquire`` has to run *as* the other owner or the row would be ours and the
    question would never arise; ``_instance_id`` is restored so the code under
    test really is a second instance.
    """
    ours = leases._instance_id
    leases._instance_id = _OTHER_OWNER
    try:
        assert await leases.acquire(thread_id) is True
    finally:
        leases._instance_id = ours


class _FakeCursor:
    """Only the call ``renew_outcome`` makes.  The answer is a row or ``None``."""

    def __init__(self, row: Any) -> None:
        self._row = row

    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def fetchone(self) -> Any:
        return self._row


class _FakeConnection:
    def __init__(self, row: Any) -> None:
        self._row = row

    def cursor(self) -> Any:
        @contextlib.asynccontextmanager
        async def _cursor() -> Any:
            yield _FakeCursor(self._row)

        return _cursor()


class _FakePool:
    """A store whose whole answer is "did the UPDATE return the row".

    That is the only thing the SQL backend reads from storage here, so the branch
    under comparison is still the module's own -- the stub supplies a row, never
    a decision.
    """

    def __init__(self, *, ours: bool) -> None:
        self._row = ("t1",) if ours else None

    def connection(self) -> Any:
        conn = _FakeConnection(self._row)

        @contextlib.asynccontextmanager
        async def _connection() -> Any:
            yield conn

        return _connection()


# ── three answers, not two spellings of "no" ─────────────────────────────────


async def test_a_held_row_renews_and_a_foreign_one_is_lost() -> None:
    assert await leases.acquire("t1") is True
    assert await leases.renew_outcome("t1") is leases.RenewOutcome.RENEWED

    await _held_by_a_foreign_owner("t2")
    assert await leases.renew_outcome("t2") is leases.RenewOutcome.LOST


async def test_a_released_row_is_lost_rather_than_unknown() -> None:
    """Released is a fact about the row, not the absence of one.

    The distinction matters precisely because both stop the run: if ``release``
    answered UNKNOWN, the log would say "we could not ask" about a row whose
    state this process set itself.
    """
    await leases.acquire("t1")
    assert await leases.release("t1") is True

    assert await leases.renew_outcome("t1") is leases.RenewOutcome.LOST


async def test_the_store_that_cannot_be_asked_answers_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SQL backend's UNKNOWN exit: a store that raises, asked for real."""
    monkeypatch.setattr(leases, "is_pool_ready", lambda: True)
    monkeypatch.setattr(leases, "get_pool", _boom)

    assert await leases.renew_outcome("t1") is leases.RenewOutcome.UNKNOWN


async def test_an_empty_question_answers_unknown_without_asking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No caller can act on an empty ``thread_id``, so it is UNKNOWN rather than a
    fourth member -- and the store is not consulted at all, which is exactly what
    the bare ``False`` did."""
    monkeypatch.setattr(leases, "is_pool_ready", _boom)

    assert await leases.renew_outcome("") is leases.RenewOutcome.UNKNOWN


async def test_the_memory_backend_cannot_spell_unknown() -> None:
    """It cannot fail, so "we could not ask" is not in its vocabulary.

    Read out of the module rather than asserted in prose: the two backends share
    this asymmetry, and an UNKNOWN appearing in this function would make the
    memory store claim it *chose* LOST where it actually has no alternative.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_renew_in_memory"
    )
    spelled = [node.attr for node in ast.walk(target) if isinstance(node, ast.Attribute)]
    assert "UNKNOWN" not in spelled, f"_renew_in_memory can answer UNKNOWN: {spelled}"


# ── the same scenario, two backends, one value ───────────────────────────────


async def test_both_backends_answer_the_same_member(monkeypatch: pytest.MonkeyPatch) -> None:
    """The memory backend has fewer answers but not *different* ones.

    Its set is a subset -- {RENEWED, LOST} against {RENEWED, LOST, UNKNOWN} -- and
    that is the property worth pinning.  The two used to differ in a way that
    mattered: one could report "could not ask" and the other could not, so a
    caller branching on the answer behaved differently by deployment shape.
    """
    await leases.acquire("t1")
    renewed_memory = await leases.renew_outcome("t1")
    await _held_by_a_foreign_owner("t2")
    lost_memory = await leases.renew_outcome("t2")

    monkeypatch.setattr(leases, "is_pool_ready", lambda: True)
    monkeypatch.setattr(leases, "get_pool", lambda: _FakePool(ours=True))
    renewed_sql = await leases.renew_outcome("t3")
    monkeypatch.setattr(leases, "get_pool", lambda: _FakePool(ours=False))
    lost_sql = await leases.renew_outcome("t4")

    assert renewed_memory is renewed_sql is leases.RenewOutcome.RENEWED
    assert lost_memory is lost_sql is leases.RenewOutcome.LOST


# ── the bool is a projection, not a second decision ──────────────────────────


@pytest.mark.parametrize("outcome", list(leases.RenewOutcome))
async def test_renew_is_one_comparison_over_the_outcome(
    monkeypatch: pytest.MonkeyPatch, outcome: leases.RenewOutcome
) -> None:
    """Only RENEWED is a yes, and ``renew`` says so for each of the three.

    The six existing ``renew`` assertions stay meaningful because the projection
    is a comparison over the outcome rather than a parallel decision that could
    drift from it -- and because they were not edited to accommodate it.
    """
    monkeypatch.setattr(leases, "renew_outcome", AsyncMock(return_value=outcome))

    assert await leases.renew("t1") is (outcome is leases.RenewOutcome.RENEWED)


# ── the ruling, in the one place that makes it ───────────────────────────────


@pytest.mark.parametrize("outcome", list(leases.RenewOutcome))
async def test_the_heartbeat_stops_on_either_non_answer_and_says_which(
    monkeypatch: pytest.MonkeyPatch, outcome: leases.RenewOutcome, caplog: pytest.LogCaptureFixture
) -> None:
    """One table, three rows, and the middle two are the ruling.

    ``RENEWED`` keeps looping; ``LOST`` **and** ``UNKNOWN`` both stop. That is the
    opposite of what ``acquire`` does with its UNKNOWN, and it is the reason the
    two members exist separately: a future "tolerate a hiccup" change has to
    change one row here and leave the other alone, instead of editing a ``bool``
    and silently widening both.

    Two more things than "it stopped" are asserted, and each was a gap on its
    own: the value it **returns** (a heartbeat that stopped without saying why
    would leave the fence printing a guess) and the sentence it **logs** (the two
    members used to print the same words, which is how a storage failure got
    recorded as a takeover).
    """
    caplog.set_level(logging.WARNING, logger="xhs_growth.db.execution_leases")
    monkeypatch.setattr(leases, "renew_outcome", AsyncMock(return_value=outcome))

    heartbeat = asyncio.create_task(
        leases._heartbeat_until_cancelled("t1", interval_seconds=0.001, ttl_seconds=90.0)
    )
    if outcome is leases.RenewOutcome.RENEWED:
        await asyncio.sleep(0.02)
        assert not heartbeat.done(), "a renewed lease must keep the loop running"
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        assert "stopped for t1" not in caplog.text
        return

    assert await asyncio.wait_for(heartbeat, timeout=5.0) is outcome

    said = "another owner holds the row" if outcome is leases.RenewOutcome.LOST else "the store"
    other = "the store" if outcome is leases.RenewOutcome.LOST else "another owner holds the row"
    assert said in caplog.text
    assert other not in caplog.text
