"""Unit tests for de_ai_taste polish tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.content.de_ai_taste import algorithmic_de_ai, de_ai_taste, polish_copy


def test_algorithmic_de_ai_scrubs_common_cliches():
    raw = {
        "selected_title": "在当今社会 好物分享",
        "body_text": (
            "在当今社会，值得一提的是这款产品能够赋能你的生活。综上所述，家人们一定要试试。"
        ),
        "cta": "欢迎在评论区留言交流。",
        "tone": "专业",
    }
    out = algorithmic_de_ai(raw)
    assert "在当今社会" not in out["body_text"]
    assert "值得一提的是" not in out["body_text"]
    assert "赋能" not in out["body_text"]
    assert "家人们" not in out["body_text"]
    assert out["polished"] is True
    assert out["method"] == "algorithmic"
    assert out["changes"]


def test_algorithmic_de_ai_preserves_clean_copy():
    raw = {
        "selected_title": "用了一周真实感受",
        "body_text": "自己用下来：开机快，续航也稳。适合通勤摸鱼写文档。",
        "cta": "你用的哪款？评论区聊聊",
    }
    out = algorithmic_de_ai(raw)
    assert out["body_text"] == raw["body_text"]
    assert out["selected_title"] == raw["selected_title"]


@pytest.mark.asyncio
async def test_polish_copy_llm_success():
    llm_result = {
        "selected_title": "用了一周，这些点真香",
        "body_text": "自己测下来续航稳，写代码不卡。",
        "cta": "你也用过的话评论区说一声",
        "tone": "口语",
        "changes": ["去掉套话"],
        "ai_signals_found": ["综上所述"],
        "polished": True,
    }
    mock_service = MagicMock()
    mock_service.enrich_with_llm = AsyncMock(return_value=llm_result)

    with (
        patch("backend.tools.content.de_ai_taste._load_prompt", return_value={"system": "x"}),
        patch("backend.tools.content.de_ai_taste.get_llm_service", return_value=mock_service),
    ):
        out = await polish_copy(
            selected_title="测试",
            body_text="综上所述这是AI味正文",
            use_llm=True,
        )

    assert out["method"] == "llm"
    assert out["selected_title"] == "用了一周，这些点真香"
    assert out["body_text"] == "自己测下来续航稳，写代码不卡。"
    assert out["changes"] == ["去掉套话"]


@pytest.mark.asyncio
async def test_polish_copy_falls_back_on_llm_error():
    mock_service = MagicMock()
    mock_service.enrich_with_llm = AsyncMock(side_effect=RuntimeError("llm down"))

    with (
        patch("backend.tools.content.de_ai_taste._load_prompt", return_value={"system": "x"}),
        patch("backend.tools.content.de_ai_taste.get_llm_service", return_value=mock_service),
    ):
        out = await polish_copy(
            selected_title="t",
            body_text="在当今社会，赋能效率。",
            use_llm=True,
        )

    assert out["method"] == "algorithmic"
    assert "赋能" not in out["body_text"]


@pytest.mark.asyncio
async def test_polish_copy_use_llm_false_skips_model():
    out = await polish_copy(
        selected_title="t",
        body_text="值得一提的是很好用",
        use_llm=False,
    )
    assert out["method"] == "algorithmic"
    assert "值得一提的是" not in out["body_text"]


@pytest.mark.asyncio
async def test_de_ai_taste_tool_ainvoke():
    with patch(
        "backend.tools.content.de_ai_taste.polish_copy",
        new=AsyncMock(
            return_value={
                "selected_title": "标题",
                "body_text": "正文",
                "cta": "",
                "tone": "口语",
                "changes": [],
                "ai_signals_found": [],
                "polished": False,
                "method": "llm",
            }
        ),
    ) as mock_polish:
        result = await de_ai_taste.ainvoke(
            {
                "body_text": "在当今社会很好",
                "selected_title": "标题",
                "revision_hints": "减少AI味；加真实细节",
            }
        )
    assert result["body_text"] == "正文"
    mock_polish.assert_awaited_once()
    kwargs = mock_polish.await_args.kwargs
    assert "减少AI味" in kwargs["revision_hints"]
