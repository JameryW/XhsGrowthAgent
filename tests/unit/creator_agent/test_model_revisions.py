from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.creator_agent import (
    CreatorAdvisor,
    CreatorModelDefinition,
    CreatorReviewDisposition,
    DecisionCandidate,
    DecisionPolicy,
    DecisionRequest,
    Evidence,
    EvidenceSource,
    FeedbackInput,
    FeedbackOutcome,
    LearningSignalReview,
    ModelRevision,
    ModelRevisionMissingError,
    ModelRevisionSource,
    build_model_revision_page,
    decode_model_revision_cursor,
    encode_model_revision_cursor,
)
from backend.creator_agent.repository import DecisionRecordMissingError
from backend.db import creator_agent as creator_agent_db


@pytest.fixture(autouse=True)
def _reset_store():
    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()


def _definition(identity: str = "耐用体验创作者") -> CreatorModelDefinition:
    evidence = Evidence(
        evidence_id="e1",
        source_kind=EvidenceSource.CREATOR_STATEMENT,
        source_ref="creator://statement/1",
        claim="优先选择耐用的方案",
    )
    return CreatorModelDefinition(
        identity_summary=identity,
        policies=[
            DecisionPolicy(
                policy_id="p1",
                label="耐用优先",
                signal_weights={"durability": 1.0},
                rationale="长期使用先看耐用性。",
                evidence_ids=["e1"],
            )
        ],
        evidence=[evidence],
    )


def _request(account_id: str = "account-a") -> DecisionRequest:
    return DecisionRequest(
        account_id=account_id,
        audience_id="audience-a",
        goal="选择日常方案",
        candidates=[
            DecisionCandidate(candidate_id="a", label="A", signals={"durability": 0.9}),
            DecisionCandidate(candidate_id="b", label="B", signals={"durability": 0.2}),
        ],
    )


def _model(account_id: str = "account-a", revision: int = 1) -> creator_agent_db.CreatorModel:
    return creator_agent_db.CreatorModel(
        **_definition().model_dump(),
        account_id=account_id,
        creator_id="creator-a",
        revision=revision,
        created_at="2026-09-07T09:00:00+00:00",
        updated_at="2026-09-07T09:00:00+00:00",
    )


def _revision(account_id: str = "account-a", revision: int = 1) -> ModelRevision:
    return ModelRevision(
        account_id=account_id,
        revision=revision,
        recorded_at="2026-09-07T10:00:00+00:00",
        source=ModelRevisionSource.CREATOR_EDIT,
        model=_model(account_id, revision),
    )


async def _save_next_revision(
    repo: creator_agent_db.DurableCreatorAgentRepository, account_id: str = "account-a"
) -> None:
    current = await repo.get_model(account_id)
    assert current is not None
    await repo.save_model(
        account_id, _definition("加入便携性权衡"), expected_revision=current.revision
    )


@pytest.mark.asyncio
async def test_first_save_creates_revision_one_and_each_edit_appends_one_snapshot():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    first = await repo.save_model("account-a", _definition(), expected_revision=0)

    page = await repo.list_model_revisions("account-a")
    assert page.total == 1
    assert [item.revision for item in page.items] == [first.revision]
    assert page.items[0].source is ModelRevisionSource.CREATOR_EDIT
    assert page.items[0].source_signal_id is None
    assert page.items[0].recorded_at == first.updated_at

    second = await repo.save_model("account-a", _definition("加入便携性权衡"), expected_revision=1)
    history = await repo.list_model_revisions("account-a")

    assert second.revision == 2
    assert history.total == 2
    assert [item.revision for item in history.items] == [2, 1]
    assert history.items[1].model.identity_summary == "耐用体验创作者"


@pytest.mark.asyncio
async def test_earlier_revision_stays_verbatim_after_later_edit_and_decision():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    advisor = CreatorAdvisor(repo)
    await repo.save_model("account-a", _definition(), expected_revision=0)
    decision = await advisor.decide(_request())
    assert decision.model_revision == 1

    await repo.save_model("account-a", _definition("加入便携性权衡"), expected_revision=1)

    resolved = await advisor.get_decision_model_revision("account-a", decision.decision_id)
    first_revision = await advisor.get_model_revision("account-a", 1)
    current = await repo.get_model("account-a")

    assert current is not None
    assert current.revision == 2
    # The decision resolves to the judgement it actually used, not the current model.
    assert resolved.revision == 1
    assert resolved.model.identity_summary == "耐用体验创作者"
    assert first_revision.model.model_dump() == resolved.model.model_dump()
    assert [policy.rationale for policy in resolved.model.policies] == ["长期使用先看耐用性。"]


