"""A refusal that says which refusal (09-19-lease-refusal-has-a-reason).

``acquire`` answered a ``bool`` until now, and that one ``False`` carried three
different meanings: a live foreign owner refused the row, the store could not be
asked, and the question was empty.  The three are not interchangeable to a caller
about to write a checkpoint -- the middle one is evidence about the row, the last
is the absence of evidence -- which is why ``docs/execution-plane.md`` §2's
non-guarantee 1 is now two rules instead of one.

Four things this file pins, and the reason each needs a test rather than a
sentence:

- the same scenario answers the **same member** on both backends.  The two used to
  answer *different sets*: the SQL backend folded "cannot ask" into the same
  ``False`` while the memory backend, which cannot fail, had no such answer at all.
- the memory backend's **only** refusal is the evidenced one, read out of the
  module rather than asserted in prose;
- ``acquire`` is a **projection** -- one comparison over the outcome, not a second
  copy of the decision, which is what keeps the 60+ existing ``acquire`` assertions
  meaningful instead of vacuous;
- an empty ``thread_id`` answers UNKNOWN **without asking the store**, which is the
  behaviour it had when the answer was a bare ``False``.
"""

from __future__ import annotations

import ast
import contextlib
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
    """Only the two calls ``acquire_outcome`` makes.  The answer is a row count."""

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
    """A store whose whole answer is "did the insert return a row".

    That is the only thing the SQL backend reads from storage, so the branch under
    comparison here is still the module's own -- the stub supplies a row, never a
    decision.
    """

    def __init__(self, *, granted: bool) -> None:
        self._row = ("t1",) if granted else None

    def connection(self) -> Any:
        conn = _FakeConnection(self._row)

        @contextlib.asynccontextmanager
        async def _connection() -> Any:
            yield conn

        return _connection()


# ── three answers, not three spellings of "no" ───────────────────────────────


async def test_a_free_row_is_granted_and_a_foreign_live_one_is_not() -> None:
    assert await leases.acquire_outcome("t1") is leases.AcquireOutcome.GRANTED

    await _held_by_a_foreign_owner("t2")
    assert await leases.acquire_outcome("t2") is leases.AcquireOutcome.HELD_BY_LIVE_OWNER


async def test_the_store_that_cannot_be_asked_answers_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SQL backend's UNKNOWN exit: a store that raises, asked for real.

    Ruling 2 keeps the caller running on this answer, so the value is not merely
    a label -- it is the one that must *not* gate.
    """
    monkeypatch.setattr(leases, "is_pool_ready", lambda: True)
    monkeypatch.setattr(leases, "get_pool", _boom)

    assert await leases.acquire_outcome("t1") is leases.AcquireOutcome.UNKNOWN


async def test_an_empty_question_answers_unknown_without_asking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No caller can act on an empty ``thread_id``, so it is UNKNOWN rather than a
    fourth member -- and the store is not consulted at all, which is exactly what
    the bare ``False`` did."""
    monkeypatch.setattr(leases, "is_pool_ready", _boom)

    assert await leases.acquire_outcome("") is leases.AcquireOutcome.UNKNOWN


async def test_the_memory_backend_cannot_spell_unknown() -> None:
    """It cannot fail, so "we could not ask" is not in its vocabulary.

    Read out of the module rather than asserted in prose: the asymmetry this slice
    removed was that the two backends answered *different sets*, and an UNKNOWN
    reappearing in that function would put the same asymmetry back while both
    backends still looked like they agreed on the words.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_acquire_in_memory"
    )
    spelled = [node.attr for node in ast.walk(target) if isinstance(node, ast.Attribute)]
    assert "UNKNOWN" not in spelled, f"_acquire_in_memory can answer UNKNOWN: {spelled}"


# ── acceptance 1: the same scenario, two backends, one value ─────────────────


async def test_both_backends_answer_the_same_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Before this slice the two answer *sets* differed; now the values agree."""
    granted_memory = await leases.acquire_outcome("t1")
    await _held_by_a_foreign_owner("t2")
    held_memory = await leases.acquire_outcome("t2")

    monkeypatch.setattr(leases, "is_pool_ready", lambda: True)
    monkeypatch.setattr(leases, "get_pool", lambda: _FakePool(granted=True))
    granted_sql = await leases.acquire_outcome("t3")
    monkeypatch.setattr(leases, "get_pool", lambda: _FakePool(granted=False))
    held_sql = await leases.acquire_outcome("t4")

    assert granted_memory is granted_sql is leases.AcquireOutcome.GRANTED
    assert held_memory is held_sql is leases.AcquireOutcome.HELD_BY_LIVE_OWNER


# ── the bool is a projection, not a second decision ──────────────────────────


@pytest.mark.parametrize("outcome", list(leases.AcquireOutcome))
async def test_acquire_is_one_comparison_over_the_outcome(
    monkeypatch: pytest.MonkeyPatch, outcome: leases.AcquireOutcome
) -> None:
    """Only one of the three answers is a grant, and ``acquire`` still says so.

    The existing ``acquire`` assertions stay meaningful because the projection is
    a comparison over the outcome rather than a parallel decision that could drift
    from it.
    """
    monkeypatch.setattr(leases, "acquire_outcome", AsyncMock(return_value=outcome))

    assert await leases.acquire("t1") is (outcome is leases.AcquireOutcome.GRANTED)
