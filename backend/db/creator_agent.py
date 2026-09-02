"""Creator Agent persistence with Postgres and process-memory adapters."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from backend.creator_agent.models import (
    CreatorModel,
    CreatorModelDefinition,
    DecisionRecord,
    FeedbackOutcome,
    RelationshipMemory,
    UserFeedback,
    utc_now_iso,
)
from backend.creator_agent.repository import CreatorModelRevisionConflictError
from backend.db.pool import get_pool, is_pool_ready

_mem_models: dict[str, CreatorModel] = {}
_mem_decisions: dict[tuple[str, str], DecisionRecord] = {}
_mem_relationships: dict[tuple[str, str], RelationshipMemory] = {}
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

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_creator_agent_decisions_audience
    ON creator_agent_decisions (account_id, audience_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_creator_agent_relationships_updated
    ON creator_agent_relationships (account_id, updated_at DESC);
"""


def _reset_memory_store() -> None:
    """Clear the process-memory adapter for isolated tests."""
    _mem_models.clear()
    _mem_decisions.clear()
    _mem_relationships.clear()


async def ensure_tables() -> None:
    if not is_pool_ready():
        return
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_MODELS_SQL)
        await conn.execute(_CREATE_DECISIONS_SQL)
        await conn.execute(_CREATE_RELATIONSHIPS_SQL)
        await conn.execute(_CREATE_INDEX_SQL)


def _dumps(model: CreatorModel | DecisionRecord | RelationshipMemory) -> str:
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
                if any(item.feedback_id == feedback.feedback_id for item in decision.feedback):
                    return decision, relationship.model_copy(deep=True), False
                decision.feedback.append(feedback)
                decision.updated_at = feedback.created_at
                relationship = _updated_relationship(relationship, feedback)
                _mem_decisions[key] = decision.model_copy(deep=True)
                _mem_relationships[relationship_key] = relationship.model_copy(deep=True)
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
            if any(item.feedback_id == feedback.feedback_id for item in decision.feedback):
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


_repository = DurableCreatorAgentRepository()


def get_repository() -> DurableCreatorAgentRepository:
    return _repository


__all__ = ["DurableCreatorAgentRepository", "ensure_tables", "get_repository"]
