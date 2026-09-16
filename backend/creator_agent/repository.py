"""Persistence seam and domain-level storage failures for Creator Agent."""

from __future__ import annotations

from typing import Protocol

from backend.creator_agent.models import (
    ActionCapability,
    ActionExecution,
    ActionIntent,
    ActionResolution,
    ActionResolutionDisposition,
    ActionStatus,
    CreatorModel,
    CreatorModelDefinition,
    CreatorReviewDisposition,
    DecisionDatasetPage,
    DecisionRecord,
    DecisionStatus,
    EvidenceGraphEntry,
    EvidenceReferenceType,
    EvidenceSource,
    FeedbackOutcome,
    LearningSignal,
    LearningSignalReview,
    LearningSignalStatus,
    ModelRevision,
    ModelRevisionPage,
    RelationshipMemory,
    UserFeedback,
)
from backend.creator_agent.policy import PolicyId


class CreatorModelRevisionConflictError(Exception):
    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"creator model revision conflict: expected {expected}, actual {actual}")


class CreatorModelMissingError(Exception):
    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(f"creator model not found for account {account_id!r}")


class ModelRevisionMissingError(Exception):
    """No immutable Model Revision snapshot exists for the requested revision."""

    def __init__(self, account_id: str, revision: int) -> None:
        self.account_id = account_id
        self.revision = revision
        super().__init__(f"creator model revision {revision} not found for account {account_id!r}")


class DecisionRecordMissingError(Exception):
    def __init__(self, decision_id: str) -> None:
        self.decision_id = decision_id
        super().__init__(f"decision record {decision_id!r} not found")


class FeedbackAudienceMismatchError(Exception):
    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"feedback audience mismatch: expected {expected!r}, actual {actual!r}")


class ActionIntentMissingError(Exception):
    def __init__(self, action_id: str) -> None:
        self.action_id = action_id
        super().__init__(f"action intent {action_id!r} not found")


class ActionResolutionConflictError(Exception):
    def __init__(
        self,
        action_id: str,
        existing_status: ActionStatus,
        requested_disposition: ActionResolutionDisposition,
    ) -> None:
        self.action_id = action_id
        self.existing_status = existing_status
        self.requested_disposition = requested_disposition
        super().__init__(
            f"action intent {action_id!r} already has status {existing_status.value!r}"
        )


class ActionValidationError(Exception):
    def __init__(self, reason: str, field: str = "action") -> None:
        self.reason = reason
        self.field = field
        super().__init__(reason)


class ActionCapabilityNotWiredError(Exception):
    """The capability has a durable intent but no executor wired yet.

    ``action_kind`` is kept **raw** rather than narrowed to
    :class:`ActionCapability`, because the one caller that raises this holds
    whatever the intent carried: assuming the enum would break on exactly the
    case the error was written for (a capability the executor does not know).
    Read :attr:`kind_label` for the printable form.
    """

    def __init__(self, action_id: str, action_kind: ActionCapability | str) -> None:
        self.action_id = action_id
        self.action_kind = action_kind
        super().__init__(f"action {action_id} of kind {self.kind_label} has no executor wired yet")

    @property
    def kind_label(self) -> str:
        """The capability as text, including values the enum does not declare.

        ``str`` serves both cases because :class:`ActionCapability` is a
        ``StrEnum``: a member prints as its value (``"publish"``), and so does a
        raw string the executor did not recognise.  Kept as one spelling on
        purpose -- a defensive ``getattr(self.action_kind, "value", ...)`` is
        indistinguishable on every input this error can receive, so the test that
        pins the member case is worth more than the branch it would justify.
        """
        return str(self.action_kind)


class ActionPolicyDeniedError(Exception):
    """Deterministic policy refused to let this intent become durable.

    Raised from ``plan_action`` *before* the intent is created, so a denial and
    a "never planned" are the same thing from the repository's point of view --
    deliberately: a human must never be asked to confirm an action that policy
    has already refused.
    """

    def __init__(
        self,
        *,
        account_id: str,
        policy_id: PolicyId,
        reason: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.account_id = account_id
        self.policy_id = policy_id
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"action policy {policy_id.value} denied the request: {reason}")