@pytest.mark.asyncio
async def test_approved_review_is_attributed_to_its_signal_and_dismissal_adds_nothing():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    advisor = CreatorAdvisor(repo)
    initial = await repo.save_model("account-a", _definition(), expected_revision=0)
    decision = await advisor.decide(_request())
    feedback = await advisor.record_feedback(
        "account-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="feedback-1",
            audience_id="audience-a",
            outcome=FeedbackOutcome.DISSATISFIED,
            correction="更在意便携性。",
        ),
    )
    signal = feedback.learning_signal
    assert signal is not None

    dismissed = await advisor.review_learning_signal(
        "account-a",
        signal.signal_id,
        LearningSignalReview(
            disposition=CreatorReviewDisposition.DISMISSED,
            review_note="一次性偏好，不纳入模型。",
        ),
    )
    after_dismissal = await advisor.list_model_revisions("account-a")
    assert dismissed.model is None
    assert [item.revision for item in after_dismissal.items] == [initial.revision]

    second_signal = (
        await advisor.record_feedback(
            "account-a",
            decision.decision_id,
            FeedbackInput(
                feedback_id="feedback-2",
                audience_id="audience-a",
                outcome=FeedbackOutcome.DISSATISFIED,
                correction="更轻便。",
            ),
        )
    ).learning_signal
    assert second_signal is not None

    approved = await advisor.review_learning_signal(
        "account-a",
        second_signal.signal_id,
        LearningSignalReview(
            disposition=CreatorReviewDisposition.APPROVED,
            expected_revision=initial.revision,
            model=_definition("加入便携性权衡"),
        ),
    )
    history = await advisor.list_model_revisions("account-a")
    newest = history.items[0]

    assert approved.model is not None
    assert approved.model.revision == newest.revision == 2
    assert newest.source is ModelRevisionSource.LEARNING_REVIEW
    assert newest.source_signal_id == second_signal.signal_id
    assert history.total == 2


@pytest.mark.asyncio
async def test_repeat_review_resolves_applied_revision_after_later_creator_edit():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    advisor = CreatorAdvisor(repo)
    initial = await repo.save_model("account-a", _definition(), expected_revision=0)
    decision = await advisor.decide(_request())
    signal = (
        await advisor.record_feedback(
            "account-a",
            decision.decision_id,
            FeedbackInput(
                feedback_id="feedback-3",
                audience_id="audience-a",
                outcome=FeedbackOutcome.DISSATISFIED,
                correction="更轻便。",
            ),
        )
    ).learning_signal
    assert signal is not None

    approved = await advisor.review_learning_signal(
        "account-a",
        signal.signal_id,
        LearningSignalReview(
            disposition=CreatorReviewDisposition.APPROVED,
            expected_revision=initial.revision,
            model=_definition("加入便携性权衡"),
        ),
    )
    await _save_next_revision(repo)

    repeated = await advisor.review_learning_signal(
        "account-a",
        signal.signal_id,
        LearningSignalReview(
            disposition=CreatorReviewDisposition.APPROVED,
            expected_revision=0,
            model=_definition("重复请求应被忽略"),
        ),
    )

    assert approved.model is not None
    assert repeated.model is not None
    # A later edit must not make a completed review forget what it produced.
    assert repeated.model.revision == approved.model.revision == 2
    assert repeated.model.identity_summary == "加入便携性权衡"
    assert (await repo.get_model("account-a")).revision == 3


