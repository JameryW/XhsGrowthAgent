"""Authenticated HTTP adapter for the Creator Agent decision core."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.api.account_scope import require_owned_account
from backend.api.deps import get_current_user
from backend.api.errors import (
    CreatorActionConflictError,
    CreatorActionExecutionNotAllowedError,
    CreatorActionExecutionNotFoundError,
    CreatorActionNotFoundError,
    CreatorDecisionNotFoundError,
    CreatorEvidenceNotFoundError,
    CreatorFeedbackAudienceMismatchError,
    CreatorLearningSignalConflictError,
    CreatorLearningSignalNotFoundError,
    CreatorModelNotFoundError,
    ValidationError,
)
from backend.api.errors import (
    CreatorModelRevisionConflictError as ApiModelRevisionConflictError,
)
from backend.api.responses import ApiResponse, success
from backend.creator_agent import (
    ActionExecution,
    ActionIntentRequest,
    ActionResolution,
    ActionResolutionDisposition,
    ActionStatus,
    CreatorAdvisor,
    CreatorModelDefinition,
    CreatorModelStore,
    CreatorReviewDisposition,
    DecisionDatasetPage,
    DecisionRequest,
    DecisionStatus,
    EvidenceGraphEntry,
    EvidenceReferenceType,
    EvidenceSource,
    FeedbackInput,
    FeedbackOutcome,
    LearningSignal,
    LearningSignalReview,
    LearningSignalStatus,
    RelationshipMemory,
)
from backend.creator_agent.repository import (
    ActionExecutionNotAllowedError,
    ActionIntentMissingError,
    ActionResolutionConflictError,
    ActionValidationError,
    CreatorModelMissingError,
    CreatorModelRevisionConflictError,
    CreatorReviewModelRequiredError,
    DecisionRecordMissingError,
    FeedbackAudienceMismatchError,
    LearningSignalMissingError,
    LearningSignalReviewConflictError,
)
from backend.db.creator_agent import get_repository

router = APIRouter()


class SaveCreatorModelRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(default=0, ge=0)
    model: CreatorModelDefinition


class RecordFeedbackRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    feedback: FeedbackInput


class ResolveActionRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    disposition: ActionResolutionDisposition


class ExecuteActionRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)


class ReviewLearningSignalRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    disposition: CreatorReviewDisposition
    review_note: str = Field(default="", max_length=2000)
    expected_revision: int | None = Field(default=None, ge=0)
    model: CreatorModelDefinition | None = None


def _advisor() -> CreatorAdvisor:
    return CreatorAdvisor(get_repository())


def _model_store() -> CreatorModelStore:
    return CreatorModelStore(get_repository())


@router.get("/model")
async def get_creator_model(
    account_id: str = Query(..., min_length=1),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    await require_owned_account(str(user["id"]), account_id)
    model = await _model_store().get(account_id.strip())
    if model is None:
        raise CreatorModelNotFoundError(account_id.strip())
    return success(data=model.model_dump(mode="json"))


@router.put("/model")
async def save_creator_model(
    request: SaveCreatorModelRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    account_id = request.account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    try:
        model = await _model_store().save(
            account_id,
            request.model,
            expected_revision=request.expected_revision,
        )
    except CreatorModelRevisionConflictError as exc:
        raise ApiModelRevisionConflictError(exc.expected, exc.actual) from exc
    return success(data=model.model_dump(mode="json"))


@router.post("/decisions")
async def create_creator_decision(
    request: DecisionRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    account_id = request.account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    request.account_id = account_id
    try:
        decision = await _advisor().decide(request)
    except CreatorModelMissingError as exc:
        raise CreatorModelNotFoundError(exc.account_id) from exc
    return success(data=decision.model_dump(mode="json"))


@router.get("/decisions/{decision_id}")
async def get_creator_decision(
    decision_id: str,
    account_id: str = Query(..., min_length=1),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    await require_owned_account(str(user["id"]), account_id)
    try:
        decision = await _advisor().get_decision(account_id.strip(), decision_id.strip())
    except DecisionRecordMissingError as exc:
        raise CreatorDecisionNotFoundError(exc.decision_id) from exc
    return success(data=decision.model_dump(mode="json"))


@router.get("/dataset/decisions")
async def list_creator_decision_dataset(
    account_id: str = Query(..., min_length=1),
    audience_id: str | None = Query(default=None, json_schema_extra={"minLength": 1}),
    status: DecisionStatus | None = Query(default=None),
    feedback_outcome: FeedbackOutcome | None = Query(default=None),
    has_feedback: bool | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, json_schema_extra={"minimum": 1, "maximum": 100}),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[DecisionDatasetPage]:
    """List immutable decision snapshots with account-scoped pagination."""
    normalized_account_id = (account_id or "").strip()
    if not normalized_account_id:
        raise ValidationError("account_id", "account_id cannot be empty")
    normalized_audience_id = audience_id.strip() if audience_id is not None else None
    if audience_id is not None and not normalized_audience_id:
        raise ValidationError("audience_id", "audience_id cannot be empty")
    if not 1 <= limit <= 100:
        raise ValidationError("limit", "limit must be between 1 and 100")
    await require_owned_account(str(user["id"]), normalized_account_id)
    try:
        page = await _advisor().list_decision_dataset(
            normalized_account_id,
            audience_id=normalized_audience_id,
            status=status,
            feedback_outcome=feedback_outcome,
            has_feedback=has_feedback,
            cursor=cursor,
            limit=limit,
        )
    except ValueError as exc:
        field = "cursor" if "cursor" in str(exc) else "dataset"
        raise ValidationError(field, str(exc)) from exc
    return success(data=page.model_dump(mode="json"))


@router.post("/decisions/{decision_id}/feedback")
async def record_creator_feedback(
    decision_id: str,
    request: RecordFeedbackRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    account_id = request.account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    try:
        result = await _advisor().record_feedback(account_id, decision_id.strip(), request.feedback)
    except DecisionRecordMissingError as exc:
        raise CreatorDecisionNotFoundError(exc.decision_id) from exc
    except FeedbackAudienceMismatchError as exc:
        raise CreatorFeedbackAudienceMismatchError() from exc
    return success(data=result.model_dump(mode="json"))


@router.get("/relationships/{audience_id}")
async def get_creator_relationship(
    audience_id: str,
    account_id: str = Query(..., min_length=1),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[RelationshipMemory]:
    await require_owned_account(str(user["id"]), account_id)
    relationship = await _advisor().get_relationship(account_id.strip(), audience_id.strip())
    return success(data=relationship.model_dump(mode="json"))


@router.post("/actions")
async def plan_creator_action(
    request: ActionIntentRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Create a pending Action Intent; no external capability is invoked."""
    account_id = request.account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    request.account_id = account_id
    try:
        action = await _advisor().plan_action(request)
    except DecisionRecordMissingError as exc:
        raise CreatorDecisionNotFoundError(exc.decision_id) from exc
    except ActionValidationError as exc:
        raise ValidationError(exc.field, exc.reason) from exc
    return success(data=action.model_dump(mode="json"))


