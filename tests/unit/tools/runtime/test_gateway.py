"""P1c-S2 contract tests: the Gateway's single invocation path.

Everything the runtime promises about a tool call is asserted here against
fake capabilities — no real tool is ever invoked, so the tests stay fast and
deterministic (backoff sleeps are injected away).
"""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from backend.tools.runtime import (
    LatencyClass,
    PermissionDeniedError,
    RetryPolicy,
    SideEffect,
    ToolGateway,
    ToolRegistry,
    ToolSpec,
    UnknownCapabilityError,
    adapt_tool,
)


def _spec(
    capability: str = "demo.echo",
    *,
    side_effect: SideEffect = SideEffect.PURE,
    max_attempts: int = 1,
    requires_idempotency_key: bool = False,
    backoff_s: float = 0.0,
    timeout_s: float | None = 1.0,
    auth_scope: tuple[str, ...] = (),
    max_concurrency: int | None = None,
) -> ToolSpec:
    return ToolSpec(
        capability=capability,
        summary="test double",
        side_effect=side_effect,
        latency=LatencyClass.FAST,
        retry_policy=RetryPolicy(
            max_attempts=max_attempts,
            backoff_s=backoff_s,
            requires_idempotency_key=requires_idempotency_key,
        ),
        timeout_s=timeout_s,
        auth_scope=auth_scope,
        max_concurrency=max_concurrency,
    )


async def _ok(payload: Mapping[str, Any]) -> str:
    """A double with the Gateway's own contract: one payload mapping in.

    Registered raw, *not* through ``adapt_tool`` — the adapter's job is to
    turn a real tool's signature into this shape, and tests that are only
    about scopes or tracing should not smuggle in that other convention.
    """
    return "ok"


class _Recorder:
    """Captures trace events and backoff sleeps without real time passing."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.sleeps: list[float] = []

    async def trace(self, event: Any) -> None:
        self.events.append(dict(event))

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def _gateway(
    fn,
    *,
    spec: ToolSpec | None = None,
    recorder: _Recorder | None = None,
    trace_raises: bool = False,
) -> tuple[ToolGateway, _Recorder]:
    registry = ToolRegistry()
    registry.register(spec or _spec(), fn)
    recorder = recorder or _Recorder()

    async def trace(event: Any) -> None:
        if trace_raises:
            raise RuntimeError("telemetry backend down")
        await recorder.trace(event)

    gateway = ToolGateway(
        registry, trace=trace if (recorder or trace_raises) else None, sleeper=recorder.sleep
    )
    return gateway, recorder


class TestSuccessPath:
    @pytest.mark.asyncio
    async def test_returns_value_and_metadata(self):
        async def echo(payload: dict[str, Any]) -> dict[str, Any]:
            return {"echo": payload}

        gateway, recorder = _gateway(echo)
        result = await gateway.invoke("demo.echo", {"a": 1})
        assert result.ok is True
        assert result.value == {"echo": {"a": 1}}
        assert result.attempts == 1
        assert result.degraded is False
        assert result.elapsed_ms >= 0
        assert result.error == ""
        assert len(recorder.events) == 1

    @pytest.mark.asyncio
    async def test_no_payload_is_fine(self):
        async def nothing(payload: dict[str, Any]) -> str:
            return "ok"

        gateway, _ = _gateway(nothing)
        assert (await gateway.invoke("demo.echo")).ok is True

    @pytest.mark.asyncio
    async def test_sync_tool_works_through_the_gateway(self):
        """adapt_tool's contract, exercised end to end."""

        def double(value: int = 0) -> int:
            return value * 2

        gateway, _ = _gateway(adapt_tool(double))
        result = await gateway.invoke("demo.echo", {"value": 21})
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_tool_reported_degradation_is_passed_through(self):
        async def partial(payload: dict[str, Any]) -> dict[str, Any]:
            return {"items": [1], "degraded": True}

        gateway, _ = _gateway(partial)
        result = await gateway.invoke("demo.echo")
        assert result.ok is True
        assert result.degraded is True


