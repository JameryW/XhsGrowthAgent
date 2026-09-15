"""P1c-S1 contract tests: ToolSpec / Registry / catalogue.

S1 registers metadata only, so these tests are about the *declaration*
being honest: capability ids are well-formed, the dangerous combinations
(retrying a side-effecting tool without an idempotency key) are refused, and
the catalogue actually covers every capability the agents call today.
"""

import inspect
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel, Field

from backend.tools.runtime import (
    CostClass,
    DuplicateCapabilityError,
    ErrorKind,
    LatencyClass,
    PassStyle,
    RetryPolicy,
    SideEffect,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    UnknownCapabilityError,
    adapt_tool,
    build_registry,
    describe_params,
)


def _spec(**overrides: Any) -> ToolSpec:
    base: dict[str, Any] = {
        "capability": "demo.echo",
        "summary": "echo the payload",
        "side_effect": SideEffect.PURE,
    }
    base.update(overrides)
    return ToolSpec(**base)


async def _async_echo(payload: Any) -> dict[str, Any]:
    """A kwargs-style double: the payload's keys are its argument names.

    Deliberately *not* annotated ``dict[str, Any]`` — a single required
    positional parameter annotated as a mapping is the ambiguous shape
    ``adapt_tool`` refuses to guess at (see ``TestPassStyle``), and this
    double means the kwargs reading, so it must not look like that shape.
    """
    return {"echo": payload}


def _sync_double(value: int = 0) -> int:
    return value * 2


def _two_args(a: int, b: int) -> int:
    return a + b


_TOPIC_SCORER = "backend.tools.analysis.topic_scorer.topic_scorer"


def _takes_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """The ambiguous shape: one required positional argument, a mapping.

    Like ``algorithmic_de_ai`` — the payload *is* this argument.
    """
    return {"got": data}


def _keyword_payload(*, payload: dict[str, Any]) -> dict[str, Any]:
    """The same signature intent, made unambiguous by being keyword-only."""
    return {"got": payload}


def _stringly_annotated(data: "dict[str, Any]") -> None:
    """A hand-written string annotation — what PEP 563 yields for every
    module in this repo, and what a naive check would fail to recognise."""


class _FakeArgs(BaseModel):
    """Mirrors what ``@tool`` generates: ``args_schema`` is a real model."""

    topic: str = Field(description="话题")
    limit: int = 0


async def _fake_ainvoke(**kwargs: Any) -> dict[str, Any]:
    return {"ok": kwargs}


def _fake_langchain_tool() -> Any:
    """A real ``StructuredTool``, because that is what production has.

    It used to be a hand-rolled object with ``ainvoke``/``args_schema``
    attributes — which is exactly the duck-typing that misclassified test
    doubles (see ``TestLangchainDetection``).
    """
    from langchain_core.tools import StructuredTool

    return StructuredTool.from_function(
        coroutine=_fake_ainvoke,
        name="fake_tool",
        description="fake",
        args_schema=_FakeArgs,
    )


class TestToolSpec:
    def test_minimal_spec(self):
        spec = _spec()
        assert spec.capability == "demo.echo"
        assert spec.qualified == "demo.echo[pure]"
        assert spec.retry_policy.max_attempts == 1

    @pytest.mark.parametrize("capability", ["", "nodot", " "])
    def test_capability_must_be_dotted(self, capability: str):
        with pytest.raises(ValueError, match="dotted id"):
            _spec(capability=capability)

    def test_summary_must_not_be_blank(self):
        with pytest.raises(ValueError, match="summary"):
            _spec(summary="   ")

    def test_timeout_must_be_positive(self):
        with pytest.raises(ValueError, match="timeout_s"):
            _spec(timeout_s=0)

    def test_side_effecting_retry_requires_idempotency_key(self):
        """Retrying a write without an idempotency key is how you
        double-publish — the spec must refuse to be declared that way."""
        with pytest.raises(ValueError, match="requires_idempotency_key"):
            _spec(
                side_effect=SideEffect.SIDE_EFFECTING,
                retry_policy=RetryPolicy(max_attempts=2),
            )

    def test_side_effecting_retry_with_key_is_allowed(self):
        spec = _spec(
            side_effect=SideEffect.SIDE_EFFECTING,
            retry_policy=RetryPolicy(max_attempts=2, requires_idempotency_key=True),
        )
        assert spec.retry_policy.retryable

    def test_read_only_retry_needs_no_key(self):
        spec = _spec(side_effect=SideEffect.READ_ONLY, retry_policy=RetryPolicy(max_attempts=3))
        assert spec.retry_policy.max_attempts == 3

    @pytest.mark.parametrize(
        ("latency", "expected"),
        [
            (LatencyClass.FAST, 5.0),
            (LatencyClass.MEDIUM, 30.0),
            (LatencyClass.SLOW, 120.0),
        ],
    )
    def test_default_timeout_follows_latency_class(self, latency, expected):
        assert _spec(latency=latency).effective_timeout_s == expected

    def test_explicit_timeout_wins(self):
        assert _spec(latency=LatencyClass.SLOW, timeout_s=7.5).effective_timeout_s == 7.5

    def test_to_dict_is_serialisable(self):
        payload = _spec().to_dict()
        assert payload["capability"] == "demo.echo"
        assert payload["side_effect"] == "pure"
        assert payload["retry"]["max_attempts"] == 1


