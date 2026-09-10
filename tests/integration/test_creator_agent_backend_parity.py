"""Cross-backend behavioral parity for the Creator Agent repository.

Repo convention is memory-only testing: ``tests/conftest.py`` deliberately pops
``POSTGRES_URI`` so the app lifespan never opens a pool. As a result the Postgres
branches of ``backend/db/creator_agent.py`` are executed by no test anywhere — not
locally, not in CI — even though they carry the durability guarantees this
subsystem exists to provide: append-only revision history, idempotent execution
receipts, advisory-lock serialization, and account isolation. The payload-shape
defect found in the revision backfill is exactly the class of bug only a real
Postgres surfaces.

This module drives one behavioral scenario against each backend and compares the
resulting traces. Generated identifiers and timestamps are masked first, so the
assertion is about *semantics* — statuses, ordering, conflicts, provenance — and
never about literal ids.

Opt-in and non-destructive by construction: point ``XHS_PG_PARITY_URI`` at any
reachable PostgreSQL server (13 or newer, for ``DROP DATABASE ... WITH (FORCE)``).
The fixture creates a randomly named scratch database on that server and drops it
at teardown, so no pre-existing database is read from or written to. Without the
variable the whole module skips, so the suite stays hermetic wherever no server is
configured.

Run it with, for example::

    XHS_PG_PARITY_URI=postgresql://user:pw@127.0.0.1:5432/postgres \
        pytest tests/integration/test_creator_agent_backend_parity.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import selectors
import uuid
from typing import Any

import pytest

PG_URI_ENV = "XHS_PG_PARITY_URI"

pytestmark = pytest.mark.skipif(
    not os.environ.get(PG_URI_ENV),
    reason=f"set {PG_URI_ENV} to a scratch-capable PostgreSQL server URI to run backend parity",
)

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)?")


def _mask(value: Any) -> Any:
    """Neutralize generated identifiers/timestamps while keeping structure visible."""
    if isinstance(value, dict):
        return {key: _mask(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item) for item in value]
    if isinstance(value, str):
        masked = _UUID.sub("<uuid>", value)
        return _TIMESTAMP.sub("<ts>", masked)
    return value


def _trace_json(value: Any) -> str:
    return json.dumps(_mask(value), ensure_ascii=False, sort_keys=True, indent=1)


async def _scenario(repo: Any) -> dict[str, Any]:
    """Exercise every Creator Agent behavior that has its own Postgres branch."""
    from backend.creator_agent.advisor import CreatorAdvisor
    from backend.creator_agent.models import (
        ActionIntentRequest,
        ActionResolution,
        ActionResolutionDisposition,
        CreatorModelDefinition,
        CreatorReviewDisposition,
        DecisionCandidate,
        DecisionPolicy,
        DecisionRequest,
        Evidence,
        EvidenceSource,
        FeedbackInput,
        FeedbackOutcome,
        LearningSignalReview,
        Preference,
        PreferenceStance,
    )

    advisor = CreatorAdvisor(repo)
    trace: dict[str, Any] = {}

    evidence = Evidence(
        evidence_id="e-durability",
        source_kind=EvidenceSource.CREATOR_STATEMENT,
        source_ref="creator://statement/durability",
        claim="我优先耐用与低维护",
    )
    definition = CreatorModelDefinition(
        identity_summary="长期体验创作者",
        domains=["家居"],
        preferences=[
            Preference(
                preference_id="pref-low-maintenance",
                label="低维护",
                stance=PreferenceStance.PREFER,
                tags=["low-maintenance"],
                strength=0.8,
                rationale="长期使用先看维护成本。",
                evidence_ids=["e-durability"],
            )
        ],
        policies=[
            DecisionPolicy(
                policy_id="policy-daily",
                label="日常先看耐用",
                applies_when={"scene": "daily"},
                signal_weights={"durability": 0.8, "price": 0.2},
                preferred_tags=["low-maintenance"],
                excluded_tags=["fragile"],
                rationale="长期使用时先保证稳定性。",
                evidence_ids=["e-durability"],
            )
        ],
        evidence=[evidence],
    )

    # 1-2. Revision history appends and stale writes are refused without damage.
    first = await repo.save_model("acct-a", definition, expected_revision=0)
    trace["first_save"] = {
        "revision": first.revision,
        "creator_id_shape": "creator_" in first.creator_id,
    }
    revised = definition.model_copy(update={"identity_summary": "长期体验创作者（改稿）"})
    await repo.save_model("acct-a", revised, expected_revision=1)
    try:
        await repo.save_model("acct-a", revised, expected_revision=1)
        trace["stale_write"] = "accepted"
    except Exception as exc:  # noqa: BLE001 - the error type is the contract
        trace["stale_write"] = type(exc).__name__

    history = await repo.list_model_revisions("acct-a")
    trace["history_after_edits"] = {
        "revisions": [item.revision for item in history.items],
        "sources": [item.source.value for item in history.items],
        "oldest_identity": history.items[-1].model.identity_summary,
    }

    # 3. A decision resolves to the revision it actually used, not the current one.
    decision = await advisor.decide(
        DecisionRequest(
            account_id="acct-a",
            audience_id="aud-1",
            goal="选一件日常耐用品",
            context={"scene": "daily"},
            candidates=[
                DecisionCandidate(
                    candidate_id="c-good",
                    label="稳固款",
                    tags=["low-maintenance"],
                    signals={"durability": 0.9, "price": 0.3},
                ),
                DecisionCandidate(
                    candidate_id="c-mid",
                    label="折中款",
                    tags=["low-maintenance"],
                    signals={"durability": 0.5, "price": 0.5},
                ),
                DecisionCandidate(
                    candidate_id="c-fragile",
                    label="易碎款",
                    tags=["fragile"],
                    signals={"durability": 0.1, "price": 0.9},
                ),
            ],
        )
    )
    resolved = await advisor.get_decision_model_revision("acct-a", decision.decision_id)
    trace["decision"] = {
        "status": decision.status.value,
        "model_revision": decision.model_revision,
        "ranked": [item.candidate_id for item in decision.recommendations],
        "excluded": [item.candidate_id for item in decision.excluded_candidates],
        "resolved_identity": resolved.model.identity_summary,
        "confidence_bucket": round(decision.confidence, 1),
    }

    # 4. Feedback is idempotent, touches relationship memory, and yields a signal.
    created = await advisor.record_feedback(
        "acct-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="fb-1",
            audience_id="aud-1",
            outcome=FeedbackOutcome.DISSATISFIED,
            correction="更在意便携。",
        ),
    )
    retry = await advisor.record_feedback(
        "acct-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="fb-1",
            audience_id="aud-1",
            outcome=FeedbackOutcome.ACCEPTED,
            correction="重试不得覆盖原文",
        ),
    )
    signal = created.learning_signal
    assert signal is not None
    relationship = await advisor.get_relationship("acct-a", "aud-1")
    trace["feedback"] = {
        "created": created.created,
        "retry_created": retry.created,
        "retry_keeps_original_correction": retry.learning_signal is not None
        and retry.learning_signal.correction == "更在意便携。",
        "signal_status": signal.status.value,
        "relationship_interactions": relationship.interaction_count,
        "relationship_accepts": sorted(relationship.accepted_candidate_ids),
    }

    # 5. An approved review appends a learning_review revision naming its signal.
    approved = await advisor.review_learning_signal(
        "acct-a",
        signal.signal_id,
        LearningSignalReview(
            disposition=CreatorReviewDisposition.APPROVED,
            expected_revision=2,
            model=definition.model_copy(update={"identity_summary": "加入便携权衡"}),
        ),
    )
    reviewed_history = await repo.list_model_revisions("acct-a")
    learning_rows = [
        item for item in reviewed_history.items if item.source.value == "learning_review"
    ]
    trace["review"] = {
        "applied_revision": approved.signal.applied_model_revision,
        "returned_model_revision": None if approved.model is None else approved.model.revision,
        "sources": [item.source.value for item in reviewed_history.items],
        "learning_rows": len(learning_rows),
        "learning_row_names_signal": all(
            item.source_signal_id is not None for item in learning_rows
        ),
    }

    # 6. A repeated review stays resolved after a later creator edit (history-backed).
    await repo.save_model("acct-a", definition, expected_revision=3)
    repeated = await advisor.review_learning_signal(
        "acct-a",
        signal.signal_id,
        LearningSignalReview(disposition=CreatorReviewDisposition.APPROVED),
    )
    trace["repeat_review"] = {
        "status": repeated.signal.status.value,
        "still_resolves_applied_revision": repeated.model is not None
        and repeated.model.revision == approved.signal.applied_model_revision,
        "history_total": (await repo.list_model_revisions("acct-a")).total,
    }

    # 7. Actions: idempotent intent, confirmation gate, immutable receipt.
    intent_request = {
        "account_id": "acct-a",
        "decision_id": decision.decision_id,
        "action_kind": "compare_options",
        "candidate_ids": ["c-good", "c-mid"],
        "idempotency_key": "parity-action-1",
    }
    intent = await advisor.plan_action(ActionIntentRequest(**intent_request))
    replay = await advisor.plan_action(
        ActionIntentRequest(**{**intent_request, "candidate_ids": ["c-good"]})
    )
    try:
        await advisor.execute_action("acct-a", intent.action_id)
        trace["pending_execution"] = "executed"
    except Exception as exc:  # noqa: BLE001
        trace["pending_execution"] = type(exc).__name__

    await advisor.resolve_action(
        "acct-a",
        intent.action_id,
        ActionResolution(disposition=ActionResolutionDisposition.CONFIRMED),
    )
    execution = await advisor.execute_action("acct-a", intent.action_id)
    reread = await advisor.get_action_execution("acct-a", intent.action_id)
    try:
        await advisor.resolve_action(
            "acct-a",
            intent.action_id,
            ActionResolution(disposition=ActionResolutionDisposition.CANCELLED),
        )
        trace["resolution_conflict"] = "accepted"
    except Exception as exc:  # noqa: BLE001
        trace["resolution_conflict"] = type(exc).__name__

    trace["action"] = {
        "idempotent_intent_replay": replay.action_id == intent.action_id,
        "replay_keeps_original_candidates": replay.candidate_ids == ["c-good", "c-mid"],
        "status": execution.status.value,
        "executor_version": execution.executor_version,
        "result_candidates": execution.result.get("candidate_ids"),
        "receipt_get_matches_post": _trace_json(reread.model_dump())
        == _trace_json(execution.model_dump()),
        "receipt_binds_decision_and_revision": execution.decision_id == decision.decision_id
        and execution.model_revision == decision.model_revision,
    }

    # 8. Read projections: Evidence Graph, Decision Dataset, revision pagination.
    graph = await advisor.list_evidence("acct-a")
    trace["evidence_graph"] = {
        "node_ids": sorted(entry.evidence.evidence_id for entry in graph),
        "refs": sorted(entry.evidence.source_ref for entry in graph),
        "reference_types": sorted(
            {reference.reference_type.value for entry in graph for reference in entry.references}
        ),
        "references_carry_revision": any(
            reference.model_revision is not None
            for entry in graph
            for reference in entry.references
        ),
    }
    dataset = await advisor.list_decision_dataset("acct-a", limit=10)
    trace["dataset"] = {
        "total": dataset.total,
        "statuses": [entry.decision.status.value for entry in dataset.items],
        "links_signals": [len(entry.learning_signal_ids) for entry in dataset.items],
        "filtered_by_feedback": (
            await advisor.list_decision_dataset(
                "acct-a", feedback_outcome=FeedbackOutcome.DISSATISFIED
            )
        ).total,
        "filtered_by_audience": (
            await advisor.list_decision_dataset("acct-a", audience_id="aud-1")
        ).total,
    }
    page_one = await advisor.list_model_revisions("acct-a", limit=2)
    page_two = await advisor.list_model_revisions("acct-a", cursor=page_one.next_cursor, limit=2)
    trace["revision_pagination"] = {
        "first": [item.revision for item in page_one.items],
        "second": [item.revision for item in page_two.items],
        "totals_stable": page_one.total == page_two.total,
        "no_overlap": not {i.revision for i in page_one.items}
        & {i.revision for i in page_two.items},
        "has_cursor": page_one.next_cursor is not None,
    }
    try:
        await advisor.list_model_revisions("acct-a", cursor="corrupt-token")
        trace["corrupt_cursor"] = "accepted"
    except ValueError as exc:
        trace["corrupt_cursor"] = str(exc)

    # 9. Account isolation must be indistinguishable from plain absence.
    trace["isolation"] = {
        "other_model_absent": await repo.get_model("acct-b") is None,
        "other_revision_absent": await repo.get_model_revision("acct-b", 1) is None,
        "foreign_receipt_absent": await repo.get_action_execution("acct-b", intent.action_id)
        is None,
        "foreign_decision_absent": await repo.get_decision("acct-b", decision.decision_id) is None,
        "foreign_history_total": (await repo.list_model_revisions("acct-b")).total,
        "foreign_dataset_total": (await repo.list_decision_dataset("acct-b")).total,
        "foreign_relationship_empty": (await repo.get_relationship("acct-b", "aud-1")) is None,
        "foreign_signal_absent": await repo.get_learning_signal("acct-b", signal.signal_id) is None,
    }
    return trace


def _run(coro: Any) -> Any:
    """Drive the async adapter on a selector loop.

    psycopg3 refuses to run async on asyncio's default ProactorEventLoop, so on
    Windows every async Postgres call needs an explicit selector loop. That is why
    this file does not use ``pytest.mark.asyncio``: the scenario must own its
    loop, and the same helper keeps the test working on Linux unchanged.
    """
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def _minimal_definition() -> Any:
    from backend.creator_agent.models import CreatorModelDefinition

    return CreatorModelDefinition(identity_summary="最小模型")


def _memory_repo() -> Any:
    from backend.db import creator_agent as creator_agent_db

    creator_agent_db._reset_memory_store()
    return creator_agent_db.DurableCreatorAgentRepository()


@pytest.fixture(autouse=True)
def _isolate_global_adapter_state() -> Any:
    """Keep process-global state from escaping this module.

    The parity scenario deliberately writes to the shared memory fallback and, on
    the Postgres side, to the module-level pool and ``POSTGRES_URI``. Neither is
    reset by any other suite, so leakage here would silently change tests that
    assume a fresh fallback or no ready pool.
    """
    from backend.db import creator_agent as creator_agent_db

    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()
    os.environ.pop("POSTGRES_URI", None)


@pytest.fixture
def scratch_database() -> Any:
    """Create a private database on the given server and drop it afterwards.

    Teardown needs PostgreSQL 13+ for ``DROP DATABASE ... WITH (FORCE)``. The
    earlier terminate-then-drop sequence raced the pool's background reconnection
    task: a connection re-established between the two statements made the drop
    fail with "database is being accessed", turning a passing test into a
    teardown error on an unrelated pull request.
    """
    import psycopg

    admin_uri = os.environ[PG_URI_ENV]
    database = f"xhs_parity_{uuid.uuid4().hex[:10]}"
    base = psycopg.conninfo.conninfo_to_dict(admin_uri)
    scratch_uri = psycopg.conninfo.make_conninfo(**{**base, "dbname": database})

    with psycopg.connect(admin_uri, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{database}"')
    try:
        yield scratch_uri
    finally:
        with psycopg.connect(admin_uri, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')


def test_postgres_and_memory_adapters_behave_identically(scratch_database: str) -> None:
    from backend.db import creator_agent as creator_agent_db
    from backend.db import pool as db_pool

    memory_trace = _run(_scenario(_memory_repo()))

    async def _postgres_side() -> dict[str, Any]:
        os.environ["POSTGRES_URI"] = scratch_database
        await db_pool.init_pool()
        try:
            await creator_agent_db.ensure_tables()
            assert db_pool.is_pool_ready(), "pool must be live for the Postgres branch to run"
            return await _scenario(creator_agent_db.DurableCreatorAgentRepository())
        finally:
            await db_pool.close_pool()
            os.environ.pop("POSTGRES_URI", None)

    postgres_trace = _run(_postgres_side())

    assert _trace_json(postgres_trace) == _trace_json(memory_trace), (
        "Postgres and memory adapters diverged:\n"
        f"--- postgres ---\n{_trace_json(postgres_trace)}\n"
        f"--- memory ---\n{_trace_json(memory_trace)}"
    )


def test_postgres_branch_is_actually_exercised(scratch_database: str) -> None:
    """Guard against a run that silently falls back to memory, making parity vacuous."""
    import psycopg

    from backend.db import creator_agent as creator_agent_db
    from backend.db import pool as db_pool

    async def _exercise() -> tuple[int, int, int, list[tuple[str, int]]]:
        from backend.creator_agent.models import ModelRevision

        os.environ["POSTGRES_URI"] = scratch_database
        await db_pool.init_pool()
        try:
            await creator_agent_db.ensure_tables()
            await creator_agent_db.DurableCreatorAgentRepository().save_model(
                "acct-a", _minimal_definition(), expected_revision=0
            )
            async with db_pool.get_pool().connection() as conn:
                models = await (
                    await conn.execute("SELECT count(*) FROM creator_agent_models")
                ).fetchone()

            # Re-running ensure_tables must stay idempotent, backfill included.
            await creator_agent_db.ensure_tables()
            async with db_pool.get_pool().connection() as conn:
                revisions = await (
                    await conn.execute("SELECT count(*) FROM creator_agent_model_revisions")
                ).fetchone()
            with psycopg.connect(scratch_database) as check:
                constraints = check.execute(
                    "SELECT count(*) FROM pg_constraint"
                    " WHERE conrelid = 'creator_agent_model_revisions'::regclass"
                ).fetchone()[0]

            # The backfill needs a real database behind it: a model row with no
            # history row must come back as a parseable ModelRevision envelope, not
            # as the raw CreatorModel payload. That is the exact defect class
            # static review kept slipping past.
            with psycopg.connect(scratch_database, autocommit=True) as check:
                check.execute("DELETE FROM creator_agent_model_revisions")
            await creator_agent_db.ensure_tables()
            async with db_pool.get_pool().connection() as conn:
                restored = await (
                    await conn.execute(
                        "SELECT source, payload_json FROM creator_agent_model_revisions"
                    )
                ).fetchall()
            backfilled = [
                (str(row[0]), ModelRevision.model_validate_json(row[1]).model.revision)
                for row in restored
            ]
            return int(models[0]), int(revisions[0]), int(constraints), backfilled
        finally:
            await db_pool.close_pool()
            os.environ.pop("POSTGRES_URI", None)

    models, revisions, constraints, backfilled = _run(_exercise())
    # The writes must land in real tables rather than the memory fallback.
    assert models == 1
    # Exactly one snapshot per revision survives a repeated ensure_tables call.
    assert revisions == 1
    # The append-only history table really carries its (account_id, revision) key.
    assert constraints >= 1
    # Backfill restored exactly one readable snapshot, tagged as imported history.
    assert backfilled == [("imported_history", 1)]
