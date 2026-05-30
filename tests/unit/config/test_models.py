"""Unit tests for config models."""

import pytest

from backend.config.models import (
    TaskType,
    ModelProvider,
    ModelConfig,
    MODEL_REGISTRY,
    resolve_model_id,
    get_model_config,
)


class TestTaskType:
    """Tests for TaskType enum."""

    def test_task_type_values(self):
        """TaskType has expected values."""
        assert TaskType.ROUTING.value == "routing"
        assert TaskType.SCOUTING.value == "scouting"
        assert TaskType.STRATEGY.value == "strategy"
        assert TaskType.WRITING.value == "writing"
        assert TaskType.VISUAL.value == "visual"
        assert TaskType.ANALYSIS.value == "analysis"
        assert TaskType.PUBLISHING.value == "publishing"
        assert TaskType.ENGAGEMENT.value == "engagement"

    def test_task_type_is_string_enum(self):
        """TaskType is string enum."""
        assert isinstance(TaskType.ROUTING, str)
        assert TaskType.ROUTING == "routing"


class TestModelProvider:
    """Tests for ModelProvider enum."""

    def test_provider_values(self):
        """ModelProvider has expected values."""
        assert ModelProvider.ANTHROPIC.value == "anthropic"
        assert ModelProvider.OPENAI.value == "openai"
        assert ModelProvider.DEEPSEEK.value == "deepseek"
        assert ModelProvider.DASHSCOPE.value == "dashscope"


class TestModelConfig:
    """Tests for ModelConfig model."""

    def test_model_config_defaults(self):
        """ModelConfig has default values."""
        config = ModelConfig(
            provider=ModelProvider.ANTHROPIC,
            model_name="test-model",
        )
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.timeout == 60

    def test_model_config_custom_values(self):
        """ModelConfig accepts custom values."""
        config = ModelConfig(
            provider=ModelProvider.OPENAI,
            model_name="custom-model",
            temperature=0.5,
            max_tokens=2048,
            timeout=30,
        )
        assert config.temperature == 0.5
        assert config.max_tokens == 2048
        assert config.timeout == 30


class TestModelRegistry:
    """Tests for MODEL_REGISTRY."""

    def test_registry_contains_expected_models(self):
        """Registry contains expected models."""
        expected_models = [
            "claude-sonnet-4-20250514",
            "gpt-4o",
            "deepseek-chat",
            "qwen-plus",
            "mimo-v2.5-pro",
        ]
        for model_id in expected_models:
            assert model_id in MODEL_REGISTRY

    def test_registry_configs_valid(self):
        """All registry configs are valid ModelConfig instances."""
        for model_id, config in MODEL_REGISTRY.items():
            assert isinstance(config, ModelConfig)
            assert config.model_name == model_id


class TestResolveModelId:
    """Tests for resolve_model_id function."""

    def test_routing_tasks_use_mimo(self):
        """ROUTING and SCOUTING use mimo-v2.5-pro."""
        assert resolve_model_id(TaskType.ROUTING) == "mimo-v2.5-pro"
        assert resolve_model_id(TaskType.SCOUTING) == "mimo-v2.5-pro"

    def test_strategy_writing_use_mimo(self):
        """STRATEGY and WRITING use mimo-v2.5-pro."""
        assert resolve_model_id(TaskType.STRATEGY) == "mimo-v2.5-pro"
        assert resolve_model_id(TaskType.WRITING) == "mimo-v2.5-pro"

    def test_visual_analysis_use_mimo(self):
        """VISUAL and ANALYSIS use mimo-v2.5-pro."""
        assert resolve_model_id(TaskType.VISUAL) == "mimo-v2.5-pro"
        assert resolve_model_id(TaskType.ANALYSIS) == "mimo-v2.5-pro"

    def test_publishing_use_mimo(self):
        """PUBLISHING uses mimo-v2.5-pro."""
        assert resolve_model_id(TaskType.PUBLISHING) == "mimo-v2.5-pro"

    def test_engagement_use_mimo(self):
        """ENGAGEMENT uses mimo-v2.5-pro."""
        assert resolve_model_id(TaskType.ENGAGEMENT) == "mimo-v2.5-pro"

    def test_routing_overrides(self):
        """Routing overrides allow custom model assignments."""
        overrides = {"routing": "deepseek-chat"}
        result = resolve_model_id(TaskType.ROUTING, routing_overrides=overrides)
        assert result == "deepseek-chat"


class TestGetModelConfig:
    """Tests for get_model_config function."""

    def test_get_existing_model(self):
        """get_model_config returns config for known model."""
        config = get_model_config("claude-sonnet-4-20250514")
        assert config.provider == ModelProvider.ANTHROPIC
        assert config.model_name == "claude-sonnet-4-20250514"

    def test_get_unknown_model_raises(self):
        """get_model_config raises KeyError for unknown model."""
        with pytest.raises(KeyError) as exc_info:
            get_model_config("unknown-model")
        assert "Unknown model" in str(exc_info.value)