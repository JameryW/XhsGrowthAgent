"""Authenticated HTTP adapter for the Creator Agent decision core."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.api.account_scope import require_owned_account
from backend.api.deps import get_current_user
from backend.api.errors import (
    CreatorDecisionNotFoundError,
    CreatorFeedbackAudienceMismatchError,
    CreatorModelNotFoundError,
)
from backend.api.errors import (
    CreatorModelRevisionConflictError as ApiModelRevisionConflictError,
)
from backend.api.responses import ApiResponse, success
from backend.creator_agent import (
    CreatorAdvisor,
    CreatorModelDefinition,
    CreatorModelStore,
    DecisionRequest,
    FeedbackInput,
    RelationshipMemory,
)
from backend.creator_agent.repository import (
    CreatorModelMissingError,
    CreatorModelRevisionConflictError,
    DecisionRecordMissingError,
    FeedbackAudienceMismatchError,
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
