"""Domain models for creator-owned, evidence-backed decisions."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class EvidenceSource(StrEnum):
    CREATOR_STATEMENT = "creator_statement"
    CREATOR_CONTENT = "creator_content"
    PRODUCT_FACT = "product_fact"
    EXTERNAL_FACT = "external_fact"
    USER_FEEDBACK = "user_feedback"


class EvidenceReferenceType(StrEnum):
    """Durable Creator Agent object types that can cite Evidence."""

    MODEL = "model"
    PREFERENCE = "preference"
    KNOWLEDGE_CLAIM = "knowledge_claim"
    DECISION_POLICY = "decision_policy"
    DECISION = "decision"
    CANDIDATE = "candidate"
    LEARNING_SIGNAL = "learning_signal"


class PreferenceStance(StrEnum):
    PREFER = "prefer"
    AVOID = "avoid"
    REQUIRE = "require"


class DecisionStatus(StrEnum):
    RECOMMENDED = "recommended"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"


class ActionCapability(StrEnum):
    """Non-transactional capabilities a future action executor may support."""

    COMPARE_OPTIONS = "compare_options"
    SAVE_SHORTLIST = "save_shortlist"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"


class ActionStatus(StrEnum):
    """Lifecycle state of a durable Action Intent."""

    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ActionResolutionDisposition(StrEnum):
    """Explicit user disposition; neither disposition executes an action."""

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class FeedbackOutcome(StrEnum):
    CONSIDERED = "considered"
    ACCEPTED = "accepted"
    PURCHASED = "purchased"
    SATISFIED = "satisfied"
    REJECTED = "rejected"
    DISSATISFIED = "dissatisfied"


class LearningStatus(StrEnum):
    OBSERVED = "observed"
    PENDING_CREATOR_REVIEW = "pending_creator_review"


class LearningSignalStatus(StrEnum):
    """Lifecycle of a feedback-derived signal awaiting creator judgement."""

    PENDING_CREATOR_REVIEW = "pending_creator_review"
    APPROVED = "approved"
    DISMISSED = "dismissed"


class CreatorReviewDisposition(StrEnum):
    """Explicit creator decision on a Learning Signal."""

    APPROVED = "approved"
    DISMISSED = "dismissed"


class Evidence(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    source_kind: EvidenceSource
    source_ref: str = Field(min_length=1, max_length=500)
    claim: str = Field(min_length=1, max_length=2000)
    observed_at: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class EvidenceReference(BaseModel):
    """A typed, account-scoped edge from Evidence to a durable object."""

    reference_type: EvidenceReferenceType
    target_id: str = Field(min_length=1, max_length=300)
    model_revision: int | None = Field(default=None, ge=1)


class EvidenceGraphEntry(BaseModel):
    """One Evidence node and its deduplicated provenance references."""

    evidence: Evidence
    references: list[EvidenceReference] = Field(default_factory=list, max_length=1000)


class Preference(BaseModel):
    preference_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=300)
    stance: PreferenceStance = PreferenceStance.PREFER
    tags: list[str] = Field(default_factory=list, max_length=50)
    applies_when: dict[str, str] = Field(default_factory=dict)
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=50)


class KnowledgeClaim(BaseModel):
    claim_id: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(min_length=1, max_length=50)


class DecisionPolicy(BaseModel):
    policy_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=300)
    applies_when: dict[str, str] = Field(default_factory=dict)
    signal_weights: dict[str, float] = Field(default_factory=dict)
    preferred_tags: list[str] = Field(default_factory=list, max_length=50)
    excluded_tags: list[str] = Field(default_factory=list, max_length=50)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("signal_weights")
    @classmethod
    def validate_signal_weights(cls, value: dict[str, float]) -> dict[str, float]:
        for key, weight in value.items():
            if not key.strip():
                raise ValueError("signal weight names cannot be empty")
            if not -1.0 <= weight <= 1.0:
                raise ValueError("signal weights must be between -1 and 1")
        return value


class CreatorModelDefinition(BaseModel):
    identity_summary: str = Field(min_length=1, max_length=2000)
    domains: list[str] = Field(default_factory=list, max_length=50)
    preferences: list[Preference] = Field(default_factory=list, max_length=200)
    knowledge: list[KnowledgeClaim] = Field(default_factory=list, max_length=500)
    policies: list[DecisionPolicy] = Field(default_factory=list, max_length=200)
    evidence: list[Evidence] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_identity_and_evidence(self) -> CreatorModelDefinition:
        collections = (
            ("preference", [item.preference_id for item in self.preferences]),
            ("knowledge claim", [item.claim_id for item in self.knowledge]),
            ("decision policy", [item.policy_id for item in self.policies]),
            ("evidence", [item.evidence_id for item in self.evidence]),
        )
        for label, identifiers in collections:
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {label} id")

        known_evidence = {item.evidence_id for item in self.evidence}
        references = [
            ("preference", item.preference_id, item.evidence_ids) for item in self.preferences
        ]
        references.extend(
            ("knowledge claim", item.claim_id, item.evidence_ids) for item in self.knowledge
        )
        references.extend(
            ("decision policy", item.policy_id, item.evidence_ids) for item in self.policies
        )
        for kind, item_id, evidence_ids in references:
            unknown = sorted(set(evidence_ids) - known_evidence)
            if unknown:
                raise ValueError(f"{kind} {item_id!r} references unknown evidence: {unknown}")
        return self


class CreatorModel(CreatorModelDefinition):
    account_id: str = Field(min_length=1, max_length=128)
    creator_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=1)
    created_at: str
    updated_at: str


class HardConstraint(BaseModel):
    field: str = Field(min_length=1, max_length=128)
    value: Any


class DecisionCandidate(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=300)
    attributes: dict[str, Any] = Field(default_factory=dict)
    signals: dict[str, float] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=100)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)

    @field_validator("signals")
    @classmethod
    def validate_signals(cls, value: dict[str, float]) -> dict[str, float]:
        for key, signal in value.items():
            if not key.strip():
                raise ValueError("signal names cannot be empty")
            if not 0.0 <= signal <= 1.0:
                raise ValueError("candidate signals must be between 0 and 1")
        return value


class DecisionRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)
    audience_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=1, max_length=2000)
    context: dict[str, str] = Field(default_factory=dict)
    hard_constraints: list[HardConstraint] = Field(default_factory=list, max_length=50)
    candidates: list[DecisionCandidate] = Field(min_length=2, max_length=100)

    @model_validator(mode="after")
    def validate_candidate_ids(self) -> DecisionRequest:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("duplicate candidate id")
        return self


class RankedCandidate(BaseModel):
    candidate_id: str
    label: str
    score: float
    rationale: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class ExcludedCandidate(BaseModel):
    candidate_id: str
    label: str
    reasons: list[str]


class FeedbackInput(BaseModel):
    feedback_id: str = Field(default="", max_length=128)
    audience_id: str = Field(min_length=1, max_length=128)
    outcome: FeedbackOutcome
    selected_candidate_id: str = Field(default="", max_length=128)
    note: str = Field(default="", max_length=2000)
    correction: str = Field(default="", max_length=2000)


class UserFeedback(FeedbackInput):
    feedback_id: str = Field(min_length=1, max_length=128)
    created_at: str


class DecisionRecord(BaseModel):
    decision_id: str
    account_id: str
    audience_id: str
    creator_id: str
    model_revision: int
    goal: str
    context: dict[str, str] = Field(default_factory=dict)
    status: DecisionStatus
    matched_policy_ids: list[str] = Field(default_factory=list)
    recommendations: list[RankedCandidate] = Field(default_factory=list)
    excluded_candidates: list[ExcludedCandidate] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    feedback: list[UserFeedback] = Field(default_factory=list)
    created_at: str
    updated_at: str


def encode_decision_dataset_cursor(created_at: str, decision_id: str) -> str:
    """Encode the canonical Decision Dataset sort key as an opaque cursor.

    The dataset is ordered newest-first by ``created_at`` and then
    ``decision_id``.  Only that key is encoded so a cursor never captures a
    filter or account identifier that could be replayed across queries.
    """

    payload = json.dumps(
        {
            "v": 1,
            "created_at": str(created_at or ""),
            "decision_id": str(decision_id or ""),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_decision_dataset_cursor(cursor: str) -> tuple[str, str]:
    """Decode and validate a versioned Decision Dataset cursor.

    Invalid tokens are deliberately rejected instead of silently restarting
    at page one.  This keeps stale links observable to API clients and makes
    future cursor format changes safe to roll out.
    """

    token = (cursor or "").strip()
    if not token:
        raise ValueError("cursor cannot be empty")
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = json.loads(base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True))
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError("invalid decision dataset cursor") from exc
    if not isinstance(raw, dict) or type(raw.get("v")) is not int or raw.get("v") != 1:
        raise ValueError("unsupported decision dataset cursor")
    if set(raw) != {"v", "created_at", "decision_id"}:
        raise ValueError("invalid decision dataset cursor fields")
    created_at = raw.get("created_at")
    decision_id = raw.get("decision_id")
    if not isinstance(created_at, str) or not isinstance(decision_id, str) or not decision_id:
        raise ValueError("invalid decision dataset cursor fields")
    return created_at, decision_id


# Short aliases keep the cursor contract discoverable to generic pagination
# callers while retaining an explicitly namespaced canonical implementation.
encode_dataset_cursor = encode_decision_dataset_cursor
decode_dataset_cursor = decode_decision_dataset_cursor


class DecisionDatasetEntry(BaseModel):
    """Read-only projection of one immutable Decision Record snapshot."""

    decision: DecisionRecord
    learning_signal_ids: list[str] = Field(default_factory=list, max_length=1000)


class DecisionDatasetPage(BaseModel):
    """A stable, account-scoped page of Decision Dataset entries."""

    items: list[DecisionDatasetEntry] = Field(default_factory=list, max_length=100)
    total: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)
    next_cursor: str | None = None


class ActionIntentRequest(BaseModel):
    """Request to create an account-scoped, confirmation-gated action."""

    account_id: str = Field(min_length=1, max_length=128)
    decision_id: str = Field(min_length=1, max_length=128)
    action_kind: ActionCapability
    candidate_ids: list[str] = Field(default_factory=list, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=256)

    @field_validator("account_id", "decision_id", "idempotency_key")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value

    @field_validator("candidate_ids")
    @classmethod
    def validate_candidate_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("candidate IDs cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("candidate IDs must be unique")
        return normalized


class ActionResolution(BaseModel):
    """Explicit confirmation/cancellation; resolution has no side effects."""

    disposition: ActionResolutionDisposition


class ActionIntent(BaseModel):
    """Durable hand-off between a Decision Record and a future executor."""

    action_id: str = Field(min_length=1, max_length=128)
    account_id: str = Field(min_length=1, max_length=128)
    creator_id: str = Field(min_length=1, max_length=128)
    audience_id: str = Field(min_length=1, max_length=128)
    decision_id: str = Field(min_length=1, max_length=128)
    action_kind: ActionCapability
    candidate_ids: list[str] = Field(default_factory=list, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=256)
    status: ActionStatus = ActionStatus.PENDING_CONFIRMATION
    resolved_at: str | None = None
    created_at: str
    updated_at: str


class RelationshipMemory(BaseModel):
    account_id: str
    audience_id: str
    interaction_count: int = Field(default=0, ge=0)
    accepted_candidate_ids: list[str] = Field(default_factory=list)
    rejected_candidate_ids: list[str] = Field(default_factory=list)
    latest_correction: str = ""
    last_interaction_at: str = ""


class FeedbackResult(BaseModel):
    decision: DecisionRecord
    relationship: RelationshipMemory
    learning_status: LearningStatus
    created: bool
    learning_signal: LearningSignal | None = None


class LearningSignal(BaseModel):
    """Auditable, reviewable observation derived from one User Feedback."""

    signal_id: str = Field(min_length=1, max_length=128)
    account_id: str = Field(min_length=1, max_length=128)
    creator_id: str = Field(min_length=1, max_length=128)
    audience_id: str = Field(min_length=1, max_length=128)
    decision_id: str = Field(min_length=1, max_length=128)
    feedback_id: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=2000)
    correction: str = Field(default="", max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=1000)
    status: LearningSignalStatus = LearningSignalStatus.PENDING_CREATOR_REVIEW
    review_note: str = Field(default="", max_length=2000)
    reviewed_at: str | None = None
    applied_model_revision: int | None = Field(default=None, ge=1)
    created_at: str
    updated_at: str


class LearningSignalReview(BaseModel):
    """Request to explicitly dismiss or apply a Learning Signal."""

    disposition: CreatorReviewDisposition
    review_note: str = Field(default="", max_length=2000)
    expected_revision: int | None = Field(default=None, ge=0)
    model: CreatorModelDefinition | None = None


class LearningSignalReviewResult(BaseModel):
    """Signal disposition and the model revision produced by approval."""

    signal: LearningSignal
    model: CreatorModel | None = None


__all__ = [
    "CreatorModel",
    "CreatorModelDefinition",
    "DecisionCandidate",
    "DecisionDatasetEntry",
    "DecisionDatasetPage",
    "DecisionPolicy",
    "DecisionRecord",
    "DecisionRequest",
    "DecisionStatus",
    "decode_decision_dataset_cursor",
    "decode_dataset_cursor",
    "encode_decision_dataset_cursor",
    "encode_dataset_cursor",
    "ActionCapability",
    "ActionIntent",
    "ActionIntentRequest",
    "ActionResolution",
    "ActionResolutionDisposition",
    "ActionStatus",
    "Evidence",
    "EvidenceGraphEntry",
    "EvidenceReference",
    "EvidenceReferenceType",
    "EvidenceSource",
    "ExcludedCandidate",
    "FeedbackInput",
    "FeedbackOutcome",
    "FeedbackResult",
    "CreatorReviewDisposition",
    "HardConstraint",
    "KnowledgeClaim",
    "LearningStatus",
    "LearningSignal",
    "LearningSignalReview",
    "LearningSignalReviewResult",
    "LearningSignalStatus",
    "Preference",
    "PreferenceStance",
    "RankedCandidate",
    "RelationshipMemory",
    "UserFeedback",
    "utc_now_iso",
]