class TestRuntimeFailures:
    @pytest.mark.asyncio
    async def test_timeout_is_normalised_not_raised(self):
        async def hangs(payload: dict[str, Any]) -> None:
            await asyncio.sleep(10)

        gateway, _ = _gateway(hangs, spec=_spec(timeout_s=0.01))
        result = await gateway.invoke("demo.echo")
        assert result.ok is False
        assert "timeout after 0.01s" in result.error
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_tool_exception_is_normalised(self):
        async def boom(payload: dict[str, Any]) -> None:
            raise ValueError("bad input")

        gateway, _ = _gateway(boom)
        result = await gateway.invoke("demo.echo")
        assert result.ok is False
        assert result.error == "ValueError: bad input"

    @pytest.mark.asyncio
    async def test_retry_then_success_is_marked_degraded(self):
        calls = 0

        async def flaky(payload: dict[str, Any]) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("transient")
            return "recovered"

        gateway, recorder = _gateway(flaky, spec=_spec(max_attempts=3, backoff_s=0.5))
        result = await gateway.invoke("demo.echo")
        assert result.ok is True
        assert result.value == "recovered"
        assert result.attempts == 2
        assert result.degraded is True
        assert recorder.sleeps == [0.5]

    @pytest.mark.asyncio
    async def test_retries_are_exhausted(self):
        calls = 0

        async def always_down(payload: dict[str, Any]) -> None:
            nonlocal calls
            calls += 1
            raise ConnectionError("nope")

        gateway, recorder = _gateway(always_down, spec=_spec(max_attempts=2, backoff_s=0.1))
        result = await gateway.invoke("demo.echo")
        assert result.ok is False
        assert result.attempts == 2
        assert calls == 2
        assert len(recorder.sleeps) == 1  # between the two attempts only
        assert "ConnectionError" in result.error


class TestIdempotencyKey:
    def _write_spec(self, **overrides: Any) -> ToolSpec:
        return _spec(
            side_effect=SideEffect.SIDE_EFFECTING,
            max_attempts=2,
            requires_idempotency_key=True,
            **overrides,
        )

    @pytest.mark.asyncio
    async def test_write_without_key_is_not_retried(self):
        """The whole point of the flag: never repeat a side effect blindly."""
        calls = 0

        async def publish(payload: dict[str, Any]) -> None:
            nonlocal calls
            calls += 1
            raise ConnectionError("dropped")

        gateway, _ = _gateway(publish, spec=self._write_spec())
        result = await gateway.invoke("demo.echo", {"title": "x"})
        assert result.ok is False
        assert result.attempts == 1
        assert calls == 1
        assert "no idempotency_key" in result.error

    @pytest.mark.asyncio
    async def test_write_with_key_is_retried(self):
        calls = 0

        async def publish(payload: dict[str, Any]) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("dropped")
            return "published"

        gateway, _ = _gateway(publish, spec=self._write_spec())
        result = await gateway.invoke("demo.echo", {"idempotency_key": "abc"})
        assert result.ok is True
        assert result.attempts == 2
        assert calls == 2


class TestContractViolations:
    @pytest.mark.asyncio
    async def test_unknown_capability_raises(self):
        gateway, _ = _gateway(_ok)
        with pytest.raises(UnknownCapabilityError):
            await gateway.invoke("demo.missing")

    @pytest.mark.asyncio
    async def test_missing_scope_raises(self):
        gateway, _ = _gateway(_ok, spec=_spec(auth_scope=("xhs:write",)))
        with pytest.raises(PermissionDeniedError) as exc_info:
            await gateway.invoke("demo.echo", granted_scopes=("xhs:read",))
        assert exc_info.value.missing == ("xhs:write",)

    @pytest.mark.asyncio
    async def test_granted_scope_passes(self):
        gateway, _ = _gateway(_ok, spec=_spec(auth_scope=("xhs:read",)))
        result = await gateway.invoke("demo.echo", granted_scopes=("xhs:read",))
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_none_scopes_means_not_checked(self):
        """S2 does not invent an identity context; callers opt in."""
        gateway, _ = _gateway(_ok, spec=_spec(auth_scope=("xhs:read",)))
        assert (await gateway.invoke("demo.echo")).ok is True

    @pytest.mark.asyncio
    async def test_payload_reaches_the_tool_as_one_mapping(self):
        """The Gateway's contract is ``fn(payload)``, positionally.

        ``adapt_tool`` is what turns a real tool's signature into this shape —
        so the two conventions ("the payload is one mapping" vs "the payload's
        keys are the arguments") live on opposite sides of this seam. Pinned
        here because mixing them up is silent, not loud.
        """
        seen: list[Any] = []

        async def capture(payload: Mapping[str, Any]) -> str:
            seen.append(dict(payload))
            return "ok"

        gateway, _ = _gateway(capture)
        await gateway.invoke("demo.echo", {"a": 1})
        assert seen == [{"a": 1}]


