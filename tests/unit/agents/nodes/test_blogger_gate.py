"""Unit tests for blogger_gate_node mock-note generation.

Pins the LLM routing of `_generate_mock_notes`: pure-fiction JSON generation
goes through TaskType.MOCK_GEN (deepseek-v4-flash, lighter/cheaper), matching
the sibling blogger_scout agent — NOT TaskType.SCOUTING (astron-code-latest,
the heavy model used by trend_scout for real trend analysis).

Also pins the bare-node LLM cost capture: blogger_gate_node is not a BaseAgent,
so #491's `_tool_llm_cost` ContextVar is never set in its scope and the direct
`model.ainvoke` is invisible to `/analytics/costs` unless the node threads a
local accumulator and merges a kind:"llm" entry into performance_log itself.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.nodes import blogger_gate as bg
from backend.agents.nodes.blogger_gate import _generate_mock_notes, blogger_gate_node
from backend.config.models import TaskType


def _state(**overrides):
    base = {
        "account_id": "test_account",
        "blogger_candidates": [
            {"user_id": "mock_001", "nickname": "测试博主"},
        ],
        "niche": "母婴",
        "brief_content": {"brand_name": "几素", "product_name": "风扇"},
    }
    base.update(overrides)
    return base


def _mock_model_with_usage(input_tokens: int = 100, output_tokens: int = 50):
    """Build a fake model whose ainvoke returns a response carrying usage_metadata."""
    mock_response = MagicMock()
    mock_response.content = (
        '{"notes": [{"note_id": "mock_note_001", "title": "t", "body": "b", '
        '"hashtags": ["h"], "likes": 1, "collects": 1, "comments": 1, '
        '"engagement_rate": 0.1}]}'
    )
    mock_response.usage_metadata = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=mock_response)
    return mock_model


class TestBloggerGateMockNotes:
    @pytest.mark.asyncio
    async def test_generate_mock_notes_routes_to_mock_gen(self):
        """_generate_mock_notes routes via MOCK_GEN (轻模型), not SCOUTING.

        Pure-fiction JSON generation matches blogger_scout (PR #468); reverting
        to SCOUTING (heavy astron model) is a regression this test guards.
        """
        mock_response = MagicMock()
        mock_response.content = (
            '{"notes": [{"note_id": "mock_note_001", "title": "t", "body": "b", '
            '"hashtags": ["h"], "likes": 1, "collects": 1, "comments": 1, '
            '"engagement_rate": 0.1}]}'
        )
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)

        with patch(
            "backend.agents.nodes.blogger_gate.get_model",
            return_value=mock_model,
        ) as mock_get_model:
            notes = await _generate_mock_notes(_state(), "mock_001", 3)

        mock_get_model.assert_called_once_with(TaskType.MOCK_GEN.value)
        assert mock_get_model.call_args[0][0] == "mock_gen"
        assert mock_get_model.call_args[0][0] != "scouting"
        assert len(notes) == 1
        assert notes[0]["note_id"] == "mock_note_001"


class TestBloggerGateNodeLlmCostCapture:
    """Bare node LLM cost capture — blogger_gate_node is not a BaseAgent."""

    @pytest.mark.asyncio
    async def test_blogger_gate_node_emits_llm_cost_entry(self):
        """Selected mock_ blogger → performance_log gets a kind:"llm" entry.

        The entry must carry agent=="blogger_gate" and cost_usd>0 derived from
        usage_metadata so /analytics/costs sees the deepseek-v4-flash call.
        """
        mock_model = _mock_model_with_usage(input_tokens=100, output_tokens=50)

        def _select_blogger(_payload):
            return {"user_id": "mock_001", "nickname": "测试博主"}

        with (
            patch("backend.agents.nodes.blogger_gate.get_model", return_value=mock_model),
            patch.object(bg, "interrupt", _select_blogger),
        ):
            result = await blogger_gate_node(_state(), store=None)  # type: ignore[arg-type]

        assert "performance_log" in result
        llm_entries = [e for e in result["performance_log"] if e.get("kind") == "llm"]
        assert len(llm_entries) == 1
        entry = llm_entries[0]
        assert entry["agent"] == "blogger_gate"
        assert entry["input_tokens"] == 100
        assert entry["output_tokens"] == 50
        assert entry["cost_usd"] > 0
        # Notes still returned unchanged
        assert len(result["blogger_notes"]) == 1
        assert result["blogger_notes"][0]["note_id"] == "mock_note_001"

    @pytest.mark.asyncio
    async def test_capture_failure_does_not_break_call(self):
        """llm_perf_entry raising must not break note generation.

        Best-effort capture: a capture bug returns no perf entry but the node
        still returns notes and does not crash.
        """
        mock_model = _mock_model_with_usage()

        def _select_blogger(_payload):
            return {"user_id": "mock_001", "nickname": "测试博主"}

        with (
            patch("backend.agents.nodes.blogger_gate.get_model", return_value=mock_model),
            patch.object(bg, "interrupt", _select_blogger),
            patch(
                "backend.agents.nodes.blogger_gate.llm_perf_entry",
                side_effect=RuntimeError("capture boom"),
            ),
        ):
            result = await blogger_gate_node(_state(), store=None)  # type: ignore[arg-type]

        # Notes returned despite capture failure
        assert len(result["blogger_notes"]) == 1
        # No perf entry merged (capture raised, accumulator stayed empty)
        assert not result.get("performance_log")

    @pytest.mark.asyncio
    async def test_no_candidates_skips_perf_entry(self):
        """Empty candidates → early return, no LLM call, no performance_log.

        The no-candidates path returns before _fetch_blogger_notes, so no
        kind:"llm" entry is emitted and performance_log is absent.
        """
        mock_model = _mock_model_with_usage()

        with (
            patch("backend.agents.nodes.blogger_gate.get_model", return_value=mock_model),
            patch.object(bg, "interrupt", side_effect=AssertionError("must not interrupt")),
        ):
            result = await blogger_gate_node(
                _state(blogger_candidates=[]),
                store=None,  # type: ignore[arg-type]
            )

        assert result["blogger_skipped"] is True
        assert result["blogger_notes"] == []
        assert "performance_log" not in result
        mock_model.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_selection_skips_perf_entry(self):
        """User skips selection → early return, no LLM call, no performance_log.

        The skip path (candidates exist, interrupt returns skip) returns before
        perf_acc is created, so no kind:"llm" entry is emitted. Guards against a
        future regression moving perf_acc creation above the skip return.
        """
        mock_model = _mock_model_with_usage()

        def _skip(_payload):
            return {"skip": True}

        with (
            patch("backend.agents.nodes.blogger_gate.get_model", return_value=mock_model),
            patch.object(bg, "interrupt", _skip),
        ):
            result = await blogger_gate_node(_state(), store=None)  # type: ignore[arg-type]

        assert result["blogger_skipped"] is True
        assert result["blogger_notes"] == []
        assert "performance_log" not in result
        mock_model.ainvoke.assert_not_called()
