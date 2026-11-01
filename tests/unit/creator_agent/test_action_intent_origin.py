"""ActionIntent identity model: creator vs mainline origin (票 5bb).

This is the model half of the control-plane migration's identity decision
(option A in ``docs/publish-action-protocol.md``'s P1b note).  The rule it pins:

* **creator origin** (the only origin that existed before P1b) must carry the
  creator/audience pair a ``DecisionRecord`` names — an intent the executor
  cannot attribute is refused at the boundary;
* **mainline origin** comes from the workflow's own human review approval, which
  has no creator/audience concepts.  Those fields must be blank: filling them
  would be the mainline borrowing an identity it never had;
* rows written before this slice carry no ``origin`` key and must keep reading
  as creator intents — the durable rows are not rewritten.

Storage is ``payload_json`` (the whole model), so no column migration is needed;
the round-trip test pins that the origin survives the real repository.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.creator_agent import ActionCapability, ActionIntent, ActionOrigin
from backend.db import creator_agent as creator_agent_db

NOW = "2026-11-01T00:00:00+00:00"
ACCOUNT = "account-a"


@pytest.fixture(autouse=True)
def _reset_store():
    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()


def _intent(**overrides) -> ActionIntent:
    base: dict = {
        "action_id": "action-1",
        "account_id": ACCOUNT,
        "creator_id": "creator-a",
        "audience_id": "audience-a",
        "decision_id": "decision-1",
        "action_kind": ActionCapability.COMPARE_OPTIONS,
        "candidate_ids": ["a", "b"],
        "idempotency_key": "compare-1",
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return ActionIntent(**base)


class TestCreatorOriginKeepsRequiringTheDecisionIdentities:
    def test_the_default_origin_is_creator(self):
        assert _intent().origin is ActionOrigin.CREATOR

    @pytest.mark.parametrize(
        "overrides",
        [
            {"creator_id": ""},
            {"audience_id": ""},
            {"creator_id": "   "},
            {"audience_id": "   "},
        ],
    )
    def test_a_creator_intent_without_both_ids_is_refused(self, overrides):
        with pytest.raises(ValidationError, match="creator-origin intents require"):
            _intent(**overrides)


class TestMainlineOriginRefusesToBorrowIdentities:
    def test_blank_creator_and_audience_are_accepted(self):
        intent = _intent(origin=ActionOrigin.MAINLINE, creator_id="", audience_id="")

        assert intent.origin is ActionOrigin.MAINLINE
        assert intent.creator_id == ""
        assert intent.audience_id == ""

    @pytest.mark.parametrize(
        "overrides",
        [
            {"creator_id": "creator-a"},
            {"audience_id": "audience-a"},
            {"creator_id": "creator-a", "audience_id": "audience-a"},
        ],
    )
    def test_a_mainline_intent_carrying_creator_identities_is_refused(self, overrides):
        with pytest.raises(ValidationError, match="must not carry creator/audience"):
            _intent(origin=ActionOrigin.MAINLINE, **overrides)


class TestDurableRowsKeepTheirOrigin:
    def test_a_row_written_before_this_slice_reads_as_creator(self):
        legacy_payload = {
            "action_id": "legacy-1",
            "account_id": ACCOUNT,
            "creator_id": "creator-a",
            "audience_id": "audience-a",
            "decision_id": "decision-1",
            "action_kind": ActionCapability.COMPARE_OPTIONS.value,
            "candidate_ids": ["a", "b"],
            "idempotency_key": "compare-1",
            "created_at": NOW,
            "updated_at": NOW,
        }
        assert "origin" not in legacy_payload

        restored = ActionIntent.model_validate(legacy_payload)

        assert restored.origin is ActionOrigin.CREATOR

    async def test_the_repository_round_trips_a_mainline_intent(self):
        repo = creator_agent_db.DurableCreatorAgentRepository()
        intent = _intent(
            action_id="mainline-action-1",
            origin=ActionOrigin.MAINLINE,
            creator_id="",
            audience_id="",
            decision_id="mainline:thread-1:publish-1",
            action_kind=ActionCapability.PUBLISH,
            candidate_ids=[],
            artifact_ref="artifact://publish_content/publish-1",
            content_hash="a" * 64,
            thread_id="thread-1",
        )

        await repo.create_action(intent)
        restored = await repo.get_action(ACCOUNT, intent.action_id)

        assert restored is not None
        assert restored.origin is ActionOrigin.MAINLINE
        assert restored.creator_id == ""
        assert restored.audience_id == ""
        assert restored.decision_id == "mainline:thread-1:publish-1"
        assert restored.artifact_ref == "artifact://publish_content/publish-1"

    async def test_the_repository_round_trips_a_creator_intent(self):
        repo = creator_agent_db.DurableCreatorAgentRepository()
        intent = _intent()

        await repo.create_action(intent)
        restored = await repo.get_action(ACCOUNT, intent.action_id)

        assert restored is not None
        assert restored.origin is ActionOrigin.CREATOR
        assert restored.creator_id == "creator-a"
        assert restored.audience_id == "audience-a"

    def test_the_serialized_row_names_its_origin(self):
        dumped = _intent().model_dump(mode="json")

        assert dumped["origin"] == "creator"
        assert json.dumps(dumped)  # the payload the durable adapter stores is JSON