class TestRetryPolicy:
    @pytest.mark.parametrize("attempts", [0, -1])
    def test_max_attempts_must_be_at_least_one(self, attempts: int):
        with pytest.raises(ValueError, match="max_attempts"):
            RetryPolicy(max_attempts=attempts)

    def test_backoff_must_not_be_negative(self):
        with pytest.raises(ValueError, match="backoff_s"):
            RetryPolicy(backoff_s=-1.0)

    def test_retryable_flag(self):
        assert RetryPolicy().retryable is False
        assert RetryPolicy(max_attempts=2).retryable is True


class TestToolResult:
    def test_success_carries_no_error(self):
        result = ToolResult(capability="demo.echo", ok=True, value={"a": 1})
        assert result.ok and result.error == ""
        assert result.error_kind is None
        assert result.to_dict()["ok"] is True

    def test_success_with_error_is_rejected(self):
        with pytest.raises(ValueError, match="must not carry an error"):
            ToolResult(capability="demo.echo", ok=True, error="boom")

    def test_success_with_an_error_kind_is_rejected(self):
        with pytest.raises(ValueError, match="must not carry an error_kind"):
            ToolResult(capability="demo.echo", ok=True, error_kind=ErrorKind.TIMEOUT)

    def test_failure_must_explain_itself(self):
        with pytest.raises(ValueError, match="must explain itself"):
            ToolResult(capability="demo.echo", ok=False)

    def test_failure_must_say_how_it_failed(self):
        """The kind is how a caller tells "never finished" from "said no", so
        it cannot be left to a message format."""
        with pytest.raises(ValueError, match="must say how it failed"):
            ToolResult(capability="demo.echo", ok=False, error="boom")

    def test_failure_with_error(self):
        result = ToolResult(
            capability="demo.echo",
            ok=False,
            error="timeout after 120s",
            error_kind=ErrorKind.TIMEOUT,
        )
        assert result.to_dict()["error"] == "timeout after 120s"
        assert result.to_dict()["error_kind"] == "timeout"


class TestRegistry:
    def test_register_and_get(self):
        registry = ToolRegistry()
        entry = registry.register(_spec(), _async_echo)
        assert entry.capability == "demo.echo"
        assert registry.get("demo.echo").fn is _async_echo
        assert "demo.echo" in registry
        assert len(registry) == 1

    def test_duplicate_capability_fails_fast(self):
        registry = ToolRegistry()
        registry.register(_spec(), _async_echo)
        with pytest.raises(DuplicateCapabilityError):
            registry.register(_spec(), _async_echo)

    def test_unknown_capability_lists_known_ones(self):
        registry = ToolRegistry()
        registry.register(_spec(), _async_echo)
        with pytest.raises(UnknownCapabilityError) as exc_info:
            registry.get("demo.missing")
        assert "demo.echo" in str(exc_info.value)

    def test_capabilities_are_sorted(self):
        registry = ToolRegistry()
        registry.register(_spec(capability="b.two"), _async_echo)
        registry.register(_spec(capability="a.one"), _async_echo)
        assert registry.capabilities() == ("a.one", "b.two")

    def test_subset_narrows_to_named_capabilities(self):
        registry = ToolRegistry()
        registry.register(_spec(capability="a.one"), _async_echo)
        registry.register(_spec(capability="b.two"), _async_echo)
        narrowed = registry.subset(["b.two"])
        assert narrowed.capabilities() == ("b.two",)

    def test_subset_rejects_unknown(self):
        registry = ToolRegistry()
        with pytest.raises(UnknownCapabilityError):
            registry.subset(["nope.nope"])

    def test_iteration_yields_registered_tools(self):
        registry = ToolRegistry()
        registry.register(_spec(), _async_echo)
        assert [entry.capability for entry in registry] == ["demo.echo"]


