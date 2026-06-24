"""State schema tests."""

from typing import get_args, get_type_hints

from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.reducers import append_list as _append_list
from backend.state.reducers import merge_dict as _merge_dict
from backend.state.reducers import replace as _replace
from backend.state.schema import XHSGrowthState


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


def _get_reducer(field_name: str):
    """Extract the reducer function from a state field's Annotated metadata."""
    hints = get_type_hints(XHSGrowthState, include_extras=True)
    annot = hints[field_name]
    # Annotated[list[...], reducer] → get_args returns (list[...], reducer)
    return get_args(annot)[1]


def test_content_versions_uses_replace_reducer():
    """content_versions must use replace (not append_list) so multi-round
    growth loops don't accumulate A/B/C versions with duplicate version_ids.

    Regression for: version_generator runs each growth loop, returning A/B/C.
    With append_list the list grew by 3 each round → duplicate version_ids →
    choice_gate's next() always matched the first round, breaking selection.
    """
    reducer = _get_reducer("content_versions")
    assert reducer is _replace


def test_content_versions_no_accumulation_across_rounds():
    """Simulate two rounds of version_generator output being reduced into state.

    Round 1 produces A/B/C, round 2 produces A/B/C again. With replace the
    final state holds only round 2's 3 versions (not 6), keeping version_ids
    unique so choice_gate can match correctly.
    """
    reducer = _get_reducer("content_versions")

    round1 = [
        {"version_id": "A", "title": "R1-A"},
        {"version_id": "B", "title": "R1-B"},
        {"version_id": "C", "title": "R1-C"},
    ]
    round2 = [
        {"version_id": "A", "title": "R2-A"},
        {"version_id": "B", "title": "R2-B"},
        {"version_id": "C", "title": "R2-C"},
    ]

    # State starts empty, version_generator round 1 writes 3 versions
    state_versions = reducer([], round1)
    assert len(state_versions) == 3

    # Round 2 — replace must swap in the new 3, not append (would be 6)
    state_versions = reducer(state_versions, round2)
    assert len(state_versions) == 3
    # All entries belong to round 2 (current round)
    assert all(v["title"].startswith("R2-") for v in state_versions)
