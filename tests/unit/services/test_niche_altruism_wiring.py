"""Structural + wiring checks: altruism dimension in evaluator + free evaluate path.

Niche-resolve wiring checks live with the creator-stats data-layer PR (they
depend on resolve_account_niche routes added there)."""

# ruff: noqa: UP031  — %-format fixtures avoid f-string/JSON brace clash

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.evaluator import _DIMENSION_WEIGHTS, EvaluatorAgent
from backend.db.evaluator_config import DEFAULT_DIMENSION_WEIGHTS


def test_evaluator_prompt_documents_altruism():
    yaml_path = Path(__file__).resolve().parents[3] / "backend/config/prompts/evaluator.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    assert "altruism" in text
    assert "利他性" in text
    assert '"dimension": "altruism"' in text or 'dimension": "altruism"' in text


def test_weights_include_altruism_sum_one():
    assert "altruism" in DEFAULT_DIMENSION_WEIGHTS
    assert abs(sum(DEFAULT_DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9
    assert abs(sum(_DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9


@pytest.mark.asyncio
async def test_free_evaluate_result_shape_has_altruism():
    """Free evaluate path uses EvaluatorAgent — result exposes altruism + hints."""
    agent = EvaluatorAgent()
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    state = {
        "account_id": "wire",
        "niche": "美妆",
        "content_plan": {"selected_topic": "种草"},
        "copy_content": {
            "selected_title": "必入链接",
            "body_text": "冲就完事",
            "hashtags": [],
            "cta": "买",
            "tone": "",
        },
        "visual_plan": {"cover_prompt": "c", "image_count": 1},
    }
    dims = []
    for name in list(_DIMENSION_WEIGHTS.keys()) + ["bias_check"]:
        score = 40 if name == "altruism" else 80
        issues = '["无干货"]' if name == "altruism" else "[]"
        extra = ',"bias_severity":5' if name == "bias_check" else ""
        dims.append(
            '{"dimension":"%s","score":%s,"rationale":"r","issues":%s,"is_blocking":false%s}'
            % (name, score, issues, extra)
        )
    content = (
        '{"overall_score":60,"dimensions":[%s],"decision":"needs_revision",'
        '"revision_hints":[],"bias_warning":"","summary":"s"}' % ",".join(dims)
    )
    resp = MagicMock()
    resp.content = content
    with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=resp)
        m.return_value = model
        out = await agent.execute(state, store=store)

    # Same shape free.evaluate_draft stores as last_evaluation / returns
    ev = out["evaluation_result"]
    assert "dimensions" in ev
    assert "revision_hints" in ev
    assert any(d["dimension"] == "altruism" for d in ev["dimensions"])
    assert any("利他性" in h or "altruism" in h for h in ev["revision_hints"])