class TestAdaptTool:
    @pytest.mark.asyncio
    async def test_langchain_tool_is_invoked_via_ainvoke(self):
        fake = _fake_langchain_tool()
        fn = adapt_tool(fake, pass_style=PassStyle.INVOKE)
        assert await fn({"topic": "辅食"}) == {"ok": {"topic": "辅食", "limit": 0}}

    @pytest.mark.asyncio
    async def test_async_function_takes_keyword_payload(self):
        """Payload keys map to keyword arguments of the wrapped function."""
        fn = adapt_tool(_async_echo)
        assert await fn({"payload": 1}) == {"echo": 1}

    @pytest.mark.asyncio
    async def test_sync_function_is_awaited_too(self):
        fn = adapt_tool(_sync_double)
        assert await fn({"value": 21}) == 42

    def test_adapt_tool_always_returns_a_coroutine_function(self):
        for target in (_async_echo, _sync_double):
            assert inspect.iscoroutinefunction(adapt_tool(target))
        assert inspect.iscoroutinefunction(
            adapt_tool(_fake_langchain_tool(), pass_style=PassStyle.INVOKE)
        )


class TestLangchainDetection:
    """Detection is the real type, not the presence of three attributes.

    Duck-typing it was a genuine bug source: a test double answers every
    attribute, so it was classified as a LangChain tool and the payload went
    to ``.ainvoke`` — the double never ran with the payload, and the code
    under test looked like it had degraded gracefully instead of being wired
    wrong. Both defects this runtime has had in schema reflection and payload
    routing came from that shortcut.

    Routing no longer asks the question at all — the capability's declared
    ``pass_style`` decides (see ``TestPassStyle``). This is how a tool is
    *described*, and how a LangChain tool declared ``KWARGS`` is caught.
    """

    @pytest.mark.asyncio
    async def test_a_real_structured_tool_is_routed_through_ainvoke(self):
        fake = _fake_langchain_tool()
        fn = adapt_tool(fake, pass_style=PassStyle.INVOKE)
        assert await fn({"topic": "辅食"}) == {"ok": {"topic": "辅食", "limit": 0}}

    @pytest.mark.asyncio
    async def test_a_double_is_called_with_the_payload_as_keywords(self):
        """It answers ``ainvoke`` as well, so only the type says it is not a
        tool — and the declaration, not the type, decides the route."""
        fake = AsyncMock(return_value={"ok": True})
        fake.name = "fake_tool"
        fake.args_schema = _FakeArgs  # looks exactly like a LangChain tool

        assert await adapt_tool(fake)({"topic": "辅食"}) == {"ok": True}
        fake.assert_awaited_once_with(topic="辅食")

    def test_a_specd_double_takes_the_tool_branch(self):
        """``AsyncMock(spec=StructuredTool)`` is the *faithful* way to double a
        tool — ``spec`` makes ``isinstance`` true. It still declares no schema,
        because its ``args_schema`` is a mock rather than a Pydantic model."""
        from langchain_core.tools import StructuredTool

        assert describe_params(AsyncMock(spec=StructuredTool)) == {}