@pytest.mark.asyncio
async def test_history_pages_are_stable_newest_first_and_total_ignores_cursor():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    for index in range(5):
        await repo.save_model("account-a", _definition(f"创作者 v{index}"), expected_revision=index)

    first_page = await repo.list_model_revisions("account-a", limit=2)
    second_page = await repo.list_model_revisions(
        "account-a", cursor=first_page.next_cursor, limit=2
    )
    third_page = await repo.list_model_revisions(
        "account-a", cursor=second_page.next_cursor, limit=2
    )

    assert first_page.limit == second_page.limit == third_page.limit == 2
    assert [item.revision for item in first_page.items] == [5, 4]
    assert [item.revision for item in second_page.items] == [3, 2]
    assert [item.revision for item in third_page.items] == [1]
    assert third_page.next_cursor is None
    # total always describes the complete filtered history, not the remainder.
    assert first_page.total == second_page.total == third_page.total == 5


@pytest.mark.asyncio
async def test_cursor_round_trips_and_invalid_input_fails_loudly():
    assert decode_model_revision_cursor(encode_model_revision_cursor(7)) == 7

    with pytest.raises(ValueError, match="cursor"):
        decode_model_revision_cursor("not-a-real-cursor")
    with pytest.raises(ValueError, match="cursor"):
        decode_model_revision_cursor(encode_model_revision_cursor(0))

    page = build_model_revision_page([_revision()], cursor=None, limit=20)
    assert page.total == 1
    with pytest.raises(ValueError, match="limit"):
        build_model_revision_page([_revision()], limit=0)
    with pytest.raises(ValueError, match="limit"):
        build_model_revision_page([_revision()], limit=101)


def test_revision_snapshot_identity_is_validated():
    with pytest.raises(PydanticValidationError, match="account mismatch"):
        ModelRevision(
            account_id="account-b",
            revision=1,
            recorded_at="2026-09-07T10:00:00+00:00",
            source=ModelRevisionSource.CREATOR_EDIT,
            model=_model("account-a", 1),
        )

    with pytest.raises(PydanticValidationError, match="revision mismatch"):
        ModelRevision(
            account_id="account-a",
            revision=2,
            recorded_at="2026-09-07T10:00:00+00:00",
            source=ModelRevisionSource.CREATOR_EDIT,
            model=_model("account-a", 1),
        )

    with pytest.raises(PydanticValidationError, match="learning_review"):
        ModelRevision(
            account_id="account-a",
            revision=1,
            recorded_at="2026-09-07T10:00:00+00:00",
            source=ModelRevisionSource.CREATOR_EDIT,
            source_signal_id="signal-1",
            model=_model("account-a", 1),
        )

    attributed = ModelRevision(
        account_id="account-a",
        revision=1,
        recorded_at="2026-09-07T10:00:00+00:00",
        source=ModelRevisionSource.LEARNING_REVIEW,
        source_signal_id="signal-1",
        model=_model("account-a", 1),
    )
    assert attributed.source_signal_id == "signal-1"


@pytest.mark.asyncio
async def test_history_reads_are_account_scoped_and_never_fall_back_to_current_model():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    advisor = CreatorAdvisor(repo)
    await repo.save_model("account-a", _definition(), expected_revision=0)
    await repo.save_model("account-b", _definition("另一位创作者"), expected_revision=0)

    assert (await repo.list_model_revisions("account-b")).total == 1
    assert await repo.get_model_revision("account-a", 99) is None
    assert await repo.get_model_revision("account-b", 1) is not None

    with pytest.raises(ModelRevisionMissingError):
        await advisor.get_model_revision("account-a", 99)
    with pytest.raises(ModelRevisionMissingError):
        await advisor.get_model_revision("account-b", 2)

    decision = await advisor.decide(_request("account-b"))
    with pytest.raises(DecisionRecordMissingError):
        await advisor.get_decision_model_revision("account-b", "missing-decision")
    # The decision's own revision resolves; an unrelated account's history stays invisible.
    assert (
        await advisor.get_decision_model_revision("account-b", decision.decision_id)
    ).revision == 1


@pytest.mark.asyncio
async def test_returned_snapshots_are_defensive_copies_of_stored_history():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)

    page = await repo.list_model_revisions("account-a")
    fetched = await repo.get_model_revision("account-a", 1)
    assert fetched is not None
    page.items[0].model.identity_summary = "客户端篡改"
    fetched.model.policies[0].rationale = "篡改存储外的返回值"

    unchanged = await repo.list_model_revisions("account-a")
    assert unchanged.items[0].model.identity_summary == "耐用体验创作者"
    assert unchanged.items[0].model.policies[0].rationale == "长期使用先看耐用性。"


