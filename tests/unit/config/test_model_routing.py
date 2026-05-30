"""Model routing tests."""

from backend.config.models import (
    MODEL_REGISTRY,
    ModelProvider,
    TaskType,
    get_model_config,
    resolve_model_id,
)


def test_resolve_model_id_default():
    """默认路由：每个任务类型映射到正确的模型"""
    assert resolve_model_id(TaskType.WRITING) == "mimo-v2.5-pro"
    assert resolve_model_id(TaskType.SCOUTING) == "mimo-v2.5-pro"
    assert resolve_model_id(TaskType.ANALYSIS) == "mimo-v2.5-pro"
    assert resolve_model_id(TaskType.PUBLISHING) == "mimo-v2.5-pro"


def test_resolve_model_id_override():
    """用户覆盖路由"""
    overrides = {"writing": "deepseek-chat"}
    assert resolve_model_id(TaskType.WRITING, overrides) == "deepseek-chat"


def test_get_model_config():
    """获取模型配置"""
    config = get_model_config("deepseek-chat")
    assert config.provider == ModelProvider.DEEPSEEK
    assert config.model_name == "deepseek-chat"


def test_get_model_config_unknown():
    """未知模型抛出 KeyError"""
    try:
        get_model_config("nonexistent-model")
        assert False, "Should have raised KeyError"
    except KeyError:
        pass


def test_all_task_types_have_routing():
    """所有任务类型都有默认路由"""
    for task in TaskType:
        model_id = resolve_model_id(task)
        assert model_id in MODEL_REGISTRY, f"Task {task} routes to unknown model {model_id}"
