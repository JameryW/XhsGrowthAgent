"""Creator Agent persistence with Postgres and process-memory adapters."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from backend.creator_agent.models import (
    ActionIntent,
    ActionResolution,
    ActionStatus,
    CreatorModel,
    CreatorModelDefinition,
    CreatorReviewDisposition,
    DecisionRecord,
    Evidence,
    EvidenceGraphEntry,
    EvidenceReference,
    EvidenceReferenceType,
    EvidenceSource,
    FeedbackOutcome,
    LearningSignal,
    LearningSignalReview,
    LearningSignalStatus,
    RelationshipMemory,
    UserFeedback,
    utc_now_iso,
)
from backend.creator_agent.repository import (
    ActionIntentMissingError,
    ActionResolutionConflictError,
    CreatorModelRevisionConflictError,
    CreatorReviewModelRequiredError,
    LearningSignalMissingError,
    LearningSignalReviewConflictError,
)
from backend.db.pool import get_pool, is_pool_ready

_mem_models: dict[str, CreatorModel] = {}
_mem_decisions: dict[tuple[str, str], DecisionRecord] = {}
_mem_relationships: dict[tuple[str, str], RelationshipMemory] = {}
_mem_learning_signals: dict[tuple[str, str], LearningSignal] = {}
_mem_feedback_signals: dict[tuple[str, str], str] = {}
_mem_actions: dict[tuple[str, str], ActionIntent] = {}
_mem_action_idempotency: dict[tuple[str, str], str] = {}
_mem_lock = asyncio.Lock()

_CREATE_MODELS_SQL = """
CREATE TABLE IF NOT EXISTS creator_agent_models (
    -- Creator ID is the durable identity; account_id is only its current
    -- operational binding.  Keep the account unique for the current API,
    -- while making the independent identity the row key.
    creator_id   TEXT PRIMARY KEY,
    account_id   TEXT NOT NULL UNIQUE,
    revision     INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""

_CREATE_DECISIONS_SQL = """
CREATE TABLE IF NOT EXISTS creator_agent_decisions (
    account_id   TEXT NOT NULL,
    decision_id  TEXT NOT NULL,
    audience_id  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (account_id, decision_id)
);
"""

_CREATE_RELATIONSHIPS_SQL = """
CREATE TABLE IF NOT EXISTS creator_agent_relationships (
    account_id   TEXT NOT NULL,
    audience_id  TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (account_id, audience_id)
);
"""

_CREATE_LEARNING_SIGNALS_SQL = """
CREATE TABLE IF NOT EXISTS creator_agent_learning_signals (
    account_id   TEXT NOT NULL,
    signal_id    TEXT NOT NULL,
    feedback_id  TEXT NOT NULL,
    status       TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (account_id, signal_id),
    UNIQUE (account_id, feedback_id)
);
"""

_CREATE_ACTIONS_SQL = """
CREATE TABLE IF NOT EXISTS creator_agent_actions (
    account_id       TEXT NOT NULL,
    action_id        TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL,
    status           TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (account_id, action_id),
    UNIQUE (account_id, idempotency_key)
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_creator_agent_decisions_audience
    ON creator_agent_decisions (account_id, audience_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_creator_agent_relationships_updated
    ON creator_agent_relationships (account_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_creator_agent_learning_signals_status
    ON creator_agent_learning_signals (account_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_creator_agent_actions_status
    ON creator_agent_actions (account_id, status, created_at DESC, action_id DESC);
"""


def _reset_memory_store() -> None:
    """Clear the process-memory adapter for isolated tests."""
    _mem_models.clear()
    _mem_decisions.clear()
    _mem_relationships.clear()
    _mem_learning_signals.clear()
    _mem_feedback_signals.clear()
    _mem_actions.clear()
    _mem_action_idempotency.clear()


async def ensure_tables() -> None:
    if not is_pool_ready():
        return
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_MODELS_SQL)
        await conn.execute(_CREATE_DECISIONS_SQL)
        await conn.execute(_CREATE_RELATIONSHIPS_SQL)
        await conn.execute(_CREATE_LEARNING_SIGNALS_SQL)
        await conn.execute(_CREATE_ACTIONS_SQL)
        await conn.execute(_CREATE_INDEX_SQL)


def _dumps(
    model: CreatorModel | DecisionRecord | RelationshipMemory | LearningSignal | ActionIntent,
) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, dict) else row[index]


