"""Tests for ContentAnalyzerAgent."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_analyzer import ContentAnalyzerAgent

# ponytail: shared mock LLM JSON — empty optimization result, repeated across tests
_EMPTY_OPT_JSON = '{"optimization_analysis": {"gaps": [], "suggestions": [], "viral_patterns": []}}'
_GAPPED_OPT_JSON = (
    '{"optimization_analysis": {"gaps": [{"dimension": "标题", '
    '"description": "草稿标题缺乏钩子元素", "severity": "high"}], '
    '"suggestions": [{"dimension": "标题", "action": "添加数字钩子", '
    '"reasoning": "爆款笔记标题包含数字", "priority": 1}], '
    '"viral_patterns": ["标题包含数字钩子"]}}'
)


@pytest.fixture
def mock_state_with_draft_and_viral():
    """Mock state with draft content and viral posts."""
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "今天分享一个很实用的穿搭技巧，希望对大家有帮助。",
            "images": [],
            "title": "穿搭技巧分享",
            "hashtags": ["#穿搭", "#时尚"],
            "provided_at": "2026-05-26T10:00:00",
        },
        "viral_posts": [
            {
                "note_id": "abc123",
                "title": "3个穿搭公式让你秒变时尚博主！",
                "body": "姐妹们！今天分享3个万能穿搭公式，学会就能轻松提升时尚感...",
                "hashtags": ["#穿搭", "#时尚", "#OOTD"],
                "likes": 10000,
                "collects": 5000,
                "comments": 200,
                "engagement_rate": 0.15,
                "visual_style": "vibrant",
                "color_palette": {"primary": "#FF6B6B", "secondary": "#4ECDC4"},
            }
        ],
    }


@pytest.fixture
def mock_state_no_draft():
    """Mock state without draft content."""
    return {
        "account_id": "test_account",
        "viral_posts": [
            {
                "note_id": "abc123",
                "title": "爆款标题",
                "body": "爆款正文",
                "hashtags": ["#爆款"],
                "likes": 10000,
            }
        ],
    }


@pytest.fixture
def mock_state_no_viral():
    """Mock state without viral posts."""
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "title": "测试标题",
        },
    }


@pytest.fixture
def mock_store():
    """Mock BaseStore."""
    store = MagicMock()
    store.asearch = AsyncMock(return_value=[])
    return store


@pytest.mark.asyncio
async def test_content_analyzer_no_draft(mock_state_no_draft, mock_store):
    """Should skip analysis when no draft provided."""
    agent = ContentAnalyzerAgent()
    result = await agent.execute(mock_state_no_draft, mock_store)
    assert result.get("skip_analysis")


@pytest.mark.asyncio
async def test_content_analyzer_no_viral(mock_state_no_viral, mock_store):
    """Should analyze draft against brief/strategy context when no viral posts provided."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=_EMPTY_OPT_JSON))

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state_no_viral, mock_store)
    assert "optimization_analysis" in result


@pytest.mark.asyncio
async def test_content_analyzer_with_draft_and_viral(mock_state_with_draft_and_viral, mock_store):
    """Should analyze gap between draft and viral posts."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=_GAPPED_OPT_JSON))

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state_with_draft_and_viral, mock_store)

    assert "optimization_analysis" in result
    assert "gaps" in result["optimization_analysis"]
    assert "suggestions" in result["optimization_analysis"]
    assert "viral_patterns" in result["optimization_analysis"]


@pytest.mark.asyncio
async def test_content_analyzer_builds_viral_summary(mock_state_with_draft_and_viral, mock_store):
    """Should build viral summary JSON correctly."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=_EMPTY_OPT_JSON))

    with patch.object(agent, "_model", mock_model):
        await agent.execute(mock_state_with_draft_and_viral, mock_store)

    # Verify viral summary was built correctly
    viral_summary = agent._build_viral_summary(mock_state_with_draft_and_viral["viral_posts"])
    assert "abc123" not in viral_summary  # note_id should not be in summary
    assert "likes" in viral_summary
    assert "engagement_rate" in viral_summary


@pytest.mark.asyncio
async def test_content_analyzer_phase_update(mock_state_with_draft_and_viral, mock_store):
    """Should update phase to CREATING."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=_EMPTY_OPT_JSON))

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state_with_draft_and_viral, mock_store)

    assert result.get("phase") is not None


@pytest.mark.asyncio
async def test_content_analyzer_empty_viral_posts(mock_store):
    """Should analyze draft against brief/strategy context when viral_posts is empty list."""
    agent = ContentAnalyzerAgent()

    state_with_empty_viral = {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "title": "测试标题",
        },
        "viral_posts": [],  # Empty list
    }

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=_EMPTY_OPT_JSON))

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(state_with_empty_viral, mock_store)
    assert "optimization_analysis" in result


@pytest.mark.asyncio
async def test_content_analyzer_handles_invalid_json(mock_state_with_draft_and_viral, mock_store):
    """Should return default structure when LLM returns invalid JSON."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content="Invalid response without JSON"))

    with patch.object(agent, "_model", mock_model):
        result = await agent.execute(mock_state_with_draft_and_viral, mock_store)

    assert "optimization_analysis" in result
    assert result["optimization_analysis"]["gaps"] == []
    assert result["optimization_analysis"]["suggestions"] == []