class TestPassStyle:
    """The three payload conventions — and the refusal to guess between them.

    ``KWARGS`` and ``MAPPING`` are indistinguishable from a signature like
    ``async def f(filters: dict)``: both call successfully, one on the wrong
    data. ``KWARGS`` and ``INVOKE`` are indistinguishable from a *double*,
    which answers both ``__call__`` and ``ainvoke``. So the style is declared,
    the route follows the declaration, and a target that cannot honour it is
    refused at build time rather than mis-called at the first request.
    """

    def test_defaults_to_kwargs(self):
        assert _spec().pass_style is PassStyle.KWARGS

    @pytest.mark.asyncio
    async def test_keyword_payload_maps_to_argument_names(self):
        fn = adapt_tool(_sync_double, pass_style=PassStyle.KWARGS)
        assert await fn({"value": 21}) == 42

    @pytest.mark.asyncio
    async def test_mapping_payload_is_handed_over_whole(self):
        fn = adapt_tool(_takes_mapping, pass_style=PassStyle.MAPPING)
        assert await fn({"a": 1}) == {"got": {"a": 1}}

    @pytest.mark.asyncio
    async def test_mapping_awaits_an_async_tool(self):
        """Otherwise the Gateway would be handed an un-awaited coroutine as
        the tool's *value*."""

        async def double(data: dict[str, Any]) -> dict[str, Any]:
            return {"got": data}

        fn = adapt_tool(double, pass_style=PassStyle.MAPPING)
        assert await fn({"a": 1}) == {"got": {"a": 1}}

    @pytest.mark.asyncio
    async def test_invoke_hands_the_payload_to_ainvoke(self):
        fake = _fake_langchain_tool()
        fn = adapt_tool(fake, pass_style=PassStyle.INVOKE)
        assert await fn({"topic": "辅食"}) == {"ok": {"topic": "辅食", "limit": 0}}

    def test_a_langchain_tool_must_declare_invoke(self):
        """A ``StructuredTool`` is not callable, so a kwargs-style declaration
        would only surface as a ``TypeError`` on the first real request."""
        with pytest.raises(ValueError, match="Declare PassStyle.INVOKE"):
            adapt_tool(_fake_langchain_tool())

    def test_invoke_needs_something_it_can_invoke(self):
        """The mirror image: a plain function cannot answer ``ainvoke``."""
        with pytest.raises(ValueError, match="no callable ainvoke"):
            adapt_tool(_async_echo, pass_style=PassStyle.INVOKE)

    def test_mapping_needs_exactly_one_positional_parameter(self):
        with pytest.raises(ValueError, match="exactly one positional"):
            adapt_tool(_two_args, pass_style=PassStyle.MAPPING)

    def test_mapping_on_a_keyword_only_tool_is_rejected(self):
        """There is no positional slot to hand the mapping to."""
        with pytest.raises(ValueError, match="exactly one positional"):
            adapt_tool(_keyword_payload, pass_style=PassStyle.MAPPING)

    def test_ambiguous_shape_must_be_declared(self):
        """A lone mapping argument is refused, not guessed at."""
        with pytest.raises(ValueError, match="takes a single mapping argument"):
            adapt_tool(_takes_mapping)

    def test_resolving_the_ambiguity_the_other_way_is_allowed(self):
        """Annotating the parameter as its real type says "these are keywords"."""
        assert adapt_tool(_keyword_payload) is not None

    def test_pep563_string_annotations_are_read_as_types(self):
        """Every module here postpones annotations, so the raw value is a str.

        A string is never a ``Mapping`` subclass; if the check compared the
        raw annotation the ambiguity guard would never fire anywhere.
        """
        assert _stringly_annotated.__annotations__["data"] == "dict[str, Any]"
        with pytest.raises(ValueError, match="takes a single mapping argument"):
            adapt_tool(_stringly_annotated)

    def test_style_is_serialised(self):
        assert _spec(pass_style=PassStyle.MAPPING).to_dict()["pass_style"] == "mapping"
        assert _spec(pass_style=PassStyle.INVOKE).to_dict()["pass_style"] == "invoke"


class TestDescribeParams:
    def test_langchain_tool_uses_its_pydantic_schema(self):
        described = describe_params(_fake_langchain_tool())
        assert described["topic"] == {
            "type": "string",
            "required": True,
            "description": "话题",
        }
        assert described["limit"]["required"] is False

    def test_plain_function_uses_signature(self):
        described = describe_params(_sync_double)
        assert described["value"]["required"] is False  # has a default
        assert described["value"]["type"] == "int"

    def test_a_double_that_looks_like_a_tool_declares_no_invented_schema(self):
        """It used to be *reflected*, and a mock's ``model_json_schema()``
        returns a coroutine — ``.get`` on that killed ``build_registry()``.

        Now such an object is simply not a LangChain tool, so it is described
        by signature and its fake schema is never consulted.
        """
        fake = AsyncMock()
        fake.name = "fake_tool"
        fake.args_schema = _FakeArgs

        assert describe_params(fake) == {
            "args": {"type": "any", "required": True, "description": ""},
            "kwargs": {"type": "any", "required": True, "description": ""},
        }


