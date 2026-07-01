"""Tests for the evaluator finetune script's training-record formatting."""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is not a package — add repo root so `import` works.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.finetune_evaluator import sample_to_jsonl  # noqa: E402


def _sample(*, snapshot=None, engagement=None, dims=None) -> dict:
    # Mirrors a real DB-exported row: bias_warning is NOT a column (it's derived
    # from bias_check issues/severity at eval time), so it's absent here.
    return {
        "overall_score": 78.5,
        "decision": "needs_revision",
        "label_source": "evaluator",
        "dimensions": dims
        if dims is not None
        else [
            {
                "dimension": "copywriting",
                "score": 80,
                "rationale": "结构清晰",
                "issues": ["标题弱"],
                "is_blocking": False,
            },
            {
                "dimension": "bias_check",
                "score": 60,
                "bias_severity": 75,
                "rationale": "偏宽松",
                "issues": ["检测到偏倚"],
                "is_blocking": False,
            },
        ],
        "content_snapshot": snapshot,
        "engagement": engagement,
    }


def _snapshot() -> dict:
    return {
        "title": "AI效率指南",
        "body": "正文内容…" * 5,
        "hashtags": ["AI", "效率"],
        "cta": "关注我",
        "tone": "专业",
        "cover_prompt": "极简封面",
        "image_prompts": ["图1prompt", "图2prompt"],
        "image_count": 2,
        "layout_style": "grid",
    }


def test_sample_to_jsonl_input_contains_content_snapshot() -> None:
    """SFT input shows the evaluated content (title/body/tags/visual), not empty."""
    record = sample_to_jsonl(_sample(snapshot=_snapshot()))
    assert record["input"]
    assert "AI效率指南" in record["input"]
    assert "正文内容" in record["input"]
    assert "AI, 效率" in record["input"]
    assert "极简封面" in record["input"]
    assert "图1：图1prompt" in record["input"]
    assert "metadata" not in record or record["metadata"].get("incomplete") is not True


def test_sample_to_jsonl_output_contains_full_judgment() -> None:
    """Output includes scores + bias_severity + rationale + issues + decision."""
    record = sample_to_jsonl(_sample(snapshot=_snapshot()))
    out = record["output"]
    assert "综合分：78.5" in out
    assert "决策：needs_revision" in out
    assert "copywriting：80" in out
    assert "bias_severity=75" in out  # PR#159 field reaches training data
    assert "结构清晰" in out  # rationale
    assert "标题弱" in out  # issue
    assert "偏倚预警：检测到偏倚" in out


def test_sample_to_jsonl_legacy_sample_marked_incomplete() -> None:
    """Samples without content_snapshot get input='' and incomplete metadata."""
    record = sample_to_jsonl(_sample(snapshot=None))
    assert record["input"] == ""
    assert record["metadata"]["incomplete"] is True
    # output still rendered from dims so the record isn't useless for inspection
    assert "综合分：78.5" in record["output"]


def test_sample_to_jsonl_engagement_attached_as_metadata() -> None:
    """Back-filled engagement is metadata, not part of SFT target."""
    record = sample_to_jsonl(_sample(snapshot=_snapshot(), engagement={"views": 1000, "likes": 50}))
    assert record["metadata"]["engagement"] == {"views": 1000, "likes": 50}
    assert "1000" not in record["output"]  # engagement not in target


def test_sample_to_jsonl_bias_warning_reconstructed_from_severity() -> None:
    """bias_warning is not a DB column — reconstructed from bias_check severity
    when issues are empty (mirrors EvaluatorAgent derivation)."""
    dims = [
        {
            "dimension": "bias_check",
            "score": 60,
            "bias_severity": 75,
            "issues": [],
            "is_blocking": False,
        }
    ]
    record = sample_to_jsonl(_sample(snapshot=_snapshot(), dims=dims))
    out = record["output"]
    assert "偏倚预警：检测到面板对 AI 生成内容可能过度宽容" in out


def test_sample_to_jsonl_no_bias_warning_when_clean() -> None:
    """No bias_warning line when bias_check has no issues and low severity."""
    dims = [
        {
            "dimension": "bias_check",
            "score": 90,
            "bias_severity": 20,
            "issues": [],
            "is_blocking": False,
        }
    ]
    record = sample_to_jsonl(_sample(snapshot=_snapshot(), dims=dims))
    assert "偏倚预警" not in record["output"]
