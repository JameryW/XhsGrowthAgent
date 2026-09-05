"""Deterministic Creator Agent decisions and feedback learning signals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from backend.creator_agent.models import (
    ActionCapability,
    ActionExecution,
    ActionExecutionStatus,
    ActionIntent,
    ActionIntentRequest,
    ActionResolution,
    ActionStatus,
    DecisionCandidate,
    DecisionDatasetPage,
    DecisionRecord,
    DecisionRequest,
    DecisionStatus,
    Evidence,
    EvidenceGraphEntry,
    EvidenceReferenceType,
    EvidenceSource,
    ExcludedCandidate,
    FeedbackInput,
    FeedbackOutcome,
    FeedbackResult,
    LearningSignal,
    LearningSignalReview,
    LearningSignalReviewResult,
    LearningSignalStatus,
    LearningStatus,
    Preference,
    PreferenceStance,
    RankedCandidate,
    RelationshipMemory,
    UserFeedback,
    utc_now_iso,
)
from backend.creator_agent.repository import (
    ActionExecutionNotAllowedError,
    ActionIntentMissingError,
    ActionValidationError,
    CreatorAgentRepository,
    CreatorModelMissingError,
    DecisionRecordMissingError,
    FeedbackAudienceMismatchError,
)


@dataclass
class _CandidateEvaluation:
    candidate: DecisionCandidate
    score: float = 0.0
    rationale: list[str] = field(default_factory=list)
    evidence_ids: set[str] = field(default_factory=set)
    declared_evidence_ids: set[str] = field(default_factory=set)


def _context_matches(conditions: dict[str, str], context: dict[str, str]) -> bool:
    # A non-empty policy/preference declaration is intentionally an exact
    # context selector.  Treating it as a subset would silently apply a
    # narrowly authored rule to requests with additional, potentially
    # conflicting context fields.
    return not conditions or conditions == context


def _constraint_failures(candidate: DecisionCandidate, request: DecisionRequest) -> list[str]:
    return [
        f"constraint:{constraint.field}"
        for constraint in request.hard_constraints
        if candidate.attributes.get(constraint.field) != constraint.value
    ]


def _preference_applies(preference: Preference, candidate: DecisionCandidate) -> bool:
    return bool(set(preference.tags) & set(candidate.tags))


class CreatorAdvisor:
    """Use one exact Creator Model revision to decide, then retain outcomes."""

    EXECUTOR_VERSION = "local-v1"

    def __init__(self, repository: CreatorAgentRepository):
        self._repository = repository

    async def decide(self, request: DecisionRequest) -> DecisionRecord:
        model = await self._repository.get_model(request.account_id)
        if model is None:
            raise CreatorModelMissingError(request.account_id)

        matched_policies = [
            policy
            for policy in model.policies
            if _context_matches(policy.applies_when, request.context)
        ]
        matched_preferences = [
            preference
            for preference in model.preferences
            if _context_matches(preference.applies_when, request.context)
        ]
        evidence_by_id = {item.evidence_id: item for item in model.evidence}
        candidate_evidence: dict[str, Evidence] = {}
        for candidate in request.candidates:
            candidate_evidence.update({item.evidence_id: item for item in candidate.evidence})

        excluded: list[ExcludedCandidate] = []
        eligible: list[_CandidateEvaluation] = []
        for candidate in request.candidates:
            reasons = _constraint_failures(candidate, request)
            candidate_tags = set(candidate.tags)
            for policy in matched_policies:
                blocked = sorted(candidate_tags & set(policy.excluded_tags))
                reasons.extend(f"policy:{policy.policy_id}:excluded_tag:{tag}" for tag in blocked)
            for preference in matched_preferences:
                if preference.stance is PreferenceStance.REQUIRE and not _preference_applies(
                    preference, candidate
                ):
                    reasons.append(f"preference:{preference.preference_id}:required_tag_missing")

            if reasons:
                excluded.append(
                    ExcludedCandidate(
                        candidate_id=candidate.candidate_id,
                        label=candidate.label,
                        reasons=sorted(set(reasons)),
                    )
                )
                continue

            evaluated = _CandidateEvaluation(candidate=candidate)
            for policy in matched_policies:
                contributions = {
                    signal: weight * candidate.signals.get(signal, 0.0)
                    for signal, weight in policy.signal_weights.items()
                }
                weight_total = sum(abs(weight) for weight in policy.signal_weights.values())
                policy_score = sum(contributions.values()) / weight_total if weight_total else 0.0
                evaluated.score += policy_score
                evaluated.rationale.append(f"{policy.label}: {policy.rationale}")
                for signal, contribution in sorted(
                    contributions.items(), key=lambda item: (-abs(item[1]), item[0])
                )[:3]:
                    evaluated.rationale.append(f"signal:{signal}={contribution:.3f}")
                evaluated.declared_evidence_ids.update(policy.evidence_ids)
                evaluated.evidence_ids.update(
                    evidence_id
                    for evidence_id in policy.evidence_ids
                    if evidence_id in evidence_by_id
                )

                preferred = sorted(candidate_tags & set(policy.preferred_tags))
                if preferred:
                    evaluated.score += 0.05 * len(preferred)
                    evaluated.rationale.append(f"preferred_tags:{','.join(preferred)}")

            for preference in matched_preferences:
                if not _preference_applies(preference, candidate):
                    continue
                if preference.stance is PreferenceStance.PREFER:
                    evaluated.score += 0.15 * preference.strength
                elif preference.stance is PreferenceStance.AVOID:
                    evaluated.score -= 0.15 * preference.strength
                evaluated.rationale.append(
                    f"preference:{preference.label}:{preference.stance.value}"
                )
                evaluated.declared_evidence_ids.update(preference.evidence_ids)
                evaluated.evidence_ids.update(
                    evidence_id
                    for evidence_id in preference.evidence_ids
                    if evidence_id in evidence_by_id
                )

            own_evidence_ids = {item.evidence_id for item in candidate.evidence}
            evaluated.declared_evidence_ids.update(own_evidence_ids)
            evaluated.evidence_ids.update(own_evidence_ids)
            evaluated.score = max(-1.0, min(1.0, evaluated.score))
            eligible.append(evaluated)

        eligible.sort(key=lambda item: (-item.score, item.candidate.candidate_id))
        declared_evidence_ids = set().union(
            *(item.declared_evidence_ids for item in eligible), set()
        )
        used_evidence_ids = set().union(*(item.evidence_ids for item in eligible), set())
        coverage = (
            len(used_evidence_ids) / len(declared_evidence_ids) if declared_evidence_ids else 0.0
        )

        if not eligible:
            status = DecisionStatus.NO_ELIGIBLE_CANDIDATE
        elif not matched_policies or not used_evidence_ids:
            status = DecisionStatus.INSUFFICIENT_EVIDENCE
        else:
            status = DecisionStatus.RECOMMENDED

        recommendations: list[RankedCandidate] = []
        if status is DecisionStatus.RECOMMENDED:
            recommendations = [
                RankedCandidate(
                    candidate_id=item.candidate.candidate_id,
                    label=item.candidate.label,
                    score=round(item.score, 6),
                    rationale=item.rationale,
                    evidence_ids=sorted(item.evidence_ids),
                )
                for item in eligible
            ]

        used_evidence = {
            evidence_id: evidence_by_id.get(evidence_id) or candidate_evidence.get(evidence_id)
            for evidence_id in used_evidence_ids
        }
        evidence = [item for _, item in sorted(used_evidence.items()) if item is not None]
        confidence = self._confidence(eligible, evidence, coverage, status)
        now = utc_now_iso()
        decision = DecisionRecord(
            decision_id=str(uuid.uuid4()),
            account_id=request.account_id,
            audience_id=request.audience_id,
            creator_id=model.creator_id,
            model_revision=model.revision,
            goal=request.goal,
            context=request.context,
            status=status,
            matched_policy_ids=[policy.policy_id for policy in matched_policies],
            recommendations=recommendations,
            excluded_candidates=excluded,
            evidence=evidence,
            evidence_coverage=round(coverage, 6),
            confidence=confidence,
            created_at=now,
            updated_at=now,
        )
        await self._repository.create_decision(decision)
        return decision

    async def plan_action(self, request: ActionIntentRequest) -> ActionIntent:
        """Validate and persist a confirmation-gated action hand-off."""
        account_id = request.account_id.strip()
        idempotency_key = request.idempotency_key.strip()
        existing = await self._repository.get_action_by_idempotency_key(account_id, idempotency_key)
        if existing is not None:
            # Idempotency intentionally precedes payload validation: a retry
            # must return the original intent and never overwrite its targets.
            return existing

        decision = await self._repository.get_decision(account_id, request.decision_id.strip())
        if decision is None:
            raise DecisionRecordMissingError(request.decision_id.strip())

        candidate_ids = list(request.candidate_ids)
        recommendations = {item.candidate_id for item in decision.recommendations}
        if request.action_kind is ActionCapability.REQUEST_MORE_EVIDENCE:
            if candidate_ids:
                raise ActionValidationError(
                    "request_more_evidence does not accept candidate IDs", "candidate_ids"
                )
        else:
            if decision.status is not DecisionStatus.RECOMMENDED:
                raise ActionValidationError(
                    "candidate actions require a recommended decision", "decision_id"
                )
            minimum = 2 if request.action_kind is ActionCapability.COMPARE_OPTIONS else 1
            if len(candidate_ids) < minimum:
                raise ActionValidationError(
                    f"{request.action_kind.value} requires at least {minimum} candidate IDs",
                    "candidate_ids",
                )
            missing = sorted(set(candidate_ids) - recommendations)
            if missing:
                raise ActionValidationError(
                    f"candidate IDs are not recommendations: {missing}", "candidate_ids"
                )

        now = utc_now_iso()
        action = ActionIntent(
            action_id=str(uuid.uuid4()),
            account_id=account_id,
            creator_id=decision.creator_id,
            audience_id=decision.audience_id,
            decision_id=decision.decision_id,
            action_kind=request.action_kind,
            candidate_ids=candidate_ids,
            idempotency_key=idempotency_key,
            status=ActionStatus.PENDING_CONFIRMATION,
            created_at=now,
            updated_at=now,
        )
        return await self._repository.create_action(action)

    async def list_actions(
        self, account_id: str, status: ActionStatus | None = None
    ) -> list[ActionIntent]:
        """List account-scoped intents, optionally filtered by lifecycle status."""
        return await self._repository.list_actions(account_id.strip(), status)

    async def resolve_action(
        self, account_id: str, action_id: str, resolution: ActionResolution
    ) -> ActionIntent:
        """Record confirmation/cancellation without executing external work."""
        return await self._repository.resolve_action(
            account_id.strip(), action_id.strip(), resolution
        )

    async def execute_action(self, account_id: str, action_id: str) -> ActionExecution:
        """Execute one confirmed intent with a deterministic local executor.

        The receipt is built from the immutable Decision Record snapshot and is
        persisted by the repository.  The repository repeats the confirmation
        and source-existence checks while holding its adapter lock/transaction,
        so a concurrent cancellation cannot slip through between these reads.
        """
        normalized_account_id = account_id.strip()
        normalized_action_id = action_id.strip()
        existing = await self._repository.get_action_execution(
            normalized_account_id, normalized_action_id
        )
        if existing is not None:
            return existing

        action = await self._repository.get_action(normalized_account_id, normalized_action_id)
        if action is None:
            # The repository's existing Action Intent error is deliberately
            # raised here rather than exposing account ownership details.
            raise ActionIntentMissingError(normalized_action_id)
        if action.status is not ActionStatus.CONFIRMED:
            raise ActionExecutionNotAllowedError(normalized_action_id, action.status)

        decision = await self._repository.get_decision(normalized_account_id, action.decision_id)
        if decision is None:
            raise DecisionRecordMissingError(action.decision_id)

        recommendations = {item.candidate_id: item for item in decision.recommendations}
        if action.action_kind is ActionCapability.COMPARE_OPTIONS:
            result: dict[str, object] = {
                "decision_id": decision.decision_id,
                "candidate_ids": list(action.candidate_ids),
                "candidates": [
                    recommendations[candidate_id].model_dump(mode="json")
                    for candidate_id in action.candidate_ids
                ],
            }
        elif action.action_kind is ActionCapability.SAVE_SHORTLIST:
            result = {
                "decision_id": decision.decision_id,
                "candidate_ids": list(action.candidate_ids),
                "saved": True,
            }
        else:
            result = {
                "decision_id": decision.decision_id,
                "decision_status": decision.status.value,
                "status": decision.status.value,
                "evidence_coverage": decision.evidence_coverage,
                "confidence": decision.confidence,
            }

        now = utc_now_iso()
        execution = ActionExecution(
            execution_id=str(uuid.uuid4()),
            account_id=normalized_account_id,
            action_id=action.action_id,
            decision_id=decision.decision_id,
            creator_id=decision.creator_id,
            audience_id=decision.audience_id,
            action_kind=action.action_kind,
            model_revision=decision.model_revision,
            executor_version=self.EXECUTOR_VERSION,
            status=ActionExecutionStatus.SUCCEEDED,
            result=result,
            created_at=now,
            updated_at=now,
        )
        return await self._repository.create_action_execution(execution)

    async def get_action_execution(self, account_id: str, action_id: str) -> ActionExecution | None:
        """Read one immutable receipt within the account scope."""
        return await self._repository.get_action_execution(account_id.strip(), action_id.strip())

    async def record_feedback(
        self, account_id: str, decision_id: str, feedback: FeedbackInput
    ) -> FeedbackResult:
        decision = await self._repository.get_decision(account_id, decision_id)
        if decision is None:
            raise DecisionRecordMissingError(decision_id)
        if feedback.audience_id != decision.audience_id:
            raise FeedbackAudienceMismatchError(decision.audience_id, feedback.audience_id)

        now = utc_now_iso()
        stored = UserFeedback(
            **feedback.model_dump(exclude={"feedback_id"}),
            feedback_id=feedback.feedback_id or str(uuid.uuid4()),
            created_at=now,
        )
        updated, relationship, created = await self._repository.apply_feedback(
            account_id, decision_id, stored
        )
        # The repository returns the existing entry on an idempotent retry.
        # Derive the status from that persisted entry, rather than from the
        # retry payload, so the same feedback ID always has the same result.
        persisted = next(
            item for item in updated.feedback if item.feedback_id == stored.feedback_id
        )
        learning_status = (
            LearningStatus.PENDING_CREATOR_REVIEW
            if persisted.correction.strip() or persisted.outcome is FeedbackOutcome.DISSATISFIED
            else LearningStatus.OBSERVED
        )
        learning_signal = await self._repository.get_learning_signal_by_feedback(
            account_id, stored.feedback_id
        )
        if learning_signal is not None:
            learning_status = LearningStatus.PENDING_CREATOR_REVIEW
        return FeedbackResult(
            decision=updated,
            relationship=relationship,
            learning_status=learning_status,
            created=created,
            learning_signal=learning_signal,
        )

    async def list_learning_signals(
        self, account_id: str, status: LearningSignalStatus | None = None
    ) -> list[LearningSignal]:
        """List account-scoped feedback signals, optionally by lifecycle status."""
        return await self._repository.list_learning_signals(account_id.strip(), status)

    async def review_learning_signal(
        self,
        account_id: str,
        signal_id: str,
        review: LearningSignalReview,
    ) -> LearningSignalReviewResult:
        """Apply an explicit creator disposition to a pending signal."""
        signal, model = await self._repository.review_learning_signal(
            account_id.strip(), signal_id.strip(), review
        )
        return LearningSignalReviewResult(signal=signal, model=model)

    async def list_evidence(
        self,
        account_id: str,
        source_kind: EvidenceSource | None = None,
        reference_type: EvidenceReferenceType | None = None,
    ) -> list[EvidenceGraphEntry]:
        """List the account-scoped read-only Evidence Graph projection."""
        return await self._repository.list_evidence(account_id.strip(), source_kind, reference_type)

    async def get_evidence(self, account_id: str, evidence_id: str) -> EvidenceGraphEntry | None:
        """Look up one Evidence Graph node within the account scope."""
        return await self._repository.get_evidence(account_id.strip(), evidence_id.strip())

    async def get_decision(self, account_id: str, decision_id: str) -> DecisionRecord:
        decision = await self._repository.get_decision(account_id, decision_id)
        if decision is None:
            raise DecisionRecordMissingError(decision_id)
        return decision

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
    ) -> DecisionDatasetPage:
        """Return the immutable, account-scoped Decision Dataset projection."""
        return await self._repository.list_decision_dataset(
            account_id.strip(),
            audience_id=audience_id.strip() if audience_id is not None else None,
            status=status,
            feedback_outcome=feedback_outcome,
            has_feedback=has_feedback,
            cursor=cursor,
            limit=limit,
        )

    async def get_relationship(self, account_id: str, audience_id: str) -> RelationshipMemory:
        relationship = await self._repository.get_relationship(account_id, audience_id)
        return relationship or RelationshipMemory(account_id=account_id, audience_id=audience_id)

    @staticmethod
    def _confidence(
        ranked: list[_CandidateEvaluation],
        evidence: list[Evidence],
        coverage: float,
        status: DecisionStatus,
    ) -> float:
        if status is not DecisionStatus.RECOMMENDED or not evidence:
            return 0.0
        mean_evidence = sum(item.confidence for item in evidence) / len(evidence)
        margin = min(1.0, max(0.0, ranked[0].score - ranked[1].score)) if len(ranked) > 1 else 0.5
        return round(max(0.0, min(1.0, mean_evidence * coverage * (0.75 + margin * 0.25))), 6)


__all__ = ["CreatorAdvisor"]
