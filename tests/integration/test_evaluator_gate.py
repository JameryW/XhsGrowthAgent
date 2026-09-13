"""Integration tests for the evaluator gate (RQGM agent-as-a-judge).

Validates the pre-publish quality-gate chain:
  review_gate(approved) → evaluator_gate → evaluator_outcome → publisher | revise_content

Covers:
1. evaluator_node writes evaluation_result + emits event
2. evaluator_node degrades to an explicit scoreless result on agent failure
   (non-blocking)
3. evaluator_outcome routing for approved / needs_revision / rejected / missing
4. revise_content_node preserves evaluation_result.revision_hints into
   human_feedback.revisions for the copywriter
5. Graph topology wires review_gate → evaluator_gate → publisher
"""

# ruff: noqa: E501, UP031  — long JSON fixtures + %-format avoids {}/f-string clash

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.evaluator import EvaluatorAgent
from backend.agents.nodes.evaluator import evaluator_node
from backend.agents.nodes.revise_content import revise_content_node
from backend.graph.builder import build_graph
from backend.graph.routers import (
    PAUSE_REASON_EVALUATOR_FAIL_CLOSED,
    evaluator_outcome,
    evaluator_requires_human,
)
from backend.state.enums import ContentStatus, WorkflowPhase


def _panel_json(decision: str, hints: list[str] | None = None) -> str:
    dims = ",".join(
        '{"dimension": "%s", "score": 80, "rationale": "r", "issues": [], "is_blocking": false}' % n
        for n in (
            "copywriting",
            "visual",
            "compliance",
            "reach",
            "audience",
            "ai_taste",
            "image_quality",
            "commercial_tone",
            "bias_check",
        )
    )
    return (
        '{"overall_score": 80, "dimensions": [%s], "decision": "%s", '
        '"revision_hints": %s, "bias_warning": "", "summary": "ok"}' % (dims, decision, hints or [])
    )


