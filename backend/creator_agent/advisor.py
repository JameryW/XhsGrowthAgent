"""Deterministic Creator Agent decisions and feedback learning signals."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.creator_agent.execution import (
    PublishDispatcher,
    PublishOutcome,
    PublishRequest,
    artifact_store_content_reader,
    content_hash_of,
    gateway_publish_dispatcher,
    load_publish_content,
)
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
    EvidenceProposalPage,
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
    ModelRevision,
    ModelRevisionPage,
    Preference,
    PreferenceStance,
    RankedCandidate,
    RelationshipMemory,
    UserFeedback,
    utc_now_iso,
)
from backend.creator_agent.observations import CreatorContentObservationSource
from backend.creator_agent.policy import (
    build_action_policy_snapshot,
    evaluate_action_policy,
)
from backend.creator_agent.proposals import build_evidence_proposals
from backend.creator_agent.repository import (
    ActionExecutionNotAllowedError,
    ActionIntentMissingError,
    ActionPolicyDeniedError,
    ActionPublishContentUnavailableError,
    ActionValidationError,
    CreatorAgentRepository,
    CreatorModelMissingError,
    DecisionRecordMissingError,
    FeedbackAudienceMismatchError,
    ModelRevisionMissingError,
)

logger = logging.getLogger(__name__)


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


def _publish_receipt_result(outcome: PublishOutcome) -> dict[str, object]:
    """The receipt payload for one publish attempt.

    ``status`` is the platform layer's own vocabulary, kept verbatim: an
    ``unknown`` outcome (a submit went out, the answer was lost) is the one
    value an operator must not read as "nothing happened", so flattening it
    into the receipt's ``error`` text alone would lose the only field a script
    can branch on.  Empty fields are omitted rather than sent as ``""`` for the
    same reason S1 omits unset publish keys: "absent" and "empty" are not the
    same claim.
    """
    result: dict[str, object] = {"status": outcome.status.value}
    if outcome.note_id:
        result["note_id"] = outcome.note_id
    if outcome.note_url:
        result["note_url"] = outcome.note_url
    if outcome.error:
        result["error"] = outcome.error
    if outcome.retry_after_seconds is not None:
        result["retry_after_seconds"] = outcome.retry_after_seconds
    return result


# Evidence Proposal scan policy: a per-family candidate budget, deliberately
# decoupled from the page size. `limit * 4` keeps the window generous for wide
# pages while the floor protects small pages, which are exactly the case where a
# storage-ordered window would otherwise hide the strongest observation. The
# Creative Memory enumeration clamps each family to 100 rows, so a bigger request
# is reported as saturated rather than silently honored.
_PROPOSAL_MIN_WINDOW = 60
_PROPOSAL_WINDOW_FACTOR = 4


class CreatorAdvisor:
    """Use one exact Creator Model revision to decide, then retain outcomes."""

    EXECUTOR_VERSION = "local-v1"

    def __init__(
        self,
        repository: CreatorAgentRepository,
        *,
        content_observations: CreatorContentObservationSource | None = None,
        artifact_store: Any | None = None,
        publish: PublishDispatcher | None = None,
    ):
        self._repository = repository
        self._content_observations = content_observations
        # Both publish seams are bound once, here.  A composition root that
        # supplies neither gets the real Artifact Store reader and the real
        # shared Gateway, which is what lets a test exercise this very code path
        # instead of a paraphrase of it.
        #
        # ``artifact_store=None`` makes the reader answer "no such artifact"
        # rather than read somewhere else, so a root that forgets to hand over
        # the store gets a loud 409 instead of publishing a body built from
        # nothing.
        self._read_publish_content = artifact_store_content_reader(artifact_store)
        self._publish: PublishDispatcher = (
            publish if publish is not None else gateway_publish_dispatcher()
        )

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
        elif request.action_kind is ActionCapability.PUBLISH:
            # A publish intent targets an artifact, not a ranked candidate, so the
            # candidate rules below do not apply.  Shape is already enforced by
            # ``_validate_publish_payload``; the decision link stays required as
            # the account-scoped anchor.  Policy gating (cooldown / risk /
            # compliance) lands in P2a-S2.
            pass
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

        # P2a-S2 policy gate.  Placement is the whole point: after shape
        # validation (so the engine never re-derives an intent's shape) and
        # before ``create_action`` (so a denial leaves no intent behind for a
        # human to confirm).  Reached on every capability; the engine itself
        # decides which ones it has an opinion about.
        verdict = evaluate_action_policy(build_action_policy_snapshot(request))
        if not verdict.allowed:
            # The denial stays observable without persisting an intent: the
            # caller gets a 403 carrying ``policy_id`` + ``retry_after_seconds``,
            # and this line puts it in the log.  A denied intent would be a
            # record nobody can ever confirm, which is why none is written.
            logger.warning(
                "creator action policy denied: policy_id=%s account_id=%s kind=%s reason=%s",
                verdict.policy_id.value,
                account_id,
                request.action_kind.value,
                verdict.reason,
            )
            raise ActionPolicyDeniedError(
                account_id=account_id,
                policy_id=verdict.policy_id,
                reason=verdict.reason,
                retry_after_seconds=verdict.retry_after_seconds,
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
            artifact_ref=request.artifact_ref,
            content_hash=request.content_hash,
            thread_id=request.thread_id,
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

        # The publish is attempted only once the Decision Record is known to
        # exist: a side effect must never sit on a path that is about to fail.
        publish_outcome: PublishOutcome | None = None
        if action.action_kind is ActionCapability.PUBLISH:
            publish_outcome = await self._execute_publish(action)

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
        elif action.action_kind is ActionCapability.PUBLISH:
            # Set on exactly the publish path above, and on no other.
            assert publish_outcome is not None
            result = _publish_receipt_result(publish_outcome)
        else:
            result = {
                "decision_id": decision.decision_id,
                "decision_status": decision.status.value,
                "status": decision.status.value,
                "evidence_coverage": decision.evidence_coverage,
                "confidence": decision.confidence,
            }

        now = utc_now_iso()
        # Only a *published* outcome is a success.  An ``unknown`` publish
        # deliberately shares ``FAILED`` rather than getting a third status:
        # the receipt's ``result["status"]`` keeps the distinction machine
        # readable, and no consumer of ``ActionExecutionStatus`` tells the two
        # apart today -- inventing a value would change a durable contract for
        # nobody.  A publish that *failed to be attempted* never reaches here at
        # all; it raises before the Gateway (see ``_execute_publish``).
        receipt_status = (
            ActionExecutionStatus.SUCCEEDED
            if publish_outcome is None or publish_outcome.succeeded
            else ActionExecutionStatus.FAILED
        )
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
            status=receipt_status,
            result=result,
            created_at=now,
            updated_at=now,
        )
        return await self._repository.create_action_execution(execution)

    async def _execute_publish(self, action: ActionIntent) -> PublishOutcome:
        """Resolve one confirmed publish intent, then hand it over exactly once.

        Everything is derived from the immutable intent plus the artifact it
        points at, so the same intent always builds the same payload.  Every
        refusal happens *before* the Gateway is reached: a half-resolved publish
        must not turn into a side effect.
        """
        action_id = action.action_id
        thread_id = (action.thread_id or "").strip()
        if not thread_id:
            raise ActionPublishContentUnavailableError(
                action_id,
                "intent has no thread_id, so its artifact_ref cannot be resolved",
            )
        artifact_ref = (action.artifact_ref or "").strip()
        body = await self._read_publish_content(thread_id=thread_id, artifact_ref=artifact_ref)
        content = load_publish_content(body)
        if content is None:
            raise ActionPublishContentUnavailableError(
                action_id, f"artifact {artifact_ref!r} has no publishable body"
            )
        # The hash is what a human confirmed.  Publishing a body that does not
        # match it would post something nobody approved, so the mismatch is a
        # refusal rather than a warning.
        expected_hash = (action.content_hash or "").strip()
        if content_hash_of(body) != expected_hash:
            raise ActionPublishContentUnavailableError(
                action_id, "artifact body does not match the confirmed content_hash"
            )
        return await self._publish(
            PublishRequest(
                account_id=action.account_id,
                thread_id=thread_id,
                idempotency_key=action.idempotency_key,
                artifact_ref=artifact_ref,
                content_hash=expected_hash,
                content=content,
            )
        )

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

    async def list_evidence_proposals(
        self,
        account_id: str,
        *,
        min_confidence: float | None = None,
        limit: int = 50,
    ) -> EvidenceProposalPage:
        """Project Creative Memory observations into a page of Evidence Proposals.

        Strictly read-only.  Nothing on this path can change a Creator Model:
        adoption remains an explicit, creator-approved revision.

        The scan budget is deliberately wider than the page.  Each Creative Memory
        family is windowed by its own storage order — materials by soft-demotion
        weight, styles and plays by raw measured rate — while proposals rank by
        sample-shrunk confidence.  Reusing ``limit`` as the window would therefore
        let a small page drop the strongest available evidence and still come back
        looking correctly ranked.
        """
        normalized_account_id = account_id.strip()
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if min_confidence is not None and not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        if self._content_observations is None or not normalized_account_id:
            return EvidenceProposalPage(limit=limit)

        scan = await self._content_observations.observations(
            normalized_account_id,
            window=max(_PROPOSAL_MIN_WINDOW, limit * _PROPOSAL_WINDOW_FACTOR),
        )
        cited = {
            entry.evidence.source_ref
            for entry in await self._repository.list_evidence(normalized_account_id)
        }
        return build_evidence_proposals(
            scan.observations,
            cited_source_refs=cited,
            min_confidence=min_confidence,
            limit=limit,
            scan_saturated=scan.saturated,
        )

    async def get_decision(self, account_id: str, decision_id: str) -> DecisionRecord:
        decision = await self._repository.get_decision(account_id, decision_id)
        if decision is None:
            raise DecisionRecordMissingError(decision_id)
        return decision

    async def list_model_revisions(
        self,
        account_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ModelRevisionPage:
        """Read the account-scoped, append-only Model Revision History."""
        return await self._repository.list_model_revisions(
            account_id.strip(), cursor=cursor, limit=limit
        )

    async def get_model_revision(self, account_id: str, revision: int) -> ModelRevision:
        """Resolve one immutable revision snapshot, independent of the current model."""
        normalized_account_id = account_id.strip()
        snapshot = await self._repository.get_model_revision(normalized_account_id, revision)
        if snapshot is None:
            raise ModelRevisionMissingError(normalized_account_id, revision)
        return snapshot

    async def get_decision_model_revision(self, account_id: str, decision_id: str) -> ModelRevision:
        """Return the exact Creator Model revision a Decision Record was judged against.

        Only the revision the decision already cites is resolved.  A missing
        snapshot is a typed error: this method never falls back to the current
        model and never re-evaluates the decision.
        """
        normalized_account_id = account_id.strip()
        decision = await self.get_decision(normalized_account_id, decision_id.strip())
        return await self.get_model_revision(normalized_account_id, decision.model_revision)

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