@pytest.fixture
def mock_state_with_many_viral():
    """Mock state with many viral posts (more than 5)."""
    viral_posts = []
    for i in range(10):
        viral_posts.append(
            {
                "note_id": f"note_{i}",
                "title": f"爆款标题 {i}",
                "body": f"爆款正文 {i}",
                "hashtags": ["#爆款"],
                "likes": 10000 + i * 100,
                "collects": 5000,
                "comments": 200,
                "engagement_rate": 0.15,
                "visual_style": "minimal",
                "color_palette": {"primary": "#ffffff"},
            }
        )
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "title": "测试标题",
        },
        "viral_posts": viral_posts,
    }


@pytest.mark.asyncio
async def test_content_analyzer_limits_viral_posts(mock_state_with_many_viral, mock_store):
    """Should limit viral summary to 5 posts."""
    agent = ContentAnalyzerAgent()

    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content=_EMPTY_OPT_JSON))

    with patch.object(agent, "_model", mock_model):
        await agent.execute(mock_state_with_many_viral, mock_store)

    viral_summary = agent._build_viral_summary(mock_state_with_many_viral["viral_posts"])
    summary_data = json.loads(viral_summary)
    assert len(summary_data) == 5  # Should only include 5 posts


class _AnsweringModel:
    """Answers the same text every time; a real object, not a ``MagicMock``.

    A mock invents ``with_structured_output``/``bind`` and answers from
    machinery that does not exist, which is how a chain gets certified against
    a level it never ran.
    """

    def __init__(self, content: str) -> None:
        self.content = content

    def bind(self, **kwargs):
        return self

    def with_structured_output(self, *args, **kwargs):
        return self

    async def ainvoke(self, messages, **kwargs):
        return SimpleNamespace(content=self.content)


class _DeadModel:
    """Every call raises the same exception instance — an endpoint that is down."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def ainvoke(self, *args, **kwargs):
        raise self.error


class TestStructuredOptimizationAnalysis:
    """S2b: same two dispositions as ``analyst``, and the same reason for them.

    "Asked and got nothing usable" is a gap analysis that could not be produced
    — an empty one is the honest record. An unreachable LLM is not that, and
    filing the same empty structure under it would turn an outage into "this
    draft has no gaps".
    """

    @pytest.mark.asyncio
    async def test_a_suggestion_keeps_the_priority_its_consumer_reads(
        self, mock_state_with_draft_and_viral, mock_store
    ):
        """``version_generator`` renders ``[P{priority}]`` into the next prompt;
        dropping the field in migration would silently renumber every
        suggestion to the consumer's fallback of 3."""
        agent = ContentAnalyzerAgent()

        with patch.object(agent, "_model", _AnsweringModel(_GAPPED_OPT_JSON)):
            result = await agent.execute(mock_state_with_draft_and_viral, mock_store)

        suggestion = result["optimization_analysis"]["suggestions"][0]
        assert suggestion["priority"] == 1
        assert suggestion["action"] == "添加数字钩子"

    @pytest.mark.asyncio
    async def test_an_answered_but_unusable_report_is_the_declared_empty_shape(
        self, mock_state_with_draft_and_viral, mock_store
    ):
        """A bare array is not the envelope at any level, so the chain exhausts
        itself. The three keys still come out — from the normaliser, which is
        now the only place that says what an empty analysis looks like."""
        agent = ContentAnalyzerAgent()

        with patch.object(agent, "_model", _AnsweringModel('[{"dimension": "标题"}]')):
            result = await agent.execute(mock_state_with_draft_and_viral, mock_store)

        assert result["optimization_analysis"] == {
            "gaps": [],
            "suggestions": [],
            "viral_patterns": [],
        }

    @pytest.mark.asyncio
    async def test_an_unreachable_model_is_not_recorded_as_no_gaps(
        self, mock_state_with_draft_and_viral, mock_store
    ):
        agent = ContentAnalyzerAgent()
        boom = RuntimeError("LLM unavailable")
        agent._model = _DeadModel(boom)

        with pytest.raises(RuntimeError) as info:
            await agent.execute(mock_state_with_draft_and_viral, mock_store)

        assert info.value is boom