def _json_text(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _model_from_row(row: Any) -> CreatorModel:
    return CreatorModel.model_validate_json(_json_text(_row_value(row, "payload_json", 0)))


def _decision_from_row(row: Any) -> DecisionRecord:
    return DecisionRecord.model_validate_json(_json_text(_row_value(row, "payload_json", 0)))


def _relationship_from_row(row: Any) -> RelationshipMemory:
    return RelationshipMemory.model_validate_json(_json_text(_row_value(row, "payload_json", 0)))


def _learning_signal_from_row(row: Any) -> LearningSignal:
    return LearningSignal.model_validate_json(_json_text(_row_value(row, "payload_json", 0)))


def _action_from_row(row: Any) -> ActionIntent:
    return ActionIntent.model_validate_json(_json_text(_row_value(row, "payload_json", 0)))


def _updated_relationship(
    relationship: RelationshipMemory,
    feedback: UserFeedback,
    *,
    increment_interaction: bool = False,
) -> RelationshipMemory:
    updated = relationship.model_copy(deep=True)
    if increment_interaction:
        updated.interaction_count += 1
    candidate_id = feedback.selected_candidate_id
    positive = {
        FeedbackOutcome.ACCEPTED,
        FeedbackOutcome.PURCHASED,
        FeedbackOutcome.SATISFIED,
    }
    negative = {FeedbackOutcome.REJECTED, FeedbackOutcome.DISSATISFIED}
    if (
        candidate_id
        and feedback.outcome in positive
        and candidate_id not in updated.accepted_candidate_ids
    ):
        updated.accepted_candidate_ids.append(candidate_id)
    if (
        candidate_id
        and feedback.outcome in negative
        and candidate_id not in updated.rejected_candidate_ids
    ):
        updated.rejected_candidate_ids.append(candidate_id)
    if feedback.correction:
        updated.latest_correction = feedback.correction
    updated.last_interaction_at = feedback.created_at
    return updated


def _feedback_creates_signal(feedback: UserFeedback) -> bool:
    return bool(feedback.correction.strip()) or feedback.outcome is FeedbackOutcome.DISSATISFIED


def _new_learning_signal(decision: DecisionRecord, feedback: UserFeedback) -> LearningSignal:
    correction = feedback.correction.strip()
    summary = correction or f"Audience feedback outcome: {feedback.outcome.value}"
    now = feedback.created_at or utc_now_iso()
    return LearningSignal(
        signal_id=str(uuid.uuid4()),
        account_id=decision.account_id,
        creator_id=decision.creator_id,
        audience_id=decision.audience_id,
        decision_id=decision.decision_id,
        feedback_id=feedback.feedback_id,
        summary=summary,
        correction=correction,
        evidence_ids=[item.evidence_id for item in decision.evidence],
        status=LearningSignalStatus.PENDING_CREATOR_REVIEW,
        created_at=now,
        updated_at=now,
    )


def _build_evidence_graph(
    model: CreatorModel | None,
    decisions: list[DecisionRecord],
    signals: list[LearningSignal],
    *,
    source_kind: EvidenceSource | None = None,
    reference_type: EvidenceReferenceType | None = None,
) -> list[EvidenceGraphEntry]:
    """Build the deterministic read projection shared by both storage paths."""

    evidence_by_id: dict[str, Evidence] = {}
    references_by_evidence: dict[
        str, dict[tuple[EvidenceReferenceType, str, int | None], EvidenceReference]
    ] = {}

    def add_evidence(item: Evidence) -> None:
        # Evidence IDs are logical identities. Keep the first durable snapshot
        # encountered so a later model revision cannot rewrite a decision's
        # historical payload under the same ID.
        evidence_by_id.setdefault(item.evidence_id, item.model_copy(deep=True))
        references_by_evidence.setdefault(item.evidence_id, {})

    def add_reference(
        evidence_id: str,
        kind: EvidenceReferenceType,
        target_id: str,
        revision: int | None,
    ) -> None:
        if evidence_id not in evidence_by_id:
            return
        reference = EvidenceReference(
            reference_type=kind,
            target_id=target_id,
            model_revision=revision,
        )
        key = (kind, target_id, revision)
        references_by_evidence.setdefault(evidence_id, {})[key] = reference

    decisions_by_id = {decision.decision_id: decision for decision in decisions}
    # Seed immutable decision snapshots first. This preserves historical
    # provenance if a later model revision happens to reuse an evidence ID.
    for decision in sorted(decisions, key=lambda item: item.decision_id):
        for item in decision.evidence:
            add_evidence(item)

    for signal in sorted(signals, key=lambda item: item.signal_id):
        matched_decision = decisions_by_id.get(signal.decision_id)
        if matched_decision is None:
            continue
        decision_evidence = {
            evidence.evidence_id: evidence for evidence in matched_decision.evidence
        }
        for evidence_id in signal.evidence_ids:
            signal_evidence = decision_evidence.get(evidence_id)
            if signal_evidence is None:
                continue
            add_evidence(signal_evidence)
            add_reference(
                evidence_id,
                EvidenceReferenceType.LEARNING_SIGNAL,
                signal.signal_id,
                matched_decision.model_revision,
            )

    if model is not None:
        for item in model.evidence:
            add_evidence(item)
            add_reference(
                item.evidence_id,
                EvidenceReferenceType.MODEL,
                model.creator_id,
                model.revision,
            )
        for preference in model.preferences:
            for evidence_id in preference.evidence_ids:
                add_reference(
                    evidence_id,
                    EvidenceReferenceType.PREFERENCE,
                    preference.preference_id,
                    model.revision,
                )
        for claim in model.knowledge:
            for evidence_id in claim.evidence_ids:
                add_reference(
                    evidence_id,
                    EvidenceReferenceType.KNOWLEDGE_CLAIM,
                    claim.claim_id,
                    model.revision,
                )
        for policy in model.policies:
            for evidence_id in policy.evidence_ids:
                add_reference(
                    evidence_id,
                    EvidenceReferenceType.DECISION_POLICY,
                    policy.policy_id,
                    model.revision,
                )

    for decision in sorted(decisions, key=lambda item: item.decision_id):
        for item in decision.evidence:
            add_reference(
                item.evidence_id,
                EvidenceReferenceType.DECISION,
                decision.decision_id,
                decision.model_revision,
            )
        for candidate in decision.recommendations:
            candidate_ref = f"{decision.decision_id}:{candidate.candidate_id}"
            for evidence_id in candidate.evidence_ids:
                add_reference(
                    evidence_id,
                    EvidenceReferenceType.CANDIDATE,
                    candidate_ref,
                    decision.model_revision,
                )

    entries: list[EvidenceGraphEntry] = []
    for evidence_id in sorted(evidence_by_id):
        evidence = evidence_by_id[evidence_id]
        references = sorted(
            references_by_evidence.get(evidence_id, {}).values(),
            key=lambda item: (
                item.reference_type.value,
                item.target_id,
                item.model_revision if item.model_revision is not None else 0,
            ),
        )
        if source_kind is not None and evidence.source_kind != source_kind:
            continue
        if reference_type is not None and not any(
            item.reference_type == reference_type for item in references
        ):
            continue
        entries.append(EvidenceGraphEntry(evidence=evidence, references=references))
    return entries


class DurableCreatorAgentRepository:
    """One adapter that uses Postgres when ready and memory for local/test runs."""

    async def get_model(self, account_id: str) -> CreatorModel | None:
        if not is_pool_ready():
            model = _mem_models.get(account_id)
            return model.model_copy(deep=True) if model else None
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT payload_json FROM creator_agent_models WHERE account_id = %s",
                (account_id,),
            )
            row = await cur.fetchone()
        return _model_from_row(row) if row else None

    async def save_model(
        self,
        account_id: str,
        definition: CreatorModelDefinition,
        *,
        expected_revision: int,
    ) -> CreatorModel:
        if not is_pool_ready():
            async with _mem_lock:
                current = _mem_models.get(account_id)
                actual_revision = current.revision if current else 0
                if actual_revision != expected_revision:
                    raise CreatorModelRevisionConflictError(expected_revision, actual_revision)
                model = self._next_model(account_id, definition, current)
                _mem_models[account_id] = model.model_copy(deep=True)
                return model

        pool = get_pool()
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            # SELECT ... FOR UPDATE cannot lock a missing row.  Serialize
            # writes by account so two concurrent expected_revision=0 creates
            # cannot both pass the check and overwrite one another.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (account_id,),
            )
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_models
                WHERE account_id = %s FOR UPDATE
                """,
                (account_id,),
            )
            row = await cur.fetchone()
            current = _model_from_row(row) if row else None
            actual_revision = current.revision if current else 0
            if actual_revision != expected_revision:
                raise CreatorModelRevisionConflictError(expected_revision, actual_revision)
            model = self._next_model(account_id, definition, current)
            await cur.execute(
                """
                INSERT INTO creator_agent_models (
                    account_id, creator_id, revision, payload_json, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (account_id) DO UPDATE SET
                    creator_id = EXCLUDED.creator_id,
                    revision = EXCLUDED.revision,
                    payload_json = EXCLUDED.payload_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    account_id,
                    model.creator_id,
                    model.revision,
                    _dumps(model),
                    model.created_at,
                    model.updated_at,
                ),
            )
        return model

    @staticmethod
    def _next_model(
        account_id: str,
        definition: CreatorModelDefinition,
        current: CreatorModel | None,
    ) -> CreatorModel:
        now = utc_now_iso()
        return CreatorModel(
            **definition.model_dump(),
            account_id=account_id,
            creator_id=current.creator_id if current else f"creator_{uuid.uuid4()}",
            revision=(current.revision + 1) if current else 1,
            created_at=current.created_at if current else now,
            updated_at=now,
        )

    async def create_decision(self, decision: DecisionRecord) -> None:
        if not is_pool_ready():
            async with _mem_lock:
                _mem_decisions[(decision.account_id, decision.decision_id)] = decision.model_copy(
                    deep=True
                )
                key = (decision.account_id, decision.audience_id)
                relationship = _mem_relationships.get(key) or RelationshipMemory(
                    account_id=decision.account_id,
                    audience_id=decision.audience_id,
                )
                relationship = relationship.model_copy(deep=True)
                relationship.interaction_count += 1
                relationship.last_interaction_at = decision.created_at
                _mem_relationships[key] = relationship
            return

        pool = get_pool()
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO creator_agent_decisions (
                    account_id, decision_id, audience_id, payload_json, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    decision.account_id,
                    decision.decision_id,
                    decision.audience_id,
                    _dumps(decision),
                    decision.created_at,
                    decision.updated_at,
                ),
            )
            relationship = await self._get_relationship_on_cursor(
                cur, decision.account_id, decision.audience_id, lock=True
            ) or RelationshipMemory(
                account_id=decision.account_id,
                audience_id=decision.audience_id,
            )
            relationship.interaction_count += 1
            relationship.last_interaction_at = decision.created_at
            await self._upsert_relationship_on_cursor(cur, relationship)

    async def get_decision(self, account_id: str, decision_id: str) -> DecisionRecord | None:
        if not is_pool_ready():
            decision = _mem_decisions.get((account_id, decision_id))
            return decision.model_copy(deep=True) if decision else None
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_decisions
                WHERE account_id = %s AND decision_id = %s
                """,
                (account_id, decision_id),
            )
            row = await cur.fetchone()
        return _decision_from_row(row) if row else None

    async def get_action_by_idempotency_key(
        self, account_id: str, idempotency_key: str
    ) -> ActionIntent | None:
        if not is_pool_ready():
            action_id = _mem_action_idempotency.get((account_id, idempotency_key))
            if action_id is None:
                return None
            action = _mem_actions.get((account_id, action_id))
            return action.model_copy(deep=True) if action else None
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_actions
                WHERE account_id = %s AND idempotency_key = %s
                """,
                (account_id, idempotency_key),
            )
            row = await cur.fetchone()
        return _action_from_row(row) if row else None

    async def create_action(self, action: ActionIntent) -> ActionIntent:
        """Persist an intent, returning the original row for idempotent retries."""
        if not is_pool_ready():
            async with _mem_lock:
                key = (action.account_id, action.idempotency_key)
                existing_id = _mem_action_idempotency.get(key)
                if existing_id is not None:
                    existing = _mem_actions[(action.account_id, existing_id)]
                    return existing.model_copy(deep=True)
                stored = action.model_copy(deep=True)
                _mem_actions[(action.account_id, action.action_id)] = stored
                _mem_action_idempotency[key] = action.action_id
                return stored.model_copy(deep=True)

        pool = get_pool()
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO creator_agent_actions (
                    account_id, action_id, idempotency_key, status, payload_json,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (account_id, idempotency_key) DO NOTHING
                """,
                (
                    action.account_id,
                    action.action_id,
                    action.idempotency_key,
                    action.status.value,
                    _dumps(action),
                    action.created_at,
                    action.updated_at,
                ),
            )
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_actions
                WHERE account_id = %s AND idempotency_key = %s
                """,
                (action.account_id, action.idempotency_key),
            )
            row = await cur.fetchone()
            if row is None:
                raise RuntimeError("action intent insert did not return a durable row")
        return _action_from_row(row)

    async def get_action(self, account_id: str, action_id: str) -> ActionIntent | None:
        if not is_pool_ready():
            action = _mem_actions.get((account_id, action_id))
            return action.model_copy(deep=True) if action else None
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_actions
                WHERE account_id = %s AND action_id = %s
                """,
                (account_id, action_id),
            )
            row = await cur.fetchone()
        return _action_from_row(row) if row else None

    async def list_actions(
        self, account_id: str, status: ActionStatus | None = None
    ) -> list[ActionIntent]:
        if not is_pool_ready():
            actions = [
                action
                for (stored_account, _), action in _mem_actions.items()
                if stored_account == account_id and (status is None or action.status is status)
            ]
            actions.sort(key=lambda item: (item.created_at, item.action_id), reverse=True)
            return [action.model_copy(deep=True) for action in actions]

        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            if status is None:
                await cur.execute(
                    """
                    SELECT payload_json FROM creator_agent_actions
                    WHERE account_id = %s
                    ORDER BY created_at DESC, action_id DESC
                    """,
                    (account_id,),
                )
            else:
                await cur.execute(
                    """
                    SELECT payload_json FROM creator_agent_actions
                    WHERE account_id = %s AND status = %s
                    ORDER BY created_at DESC, action_id DESC
                    """,
                    (account_id, status.value),
                )
            rows = await cur.fetchall()
        return [_action_from_row(row) for row in rows]

    async def resolve_action(
        self, account_id: str, action_id: str, resolution: ActionResolution
    ) -> ActionIntent:
        if not is_pool_ready():
            async with _mem_lock:
                action = _mem_actions.get((account_id, action_id))
                if action is None:
                    raise ActionIntentMissingError(action_id)
                action = action.model_copy(deep=True)
                if action.status is not ActionStatus.PENDING_CONFIRMATION:
                    if action.status.value != resolution.disposition.value:
                        raise ActionResolutionConflictError(
                            action_id, action.status, resolution.disposition
                        )
                    return action
                action.status = ActionStatus(resolution.disposition.value)
                action.resolved_at = utc_now_iso()
                action.updated_at = action.resolved_at
                _mem_actions[(account_id, action_id)] = action.model_copy(deep=True)
                return action

        pool = get_pool()
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_actions
                WHERE account_id = %s AND action_id = %s FOR UPDATE
                """,
                (account_id, action_id),
            )
            row = await cur.fetchone()
            if row is None:
                raise ActionIntentMissingError(action_id)
            action = _action_from_row(row)
            if action.status is not ActionStatus.PENDING_CONFIRMATION:
                if action.status.value != resolution.disposition.value:
                    raise ActionResolutionConflictError(
                        action_id, action.status, resolution.disposition
                    )
                return action
            action.status = ActionStatus(resolution.disposition.value)
            action.resolved_at = utc_now_iso()
            action.updated_at = action.resolved_at
            await cur.execute(
                """
                UPDATE creator_agent_actions
                SET status = %s, payload_json = %s, updated_at = %s
                WHERE account_id = %s AND action_id = %s
                """,
                (
                    action.status.value,
                    _dumps(action),
                    action.updated_at,
                    account_id,
                    action_id,
                ),
            )
        return action

    async def apply_feedback(
        self,
        account_id: str,
        decision_id: str,
        feedback: UserFeedback,
    ) -> tuple[DecisionRecord, RelationshipMemory, bool]:
        if not is_pool_ready():
            async with _mem_lock:
                key = (account_id, decision_id)
                current = _mem_decisions.get(key)
                if current is None:
                    raise KeyError(decision_id)
                decision = current.model_copy(deep=True)
                relationship_key = (account_id, decision.audience_id)
                relationship = _mem_relationships.get(relationship_key) or RelationshipMemory(
                    account_id=account_id,
                    audience_id=decision.audience_id,
                )
                existing_feedback = next(
                    (
                        item
                        for item in decision.feedback
                        if item.feedback_id == feedback.feedback_id
                    ),
                    None,
                )
                if existing_feedback is not None:
                    if (
                        _feedback_creates_signal(existing_feedback)
                        and (
                            account_id,
                            feedback.feedback_id,
                        )
                        not in _mem_feedback_signals
                    ):
                        signal = _new_learning_signal(decision, existing_feedback)
                        _mem_learning_signals[(account_id, signal.signal_id)] = signal.model_copy(
                            deep=True
                        )
                        _mem_feedback_signals[(account_id, feedback.feedback_id)] = signal.signal_id
                    return decision, relationship.model_copy(deep=True), False
                decision.feedback.append(feedback)
                decision.updated_at = feedback.created_at
                relationship = _updated_relationship(relationship, feedback)
                _mem_decisions[key] = decision.model_copy(deep=True)
                _mem_relationships[relationship_key] = relationship.model_copy(deep=True)
                if _feedback_creates_signal(feedback):
                    signal = _new_learning_signal(decision, feedback)
                    _mem_learning_signals[(account_id, signal.signal_id)] = signal.model_copy(
                        deep=True
                    )
                    _mem_feedback_signals[(account_id, feedback.feedback_id)] = signal.signal_id
                return decision, relationship, True

        pool = get_pool()
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_decisions
                WHERE account_id = %s AND decision_id = %s FOR UPDATE
                """,
                (account_id, decision_id),
            )
            row = await cur.fetchone()
            if row is None:
                raise KeyError(decision_id)
            decision = _decision_from_row(row)
            relationship = await self._get_relationship_on_cursor(
                cur, account_id, decision.audience_id, lock=True
            ) or RelationshipMemory(account_id=account_id, audience_id=decision.audience_id)
            existing_feedback = next(
                (item for item in decision.feedback if item.feedback_id == feedback.feedback_id),
                None,
            )
            if existing_feedback is not None:
                if _feedback_creates_signal(existing_feedback):
                    await self._ensure_learning_signal_on_cursor(cur, decision, existing_feedback)
                return decision, relationship, False

            decision.feedback.append(feedback)
            decision.updated_at = feedback.created_at
            relationship = _updated_relationship(relationship, feedback)
            await cur.execute(
                """
                UPDATE creator_agent_decisions
                SET payload_json = %s, updated_at = %s
                WHERE account_id = %s AND decision_id = %s
                """,
                (_dumps(decision), decision.updated_at, account_id, decision_id),
            )
            await self._upsert_relationship_on_cursor(cur, relationship)
            if _feedback_creates_signal(feedback):
                signal = _new_learning_signal(decision, feedback)
                await cur.execute(
                    """
                    INSERT INTO creator_agent_learning_signals (
                        account_id, signal_id, feedback_id, status, payload_json,
                        created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (account_id, feedback_id) DO NOTHING
                    """,
                    (
                        account_id,
                        signal.signal_id,
                        signal.feedback_id,
                        signal.status.value,
                        _dumps(signal),
                        signal.created_at,
                        signal.updated_at,
                    ),
                )
        return decision, relationship, True

    async def get_relationship(
        self, account_id: str, audience_id: str
    ) -> RelationshipMemory | None:
        if not is_pool_ready():
            relationship = _mem_relationships.get((account_id, audience_id))
            return relationship.model_copy(deep=True) if relationship else None
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            return await self._get_relationship_on_cursor(cur, account_id, audience_id)

    async def get_learning_signal(self, account_id: str, signal_id: str) -> LearningSignal | None:
        if not is_pool_ready():
            signal = _mem_learning_signals.get((account_id, signal_id))
            return signal.model_copy(deep=True) if signal else None
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_learning_signals
                WHERE account_id = %s AND signal_id = %s
                """,
                (account_id, signal_id),
            )
            row = await cur.fetchone()
        return _learning_signal_from_row(row) if row else None

    async def get_learning_signal_by_feedback(
        self, account_id: str, feedback_id: str
    ) -> LearningSignal | None:
        if not is_pool_ready():
            signal_id = _mem_feedback_signals.get((account_id, feedback_id))
            if signal_id is None:
                return None
            return await self.get_learning_signal(account_id, signal_id)
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_learning_signals
                WHERE account_id = %s AND feedback_id = %s
                """,
                (account_id, feedback_id),
            )
            row = await cur.fetchone()
        return _learning_signal_from_row(row) if row else None

    async def list_evidence(
        self,
        account_id: str,
        source_kind: EvidenceSource | None = None,
        reference_type: EvidenceReferenceType | None = None,
    ) -> list[EvidenceGraphEntry]:
        """Return an account-scoped, deterministic Evidence Graph projection."""
        if not is_pool_ready():
            async with _mem_lock:
                model = _mem_models.get(account_id)
                decisions = [
                    decision
                    for (stored_account, _), decision in _mem_decisions.items()
                    if stored_account == account_id
                ]
                signals = [
                    signal
                    for (stored_account, _), signal in _mem_learning_signals.items()
                    if stored_account == account_id
                ]
                model_snapshot = model.model_copy(deep=True) if model else None
                decision_snapshots = [item.model_copy(deep=True) for item in decisions]
                signal_snapshots = [item.model_copy(deep=True) for item in signals]
            return _build_evidence_graph(
                model_snapshot,
                decision_snapshots,
                signal_snapshots,
                source_kind=source_kind,
                reference_type=reference_type,
            )

        pool = get_pool()
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_models
                WHERE account_id = %s
                """,
                (account_id,),
            )
            model_row = await cur.fetchone()
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_decisions
                WHERE account_id = %s
                ORDER BY decision_id ASC
                """,
                (account_id,),
            )
            decision_rows = await cur.fetchall()
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_learning_signals
                WHERE account_id = %s
                ORDER BY signal_id ASC
                """,
                (account_id,),
            )
            signal_rows = await cur.fetchall()
        return _build_evidence_graph(
            _model_from_row(model_row) if model_row else None,
            [_decision_from_row(row) for row in decision_rows],
            [_learning_signal_from_row(row) for row in signal_rows],
            source_kind=source_kind,
            reference_type=reference_type,
        )

    async def get_evidence(self, account_id: str, evidence_id: str) -> EvidenceGraphEntry | None:
        """Return one graph node without crossing the account boundary."""
        entries = await self.list_evidence(account_id)
        return next((entry for entry in entries if entry.evidence.evidence_id == evidence_id), None)

    async def list_learning_signals(
        self, account_id: str, status: LearningSignalStatus | None = None
    ) -> list[LearningSignal]:
        if not is_pool_ready():
            signals = [
                signal
                for (stored_account, _), signal in _mem_learning_signals.items()
                if stored_account == account_id and (status is None or signal.status is status)
            ]
            signals.sort(key=lambda item: (item.created_at, item.signal_id), reverse=True)
            return [signal.model_copy(deep=True) for signal in signals]

        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            if status is None:
                await cur.execute(
                    """
                    SELECT payload_json FROM creator_agent_learning_signals
                    WHERE account_id = %s
                    ORDER BY created_at DESC, signal_id DESC
                    """,
                    (account_id,),
                )
            else:
                await cur.execute(
                    """
                    SELECT payload_json FROM creator_agent_learning_signals
                    WHERE account_id = %s AND status = %s
                    ORDER BY created_at DESC, signal_id DESC
                    """,
                    (account_id, status.value),
                )
            rows = await cur.fetchall()
        return [_learning_signal_from_row(row) for row in rows]

    async def review_learning_signal(
        self,
        account_id: str,
        signal_id: str,
        review: LearningSignalReview,
    ) -> tuple[LearningSignal, CreatorModel | None]:
        if not is_pool_ready():
            async with _mem_lock:
                signal = _mem_learning_signals.get((account_id, signal_id))
                if signal is None:
                    raise LearningSignalMissingError(signal_id)
                signal = signal.model_copy(deep=True)
                if signal.status is not LearningSignalStatus.PENDING_CREATOR_REVIEW:
                    if signal.status.value != review.disposition.value:
                        raise LearningSignalReviewConflictError(
                            signal_id, signal.status, review.disposition
                        )
                    model = _mem_models.get(account_id)
                    if (
                        model is not None
                        and signal.applied_model_revision is not None
                        and model.revision != signal.applied_model_revision
                    ):
                        model = None
                    return signal, model.model_copy(deep=True) if model else None
                if review.disposition is CreatorReviewDisposition.APPROVED:
                    if review.model is None or review.expected_revision is None:
                        raise CreatorReviewModelRequiredError()
                    current = _mem_models.get(account_id)
                    actual_revision = current.revision if current else 0
                    if actual_revision != review.expected_revision:
                        raise CreatorModelRevisionConflictError(
                            review.expected_revision, actual_revision
                        )
                    model = self._next_model(account_id, review.model, current)
                    _mem_models[account_id] = model.model_copy(deep=True)
                    signal.applied_model_revision = model.revision
                else:
                    model = None
                now = utc_now_iso()
                signal.status = LearningSignalStatus(review.disposition.value)
                signal.review_note = review.review_note
                signal.reviewed_at = now
                signal.updated_at = now
                _mem_learning_signals[(account_id, signal_id)] = signal.model_copy(deep=True)
                return signal, model

        if review.disposition is CreatorReviewDisposition.APPROVED and (
            review.model is None or review.expected_revision is None
        ):
            raise CreatorReviewModelRequiredError()

        pool = get_pool()
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await cur.execute(
                """
                SELECT payload_json FROM creator_agent_learning_signals
                WHERE account_id = %s AND signal_id = %s FOR UPDATE
                """,
                (account_id, signal_id),
            )
            row = await cur.fetchone()
            if row is None:
                raise LearningSignalMissingError(signal_id)
            signal = _learning_signal_from_row(row)
            if signal.status is not LearningSignalStatus.PENDING_CREATOR_REVIEW:
                if signal.status.value != review.disposition.value:
                    raise LearningSignalReviewConflictError(
                        signal_id, signal.status, review.disposition
                    )
                model = await self._model_for_applied_revision(cur, account_id, signal)
                return signal, model

            if review.disposition is CreatorReviewDisposition.DISMISSED:
                model = None
            else:
                assert review.model is not None
                assert review.expected_revision is not None
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (account_id,),
                )
                await cur.execute(
                    """
                    SELECT payload_json FROM creator_agent_models
                    WHERE account_id = %s FOR UPDATE
                    """,
                    (account_id,),
                )
                model_row = await cur.fetchone()
                current = _model_from_row(model_row) if model_row else None
                actual_revision = current.revision if current else 0
                if actual_revision != review.expected_revision:
                    raise CreatorModelRevisionConflictError(
                        review.expected_revision, actual_revision
                    )
                model = self._next_model(account_id, review.model, current)
                await cur.execute(
                    """
                    INSERT INTO creator_agent_models (
                        account_id, creator_id, revision, payload_json, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (account_id) DO UPDATE SET
                        creator_id = EXCLUDED.creator_id,
                        revision = EXCLUDED.revision,
                        payload_json = EXCLUDED.payload_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        account_id,
                        model.creator_id,
                        model.revision,
                        _dumps(model),
                        model.created_at,
                        model.updated_at,
                    ),
                )

            now = utc_now_iso()
            signal.status = LearningSignalStatus(review.disposition.value)
            signal.review_note = review.review_note
            signal.reviewed_at = now
            signal.updated_at = now
            if model is not None:
                signal.applied_model_revision = model.revision
            await cur.execute(
                """
                UPDATE creator_agent_learning_signals
                SET status = %s, payload_json = %s, updated_at = %s
                WHERE account_id = %s AND signal_id = %s
                """,
                (
                    signal.status.value,
                    _dumps(signal),
                    signal.updated_at,
                    account_id,
                    signal_id,
                ),
            )
        return signal, model

    @staticmethod
    async def _model_for_applied_revision(
        cur: Any, account_id: str, signal: LearningSignal
    ) -> CreatorModel | None:
        if signal.applied_model_revision is None:
            return None
        await cur.execute(
            "SELECT payload_json FROM creator_agent_models WHERE account_id = %s",
            (account_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        model = _model_from_row(row)
        return model if model.revision == signal.applied_model_revision else None

    @staticmethod
    async def _get_relationship_on_cursor(
        cur: Any,
        account_id: str,
        audience_id: str,
        *,
        lock: bool = False,
    ) -> RelationshipMemory | None:
        lock_sql = " FOR UPDATE" if lock else ""
        await cur.execute(
            """
            SELECT payload_json FROM creator_agent_relationships
            WHERE account_id = %s AND audience_id = %s
            """
            + lock_sql,
            (account_id, audience_id),
        )
        row = await cur.fetchone()
        return _relationship_from_row(row) if row else None

    @staticmethod
    async def _upsert_relationship_on_cursor(cur: Any, relationship: RelationshipMemory) -> None:
        await cur.execute(
            """
            INSERT INTO creator_agent_relationships (
                account_id, audience_id, payload_json, updated_at
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (account_id, audience_id) DO UPDATE SET
                payload_json = EXCLUDED.payload_json,
                updated_at = EXCLUDED.updated_at
            """,
            (
                relationship.account_id,
                relationship.audience_id,
                _dumps(relationship),
                relationship.last_interaction_at,
            ),
        )

    @staticmethod
    async def _ensure_learning_signal_on_cursor(
        cur: Any, decision: DecisionRecord, feedback: UserFeedback
    ) -> LearningSignal:
        await cur.execute(
            """
            SELECT payload_json FROM creator_agent_learning_signals
            WHERE account_id = %s AND feedback_id = %s
            """,
            (decision.account_id, feedback.feedback_id),
        )
        row = await cur.fetchone()
        if row:
            return _learning_signal_from_row(row)
        signal = _new_learning_signal(decision, feedback)
        await cur.execute(
            """
            INSERT INTO creator_agent_learning_signals (
                account_id, signal_id, feedback_id, status, payload_json,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, feedback_id) DO NOTHING
            """,
            (
                decision.account_id,
                signal.signal_id,
                signal.feedback_id,
                signal.status.value,
                _dumps(signal),
                signal.created_at,
                signal.updated_at,
            ),
        )
        return signal


_repository = DurableCreatorAgentRepository()


def get_repository() -> DurableCreatorAgentRepository:
    return _repository


__all__ = ["DurableCreatorAgentRepository", "ensure_tables", "get_repository"]