class TestEvaluatorNodeIntegration:
    """evaluator_node wraps EvaluatorAgent, writes result, emits event, degrades."""

    @pytest.fixture
    def state(self):
        return {
            "account_id": "a",
            "niche": "母婴",
            "session_id": "thread-1",
            "phase": WorkflowPhase.REVIEWING,
            "content_plan": {"selected_topic": "婴儿车"},
            "copy_content": {"selected_title": "t", "body_text": "b"},
            "visual_plan": {"cover_prompt": "c"},
        }

    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.asearch = AsyncMock(return_value=[])
        return s

    @pytest.mark.asyncio
    async def test_node_writes_evaluation_result_and_emits(self, state, store):
        mock_response = MagicMock()
        mock_response.content = _panel_json("approved")
        with patch.object(EvaluatorAgent, "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await evaluator_node(state, store=store)

        assert "evaluation_result" in result
        assert result["evaluation_result"]["decision"] == ContentStatus.APPROVED
        assert result["current_agent"] == "evaluator"

    @pytest.mark.asyncio
    async def test_node_degrades_to_pass_on_agent_failure(self, state, store):
        """Agent throwing → explicit degraded/scoreless output, and the workflow
        is parked for a human (P0-W5: a degraded quality gate must never
        silently reach the publisher)."""
        with patch.object(EvaluatorAgent, "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(side_effect=RuntimeError("LLM down"))
            m.return_value = model
            result = await evaluator_node(state, store=store)

        ev = result["evaluation_result"]
        assert ev["decision"] is None
        assert ev["overall_score"] is None
        assert ev["status"] == "degraded"
        assert ev["degraded"] is True
        assert "评估器异常" in ev["summary"]
        # Human channel: existing paused semantics (derive_status → "paused"),
        # no new status enum for the frontend.
        assert result["phase"] == WorkflowPhase.PAUSED
        # W5 continuation: the pause carries a machine-readable reason so
        # /resume can demand an explicit human decision instead of restarting
        # the whole pipeline.
        assert result["pause_reason"] == PAUSE_REASON_EVALUATOR_FAIL_CLOSED

    @pytest.mark.asyncio
    async def test_compliance_rejection_at_cap_pauses_with_reason(self, state, store):
        """Node marker and router share ONE predicate (no divergence).

        A compliance rejection at the revision cap is fail-closed: the node
        marks the pause with a reason and the router ends the run — the human
        continuation channel is the only way forward.
        """
        dims = ",".join(
            '{"dimension": "%s", "score": %s, "rationale": "r", "issues": [], '
            '"is_blocking": %s}' % (name, score, str(blocking).lower())
            for name, score, blocking in (
                ("copywriting", 80, False),
                ("visual", 80, False),
                ("compliance", 10, True),
                ("reach", 80, False),
                ("audience", 80, False),
                ("ai_taste", 80, False),
                ("image_quality", 80, False),
                ("commercial_tone", 80, False),
                ("bias_check", 90, False),
            )
        )
        mock_response = MagicMock()
        mock_response.content = (
            '{"overall_score": 80, "dimensions": [%s], "decision": "approved", '
            '"revision_hints": [], "bias_warning": "", "summary": "ok"}' % dims
        )
        capped = {**state, "revision_count": 99}
        with patch.object(EvaluatorAgent, "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await evaluator_node(capped, store=store)

        evaluation = result["evaluation_result"]
        # The panel's blocking compliance evidence overrides the LLM self-report.
        assert evaluation["decision"] == ContentStatus.REJECTED
        assert result["phase"] == WorkflowPhase.PAUSED
        assert result["pause_reason"] == PAUSE_REASON_EVALUATOR_FAIL_CLOSED
        merged = {**capped, **result}
        assert evaluator_requires_human(merged) is True
        assert evaluator_outcome(merged) == "__end__"

    @pytest.mark.asyncio
    async def test_router_and_predicate_agree_on_healthy_approval(self):
        """The approved track keeps auto-publishing and never claims a reason."""
        evaluation = {"decision": ContentStatus.APPROVED, "status": "ready", "dimensions": []}
        thread_state = {"evaluation_result": evaluation, "revision_count": 99}
        assert evaluator_requires_human(thread_state) is False
        assert evaluator_outcome(thread_state) == "publisher"

    @pytest.mark.asyncio
    async def test_node_does_not_pause_on_approved(self, state, store):
        """A healthy approved evaluation keeps the phase untouched (no pause)."""
        mock_response = MagicMock()
        mock_response.content = _panel_json("approved")
        with patch.object(EvaluatorAgent, "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await evaluator_node(state, store=store)

        assert result["evaluation_result"]["decision"] == ContentStatus.APPROVED
        assert result.get("phase") != WorkflowPhase.PAUSED
        assert result.get("pause_reason") is None, "a passed gate must not stay marked"

    @pytest.mark.asyncio
    async def test_node_emits_data_updated_event(self, state, store):
        mock_response = MagicMock()
        mock_response.content = _panel_json("needs_revision", ["改标题"])
        with patch.object(EvaluatorAgent, "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            # Should not raise even when emitting through the real event bus
            await evaluator_node(state, store=store)


class TestEvaluatorOutcomeRouting:
    """evaluator_outcome routes by evaluation_result.decision."""

    def test_approved_to_publisher(self):
        assert (
            evaluator_outcome({"evaluation_result": {"decision": ContentStatus.APPROVED}})
            == "publisher"
        )

    def test_needs_revision_to_revise(self):
        assert (
            evaluator_outcome({"evaluation_result": {"decision": ContentStatus.NEEDS_REVISION}})
            == "revise_content"
        )

    def test_rejected_to_revise(self):
        assert (
            evaluator_outcome({"evaluation_result": {"decision": ContentStatus.REJECTED}})
            == "revise_content"
        )

    def test_missing_evaluation_is_fail_closed(self):
        """P0-W5: missing evaluation_result must NOT default to publisher."""
        assert evaluator_outcome({}) == "__end__"

    def test_degraded_none_decision_is_not_published(self):
        state = {"evaluation_result": {"decision": None, "degraded": True, "status": "degraded"}}
        assert evaluator_outcome(state) == "__end__"


class TestReviseContentPreservesHints:
    """revise_content_node carries evaluator revision_hints into human_feedback."""

    @pytest.mark.asyncio
    async def test_hints_propagated_to_human_feedback(self):
        state = {
            "evaluation_result": {
                "revision_hints": ["[copywriting] 标题太平", "[visual] 封面与内容不符"],
                "decision": ContentStatus.NEEDS_REVISION,
            },
            "human_feedback": {"decision": ContentStatus.APPROVED},  # stale
        }
        store = AsyncMock()
        result = await revise_content_node(state, store=store)

        # content cleared for rewrite
        assert result["copy_content"] == {}
        assert result["visual_plan"] == {}
        assert result["phase"] == WorkflowPhase.CREATING
        # hints carried
        assert result["human_feedback"]["revisions"] == [
            "[copywriting] 标题太平",
            "[visual] 封面与内容不符",
        ]

    @pytest.mark.asyncio
    async def test_no_hints_no_feedback_written(self):
        state = {"evaluation_result": {"decision": ContentStatus.APPROVED}}
        store = AsyncMock()
        result = await revise_content_node(state, store=store)
        # no revision_hints → human_feedback not set (or empty)
        assert "revisions" not in (result.get("human_feedback") or {})

    @pytest.mark.asyncio
    async def test_revision_count_incremented(self):
        """revise_content_node increments revision_count for loop guard."""
        state = {
            "evaluation_result": {
                "decision": ContentStatus.NEEDS_REVISION,
                "revision_hints": ["fix"],
            },
            "revision_count": 1,
        }
        store = AsyncMock()
        result = await revise_content_node(state, store=store)
        assert result["revision_count"] == 2

    @pytest.mark.asyncio
    async def test_revision_count_starts_from_zero(self):
        """Missing revision_count defaults to 0, incremented to 1."""
        state = {"evaluation_result": {"decision": ContentStatus.NEEDS_REVISION}}
        store = AsyncMock()
        result = await revise_content_node(state, store=store)
        assert result["revision_count"] == 1


class TestGraphTopologyEvaluatorGate:
    """build_graph wires review_gate → evaluator_gate → publisher."""

    def test_evaluator_gate_node_exists(self):
        g = build_graph()
        assert "evaluator_gate" in g.nodes

    def test_review_gate_approved_branch_to_evaluator_gate(self):
        g = build_graph()
        review_branch = g.branches.get("review_gate")
        assert review_branch is not None
        ends = next(iter(review_branch.values())).ends
        assert ends.get("evaluator_gate") == "evaluator_gate"

    def test_evaluator_gate_branch_to_publisher_and_revise(self):
        g = build_graph()
        ev_branch = g.branches.get("evaluator_gate")
        assert ev_branch is not None
        ends = next(iter(ev_branch.values())).ends
        assert ends.get("publisher") == "publisher"
        assert ends.get("revise_content") == "revise_content"
        # P0-W5 human channel: fail-closed outcomes end the run (the node has
        # already parked the workflow in the existing paused status).
        assert "__end__" in ends
