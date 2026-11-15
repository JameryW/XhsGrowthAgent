"""SearchLLM-style Layer I soft-AND gate and GEO-readiness tests."""

from __future__ import annotations

from backend.services.quality_gate import (
    DEFAULT_LAYER_ONE,
    FloorSpec,
    apply_quality_gate,
    evaluate_layer_one,
    geo_readiness,
)


def _dimensions(**scores: float) -> list[dict[str, object]]:
    return [
        {"dimension": name, "score": score, "available": True} for name, score in scores.items()
    ]


def test_all_floors_pass_keeps_score() -> None:
    gate = evaluate_layer_one(_dimensions(compliance=90, copywriting=85, commercial_tone=80))
    assert gate["gate_factor"] == 1.0
    assert gate["blocked_dimensions"] == []
    result = apply_quality_gate(
        _dimensions(compliance=90, copywriting=85, commercial_tone=80),
        base_overall=88.0,
    )
    assert result["overall"] == 88.0


def test_floor_breach_multiplies_down_toward_zero() -> None:
    gate = evaluate_layer_one(_dimensions(compliance=10, copywriting=85, commercial_tone=80))
    assert gate["gate_factor"] < 0.05
    assert gate["blocked_dimensions"] == ["compliance"]
    result = apply_quality_gate(
        _dimensions(compliance=10, copywriting=85, commercial_tone=80),
        base_overall=90.0,
    )
    assert result["overall"] < 5.0


def test_multiple_floor_breaches_compound() -> None:
    one = evaluate_layer_one(_dimensions(compliance=10, copywriting=85, commercial_tone=80))[
        "gate_factor"
    ]
    two = evaluate_layer_one(_dimensions(compliance=10, copywriting=30, commercial_tone=80))[
        "gate_factor"
    ]
    assert two < one


def test_missing_dimension_does_not_zero_the_gate() -> None:
    gate = evaluate_layer_one(_dimensions(copywriting=85))
    assert gate["gate_factor"] == 1.0
    assert gate["blocked_dimensions"] == []


def test_custom_floor_spec() -> None:
    gate = evaluate_layer_one(
        _dimensions(reach=50), specs=[FloorSpec("reach", floor=60, temperature=10)]
    )
    assert gate["blocked_dimensions"] == ["reach"]
    assert gate["gate_factor"] < 1.0


def test_geo_readiness_rewards_answer_first_structure() -> None:
    good = geo_readiness(
        "新手化妆步骤",
        "结论：先保湿再上妆。\n1. 保湿\n2. 底妆\n3. 定妆\n#化妆 #新手教程 #干货",
        ["化妆", "新手教程", "干货"],
    )
    bad = geo_readiness("", "随便写写", [])
    assert good["score"] >= 75
    assert bad["score"] < good["score"]


def test_default_layer_one_contains_bottom_lines() -> None:
    names = {spec.dimension for spec in DEFAULT_LAYER_ONE}
    assert names == {"compliance", "copywriting", "commercial_tone"}
