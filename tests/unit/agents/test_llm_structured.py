"""Tests for ``BaseAgent._llm_structured`` — the chain and its two failure kinds.

The behaviour that matters most here is not "does it retry" but **which kinds of
bad answer are allowed to become a result**. A malformed payload never may; a
well-formed payload a validator refuses may, but only when the caller says the
check is advisory. Both are pinned below, because plumbing an advisory nudge
through this method is exactly how it goes silent.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from backend.agents.base import BaseAgent
from backend.config.models import ModelConfig, ModelProvider, TaskType
from backend.models.structured import StructuredMode, StructuredOutputError

_REFUSAL = "topic 不在候选话题内，必须从中选取一个"


class _Plan(BaseModel):
    topic: str
    score: int = 0


class _Agent(BaseAgent):
    """A concrete agent with no execute() body — the methods under test are the
    LLM plumbing, which does not need a graph to exercise."""

    task_type = TaskType.ROUTING
    agent_name = "structured_test"

    async def execute(self, state: Any, store: Any) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


def _with_provider(provider: ModelProvider):
    """Pin the routed provider so the test states which level it starts at."""
    return patch(
        "backend.config.models.get_model_config",
        return_value=ModelConfig(provider=provider, model_name="test-model"),
    )


def _text_response(payload: str) -> MagicMock:
    response = MagicMock()
    response.content = payload
    return response


class _PlainModel:
    """A plain chat model — no native structured output, no ``bind``.

    Deliberately a real object rather than a ``MagicMock``: a MagicMock
    *invents* ``with_structured_output`` and ``bind`` on attribute access, so a
    level that cannot actually be called would look callable and return another
    MagicMock instead of failing. The chain has to survive the absence, which
    only a model that genuinely lacks the attributes can demonstrate.
    """

    def __init__(self, *payloads: str) -> None:
        self._responses = list(payloads)
        self.calls: list[list[Any]] = []

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> MagicMock:
        self.calls.append(messages)
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return _text_response(self._responses[index])


def _text_agent(*payloads: str) -> tuple[_Agent, list[list[Any]]]:
    """The common case: a model that is mocked but *does* speak text."""
    agent = _Agent()
    calls: list[list[Any]] = []
    responses = [_text_response(payload) for payload in payloads]

    async def _ainvoke(messages, **kwargs):
        calls.append(messages)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    model = MagicMock()
    model.ainvoke = _ainvoke
    agent._model = model
    return agent, calls


def _messages() -> list[Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    return [SystemMessage(content="系统提示"), HumanMessage(content="用户输入")]


class TestTheChainPicksTheRightCallShape:
    @pytest.mark.asyncio
    async def test_prompted_asks_for_the_schema_in_a_runtime_message(self):
        agent, calls = _text_agent('{"topic": "美食探店"}')
        with _with_provider(ModelProvider.XUNFEI):
            plan = await agent._llm_structured(_messages(), _Plan)

        assert plan == _Plan(topic="美食探店")
        # No native channel is exercised at this level.
        agent.model.with_structured_output.assert_not_called()
        # …and the shape is asked for in the *conversation*, never by mutating
        # the compiled system prompt (which P1b measures against a snapshot).
        assert calls[0][0].content == "系统提示"
        assert "JSON" in calls[0][-1].content

    @pytest.mark.asyncio
    async def test_json_object_binds_response_format(self):
        agent = _Agent()
        bound = MagicMock()
        bound.ainvoke = AsyncMock(return_value=_text_response('{"topic": "x"}'))
        agent._model = MagicMock()
        agent._model.bind = MagicMock(return_value=bound)

        with _with_provider(ModelProvider.DEEPSEEK):
            plan = await agent._llm_structured(_messages(), _Plan)

        assert plan == _Plan(topic="x")
        agent.model.bind.assert_called_once_with(response_format={"type": "json_object"})

    @pytest.mark.asyncio
    async def test_native_schema_reads_the_parsed_field(self):
        parsed = _Plan(topic="native", score=4)
        runnable = MagicMock()
        runnable.ainvoke = AsyncMock(
            return_value={"raw": _text_response("{}"), "parsed": parsed, "parsing_error": None}
        )
        agent = _Agent()
        agent._model = MagicMock()
        agent._model.with_structured_output = MagicMock(return_value=runnable)

        with _with_provider(ModelProvider.OPENAI):
            plan = await agent._llm_structured(_messages(), _Plan)

        assert plan == parsed
        agent.model.with_structured_output.assert_called_once_with(_Plan, include_raw=True)


class TestDegradation:
    @pytest.mark.asyncio
    async def test_a_level_whose_call_cannot_be_made_hands_over_to_the_next(self):
        """A plain-text model has no ``with_structured_output``; the chain must
        survive that absence rather than propagate the AttributeError."""
        agent = _Agent()
        agent._model = _PlainModel('{"topic": "fallback"}')

        with _with_provider(ModelProvider.OPENAI):
            plan = await agent._llm_structured(_messages(), _Plan)

        assert plan == _Plan(topic="fallback")

    @pytest.mark.asyncio
    async def test_a_native_parsing_error_degrades_instead_of_failing(self):
        native = MagicMock()
        native.ainvoke = AsyncMock(
            return_value={"raw": None, "parsed": None, "parsing_error": ValueError("boom")}
        )
        bound = MagicMock()
        bound.ainvoke = AsyncMock(return_value=_text_response('{"topic": "via-json-object"}'))
        agent = _Agent()
        agent._model = MagicMock()
        agent._model.with_structured_output = MagicMock(return_value=native)
        agent._model.bind = MagicMock(return_value=bound)

        with _with_provider(ModelProvider.OPENAI):
            plan = await agent._llm_structured(_messages(), _Plan)

        assert plan == _Plan(topic="via-json-object")
        native.ainvoke.assert_awaited_once()
        bound.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_an_exhausted_chain_reports_one_attempt_per_level(self):
        agent = _Agent()
        agent._model = _PlainModel("{}")

        with _with_provider(ModelProvider.OPENAI), pytest.raises(StructuredOutputError) as info:
            await agent._llm_structured(_messages(), _Plan)

        levels = [level for level, _ in info.value.attempts]
        # The two levels that cannot be called are recorded once each — a retry
        # would fail identically — while the level that *can* be called spends
        # its whole budget before giving up.
        assert levels == [
            StructuredMode.NATIVE_SCHEMA,
            StructuredMode.JSON_OBJECT,
            StructuredMode.PROMPTED,
            StructuredMode.PROMPTED,
        ]
        for level, _ in info.value.attempts:
            assert level.value in str(info.value)


class TestCorrectionRetry:
    @pytest.mark.asyncio
    async def test_the_correction_is_an_appended_framed_message(self):
        agent, calls = _text_agent('{"topic": "drifted"}', '{"topic": "fixed"}')
        seen: list[str] = []

        def _validator(plan: _Plan) -> str | None:
            seen.append(plan.topic)
            return None if plan.topic == "fixed" else _REFUSAL

        with _with_provider(ModelProvider.XUNFEI):
            plan = await agent._llm_structured(_messages(), _Plan, validator=_validator)

        assert plan == _Plan(topic="fixed")
        assert seen == ["drifted", "fixed"]
        assert len(calls) == 2
        # The first attempt carries the two original messages plus the schema
        # hint; the retry adds exactly one framed correction.
        assert len(calls[0]) == 3
        assert len(calls[1]) == 4
        corrections = [m for m in calls[1] if "【纠偏】" in str(m.content)]
        assert len(corrections) == 1
        assert _REFUSAL in str(corrections[0].content)
        assert not [m for m in calls[0] if "【纠偏】" in str(m.content)]

    @pytest.mark.asyncio
    async def test_the_callers_message_list_is_not_mutated(self):
        """Corrections accumulate on a copy — a caller that reuses its message
        list (or a shared compiled prompt) must not inherit retry history."""
        agent, _ = _text_agent('{"topic": "drifted"}', '{"topic": "fixed"}')
        messages = _messages()

        with _with_provider(ModelProvider.XUNFEI):
            await agent._llm_structured(
                messages, _Plan, validator=lambda plan: None if plan.topic == "fixed" else _REFUSAL
            )

        assert len(messages) == 2
        assert not [m for m in messages if "【纠偏】" in str(m.content)]


class TestWhatMayBecomeAResult:
    @pytest.mark.asyncio
    async def test_a_malformed_payload_is_never_accepted_even_when_advisory(self):
        """The invariant that survives every configuration: "mostly validated"
        is how bad data reaches state, so schema failures are not negotiable."""
        agent, _ = _text_agent('{"score": 3}')  # no `topic`

        with _with_provider(ModelProvider.XUNFEI), pytest.raises(StructuredOutputError) as info:
            await agent._llm_structured(_messages(), _Plan, accept_last_valid=True)

        assert "topic" in str(info.value)

    @pytest.mark.asyncio
    async def test_a_non_json_answer_is_never_accepted_even_when_advisory(self):
        agent, _ = _text_agent("我建议选美食探店这个方向")

        with _with_provider(ModelProvider.XUNFEI), pytest.raises(StructuredOutputError):
            await agent._llm_structured(_messages(), _Plan, accept_last_valid=True)

    @pytest.mark.asyncio
    async def test_an_advisory_validator_returns_the_last_schema_valid_payload(self):
        agent, calls = _text_agent('{"topic": "drifted"}')

        with _with_provider(ModelProvider.XUNFEI):
            plan = await agent._llm_structured(
                _messages(), _Plan, validator=lambda _: _REFUSAL, accept_last_valid=True
            )

        assert plan == _Plan(topic="drifted")
        assert len(calls) == 2  # retried to the limit, then gave the model's answer

    @pytest.mark.asyncio
    async def test_a_strict_validator_raises_when_the_model_never_complies(self):
        """The default: refuse, loudly, instead of returning what was refused."""
        agent, calls = _text_agent('{"topic": "drifted"}')

        with _with_provider(ModelProvider.XUNFEI), pytest.raises(StructuredOutputError) as info:
            await agent._llm_structured(_messages(), _Plan, validator=lambda _: _REFUSAL)

        assert len(calls) == 2
        assert len(info.value.attempts) == 2
        assert _REFUSAL in str(info.value)

    @pytest.mark.asyncio
    async def test_attempts_per_level_is_honoured(self):
        agent, calls = _text_agent('{"topic": "drifted"}')

        with _with_provider(ModelProvider.XUNFEI), pytest.raises(StructuredOutputError):
            await agent._llm_structured(
                _messages(), _Plan, validator=lambda _: _REFUSAL, attempts_per_level=3
            )

        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_a_validator_is_not_consulted_for_a_malformed_payload(self):
        """Order matters: the schema gate runs first, so a validator can assume
        a populated instance rather than defend against ``None``."""
        agent, _ = _text_agent("{}")
        seen: list[Any] = []

        with _with_provider(ModelProvider.XUNFEI), pytest.raises(StructuredOutputError):
            await agent._llm_structured(_messages(), _Plan, validator=lambda p: seen.append(p))

        assert seen == []


class TestTokenAccounting:
    @pytest.mark.asyncio
    async def test_a_structured_response_is_unwrapped_before_measuring(self):
        """``with_structured_output(include_raw=True)`` answers with a dict,
        which has no ``usage_metadata`` — measuring it records nothing and puts
        the cost dashboard back to $0. ``_llm_ainvoke`` must unwrap first."""
        raw = _text_response("{}")
        runnable = MagicMock()
        runnable.ainvoke = AsyncMock(return_value={"raw": raw, "parsed": {}, "parsing_error": None})
        agent = _Agent()

        with patch("backend.agents.nodes._base.llm_perf_entry", return_value=None) as entry:
            await agent._llm_ainvoke(_messages(), runnable=runnable)

        assert entry.call_args.args[1] is raw

    def test_the_reason_the_unwrap_exists(self):
        """Non-vacuous companion: a wrapped dict really does measure to nothing."""
        from backend.agents.nodes._base import llm_perf_entry

        wrapped = {"raw": _text_response("{}"), "parsed": {}, "parsing_error": None}
        assert (
            llm_perf_entry("a", wrapped, "astron-code-latest", started_at="t0", completed_at="t1")
            is None
        )

    @pytest.mark.asyncio
    async def test_a_plain_response_is_measured_as_is(self):
        response = _text_response("{}")
        runnable = MagicMock()
        runnable.ainvoke = AsyncMock(return_value=response)
        agent = _Agent()

        with patch("backend.agents.nodes._base.llm_perf_entry", return_value=None) as entry:
            await agent._llm_ainvoke(_messages(), runnable=runnable)

        assert entry.call_args.args[1] is response

    @pytest.mark.asyncio
    async def test_model_kwargs_are_bound_without_a_runnable(self):
        bound = MagicMock()
        bound.ainvoke = AsyncMock(return_value=_text_response("{}"))
        agent = _Agent()
        agent._model = MagicMock()
        agent._model.bind = MagicMock(return_value=bound)

        await agent._llm_ainvoke(_messages(), model_kwargs={"temperature": 0})

        agent.model.bind.assert_called_once_with(temperature=0)
        agent.model.ainvoke.assert_not_called()
