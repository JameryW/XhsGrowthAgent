"""Tests for optimization-related state models."""

import pytest
from xhs_growth.state.substates import (
    DraftContent,
    ViralPost,
    GapItem,
    SuggestionItem,
    OptimizationAnalysis,
    ContentVersion,
)


def test_draft_content_defaults():
    """DraftContent should have optional fields."""
    draft: DraftContent = {
        "text": "原始文案",
        "images": [],
        "provided_at": "2026-05-26T10:00:00",
    }
    assert draft["text"] == "原始文案"
    assert draft["images"] == []
    assert "title" not in draft  # optional


def test_viral_post_structure():
    """ViralPost should contain all required fields."""
    viral: ViralPost = {
        "note_id": "abc123",
        "title": "爆款标题",
        "body": "正文内容",
        "hashtags": ["#穿搭", "#OOTD"],
        "cover_url": "https://example.com/cover.jpg",
        "image_urls": ["https://example.com/1.jpg"],
        "likes": 10000,
        "collects": 5000,
        "comments": 200,
        "engagement_rate": 0.15,
        "visual_style": "vibrant",
        "color_palette": {"primary": "#FF5733", "secondary": "#33FF57"},
    }
    assert viral["note_id"] == "abc123"
    assert viral["engagement_rate"] == 0.15


def test_gap_item_severity():
    """GapItem severity should be one of high/medium/low."""
    gap: GapItem = {
        "dimension": "title",
        "description": "标题缺乏吸引力",
        "severity": "high",
    }
    assert gap["severity"] in ["high", "medium", "low"]


def test_suggestion_item_priority():
    """SuggestionItem priority should be an integer."""
    suggestion: SuggestionItem = {
        "dimension": "title",
        "action": "添加情感元素",
        "reasoning": "爆款标题多用情感词",
        "priority": 1,
    }
    assert isinstance(suggestion["priority"], int)
    assert suggestion["dimension"] == "title"


def test_optimization_analysis_structure():
    """OptimizationAnalysis should contain lists."""
    analysis: OptimizationAnalysis = {
        "gaps": [],
        "suggestions": [],
        "viral_patterns": ["情感共鸣", "视觉冲击"],
    }
    assert isinstance(analysis["gaps"], list)
    assert isinstance(analysis["suggestions"], list)
    assert len(analysis["viral_patterns"]) == 2


def test_content_version_predicted_score():
    """ContentVersion predicted_score should be 0-1 range."""
    version: ContentVersion = {
        "version_id": "A",
        "title": "优化标题",
        "body": "优化正文",
        "hashtags": ["#优化"],
        "image_prompts": ["prompt1"],
        "style_suggestion": "minimal",
        "changes_summary": "增加了情感元素",
        "predicted_score": 0.85,
    }
    assert 0 <= version["predicted_score"] <= 1
    assert version["version_id"] == "A"