@pytest.mark.asyncio
async def test_backfill_and_live_append_emit_the_same_readable_row_shape():
    """Guard the one column contract shared by the backfill and both write paths.

    The Postgres backfill and the live appends must serialize the identical
    ModelRevision envelope, because every reader parses the column as such. A
    Creator Model payload written straight into the history column would parse
    as a model but fail as a snapshot, which is exactly the shape this asserts.
    """

    class _RecordingCursor:
        def __init__(self) -> None:
            self.statement = ""
            self.params: tuple[object, ...] = ()

        async def execute(self, statement: str, params: tuple[object, ...] = ()) -> None:
            self.statement = statement
            self.params = tuple(params)

    repo = creator_agent_db.DurableCreatorAgentRepository()
    model = await repo.save_model("account-a", _definition(), expected_revision=0)
    cursor = _RecordingCursor()

    await repo._insert_model_revision(  # noqa: SLF001
        cursor,
        creator_agent_db._model_revision_snapshot(model, ModelRevisionSource.CREATOR_EDIT),  # noqa: SLF001
    )
    appended = cursor.params
    imported = repo._model_revision_params(  # noqa: SLF001
        creator_agent_db._model_revision_snapshot(  # noqa: SLF001
            model, ModelRevisionSource.IMPORTED_HISTORY, recorded_at=model.updated_at
        )
    )

    assert len(appended) == 7
    assert len(imported) == 7
    assert cursor.statement == creator_agent_db._INSERT_MODEL_REVISION_SQL  # noqa: SLF001
    for params, source in ((appended, "creator_edit"), (imported, "imported_history")):
        account_id, creator_id, revision, stored_source, signal_id, payload, recorded_at = params
        assert (account_id, creator_id, revision) == ("account-a", model.creator_id, 1)
        assert stored_source == source
        assert signal_id is None
        assert isinstance(recorded_at, str) and recorded_at
        parsed = ModelRevision.model_validate_json(payload)
        assert parsed.source.value == source
        assert parsed.model.model_dump() == model.model_dump()


@pytest.mark.asyncio
async def test_replayed_write_never_rewrites_history_or_changes_total():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    first = await repo.save_model("account-a", _definition(), expected_revision=0)
    before = await repo.list_model_revisions("account-a")

    # A replayed construction of the same revision must not displace the stored
    # snapshot, mirroring Postgres ON CONFLICT DO NOTHING.
    repo._remember_model_revision(  # noqa: SLF001
        first.model_copy(update={"identity_summary": "重放不应改写历史"}),
        ModelRevisionSource.CREATOR_EDIT,
    )
    after = await repo.list_model_revisions("account-a")

    assert after.total == before.total == 1
    assert after.items[0].model.identity_summary == "耐用体验创作者"


@pytest.mark.asyncio
async def test_cursor_carries_no_account_identity_and_rejects_unknown_version():
    import base64
    import json

    repo = creator_agent_db.DurableCreatorAgentRepository()
    for index in range(3):
        await repo.save_model("account-a", _definition(f"甲 v{index}"), expected_revision=index)
        await repo.save_model("account-b", _definition(f"乙 v{index}"), expected_revision=index)

    token = encode_model_revision_cursor(3)
    page_a = await repo.list_model_revisions("account-a", cursor=token, limit=5)
    page_b = await repo.list_model_revisions("account-b", cursor=token, limit=5)

    # The same token only paginates whatever account the request is scoped to.
    assert [item.revision for item in page_a.items] == [2, 1]
    assert [item.revision for item in page_b.items] == [2, 1]
    assert page_a.total == page_b.total == 3
    assert "account" not in base64.b64decode(token + "==").decode("utf-8")

    unsupported = (
        base64.urlsafe_b64encode(json.dumps({"v": 2, "revision": 3}).encode())
        .decode("ascii")
        .rstrip("=")
    )
    with pytest.raises(ValueError, match="unsupported"):
        decode_model_revision_cursor(unsupported)