class ActionExecutionNotAllowedError(Exception):
    """An Action Intent is not confirmed and therefore cannot execute."""

    def __init__(self, action_id: str, status: ActionStatus) -> None:
        self.action_id = action_id
        self.status = status
        super().__init__(f"action intent {action_id!r} with status {status.value!r} cannot execute")


class ActionPublishContentUnavailableError(Exception):
    """A confirmed publish intent cannot locate a usable payload.

    Raised before the Gateway is consulted, so the refusal costs no side
    effect.  Two causes share one error because they share one remedy: a human
    has to look at the intent.  Either the row carries no ``thread_id``
    (written before P2a-S3 added it), or the artifact it points at is missing,
    unreadable, or not shaped like a publish payload.  ``reason`` says which,
    because that is what an operator reading the 409 needs.
    """

    def __init__(self, action_id: str, reason: str) -> None:
        self.action_id = action_id
        self.reason = reason
        super().__init__(f"publish intent {action_id!r} has no usable content: {reason}")


class ActionCredentialUnavailableError(Exception):
    """The account holds no credential for the capability being executed.

    The third refusal on the publish path, raised where the other two are —
    before the Gateway, so an unentitled action costs no side effect.  P2a-S5a
    gives the account a grant owner; until this check existed, ``xhs.publish``'s
    declared ``auth_scope`` was enforced only when a caller happened to pass
    scopes, which nothing in production did.

    ``required_scopes`` is what the capability *declares* it needs (read from
    the registry at refusal time), so the message reports the missing scope
    instead of restating one this module guessed at.
    """

    def __init__(self, account_id: str, required_scopes: tuple[str, ...], reason: str) -> None:
        self.account_id = account_id
        self.required_scopes = required_scopes
        self.reason = reason
        scopes = ", ".join(required_scopes) or "(none declared)"
        super().__init__(f"account {account_id!r} holds no credential for {scopes}: {reason}")


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

    async def list_model_revisions(
        self,
        account_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ModelRevisionPage: ...

    async def get_model_revision(self, account_id: str, revision: int) -> ModelRevision | None: ...

    async def create_decision(self, decision: DecisionRecord) -> None: ...

    async def get_decision(self, account_id: str, decision_id: str) -> DecisionRecord | None: ...

    async def list_decision_dataset(
        self,
        account_id: str,
        *,
        audience_id: str | None = None,
        status: DecisionStatus | None = None,
        feedback_outcome: FeedbackOutcome | None = None,
        has_feedback: bool | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> DecisionDatasetPage: ...

    async def get_action_by_idempotency_key(
        self, account_id: str, idempotency_key: str
    ) -> ActionIntent | None: ...

    async def create_action(self, action: ActionIntent) -> ActionIntent: ...

    async def get_action(self, account_id: str, action_id: str) -> ActionIntent | None: ...

    async def list_actions(
        self, account_id: str, status: ActionStatus | None = None
    ) -> list[ActionIntent]: ...

    async def resolve_action(
        self, account_id: str, action_id: str, resolution: ActionResolution
    ) -> ActionIntent: ...

    async def get_action_execution(
        self, account_id: str, action_id: str
    ) -> ActionExecution | None: ...

    async def create_action_execution(self, execution: ActionExecution) -> ActionExecution: ...

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

    async def list_evidence(
        self,
        account_id: str,
        source_kind: EvidenceSource | None = None,
        reference_type: EvidenceReferenceType | None = None,
    ) -> list[EvidenceGraphEntry]: ...

    async def get_evidence(
        self, account_id: str, evidence_id: str
    ) -> EvidenceGraphEntry | None: ...


__all__ = [
    "CreatorAgentRepository",
    "ActionIntentMissingError",
    "ActionExecutionNotAllowedError",
    "ActionCredentialUnavailableError",
    "ActionResolutionConflictError",
    "ActionValidationError",
    "CreatorModelMissingError",
    "CreatorModelRevisionConflictError",
    "DecisionRecordMissingError",
    "ModelRevisionMissingError",
    "FeedbackAudienceMismatchError",
    "LearningSignalMissingError",
    "LearningSignalReviewConflictError",
    "CreatorReviewModelRequiredError",
]
