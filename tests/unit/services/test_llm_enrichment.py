"""Unit tests for LLM Enrichment Service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config.models import TaskType
from backend.services.llm_enrichment import (
    LLMEnrichmentError,
    LLMEnrichmentService,
    get_llm_service,
)


class TestLLMEnrichmentService:
    """Tests for LLMEnrichmentService."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return LLMEnrichmentService()

    def test_parse_json_response_raw_json(self, service):
        """Parse raw JSON string."""
        content = '{"key": "value", "number": 42}'
        result = service._parse_json_response(content)
        assert result == {"key": "value", "number": 42}

    def test_parse_json_response_markdown_block(self, service):
        """Parse JSON from markdown code block."""
        content = """```json
{"key": "value"}
```"""
        result = service._parse_json_response(content)
        assert result == {"key": "value"}

    def test_parse_json_response_plain_block(self, service):
        """Parse JSON from plain code block."""
        content = """```
{"key": "value"}
```"""
        result = service._parse_json_response(content)
        assert result == {"key": "value"}

    def test_parse_json_response_list(self, service):
        """Parse JSON list."""
        content = '[{"id": 1}, {"id": 2}]'
        result = service._parse_json_response(content)
        assert result == [{"id": 1}, {"id": 2}]

    def test_parse_json_response_embedded_json(self, service):
        """Parse embedded JSON object."""
        content = 'Some text {"key": "value"} more text'
        result = service._parse_json_response(content)
        assert result == {"key": "value"}

    def test_parse_json_response_invalid_raises(self, service):
        """Invalid JSON raises LLMEnrichmentError."""
        content = "Not valid JSON at all"
        with pytest.raises(LLMEnrichmentError):
            service._parse_json_response(content)

    @pytest.mark.asyncio
    async def test_enrich_with_llm_success(self, service):
        """Successful LLM enrichment returns parsed result."""
        mock_response = MagicMock()
        mock_response.content = '{"result": "success"}'

        with patch.object(service, "_get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_get_model.return_value = mock_model

            result = await service.enrich_with_llm(
                task_type=TaskType.WRITING,
                prompt_template={
                    "system": "You are helpful",
                    "user_template": "Topic: {topic}",
                },
                input_data={"topic": "美食"},
            )

        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_enrich_with_llm_uses_fallback_on_error(self, service):
        """LLM failure triggers fallback function."""

        def fallback_fn(data):
            return {"fallback": data.get("topic")}

        with patch.object(service, "_get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
            mock_get_model.return_value = mock_model

            result = await service.enrich_with_llm(
                task_type=TaskType.WRITING,
                prompt_template={"system": "", "user_template": ""},
                input_data={"topic": "美食"},
                fallback_fn=fallback_fn,
            )

        assert result == {"fallback": "美食"}

    @pytest.mark.asyncio
    async def test_enrich_with_llm_empty_on_no_fallback(self, service):
        """No fallback returns empty dict."""
        with patch.object(service, "_get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
            mock_get_model.return_value = mock_model

            result = await service.enrich_with_llm(
                task_type=TaskType.WRITING,
                prompt_template={},
                input_data={},
            )

        assert result == {}

    @pytest.mark.asyncio
    async def test_generate_with_llm_returns_list(self, service):
        """generate_with_llm returns list."""
        mock_response = MagicMock()
        mock_response.content = '[{"id": 1}, {"id": 2}]'

        with patch.object(service, "_get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_get_model.return_value = mock_model

            result = await service.generate_with_llm(
                task_type=TaskType.WRITING,
                prompt_template={"system": "", "user_template": ""},
                input_data={},
            )

        assert result == [{"id": 1}, {"id": 2}]

    @pytest.mark.asyncio
    async def test_generate_with_llm_wraps_dict(self, service):
        """generate_with_llm wraps dict result in list."""
        mock_response = MagicMock()
        mock_response.content = '{"id": 1}'

        with patch.object(service, "_get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_get_model.return_value = mock_model

            result = await service.generate_with_llm(
                task_type=TaskType.WRITING,
                prompt_template={},
                input_data={},
            )

        assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_generate_with_llm_extracts_items_key(self, service):
        """generate_with_llm extracts 'items' key from dict."""
        mock_response = MagicMock()
        mock_response.content = '{"items": [{"id": 1}, {"id": 2}]}'

        with patch.object(service, "_get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_get_model.return_value = mock_model

            result = await service.generate_with_llm(
                task_type=TaskType.WRITING,
                prompt_template={},
                input_data={},
            )

        assert result == [{"id": 1}, {"id": 2}]

    def test_get_model_caches(self, service):
        """_get_model caches model instances."""
        with patch("backend.services.llm_enrichment.get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            # First call
            model1 = service._get_model(TaskType.WRITING)
            # Second call
            model2 = service._get_model(TaskType.WRITING)

            # Only one get_model call (cached)
            mock_get_model.assert_called_once_with("writing")
            assert model1 == model2


class TestGetLLMService:
    """Tests for get_llm_service singleton."""

    def test_returns_service_instance(self):
        """get_llm_service returns LLMEnrichmentService."""
        service = get_llm_service()
        assert isinstance(service, LLMEnrichmentService)

    def test_returns_same_instance(self):
        """get_llm_service returns singleton."""
        service1 = get_llm_service()
        service2 = get_llm_service()
        assert service1 == service2
