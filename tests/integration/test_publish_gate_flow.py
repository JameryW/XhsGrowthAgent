"""P2a-S4b — the publish gate, end to end, on the REAL compiled graph.

The node's unit tests pin its decision table.  This file pins the thing that made
the slice necessary in the first place: on a real (non-rehearsal) run an approved
evaluation is NOT authorisation to publish.  The graph stops at the gate, and the
run only reaches the publisher once a confirmation comes back through
``Command(resume=...)``.

The publisher node is replaced here — its own behaviour is covered by
tests/unit/agents/test_run_publish.py and the Tool Gateway suite.  What is under
test is the ordering of the two decisions: quality (the AI verdict) and
authorisation (the human).

The stub has to be in place *before* ``build_graph()`` runs: ``artifact_seam``
binds the callable it is handed, so a later patch would not be seen.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from backend.graph.builder import build_graph
from backend.state.enums import ContentStatus, WorkflowPhase

FAKE_PUBLISHER = "backend.graph.builder.publisher_node"


def _recording_publisher(calls: list[str]) -> Any:
    """A publisher stand-in that reports only that it was reached."""

    async def _publisher(state: Any, *, store: Any) -> dict[str, Any]:
        calls.append("publisher")
        return {
            "publish_result": {"status": "published", "note_id": "note-1"},
            "phase": WorkflowPhase.COMPLETED,
            "current_agent": "publisher",
        }

    _publisher.__name__ = "publisher_node"
    return _publisher


def _compile_test_graph() -> Any:
    graph = build_graph()
    return graph.compile(
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
        interrupt_before=["choice_gate", "draft_gate"],
    )


def _approved_real_run(thread_id: str, **overrides: Any) -> dict[str, Any]:
    """State right after the AI quality gate approved a REAL publish.

    ``dry_run`` is absent on purpose: a rehearsal would make the gate stand down,
    and this seed exists to be the case where it must not.
    """
    seed: dict[str, Any] = {
        "phase": WorkflowPhase.REVIEWING,
        "current_agent": "evaluator_gate",
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
        "copy_content": {"selected_title": "露营装备清单", "body_text": "b"},
        "visual_plan": {"cover_prompt": "c", "image_paths": ["a.jpg"]},
        "publish_result": {},
        "analytics": {},
        "engagement_actions": [],
        "human_feedback": {"decision": ContentStatus.APPROVED},
        "evaluation_result": {
            "overall_score": 88,
            "decision": ContentStatus.APPROVED,
            "status": "completed",
            "dimensions": [{"dimension": "copywriting", "score": 88, "is_blocking": False}],
            "revision_hints": [],
            "summary": "质量合格",
        },
    }
    seed.update(overrides)
    return seed


async def _park_with_quality_approved(
    graph: Any, config: dict[str, Any], seed: dict[str, Any]
) -> None:
    """Enter the publish path as if evaluator_gate had just approved."""
    await graph.aupdate_state(config, seed, as_node="evaluator_gate")


async def _collect_visited(graph: Any, config: dict[str, Any], payload: Any) -> list[str]:
    visited: list[str] = []
    async for chunk in graph.astream(payload, config, stream_mode="updates"):
        visited.extend(chunk)
    return visited


class TestRealPublishStopsAtTheGate:
    """An approved evaluation enters the gate and waits there."""

    @pytest.mark.asyncio
    async def test_the_run_pauses_at_the_gate_instead_of_publishing(self):
        calls: list[str] = []
        with patch(FAKE_PUBLISHER, _recording_publisher(calls)):
            graph = _compile_test_graph()
            config = {"configurable": {"thread_id": "s4b-stops"}}
            await _park_with_quality_approved(graph, config, _approved_real_run("s4b-stops"))

            await graph.ainvoke(None, config)
            snapshot = await graph.aget_state(config)

        assert calls == [], "nothing may be published before a human authorises it"
        # The gate is *waiting*, not resolved: no decision, no result, no phase move.
        assert "publish_confirmation" not in snapshot.values
        assert not snapshot.values.get("publish_result")
        assert snapshot.values["phase"] == WorkflowPhase.REVIEWING
        # The interrupt itself names the gate — this is the contract derive_status
        # reads to report AWAITING_PUBLISH, pinned here rather than assumed.
        assert snapshot.interrupts, "the gate must raise a resumable interrupt"
        assert snapshot.interrupts[0].value["gate"] == "publish"
        assert snapshot.interrupts[0].value["publish_summary"]["title"] == "露营装备清单"
        assert tuple(snapshot.next or ()) == ("publish_gate",)


class TestConfirmationResumesIntoThePublisher:
    @pytest.mark.asyncio
    async def test_confirmed_publishes_exactly_once(self):
        calls: list[str] = []
        with patch(FAKE_PUBLISHER, _recording_publisher(calls)):
            graph = _compile_test_graph()
            config = {"configurable": {"thread_id": "s4b-confirmed"}}
            await _park_with_quality_approved(graph, config, _approved_real_run("s4b-confirmed"))
            await graph.ainvoke(None, config)

            visited = await _collect_visited(
                graph, config, Command(resume={"decision": "confirmed"})
            )
            values = (await graph.aget_state(config)).values

        assert "publisher" in visited
        assert calls == ["publisher"], "a confirmation publishes once, not more"
        assert values["publish_confirmation"]["decision"] == "confirmed"
        assert values["publish_confirmation"]["source"] == "human"
        assert values["publish_result"]["status"] == "published"
        assert values["phase"] == WorkflowPhase.COMPLETED

    @pytest.mark.asyncio
    async def test_cancelled_ends_the_run_without_publishing(self):
        calls: list[str] = []
        with patch(FAKE_PUBLISHER, _recording_publisher(calls)):
            graph = _compile_test_graph()
            config = {"configurable": {"thread_id": "s4b-cancelled"}}
            await _park_with_quality_approved(graph, config, _approved_real_run("s4b-cancelled"))
            await graph.ainvoke(None, config)

            visited = await _collect_visited(
                graph, config, Command(resume={"decision": "cancelled", "comments": "标题不合适"})
            )
            snapshot = await graph.aget_state(config)

        assert calls == []
        assert "publisher" not in visited
        assert snapshot.values["publish_confirmation"]["decision"] == "cancelled"
        assert snapshot.values["publish_confirmation"]["comments"] == "标题不合适"
        # A refusal is a decision, so the run ends cancelled rather than stranded
        # (a phase left at PUBLISHING with no next node would read as *completed*).
        assert snapshot.values["phase"] == WorkflowPhase.CANCELLED
        assert tuple(snapshot.next or ()) == ()

    @pytest.mark.parametrize(
        "resume_value",
        [{"decision": "yes"}, {"decision": "confirmed "}, {"decision": True}, "confirmed"],
    )
    @pytest.mark.asyncio
    async def test_an_unrecognised_resume_does_not_publish(self, resume_value: Any):
        """Version skew reaching the resume channel must not become a publish."""
        calls: list[str] = []
        with patch(FAKE_PUBLISHER, _recording_publisher(calls)):
            graph = _compile_test_graph()
            tid = "s4b-bogus"
            config = {"configurable": {"thread_id": tid}}
            await _park_with_quality_approved(graph, config, _approved_real_run(tid))
            await graph.ainvoke(None, config)

            await _collect_visited(graph, config, Command(resume=resume_value))
            values = (await graph.aget_state(config)).values

        assert calls == [], f"{resume_value!r} must not authorise a publish"
        assert values["publish_confirmation"]["decision"] == "cancelled"
        assert values["phase"] == WorkflowPhase.CANCELLED

    @pytest.mark.asyncio
    async def test_an_empty_resume_leaves_the_gate_waiting(self):
        """An empty payload resumes nothing, so the gate simply asks again.

        Probed LangGraph semantics: ``Command(resume={})`` does not deliver a
        value to ``interrupt()`` — the node re-raises and the thread stays parked
        with the same interrupt and an untouched state.  That is the safest
        reading of a blank answer (a form submitted with no choice), and it is
        distinguishable from a refusal, so it is pinned separately.
        """
        calls: list[str] = []
        with patch(FAKE_PUBLISHER, _recording_publisher(calls)):
            graph = _compile_test_graph()
            tid = "s4b-empty"
            config = {"configurable": {"thread_id": tid}}
            await _park_with_quality_approved(graph, config, _approved_real_run(tid))
            await graph.ainvoke(None, config)

            await _collect_visited(graph, config, Command(resume={}))
            snapshot = await graph.aget_state(config)

        assert calls == []
        assert "publish_confirmation" not in snapshot.values
        assert snapshot.values["phase"] == WorkflowPhase.REVIEWING
        assert tuple(snapshot.next or ()) == ("publish_gate",)
        assert snapshot.interrupts[0].value["gate"] == "publish"


class TestStandingAuthorisationKeepsTheOldPath:
    """A workflow that already asked not to be asked again still publishes through."""

    @pytest.mark.asyncio
    async def test_auto_publish_is_not_asked_for_a_confirmation(self):
        calls: list[str] = []
        with patch(FAKE_PUBLISHER, _recording_publisher(calls)):
            graph = _compile_test_graph()
            config = {"configurable": {"thread_id": "s4b-auto"}}
            seed = _approved_real_run("s4b-auto", auto_publish=True)
            await _park_with_quality_approved(graph, config, seed)

            visited = await _collect_visited(graph, config, None)
            snapshot = await graph.aget_state(config)

        assert calls == ["publisher"]
        assert "publish_gate" in visited
        assert tuple(snapshot.next or ()) == (), "the run finished; it never stopped"
        assert snapshot.values["publish_confirmation"] == {
            "decision": "confirmed",
            "source": "auto_publish",
        }
        assert snapshot.values["phase"] == WorkflowPhase.COMPLETED