class TestCatalogue:
    def test_covers_every_agent_call_site(self):
        """The nine capabilities the agents call today must all be declared,
        plus publishing for P2a. A missing one means the Gateway cannot route
        it later, and the S5 gate would have nothing to check against."""
        registry = build_registry()
        expected = {
            "analysis.topic_scorer",
            "content.algorithmic_de_ai",
            "content.polish_copy",
            "ripple.get_report",
            "ripple.predict_spread",
            "ripple.validate_pmf",
            "xhs.trending",
            "xhs.keyword_monitor",
            "xhs.competitor_analyzer",
            "xhs.publish",
        }
        assert set(registry.capabilities()) == expected

    def test_every_spec_is_described(self):
        for spec in build_registry().specs():
            assert spec.summary.strip(), spec.capability
            assert spec.input_schema, f"{spec.capability} has no input schema"

    def test_write_capability_is_not_retried_yet(self):
        """Publishing is not idempotent until P2a adds the key — the catalogue
        must not pretend otherwise."""
        spec = build_registry().spec("xhs.publish")
        assert spec.side_effect is SideEffect.SIDE_EFFECTING
        assert spec.retry_policy.retryable is False
        assert "xhs:write" in spec.auth_scope

    def test_read_capabilities_declare_their_scope(self):
        registry = build_registry()
        assert registry.spec("xhs.trending").auth_scope == ("xhs:read",)
        assert registry.spec("ripple.get_report").auth_scope == ("ripple:read",)

    def test_the_report_fetch_declares_its_wait_budget(self):
        """S3c: the call site used to guard this fetch with a 120s wait.

        The budget now lives on the declaration, so it must not quietly fall
        back to the MEDIUM default (30s) — that would cut the analyst's report
        fetch to a quarter of what it was. No retry either: the tool reports
        failures as data, so the only retryable event would be the Gateway's
        own timeout, and retrying a timeout is a longer wait rather than a
        transient-failure remedy (see the catalogue comment).
        """
        spec = build_registry().spec("ripple.get_report")
        assert spec.timeout_s == 120.0
        assert spec.retry_policy.retryable is False

    def test_pure_capabilities_need_no_scope(self):
        registry = build_registry()
        assert registry.spec("content.algorithmic_de_ai").auth_scope == ()

    def test_every_entry_is_async_callable(self):
        for entry in build_registry():
            assert inspect.iscoroutinefunction(entry.fn), entry.capability

    def test_build_registry_is_isolated_per_call(self):
        """Explicit composition roots: two builds must not share state."""
        first, second = build_registry(), build_registry()
        assert first is not second
        assert first.capabilities() == second.capabilities()

    def test_builds_while_a_tool_is_doubled(self):
        """The catalogue must survive being built with a test double in place.

        The shared gateway is built lazily on first use, which can land inside
        a ``patch`` block — so a doubled tool must not be able to take the
        composition root down. See the AsyncMock case in ``TestDescribeParams``.
        """
        with patch(_TOPIC_SCORER, AsyncMock()):
            registry = build_registry()
        assert "analysis.topic_scorer" in registry

    def test_costs_are_classified(self):
        registry = build_registry()
        assert registry.spec("content.polish_copy").cost is CostClass.EXPENSIVE
        assert registry.spec("content.algorithmic_de_ai").cost is CostClass.FREE

    def test_only_the_free_form_tool_is_mapping(self):
        """Pinned so adopting the other convention stays a deliberate change.

        ``build_registry()`` itself validates every declaration against its
        target's signature, so a *mismatched* style cannot even be built —
        this test is about which side each capability is on.
        """
        mapping = [
            entry.capability
            for entry in build_registry()
            if entry.spec.pass_style is PassStyle.MAPPING
        ]
        assert mapping == ["content.algorithmic_de_ai"]

    def test_the_langchain_tools_are_declared_invoke(self):
        """The other deliberate side of the same coin: these five reach their
        target through ``ainvoke``, and the catalogue must say so — a missing
        declaration is refused by ``build_registry()`` itself."""
        invoke = {
            entry.capability
            for entry in build_registry()
            if entry.spec.pass_style is PassStyle.INVOKE
        }
        assert invoke == {
            "analysis.topic_scorer",
            "xhs.trending",
            "xhs.keyword_monitor",
            "xhs.competitor_analyzer",
            "xhs.publish",
        }

    @pytest.mark.asyncio
    async def test_the_free_form_tool_actually_runs(self):
        """Regression: it was adapted as kwargs-style, so every call raised
        ``TypeError: unexpected keyword argument`` — which the Gateway would
        have faithfully reported as the tool failing. Now it runs, and its
        payload arrives as the mapping it reads."""
        fn = build_registry().get("content.algorithmic_de_ai").fn
        result = await fn({"selected_title": "震惊！这个方法绝了", "body_text": "总之就是非常好用"})
        assert result["selected_title"] == "震惊！这个方法绝了"
        assert result["body_text"] == "总之就是非常好用"
        assert result["method"] == "algorithmic"
