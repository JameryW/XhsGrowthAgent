"""P1c-S1 contract tests: ToolSpec / Registry / catalogue.

S1 registers metadata only, so these tests are about the *declaration*
being honest: capability ids are well-formed, the dangerous combinations
(retrying a side-effecting tool without an idempotency key) are refused, and
the catalogue actually covers every capability the agents call today.
"""

import inspect
from typing import Any

import pytest

from backend.tools.runtime import (
    CostClass,
    DuplicateCapabilityError,
    LatencyClass,
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


async def _async_echo(payload: dict[str, Any]) -> dict[str, Any]:
    return {"echo": payload}


def _sync_double(value: int = 0) -> int:
    return value * 2


class _FakeLangchainTool:
    """Duck-typed stand-in for a StructuredTool — no langchain import needed."""

    name = "fake_tool"

    class args_schema:  # noqa: N801 - mimics the attribute, not a class we use
        @staticmethod
        def model_json_schema() -> dict[str, Any]:
            return {
                "properties": {
                    "topic": {"type": "string", "description": "话题"},
                    "limit": {"type": "integer"},
                },
                "required": ["topic"],
            }

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def ainvoke(self, payload: Any) -> Any:
        self.calls.append(payload)
        return {"ok": payload}


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
        assert result.to_dict()["ok"] is True

    def test_success_with_error_is_rejected(self):
        with pytest.raises(ValueError, match="must not carry an error"):
            ToolResult(capability="demo.echo", ok=True, error="boom")

    def test_failure_must_explain_itself(self):
        with pytest.raises(ValueError, match="must explain itself"):
            ToolResult(capability="demo.echo", ok=False)

    def test_failure_with_error(self):
        result = ToolResult(capability="demo.echo", ok=False, error="timeout")
        assert result.to_dict()["error"] == "timeout"


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
        fake = _FakeLangchainTool()
        fn = adapt_tool(fake)
        assert await fn({"topic": "辅食"}) == {"ok": {"topic": "辅食"}}
        assert fake.calls == [{"topic": "辅食"}]

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
        for target in (_async_echo, _sync_double, _FakeLangchainTool()):
            assert inspect.iscoroutinefunction(adapt_tool(target))


class TestDescribeParams:
    def test_langchain_tool_uses_its_pydantic_schema(self):
        described = describe_params(_FakeLangchainTool())
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

    def test_costs_are_classified(self):
        registry = build_registry()
        assert registry.spec("content.polish_copy").cost is CostClass.EXPENSIVE
        assert registry.spec("content.algorithmic_de_ai").cost is CostClass.FREE
