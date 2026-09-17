"""P0-W5 continuation channel — resuming past an evaluator fail-closed pause.

The evaluator gate is fail-closed: a degraded evaluation or a compliance
rejection ends the run with phase=PAUSED (+ pause_reason). Round 1 of this task
parked the workflow there but left NO supported way to continue: /resume on that
thread fell through to the legacy restart, which re-runs the whole pipeline from
trend_scout.

These tests drive the REAL compiled graph (in-memory checkpointer) and pin the
LangGraph semantics the /resume endpoint depends on:

  1. after the fail-closed END the thread is terminal and carries
     pause_reason="evaluator_fail_closed";
  2. a human "approve" patched with as_node="evaluator_gate" makes the *next*
     node the publish path — the conditional edge (evaluator_outcome) is
     re-evaluated and upstream agents are not re-run.  Since P2a-S4b that next
     node is publish_gate rather than publisher: the AI verdict answers whether
     the content MAY be published, the human authorisation is a separate hop;
  3. a human "revise" routes to revise_content with a fresh revision budget.

The state patch comes from the same builder the route uses
(build_evaluator_pause_resume_updates), so this cannot pass on a fiction.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from backend.api.routes._wf_runtime import build_evaluator_pause_resume_updates
from backend.graph.builder import build_graph
from backend.graph.routers import (
    PAUSE_REASON_EVALUATOR_FAIL_CLOSED,
    evaluator_outcome,
    evaluator_requires_human,
)
from backend.state.enums import ContentStatus, WorkflowPhase

# Nodes upstream of the gate that must NEVER re-run for a gate decision.
UPSTREAM_NODES = (
    "trend_scout",
    "content_strategist",
    "copywriter",
    "visual_designer",
    "review_gate",
    "evaluator_gate",
)


def _compile_test_graph() -> Any:
    builder = build_graph()
    return builder.compile(
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
        interrupt_before=["choice_gate", "draft_gate"],
    )


def _seed_after_human_approval(thread_id: str) -> dict[str, Any]:
    """State as it stands right after review_gate approved the content.

    The global conftest LLM stub returns ``{"result": "mocked"}``, which the
    evaluator cannot turn into a verdict → degraded, decision-less evaluation
    → P0-W5 fail-closed pause.
    """
    return {
        "phase": WorkflowPhase.REVIEWING,
        "current_agent": "review_gate",
        "workflow_mode": "trend",
        "execution_mode": "single",
        "session_id": thread_id,
        "account_id": "test_account",
        "niche": "母婴",
        "revision_count": 0,
        "error": None,
        "retry_count": 0,
        "trend_data": {"hot_topics": [{"topic": "test"}]},
        "content_plan": {"selected_topic": "test"},
        "copy_content": {"selected_title": "t", "body_text": "b"},
        "visual_plan": {"cover_prompt": "c"},
        "publish_result": {},
        "analytics": {},
        "engagement_actions": [],
        "human_feedback": {"decision": ContentStatus.APPROVED},
        "publish_options": {"dry_run": True},
        "dry_run": True,
    }


async def _drive_to_fail_closed_pause(graph: Any, config: dict[str, Any]) -> dict[str, Any]:
    thread_id = config["configurable"]["thread_id"]
    await graph.aupdate_state(config, _seed_after_human_approval(thread_id), as_node="review_gate")
    return await graph.ainvoke(None, config)


async def _collect_visited(graph: Any, config: dict[str, Any]) -> list[str]:
    visited: list[str] = []
    async for chunk in graph.astream(None, config, stream_mode="updates"):
        visited.extend(chunk)
    return visited


class TestEvaluatorFailClosedPause:
    """The paused hand-off carries a machine-readable reason (W5 continuation)."""

    @pytest.mark.asyncio
    async def test_pause_is_terminal_and_marked(self):
        graph = _compile_test_graph()
        config = {"configurable": {"thread_id": "w5-pause-marked"}}

        final = await _drive_to_fail_closed_pause(graph, config)

        assert final.get("phase") == WorkflowPhase.PAUSED
        assert final.get("pause_reason") == PAUSE_REASON_EVALUATOR_FAIL_CLOSED
        snapshot = await graph.aget_state(config)
        assert tuple(snapshot.next or ()) == ()  # terminal — the run ended
        assert evaluator_requires_human(snapshot.values) is True

    @pytest.mark.asyncio
    async def test_approved_patch_clears_the_human_requirement(self):
        """The patch the resume endpoint writes must flip the SHARED predicate."""
        graph = _compile_test_graph()
        config = {"configurable": {"thread_id": "w5-patch-predicate"}}
        final = await _drive_to_fail_closed_pause(graph, config)

        updates = build_evaluator_pause_resume_updates(final, "approve")
        merged = {**final, **updates}

        assert evaluator_requires_human(merged) is False
        # The router still ANSWERS "publisher" — that verdict is a statement
        # about content quality.  P2a-S4b only moved the edge's target, see
        # test_as_node_patch_routes_to_the_publish_gate below.
        assert evaluator_outcome(merged) == "publisher"
        assert updates["pause_reason"] is None


class TestResumeApproveReachesThePublishPath:
    """approve → the publish path is entered; upstream agents do NOT re-run."""

    @pytest.mark.asyncio
    async def test_as_node_patch_routes_to_the_publish_gate(self):
        graph = _compile_test_graph()
        config = {"configurable": {"thread_id": "w5-approve-next"}}
        final = await _drive_to_fail_closed_pause(graph, config)

        updates = build_evaluator_pause_resume_updates(final, "approve")
        await graph.aupdate_state(config, updates, as_node="evaluator_gate")

        snapshot = await graph.aget_state(config)
        # Empirical LangGraph semantics: the conditional edge is re-evaluated.
        # evaluator_outcome still ANSWERS "publisher"; P2a-S4b moved the edge's
        # target one hop on, to the gate that asks a human before the
        # irreversible act.  Pinned here so a future re-wiring of this edge has
        # to come through this assertion.
        assert tuple(snapshot.next or ()) == ("publish_gate",)

    @pytest.mark.asyncio
    async def test_continue_runs_only_the_publish_path(self):
        graph = _compile_test_graph()
        config = {"configurable": {"thread_id": "w5-approve-run"}}
        final = await _drive_to_fail_closed_pause(graph, config)

        updates = build_evaluator_pause_resume_updates(final, "approve")
        await graph.aupdate_state(config, updates, as_node="evaluator_gate")

        visited = await _collect_visited(graph, config)

        # This seed is a dry run, so the gate finds a standing authorisation and
        # passes the run straight through without asking — which is what keeps
        # this a publish-path test rather than a gate test (the gate's own
        # behaviour is pinned in test_publish_gate_flow.py).
        assert "publish_gate" in visited
        assert "publisher" in visited
        for upstream in UPSTREAM_NODES:
            assert upstream not in visited, f"{upstream} re-ran after an approve resume"

        done = await graph.aget_state(config)
        assert done.values.get("pause_reason") in (None, "")
        assert done.values.get("publish_result", {}).get("status") == "mock_published"


class TestResumeReviseTakesAFreshRevisionBudget:
    """revise → the revise node runs with a reset revision budget (no instant cap)."""

    @pytest.mark.asyncio
    async def test_revise_routes_to_revise_content_with_fresh_budget(self):
        graph = _compile_test_graph()
        config = {"configurable": {"thread_id": "w5-revise"}}
        final = await _drive_to_fail_closed_pause(graph, config)

        updates = build_evaluator_pause_resume_updates(final, "revise")
        # The human-initiated cycle starts from a full budget, so the
        # fail-closed revision-cap path cannot re-trigger immediately.
        assert updates["revision_count"] == 0
        await graph.aupdate_state(config, updates, as_node="evaluator_gate")

        snapshot = await graph.aget_state(config)
        assert tuple(snapshot.next or ()) == ("revise_content",)

        visited = await _collect_visited(graph, config)

        assert "revise_content" in visited
        assert "publisher" not in visited
        assert "trend_scout" not in visited

        values = (await graph.aget_state(config)).values
        # Exactly one cycle consumed out of the freshly granted budget.
        assert values.get("revision_count") == 1
        evaluation = values.get("evaluation_result") or {}
        assert evaluation.get("decision") == ContentStatus.NEEDS_REVISION
        assert evaluation.get("revision_hints"), "revise must give the writer hints"
        assert values.get("pause_reason") in (None, "")
