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
from backend.graph.routers import evaluator_outcome
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
        """Agent throwing → node returns explicit degraded/scoreless output."""
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

    def test_missing_evaluation_defaults_to_publisher(self):
        assert evaluator_outcome({}) == "publisher"


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
