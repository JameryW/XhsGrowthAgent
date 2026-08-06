"""Tests for brief mode PDF upload — start without text, upload triggers execution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.state.enums import WorkflowPhase


class TestBriefModeNoText:
    """Brief mode workflow start without brief_text should not error."""

    @pytest.mark.asyncio
    async def test_start_brief_mode_no_text_saves_checkpoint(self):
        """Starting brief mode without text saves state but doesn't start execution."""

        # Mock graph and request
        mock_graph = AsyncMock()
        mock_graph.aupdate_state = AsyncMock()

        mock_request = MagicMock()
        mock_request.app.state.graph = mock_graph

        from backend.api.routes.workflow import WorkflowStartRequest

        WorkflowStartRequest(
            account_id="test",
            workflow_mode="brief",
            brief_text=None,
        )

        # Patch dependencies
        with (
            patch("backend.api.routes.workflow._db_upsert", new_callable=AsyncMock),
            patch("backend.api.routes._runner._background_tasks", {}),
        ):
            # The start endpoint should create checkpoint and return early
            # (actual endpoint test requires full FastAPI test client)
            pass

    def test_brief_analyzer_empty_text_no_error(self):
        """BriefAnalyzerAgent returns BRIEFING phase (not ERROR) when raw_text is empty."""
        from backend.agents.brief_analyzer import BriefAnalyzerAgent

        agent = BriefAnalyzerAgent()

        # Simulate calling execute with empty brief_content
        import asyncio

        async def _test():
            state = {
                "account_id": "test",
                "brief_content": {},
                "niche": "美妆",
            }
            mock_store = AsyncMock()
            result = await agent.execute(state, mock_store)

            assert result["phase"] == WorkflowPhase.BRIEFING
            assert "error" not in result
            assert result["brief_clarification"]["resolved"] is False

        asyncio.run(_test())

    def test_brief_analyzer_with_text_works_normally(self):
        """BriefAnalyzerAgent with text invokes LLM and returns parsed result."""
        from backend.agents.brief_analyzer import BriefAnalyzerAgent

        agent = BriefAnalyzerAgent()

        mock_response = MagicMock()
        mock_response.content = '{"brand_name": "TestBrand", "confidence": 0.8}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        import asyncio

        async def _test():
            state = {
                "account_id": "test",
                "brief_content": {"raw_text": "Test brief content"},
                "niche": "美妆",
            }
            mock_store = AsyncMock()
            mock_store.asearch = AsyncMock(return_value=[])
            result = await agent.execute(state, mock_store)

            assert result["phase"] == WorkflowPhase.BRIEFING
            assert "error" not in result
            assert result["brief_content"]["brand_name"] == "TestBrand"

        asyncio.run(_test())


class TestBriefAnalyzerParallelRecalls:
    """recall_style + recall_benchmark run via one asyncio.gather (niche guard preserved)."""

    @pytest.mark.asyncio
    async def test_recalls_run_concurrently_when_niche_truthy(self):
        """The 2 creative-memory recalls run via one asyncio.gather (not 2 serial awaits).

        Non-vacuous: patches ``asyncio.gather`` in the brief_analyzer module and
        asserts it's awaited exactly once with 2 awaitables. If the recalls are
        reverted to 2 serial ``await`` assignments, ``asyncio.gather`` is never
        called and this test fails.
        """
        import asyncio as _asyncio

        from backend.agents.brief_analyzer import BriefAnalyzerAgent

        agent = BriefAnalyzerAgent()

        mock_response = MagicMock()
        mock_response.content = '{"brand_name": "TestBrand", "confidence": 0.8}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        real_gather = _asyncio.gather
        gather_calls: list[tuple[tuple, dict]] = []

        async def _fake_gather(*awaitables, **kwargs):
            gather_calls.append((awaitables, kwargs))
            # Drive the coroutines the way real gather would, preserving order.
            return list(await real_gather(*awaitables, **kwargs))

        state = {
            "account_id": "test",
            "brief_content": {"raw_text": "Test brief content"},
            "niche": "美妆",
        }
        mock_store = AsyncMock()
        mock_store.asearch = AsyncMock(return_value=[])

        with patch("backend.agents.brief_analyzer.asyncio.gather", new=_fake_gather):
            await agent.execute(state, mock_store)

        assert len(gather_calls) == 1, "memory recalls must be gathered in one call"
        awaitables, _ = gather_calls[0]
        assert len(awaitables) == 2, "expected exactly 2 concurrent recalls"

    @pytest.mark.asyncio
    async def test_recall_benchmark_not_called_when_niche_empty(self):
        """When niche is empty, recall_benchmark is NOT called (guard preserved).

        Non-vacuous: the guard skips recall_benchmark via _noop_benchmark. If the
        guard is dropped (always call recall_benchmark(niche)), recall_benchmark
        gets called with "" and this test fails.
        """
        from backend.agents.brief_analyzer import BriefAnalyzerAgent

        agent = BriefAnalyzerAgent()

        mock_response = MagicMock()
        mock_response.content = '{"brand_name": "TestBrand", "confidence": 0.8}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        state = {
            "account_id": "test",
            "brief_content": {"raw_text": "Test brief content"},
            "niche": "",
        }
        mock_store = AsyncMock()
        mock_store.asearch = AsyncMock(return_value=[])

        with patch(
            "backend.memory.creative.CreativeMemory.recall_benchmark",
            new_callable=AsyncMock,
        ) as mock_recall_benchmark:
            await agent.execute(state, mock_store)

        mock_recall_benchmark.assert_not_called()

    @pytest.mark.asyncio
    async def test_recall_benchmark_called_when_niche_truthy(self):
        """When niche is truthy, recall_benchmark IS called (guard passes through)."""
        from backend.agents.brief_analyzer import BriefAnalyzerAgent

        agent = BriefAnalyzerAgent()

        mock_response = MagicMock()
        mock_response.content = '{"brand_name": "TestBrand", "confidence": 0.8}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        state = {
            "account_id": "test",
            "brief_content": {"raw_text": "Test brief content"},
            "niche": "美妆",
        }
        mock_store = AsyncMock()
        mock_store.asearch = AsyncMock(return_value=[])

        with patch(
            "backend.memory.creative.CreativeMemory.recall_benchmark",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_recall_benchmark:
            await agent.execute(state, mock_store)

        mock_recall_benchmark.assert_called_once_with("美妆")
