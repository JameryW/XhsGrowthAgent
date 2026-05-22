"""State schema tests."""

from xhs_growth.state.schema import (
    XHSGrowthState,
    WorkflowPhase,
    ContentStatus,
    Urgency,
    ContentType,
    _merge_dict,
    _append_list,
)


def test_workflow_phases():
    """验证工作流阶段枚举"""
    assert WorkflowPhase.SCOUTING == "scouting"
    assert WorkflowPhase.REVIEWING == "reviewing"
    assert WorkflowPhase.COMPLETED == "completed"


def test_content_status():
    """验证内容状态枚举"""
    assert ContentStatus.APPROVED == "approved"
    assert ContentStatus.REJECTED == "rejected"


def test_merge_dict_reducer():
    """字典合并 reducer"""
    left = {"a": 1, "b": 2}
    right = {"b": 3, "c": 4}
    result = _merge_dict(left, right)
    assert result == {"a": 1, "b": 3, "c": 4}


def test_append_list_reducer():
    """列表追加 reducer"""
    left = [1, 2]
    right = [3, 4]
    result = _append_list(left, right)
    assert result == [1, 2, 3, 4]


def test_state_has_required_fields():
    """状态 TypedDict 包含所有必需字段"""
    # 验证 TypedDict 的注解
    annotations = XHSGrowthState.__annotations__
    required_keys = {"phase", "current_agent", "error", "messages", "trend_data", "content_plan"}
    assert required_keys.issubset(annotations.keys())
