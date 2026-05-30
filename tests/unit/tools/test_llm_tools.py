"""Unit tests for LLM-enhanced tools.

Tests the three-tier fallback pattern and output structure validation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.content import (
    hashtag_researcher,
    image_prompt_generator,
    title_generator,
)
from backend.tools.scheduling import timing_optimizer

# ── hashtag_researcher tests ──

@pytest.mark.asyncio
async def test_hashtag_researcher_llm_success():
    """LLM returns structured hashtag analysis"""
    with patch("backend.tools.content.hashtag_researcher._load_prompt", return_value={"system": "test", "user_template": "test"}):
        with patch("backend.tools.content.hashtag_researcher.get_llm_service") as mock_service:
            mock_llm = MagicMock()
            mock_llm.enrich_with_llm = AsyncMock(return_value={
                "hashtags": [
                    {"tag": "#美食", "heat_score": 85, "competition": "high", "traffic_potential": "high", "recommended_position": "primary"},
                    {"tag": "#美食推荐", "heat_score": 70, "competition": "medium", "traffic_potential": "medium", "recommended_position": "secondary"},
                ]
            })
            mock_service.return_value = mock_llm

            result = await hashtag_researcher.ainvoke({"keyword": "美食", "limit": 2})

            assert len(result) == 2
            assert result[0]["tag"] == "#美食"
            assert result[0]["heat_score"] == 85
            assert result[0]["competition"] == "high"


@pytest.mark.asyncio
async def test_hashtag_researcher_fallback_on_error():
    """Uses algorithmic fallback when LLM fails"""
    with patch("backend.tools.content.hashtag_researcher.get_llm_service") as mock_service:
        mock_llm = MagicMock()
        mock_llm.enrich_with_llm = AsyncMock(side_effect=Exception("LLM error"))
        mock_service.return_value = mock_llm

        result = await hashtag_researcher.ainvoke({"keyword": "美食", "limit": 5})

        # Should return algorithmic fallback
        assert len(result) > 0
        assert result[0]["tag"] == "#美食"
        assert result[0]["heat_score"] == 50
        assert result[0]["competition"] == "medium"


@pytest.mark.asyncio
async def test_hashtag_researcher_default_fallback():
    """Returns default hashtags when everything fails"""
    # Force both LLM and fallback to fail
    with patch("backend.tools.content.hashtag_researcher._load_prompt") as mock_load:
        mock_load.side_effect = Exception("No prompt file")

        result = await hashtag_researcher.ainvoke({"keyword": "美食", "limit": 5})

        # Should still return some hashtags (never fails)
        assert len(result) > 0


# ── title_generator tests ──

@pytest.mark.asyncio
async def test_title_generator_llm_success():
    """LLM returns creative titles"""
    with patch("backend.tools.content.title_generator._load_prompt", return_value={"system": "test", "user_template": "test"}):
        with patch("backend.tools.content.title_generator.get_llm_service") as mock_service:
            mock_llm = MagicMock()
            mock_llm.enrich_with_llm = AsyncMock(return_value={
                "titles": [
                    {"title": "🔥 美食必看！超实用攻略", "style": "attractive", "hook_type": "数字钩子", "predicted_engagement": "high", "reasoning": "emoji开头吸引眼球"},
                    {"title": "美食干货合集｜建议收藏", "style": "value", "hook_type": "价值钩子", "predicted_engagement": "medium", "reasoning": "强调实用性"},
                ]
            })
            mock_service.return_value = mock_llm

            result = await title_generator.ainvoke({"topic": "美食", "style": "attractive", "count": 2})

            assert len(result) == 2
            assert result[0]["title"] == "🔥 美食必看！超实用攻略"
            assert result[0]["style"] == "attractive"
            assert result[0]["hook_type"] == "数字钩子"


@pytest.mark.asyncio
async def test_title_generator_fallback_on_error():
    """Uses algorithmic fallback when LLM fails"""
    with patch("backend.tools.content.title_generator.get_llm_service") as mock_service:
        mock_llm = MagicMock()
        mock_llm.enrich_with_llm = AsyncMock(side_effect=Exception("LLM error"))
        mock_service.return_value = mock_llm

        result = await title_generator.ainvoke({"topic": "美食", "style": "attractive", "count": 3})

        # Should return algorithmic fallback templates
        assert len(result) == 3
        assert result[0]["style"] == "attractive"
        assert "美食" in result[0]["title"]


@pytest.mark.asyncio
async def test_title_generator_value_style():
    """Generates value-style titles"""
    with patch("backend.tools.content.title_generator.get_llm_service") as mock_service:
        mock_llm = MagicMock()
        mock_llm.enrich_with_llm = AsyncMock(return_value={
            "titles": [
                {"title": "美食干货合集｜建议收藏", "style": "value", "hook_type": "价值钩子", "predicted_engagement": "medium", "reasoning": "强调实用性"},
            ]
        })
        mock_service.return_value = mock_llm

        result = await title_generator.ainvoke({"topic": "美食", "style": "value", "count": 1})

        assert result[0]["style"] == "value"


# ── image_prompt_generator tests ──

@pytest.mark.asyncio
async def test_image_prompt_generator_llm_success():
    """LLM returns visual prompts"""
    with patch("backend.tools.content.image_prompt._load_prompt", return_value={"system": "test", "user_template": "test"}):
        with patch("backend.tools.content.image_prompt.get_llm_service") as mock_service:
            mock_llm = MagicMock()
            mock_llm.enrich_with_llm = AsyncMock(return_value={
                "prompts": [
                    {
                        "prompt": "A modern style food scene featuring 美食, soft lighting, pastel accents",
                        "prompt_type": "cover",
                        "aspect_ratio": "3:4",
                        "key_elements": ["美食", "modern", "food"],
                        "color_suggestions": ["#FFE4E1", "#F5F5F5"],
                        "negative_prompt": "blur, low quality",
                    },
                ]
            })
            mock_service.return_value = mock_llm

            result = await image_prompt_generator.ainvoke({"topic": "美食", "style": "modern", "count": 1})

            assert len(result) == 1
            assert result[0]["prompt_type"] == "cover"
            assert result[0]["aspect_ratio"] == "3:4"
            assert "美食" in result[0]["prompt"]
            assert result[0]["negative_prompt"] == "blur, low quality"


@pytest.mark.asyncio
async def test_image_prompt_generator_fallback_on_error():
    """Uses algorithmic fallback when LLM fails"""
    with patch("backend.tools.content.image_prompt.get_llm_service") as mock_service:
        mock_llm = MagicMock()
        mock_llm.enrich_with_llm = AsyncMock(side_effect=Exception("LLM error"))
        mock_service.return_value = mock_llm

        result = await image_prompt_generator.ainvoke({"topic": "美食", "style": "modern", "count": 2})

        # Should return algorithmic fallback prompts
        assert len(result) == 2
        assert result[0]["prompt_type"] in ["cover", "carousel", "story"]
        assert result[0]["aspect_ratio"] in ["3:4", "1:1", "16:9"]


@pytest.mark.asyncio
async def test_image_prompt_generator_vintage_style():
    """Generates vintage style prompts"""
    with patch("backend.tools.content.image_prompt.get_llm_service") as mock_service:
        mock_llm = MagicMock()
        mock_llm.enrich_with_llm = AsyncMock(return_value={
            "prompts": [
                {
                    "prompt": "Vintage style food photography, warm tones",
                    "prompt_type": "cover",
                    "aspect_ratio": "3:4",
                    "key_elements": ["美食", "vintage"],
                    "color_suggestions": ["#D4A574", "#8B4513"],
                    "negative_prompt": "modern elements",
                },
            ]
        })
        mock_service.return_value = mock_llm

        result = await image_prompt_generator.ainvoke({"topic": "美食", "style": "vintage", "count": 1})

        assert len(result) == 1
        assert "vintage" in result[0]["key_elements"]


# ── timing_optimizer tests ──

@pytest.mark.asyncio
async def test_timing_optimizer_llm_success():
    """LLM returns timing analysis"""
    with patch("backend.tools.scheduling.calendar._load_prompt", return_value={"system": "test", "user_template": "test"}):
        with patch("backend.tools.scheduling.calendar.get_llm_service") as mock_service:
            mock_llm = MagicMock()
            mock_llm.enrich_with_llm = AsyncMock(return_value={
                "best_times": ["08:00", "12:00", "18:00"],
                "best_days": ["周三", "周五", "周六"],
                "reasoning": {
                    "best_times_reason": "饭点前后是美食内容高峰浏览时段",
                    "best_days_reason": "周末空闲时间多",
                },
                "audience_active_pattern": "上班族在早晚和午休时段活跃",
                "niche_specific_insights": "美食类适合饭点发布",
                "avoid_times": ["14:00", "15:00"],
                "avoid_reasons": "下午工作时段流量较低",
            })
            mock_service.return_value = mock_llm

            result = await timing_optimizer.ainvoke({"niche": "美食", "target_audience": "上班族"})

            assert result["best_times"] == ["08:00", "12:00", "18:00"]
            assert result["best_days"] == ["周三", "周五", "周六"]
            assert result["avoid_times"] == ["14:00", "15:00"]
            assert "饭点" in result["reasoning"]["best_times_reason"]


@pytest.mark.asyncio
async def test_timing_optimizer_fallback_on_error():
    """Uses algorithmic fallback when LLM fails"""
    with patch("backend.tools.scheduling.calendar.get_llm_service") as mock_service:
        mock_llm = MagicMock()
        mock_llm.enrich_with_llm = AsyncMock(side_effect=Exception("LLM error"))
        mock_service.return_value = mock_llm

        result = await timing_optimizer.ainvoke({"niche": "美食", "target_audience": "上班族"})

        # Should return niche-specific algorithmic fallback
        assert result["best_times"] == ["07:00", "11:30", "17:30", "21:00"]
        assert result["best_days"] == ["周三", "周五", "周六"]
        assert "饭点" in result["niche_specific_insights"]


@pytest.mark.asyncio
async def test_timing_optimizer_unknown_niche():
    """Returns default pattern for unknown niche"""
    with patch("backend.tools.scheduling.calendar.get_llm_service") as mock_service:
        mock_llm = MagicMock()
        mock_llm.enrich_with_llm = AsyncMock(side_effect=Exception("LLM error"))
        mock_service.return_value = mock_llm

        result = await timing_optimizer.ainvoke({"niche": "未知领域", "target_audience": "大众"})

        # Should return default pattern
        assert result["best_times"] == ["08:00", "12:00", "18:00", "21:00"]
        assert result["best_days"] == ["周三", "周五", "周六"]


@pytest.mark.asyncio
async def test_timing_optimizer_niche_matching():
    """Correctly matches niche keywords"""
    with patch("backend.tools.scheduling.calendar.get_llm_service") as mock_service:
        mock_llm = MagicMock()
        mock_llm.enrich_with_llm = AsyncMock(side_effect=Exception("LLM error"))
        mock_service.return_value = mock_llm

        # Test "美食家常菜" matches "美食" pattern
        result = await timing_optimizer.ainvoke({"niche": "美食家常菜", "target_audience": "家庭主妇"})

        assert "饭点" in result["niche_specific_insights"]

        # Test "穿搭分享" matches "穿搭" pattern
        result2 = await timing_optimizer.ainvoke({"niche": "穿搭分享", "target_audience": "年轻女性"})

        assert "睡前" in result2["niche_specific_insights"] or "周末" in result2["reasoning"]["best_days_reason"]


# ── Tool Registry tests ──

def test_tool_registry_has_content_tools():
    """Tool registry contains content tools"""
    from backend.tools.registry import ToolRegistry

    ToolRegistry.register_content_tools()
    names = ToolRegistry.available_tool_names()

    assert "hashtag_researcher" in names
    assert "title_generator" in names
    assert "image_prompt_generator" in names


def test_tool_registry_has_scheduling_tools():
    """Tool registry contains scheduling tools."""
    from backend.tools.registry import ToolRegistry

    ToolRegistry.register_scheduling_tools()
    names = ToolRegistry.available_tool_names()

    assert "timing_optimizer" in names


def test_content_strategist_has_timing_optimizer():
    """ContentStrategist agent has timing_optimizer tool"""
    from backend.tools.registry import ToolRegistry

    ToolRegistry.register_scheduling_tools()
    tools = ToolRegistry.get_tools_for_agent("content_strategist")
    tool_names = [t.name for t in tools]

    assert "timing_optimizer" in tool_names


def test_copywriter_has_content_tools():
    """Copywriter agent has content tools"""
    from backend.tools.registry import ToolRegistry

    ToolRegistry.register_content_tools()
    tools = ToolRegistry.get_tools_for_agent("copywriter")
    tool_names = [t.name for t in tools]

    assert "hashtag_researcher" in tool_names
    assert "title_generator" in tool_names


def test_visual_designer_has_image_prompt():
    """VisualDesigner agent has image_prompt_generator tool"""
    from backend.tools.registry import ToolRegistry

    ToolRegistry.register_content_tools()
    tools = ToolRegistry.get_tools_for_agent("visual_designer")
    tool_names = [t.name for t in tools]

    assert "image_prompt_generator" in tool_names