"""Persistence seam and domain-level storage failures for Creator Agent."""

from __future__ import annotations

from typing import Protocol

from backend.creator_agent.models import (
    CreatorModel,
    CreatorModelDefinition,
    CreatorReviewDisposition,
    DecisionRecord,
    LearningSignal,
    LearningSignalReview,
    LearningSignalStatus,
    RelationshipMemory,
    UserFeedback,
)


class CreatorModelRevisionConflictError(Exception):
    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"creator model revision conflict: expected {expected}, actual {actual}")


class CreatorModelMissingError(Exception):
    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(f"creator model not found for account {account_id!r}")


class DecisionRecordMissingError(Exception):
    def __init__(self, decision_id: str) -> None:
        self.decision_id = decision_id
        super().__init__(f"decision record {decision_id!r} not found")


class FeedbackAudienceMismatchError(Exception):
    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"feedback audience mismatch: expected {expected!r}, actual {actual!r}")


class LearningSignalMissingError(Exception):
    def __init__(self, signal_id: str) -> None:
        self.signal_id = signal_id
        super().__init__(f"learning signal {signal_id!r} not found")


class LearningSignalReviewConflictError(Exception):
    def __init__(
        self,
        signal_id: str,
        existing_status: LearningSignalStatus,
        requested_disposition: CreatorReviewDisposition,
    ) -> None:
        self.signal_id = signal_id
        self.existing_status = existing_status
        self.requested_disposition = requested_disposition
        super().__init__(
            f"learning signal {signal_id!r} already has status {existing_status.value!r}"
        )


class CreatorReviewModelRequiredError(Exception):
    def __init__(self) -> None:
        super().__init__("approved creator review requires model and expected_revision")


class CreatorAgentRepository(Protocol):
    async def get_model(self, account_id: str) -> CreatorModel | None: ...

    async def save_model(
        self,
        account_id: str,
        definition: CreatorModelDefinition,
        *,
        expected_revision: int,
    ) -> CreatorModel: ...

    async def create_decision(self, decision: DecisionRecord) -> None: ...

    async def get_decision(self, account_id: str, decision_id: str) -> DecisionRecord | None: ...

    async def apply_feedback(
        self,
        account_id: str,
        decision_id: str,
        feedback: UserFeedback,
    ) -> tuple[DecisionRecord, RelationshipMemory, bool]: ...

    async def get_relationship(
        self, account_id: str, audience_id: str
    ) -> RelationshipMemory | None: ...

    async def get_learning_signal(
        self, account_id: str, signal_id: str
    ) -> LearningSignal | None: ...

    async def get_learning_signal_by_feedback(
        self, account_id: str, feedback_id: str
    ) -> LearningSignal | None: ...

    async def list_learning_signals(
        self, account_id: str, status: LearningSignalStatus | None = None
    ) -> list[LearningSignal]: ...

    async def review_learning_signal(
        self,
        account_id: str,
        signal_id: str,
        review: LearningSignalReview,
    ) -> tuple[LearningSignal, CreatorModel | None]: ...


__all__ = [
    "CreatorAgentRepository",
    "CreatorModelMissingError",
    "CreatorModelRevisionConflictError",
    "DecisionRecordMissingError",
    "FeedbackAudienceMismatchError",
    "LearningSignalMissingError",
    "LearningSignalReviewConflictError",
    "CreatorReviewModelRequiredError",
]
