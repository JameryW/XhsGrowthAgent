"""Unit tests for blogger_gate_node mock-note generation.

Pins the LLM routing of `_generate_mock_notes`: pure-fiction JSON generation
goes through TaskType.MOCK_GEN (deepseek-v4-flash, lighter/cheaper), matching
the sibling blogger_scout agent — NOT TaskType.SCOUTING (astron-code-latest,
the heavy model used by trend_scout for real trend analysis).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.nodes.blogger_gate import _generate_mock_notes
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
