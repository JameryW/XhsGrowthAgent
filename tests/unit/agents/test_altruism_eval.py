"""Altruism (利他性) dimension in RQGM evaluator — score + suggestions."""

# ruff: noqa: UP031  — %-format fixtures avoid f-string/JSON brace clash

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.evaluator import _DIMENSION_WEIGHTS, EvaluatorAgent
from backend.db.evaluator_config import DEFAULT_DIMENSION_WEIGHTS, WEIGHTED_DIMENSIONS
from backend.state.enums import ContentStatus


def test_altruism_in_default_weights_and_sums_to_one():
    assert "altruism" in DEFAULT_DIMENSION_WEIGHTS
    assert "altruism" in WEIGHTED_DIMENSIONS
    assert "altruism" in _DIMENSION_WEIGHTS
    s = sum(DEFAULT_DIMENSION_WEIGHTS.values())
    assert abs(s - 1.0) < 1e-6
    assert abs(sum(_DIMENSION_WEIGHTS.values()) - 1.0) < 1e-6


def test_build_evaluation_result_includes_altruism_and_weights_it():
    agent = EvaluatorAgent()
    # High on most dims, low altruism — overall should be pulled down vs all-high
    raw = {
        "dimensions": [
            {"dimension": "copywriting", "score": 90, "rationale": "ok", "issues": []},
            {"dimension": "visual", "score": 90, "rationale": "ok", "issues": []},
            {"dimension": "compliance", "score": 90, "rationale": "ok", "issues": []},
            {"dimension": "reach", "score": 90, "rationale": "ok", "issues": []},
            {"dimension": "audience", "score": 90, "rationale": "ok", "issues": []},
            {"dimension": "ai_taste", "score": 90, "rationale": "ok", "issues": []},
            {"dimension": "image_quality", "score": 90, "rationale": "ok", "issues": []},
            {"dimension": "commercial_tone", "score": 90, "rationale": "ok", "issues": []},
            {
                "dimension": "altruism",
                "score": 30,
                "rationale": "纯硬广无干货",
                "issues": ["缺少可执行建议", "信息对读者无增量"],
                "is_blocking": False,
            },
            {
                "dimension": "bias_check",
                "score": 90,
                "bias_severity": 10,
                "rationale": "ok",
                "issues": [],
            },
        ],
        "revision_hints": [],
        "summary": "利他性不足",
    }
    result = agent._build_evaluation_result(raw)
    dims = {d["dimension"]: d for d in result["dimensions"]}
    assert "altruism" in dims
    assert dims["altruism"]["score"] == 30
    assert "缺少可执行建议" in dims["altruism"]["issues"]
    # Weighted: 0.91*90 + 0.09*30 = 81.9 + 2.7 = 84.6 without bias
    # Actually sum of non-altruism weights = 0.91, altruism 0.09
    # overall = 90*0.91 + 30*0.09 = 81.9 + 2.7 = 84.6
    assert result["overall_score"] == pytest.approx(84.6, abs=0.2)
    # Low altruism → revision hints name 利他性
    hints_blob = " ".join(result["revision_hints"])
    assert "利他性" in hints_blob or "altruism" in hints_blob
    assert result["decision"] in (
        ContentStatus.APPROVED,
        ContentStatus.NEEDS_REVISION,
        "approved",
        "needs_revision",
    )


def test_missing_altruism_is_unavailable_instead_of_neutral_default():
    agent = EvaluatorAgent()
    raw = {
        "dimensions": [
            {"dimension": name, "score": 80, "rationale": "r", "issues": [], "is_blocking": False}
            for name in [
                "copywriting",
                "visual",
                "compliance",
                "reach",
                "audience",
                "ai_taste",
                "image_quality",
                "commercial_tone",
                "bias_check",
            ]
        ],
        "revision_hints": [],
        "summary": "no altruism dim",
    }
    # add bias_severity for bias_check
    for d in raw["dimensions"]:
        if d["dimension"] == "bias_check":
            d["bias_severity"] = 0
    result = agent._build_evaluation_result(raw)
    dims = {d["dimension"]: d for d in result["dimensions"]}
    assert "altruism" in dims
    assert dims["altruism"]["score"] is None
    assert dims["altruism"]["available"] is False
    assert result["status"] == "partial"
    assert result["overall_score"] == 80.0
    # overall includes weight * 70 for altruism
    assert result["overall_score"] > 0


def test_low_altruism_forces_named_suggestions_even_when_llm_hints_empty():
    agent = EvaluatorAgent()
    dims = [
        {
            "dimension": "altruism",
            "score": 40,
            "rationale": "弱",
            "issues": ["只有产品安利没有方法"],
            "is_blocking": False,
        },
        {
            "dimension": "copywriting",
            "score": 80,
            "rationale": "ok",
            "issues": [],
            "is_blocking": False,
        },
    ]
    # fill other required dims for compute_decision path via _build
    raw = {
        "dimensions": dims
        + [
            {"dimension": n, "score": 80, "rationale": "r", "issues": [], "is_blocking": False}
            for n in [
                "visual",
                "compliance",
                "reach",
                "audience",
                "ai_taste",
                "image_quality",
                "commercial_tone",
                "bias_check",
            ]
        ],
        "revision_hints": [],
        "summary": "x",
    }
    for d in raw["dimensions"]:
        if d["dimension"] == "bias_check":
            d["bias_severity"] = 0
    result = agent._build_evaluation_result(raw)
    assert any("利他性" in h or "altruism" in h for h in result["revision_hints"])
    assert any("可执行" in h or "方法" in h or "步骤" in h for h in result["revision_hints"])


@pytest.mark.asyncio
async def test_execute_panel_with_altruism_dimension():
    agent = EvaluatorAgent()
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    state = {
        "account_id": "a",
        "niche": "母婴",
        "content_plan": {"selected_topic": "t", "content_angle": "", "target_audience": ""},
        "copy_content": {
            "selected_title": "买它就对了",
            "body_text": "最好用必入链接在这",
            "hashtags": [],
            "cta": "下单",
            "tone": "",
        },
        "visual_plan": {"cover_prompt": "x", "image_count": 1},
    }
    dims_json = ",".join(
        [
            '{"dimension":"%s","score":%s,"rationale":"r","issues":%s,"is_blocking":false%s}'
            % (
                name,
                85 if name != "altruism" else 35,
                '["纯硬广"]' if name == "altruism" else "[]",
                ',"bias_severity":5' if name == "bias_check" else "",
            )
            for name in list(_DIMENSION_WEIGHTS.keys()) + ["bias_check"]
        ]
    )
    content = (
        '{"overall_score":70,"dimensions":[%s],"decision":"needs_revision",'
        '"revision_hints":[],"bias_warning":"","summary":"弱利他"}' % dims_json
    )
    mock_response = MagicMock()
    mock_response.content = content
    with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=mock_response)
        m.return_value = model
        out = await agent.execute(state, store=store)

    ev = out["evaluation_result"]
    assert any(d["dimension"] == "altruism" for d in ev["dimensions"])
    alt = next(d for d in ev["dimensions"] if d["dimension"] == "altruism")
    assert alt["score"] == 35
    assert any("利他性" in h or "altruism" in h for h in ev["revision_hints"])
