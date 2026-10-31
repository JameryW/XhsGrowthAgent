"""``EVENT_KINDS`` is the set of kinds an emitter can actually produce.

It is pinned as a literal because the interesting failure is silent: declaring a
kind nobody writes costs nothing at runtime, and ``signal_inventory`` only
reports *undeclared* kinds as drift -- so "declared but never emitted" is
invisible debt by construction.  Two names were exactly that until 票 5ao:

- ``cost`` never had an emitter.  Cost rides on ``kind:"llm"`` entries
  (``cost_usd``, built by ``backend.agents.nodes._base.llm_perf_entry``) and the
  ``/analytics/costs`` reader aggregates from those.
- ``error`` never had one either.  The live channel is the realtime
  ``EventBusService.WORKFLOW_ERROR`` bus; the durable per-node record is
  ``kind:"node"`` with ``status``/``error``.

Emitting them would have created a second truth for the same fact, which is the
one thing this repository keeps refusing (two renderings of a state, two
parsers, two owners of a lease).  Retiring the declaration makes the vocabulary
match the writers.  Re-adding a kind -- or re-adding one of these two -- now
takes an edit to the literal below, i.e. a deliberate decision.
"""

from __future__ import annotations

from backend.db.workflow_events import EVENT_KINDS

#: The complete declared vocabulary. Keep it a literal: this is the pin.
DECLARED_KINDS = frozenset(
    {
        "action",
        "attempt",
        "context",
        "human_wait",
        "llm",
        "node",
        "progress",
        "ripple",
        "run",
        "tool",
        "verification",
    }
)


def test_the_declared_vocabulary_is_exactly_the_pinned_set() -> None:
    assert EVENT_KINDS == DECLARED_KINDS


def test_the_retired_kinds_stay_retired() -> None:
    """The two names that never had an emitter must not come back by accident."""
    assert "cost" not in EVENT_KINDS
    assert "error" not in EVENT_KINDS