@router.get("/actions")
async def list_creator_actions(
    account_id: str = Query(..., min_length=1),
    status: ActionStatus | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    account_id = account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    actions = await _advisor().list_actions(account_id, status)
    return success(data=[action.model_dump(mode="json") for action in actions])


@router.post("/actions/{action_id}/resolve")
async def resolve_creator_action(
    action_id: str,
    request: ResolveActionRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Resolve an intent without executing it or contacting an external system."""
    account_id = request.account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    try:
        action = await _advisor().resolve_action(
            account_id, action_id.strip(), ActionResolution(disposition=request.disposition)
        )
    except ActionIntentMissingError as exc:
        raise CreatorActionNotFoundError(exc.action_id) from exc
    except ActionResolutionConflictError as exc:
        raise CreatorActionConflictError(exc.action_id, exc.existing_status.value) from exc
    return success(data=action.model_dump(mode="json"))


@router.post("/actions/{action_id}/execute")
async def execute_creator_action(
    action_id: str,
    request: ExecuteActionRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[ActionExecution]:
    """Execute a confirmed intent with the local deterministic executor."""
    account_id = request.account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    try:
        execution = await _advisor().execute_action(account_id, action_id.strip())
    except ActionIntentMissingError as exc:
        raise CreatorActionNotFoundError(exc.action_id) from exc
    except ActionExecutionNotAllowedError as exc:
        raise CreatorActionExecutionNotAllowedError(exc.action_id, exc.status.value) from exc
    except DecisionRecordMissingError as exc:
        raise CreatorDecisionNotFoundError(exc.decision_id) from exc
    return success(data=execution.model_dump(mode="json"))


@router.get("/actions/{action_id}/execution")
async def get_creator_action_execution(
    action_id: str,
    account_id: str = Query(..., min_length=1),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[ActionExecution]:
    """Read an immutable local execution receipt within the account scope."""
    account_id = account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    execution = await _advisor().get_action_execution(account_id, action_id.strip())
    if execution is None:
        raise CreatorActionExecutionNotFoundError(action_id.strip())
    return success(data=execution.model_dump(mode="json"))


@router.get("/learning-signals")
async def list_creator_learning_signals(
    account_id: str = Query(..., min_length=1),
    status: LearningSignalStatus | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[list[LearningSignal]]:
    account_id = account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    signals = await _advisor().list_learning_signals(account_id, status)
    return success(data=[signal.model_dump(mode="json") for signal in signals])


@router.post("/learning-signals/{signal_id}/review")
async def review_creator_learning_signal(
    signal_id: str,
    request: ReviewLearningSignalRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    account_id = request.account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    review = LearningSignalReview(
        disposition=request.disposition,
        review_note=request.review_note,
        expected_revision=request.expected_revision,
        model=request.model,
    )
    try:
        result = await _advisor().review_learning_signal(account_id, signal_id.strip(), review)
    except LearningSignalMissingError as exc:
        raise CreatorLearningSignalNotFoundError(exc.signal_id) from exc
    except LearningSignalReviewConflictError as exc:
        raise CreatorLearningSignalConflictError(exc.signal_id, exc.existing_status.value) from exc
    except CreatorModelRevisionConflictError as exc:
        raise ApiModelRevisionConflictError(exc.expected, exc.actual) from exc
    except CreatorReviewModelRequiredError as exc:
        raise ValidationError("model", str(exc)) from exc
    return success(data=result.model_dump(mode="json"))


@router.get("/evidence")
async def list_creator_evidence(
    account_id: str = Query(..., min_length=1),
    source_kind: EvidenceSource | None = Query(default=None),
    reference_type: EvidenceReferenceType | None = Query(default=None),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[list[EvidenceGraphEntry]]:
    """List the account-scoped, read-only Evidence Graph projection."""
    account_id = account_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    entries = await _advisor().list_evidence(account_id, source_kind, reference_type)
    return success(data=[entry.model_dump(mode="json") for entry in entries])


@router.get("/evidence/{evidence_id}")
async def get_creator_evidence(
    evidence_id: str,
    account_id: str = Query(..., min_length=1),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[EvidenceGraphEntry]:
    """Get one account-scoped Evidence Graph node and its typed references."""
    account_id = account_id.strip()
    evidence_id = evidence_id.strip()
    await require_owned_account(str(user["id"]), account_id)
    entry = await _advisor().get_evidence(account_id, evidence_id)
    if entry is None:
        raise CreatorEvidenceNotFoundError(evidence_id)
    return success(data=entry.model_dump(mode="json"))