class TestTracing:
    @pytest.mark.asyncio
    async def test_event_carries_the_audit_fields(self):
        async def boom(payload: dict[str, Any]) -> None:
            raise ValueError("x")

        gateway, recorder = _gateway(boom)
        await gateway.invoke("demo.echo", thread_id="t-1")
        event = recorder.events[0]
        assert event["kind"] == "tool"
        assert event["capability"] == "demo.echo"
        assert event["thread_id"] == "t-1"
        assert event["ok"] is False
        assert event["attempts"] == 1
        assert event["side_effect"] == "pure"
        assert "elapsed_ms" in event

    @pytest.mark.asyncio
    async def test_trace_failure_never_breaks_the_call(self):
        async def ok(payload: dict[str, Any]) -> str:
            return "fine"

        gateway, _ = _gateway(ok, trace_raises=True)
        result = await gateway.invoke("demo.echo")
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_no_sink_means_no_events_and_no_error(self):
        gateway = ToolGateway(_registry_with(_ok, _spec()))
        assert (await gateway.invoke("demo.echo")).ok is True


def _registry_with(fn, spec: ToolSpec) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(spec, fn)
    return registry


class TestConcurrencyGate:
    @pytest.mark.asyncio
    async def test_ceiling_is_enforced(self):
        active = 0
        peak = 0

        async def slow(payload: dict[str, Any]) -> str:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return "done"

        gateway, _ = _gateway(slow, spec=_spec(max_concurrency=1))
        await asyncio.gather(*(gateway.invoke("demo.echo") for _ in range(4)))
        assert peak == 1

    @pytest.mark.asyncio
    async def test_no_ceiling_means_no_gate(self):
        active = 0
        peak = 0

        async def slow(payload: dict[str, Any]) -> str:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return "done"

        gateway, _ = _gateway(slow)
        await asyncio.gather(*(gateway.invoke("demo.echo") for _ in range(4)))
        assert peak > 1

    @pytest.mark.asyncio
    async def test_gate_is_released_after_failure(self):
        """A failed call must not leak its slot."""
        calls = 0

        async def boom(payload: dict[str, Any]) -> None:
            nonlocal calls
            calls += 1
            raise ValueError("x")

        gateway, _ = _gateway(boom, spec=_spec(max_concurrency=1))
        for _ in range(3):
            assert (await gateway.invoke("demo.echo")).ok is False
        assert calls == 3


class TestCatalogueIntegration:
    @pytest.mark.asyncio
    async def test_gateway_reports_real_catalogue_metadata(self):
        """The Gateway must work off the real table, not just test doubles."""
        from backend.tools.runtime import build_registry

        registry = build_registry()
        gateway = ToolGateway(registry)
        spec = registry.spec("xhs.publish")
        assert spec.effective_timeout_s > 0
        assert gateway.registry is registry

    @pytest.mark.asyncio
    async def test_the_s2_pilot_runs_a_real_capability_end_to_end(self):
        """No doubles: a real catalogue entry, through the real Gateway.

        ``content.algorithmic_de_ai`` is the pilot precisely because it is the
        only capability that is pure *and* free *and* offline — everything
        else either spends money or touches the platform. It also rides on the
        MAPPING pass style being declared correctly, so this test fails if
        either the gateway or the binding regresses.
        """
        from backend.tools.runtime import build_registry

        gateway = ToolGateway(build_registry())
        result = await gateway.invoke(
            "content.algorithmic_de_ai",
            {"selected_title": "震惊！这个方法绝了", "body_text": "总之就是非常好用"},
        )
        assert result.ok is True, result.error
        assert result.value["selected_title"] == "震惊！这个方法绝了"
        assert result.value["method"] == "algorithmic"
        assert result.attempts == 1
        assert result.degraded is False
