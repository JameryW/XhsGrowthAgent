"""Persistence seam and domain-level storage failures for Creator Agent."""

from __future__ import annotations

from typing import Protocol

from backend.creator_agent.models import (
    CreatorModel,
    CreatorModelDefinition,
    DecisionRecord,
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


__all__ = [
    "CreatorAgentRepository",
    "CreatorModelMissingError",
    "CreatorModelRevisionConflictError",
    "DecisionRecordMissingError",
    "FeedbackAudienceMismatchError",
]
