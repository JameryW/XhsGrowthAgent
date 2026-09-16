"""P2a-S5b: the Decision Record's frozen judgment, and its single writer.

``DecisionRecord`` is documented as frozen-at-write, and until this slice the
implementation disagreed with its own readers: ``apply_feedback`` rewrote the
stored payload in place — appending a reaction *and* re-serialising every field
that judged the decision — while ``DecisionDatasetEntry`` called the very same
object "an immutable snapshot".  Two descriptions of one thing, neither checked.

What is pinned here is the split that makes both true:

* the judgment is byte-identical after a reaction arrives, read back **from the
  store** rather than from the returned object;
* ``feedback`` is append-only, and a retry of the same reaction changes nothing
  at all;
* exactly one place in the adapter mutates a stored record — the last test is
  structural because "one writer" is a claim a comment cannot enforce.

Nothing here asserts *which* fields exist; the frozen set is derived from the
model so a field added later cannot slip past the comparison unexamined.
"""

from __future__ import annotations

import pathlib

import pytest

from backend.creator_agent import CreatorAdvisor, FeedbackInput, FeedbackOutcome
from backend.creator_agent.models import DecisionRecord
from backend.db import creator_agent as creator_agent_db
from tests.unit.creator_agent.test_core import _definition, _request

ACCOUNT = "account-a"

#: The only two fields a stored record is allowed to move.  Everything else is
#: derived from the model rather than listed, so a new field is compared by
#: default instead of being silently ignored.
APPEND_ONLY = frozenset({"feedback", "updated_at"})


@pytest.fixture(autouse=True)
def _reset_store():
    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()


def _feedback(feedback_id: str = "feedback-1", **overrides) -> FeedbackInput:
    base: dict = {
        "feedback_id": feedback_id,
        "audience_id": "audience-a",
        "outcome": FeedbackOutcome.SATISFIED,
        "selected_candidate_id": "candidate-a",
    }
    base.update(overrides)
    return FeedbackInput(**base)


async def _decided():
    """A real decision, produced the way production produces one."""
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model(ACCOUNT, _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    return advisor, await advisor.decide(_request(ACCOUNT))


def _frozen(record: dict) -> dict:
    return {key: value for key, value in record.items() if key not in APPEND_ONLY}


class TestTheJudgmentIsFrozen:
    @pytest.mark.asyncio
    async def test_a_reaction_does_not_rewrite_what_judged_the_decision(self):
        advisor, decision = await _decided()
        before = decision.model_dump(mode="json")

        await advisor.record_feedback(ACCOUNT, decision.decision_id, _feedback())

        stored = (await advisor.get_decision(ACCOUNT, decision.decision_id)).model_dump(mode="json")
        assert _frozen(stored) == _frozen(before)

    @pytest.mark.asyncio
    async def test_the_reaction_is_appended_and_dated(self):
        advisor, decision = await _decided()

        result = await advisor.record_feedback(ACCOUNT, decision.decision_id, _feedback())

        stored = await advisor.get_decision(ACCOUNT, decision.decision_id)
        assert result.created is True
        assert len(stored.feedback) == len(decision.feedback) + 1
        assert stored.feedback[-1].feedback_id == "feedback-1"
        # updated_at is not a wall clock of its own: it names when the reaction
        # arrived, which is what makes the record's age readable from one field.
        assert stored.updated_at == stored.feedback[-1].created_at

    @pytest.mark.asyncio
    async def test_reactions_keep_arriving_at_the_end(self):
        """Append-only means the order *is* the history: a new reaction must
        land after the ones already there, never in front of them."""
        advisor, decision = await _decided()

        await advisor.record_feedback(ACCOUNT, decision.decision_id, _feedback("feedback-1"))
        await advisor.record_feedback(ACCOUNT, decision.decision_id, _feedback("feedback-2"))

        stored = await advisor.get_decision(ACCOUNT, decision.decision_id)
        assert [item.feedback_id for item in stored.feedback] == ["feedback-1", "feedback-2"]

    def test_the_comparison_covers_every_field_but_the_append_only_two(self):
        """Guards the guard: an empty or truncated ``_frozen`` would pass silently."""
        record = dict.fromkeys(DecisionRecord.model_fields, None)
        assert len(_frozen(record)) == len(DecisionRecord.model_fields) - len(APPEND_ONLY)
        assert set(record) - APPEND_ONLY == set(_frozen(record))


class TestAnIdempotentRetryIsATotalNoOp:
    @pytest.mark.asyncio
    async def test_the_same_reaction_twice_leaves_the_record_byte_identical(self):
        advisor, decision = await _decided()
        await advisor.record_feedback(ACCOUNT, decision.decision_id, _feedback())
        after_first = (await advisor.get_decision(ACCOUNT, decision.decision_id)).model_dump(
            mode="json"
        )

        result = await advisor.record_feedback(ACCOUNT, decision.decision_id, _feedback())

        after_second = (await advisor.get_decision(ACCOUNT, decision.decision_id)).model_dump(
            mode="json"
        )
        assert result.created is False
        assert after_second == after_first


class TestThereIsExactlyOneWriter:
    """The structural half: "one writer" has to be checkable, not just stated."""

    def test_only_the_helper_mutates_a_stored_record(self):
        source = pathlib.Path(creator_agent_db.__file__).read_text(encoding="utf-8")
        assert source.count("decision.feedback.append") == 1
        assert source.count("decision.updated_at = feedback.created_at") == 1

    def test_both_storage_adapters_go_through_it(self):
        """One call per adapter — memory and Postgres cannot drift apart."""
        source = pathlib.Path(creator_agent_db.__file__).read_text(encoding="utf-8")
        assert source.count("_append_feedback(decision, feedback)") == 2

    @pytest.mark.asyncio
    async def test_the_helper_is_what_the_memory_adapter_actually_calls(self, monkeypatch):
        """The structural counts above must describe the executed path, not a
        coincidence: replace the helper and the stored record stops moving."""
        advisor, decision = await _decided()
        calls: list[str] = []
        original = creator_agent_db._append_feedback

        def _spy(target, feedback):
            calls.append(feedback.feedback_id)
            original(target, feedback)

        monkeypatch.setattr(creator_agent_db, "_append_feedback", _spy)

        await advisor.record_feedback(ACCOUNT, decision.decision_id, _feedback())

        assert calls == ["feedback-1"]
