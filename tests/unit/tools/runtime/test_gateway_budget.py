"""Gateway wiring tests for the tool payload budget (ledger scheme #46).

The promise under test is a *mode*: with the switch off the success path must
be byte-identical to a deployment without the module (same value, no extra
result fields, no extra trace keys), and the two enabled modes must be
observable without changing any other documented behaviour.
"""

from collections.abc import Mapping
from typing import Any

import pytest

from backend.services.tool_budget import TOOL_BUDGET_ENV
from backend.tools.runtime import (
    LatencyClass,
    RetryPolicy,
    SideEffect,
    ToolGateway,
    ToolRegistry,
    ToolSpec,
)

_LEGACY_EVENT_KEYS = {
    "kind",
    "event",
    "capability",
    "side_effect",
    "thread_id",
    "ok",
    "attempts",
    "elapsed_ms",
    "error",
    "error_kind",
    "domain_reason",
    "degraded",
    "untrusted",
    "scopes",
}


def _spec(capability: str) -> ToolSpec:
    return ToolSpec(
        capability=capability,
        summary="test double",
        side_effect=SideEffect.PURE,
        latency=LatencyClass.FAST,
        retry_policy=RetryPolicy(),
        timeout_s=1.0,
    )


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def trace(self, event: Any) -> None:
        self.events.append(dict(event))

    async def sleep(self, seconds: float) -> None:
        return None


def _gateway(fn, capability: str) -> tuple[ToolGateway, _Recorder]:
    registry = ToolRegistry()
    registry.register(_spec(capability), fn)
    recorder = _Recorder()
    return ToolGateway(registry, trace=recorder.trace, sleeper=recorder.sleep), recorder


@pytest.fixture(autouse=True)
def _local_slot_gates_only(monkeypatch):
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)
    from backend.tools.runtime.account_gate import reset_account_gates_for_tests

    reset_account_gates_for_tests()
    yield
    reset_account_gates_for_tests()


async def _ripple(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {"prediction": {"reach": 1200}, "job_id": "job-1", "debug": "x" * 400}


async def _trending(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{"title": "川西自驾", "likes": 10, "noise": "x" * 50}]


async def _plain(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {"echo": dict(payload), "debug": "x" * 400}


class TestSwitchOff:
    @pytest.mark.asyncio
    async def test_value_and_fields_unchanged(self, monkeypatch):
        monkeypatch.delenv(TOOL_BUDGET_ENV, raising=False)
        gateway, _ = _gateway(_ripple, "ripple.predict_spread")
        result = await gateway.invoke("ripple.predict_spread", {})
        assert result.ok is True
        assert result.value == {
            "prediction": {"reach": 1200},
            "job_id": "job-1",
            "debug": "x" * 400,
        }
        assert result.projection == {}
        assert result.full_value is None

    @pytest.mark.asyncio
    async def test_trace_event_keeps_its_exact_key_set(self, monkeypatch):
        monkeypatch.delenv(TOOL_BUDGET_ENV, raising=False)
        gateway, recorder = _gateway(_ripple, "ripple.predict_spread")
        await gateway.invoke("ripple.predict_spread", {})
        assert set(recorder.events[0]) == _LEGACY_EVENT_KEYS


class TestReportMode:
    @pytest.mark.asyncio
    async def test_measures_without_trimming(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "report")
        gateway, recorder = _gateway(_ripple, "ripple.predict_spread")
        result = await gateway.invoke("ripple.predict_spread", {})
        assert result.value == {
            "prediction": {"reach": 1200},
            "job_id": "job-1",
            "debug": "x" * 400,
        }
        assert result.full_value is None
        assert result.projection["mode"] == "report"
        assert result.projection["trimmed"] is False
        assert result.projection["dropped_keys"] == ["debug"]
        event = recorder.events[0]
        assert event["projection"] == "report"
        assert event["projection_applied"] is False
        assert event["payload_chars"] > event["projected_chars"] > 0
        assert 0.0 < event["retention_ratio"] < 1.0
        assert event["projection_dropped"] == ["debug"]


class TestTrimMode:
    @pytest.mark.asyncio
    async def test_value_is_the_projection_and_full_payload_survives(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        gateway, recorder = _gateway(_ripple, "ripple.predict_spread")
        result = await gateway.invoke("ripple.predict_spread", {})
        assert result.value == {"prediction": {"reach": 1200}, "job_id": "job-1"}
        assert result.full_value == {
            "prediction": {"reach": 1200},
            "job_id": "job-1",
            "debug": "x" * 400,
        }
        assert result.projection["trimmed"] is True
        assert recorder.events[0]["projection_applied"] is True

    @pytest.mark.asyncio
    async def test_degraded_is_decided_before_the_trim(self, monkeypatch):
        async def partial(payload: Mapping[str, Any]) -> dict[str, Any]:
            return {"prediction": {"reach": 1}, "job_id": "j", "degraded": True, "noise": "x"}

        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        gateway, _ = _gateway(partial, "ripple.predict_spread")
        result = await gateway.invoke("ripple.predict_spread", {})
        # ``degraded`` is dropped from the projected payload on purpose: the
        # signal must still be on the result, or trimming would hide a
        # partial read.
        assert "degraded" not in result.value
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_list_payload_is_not_trimmed(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        gateway, _ = _gateway(_trending, "xhs.trending")
        result = await gateway.invoke("xhs.trending", {})
        assert result.value == [{"title": "川西自驾", "likes": 10, "noise": "x" * 50}]
        assert result.full_value is None
        assert result.projection["note"] == "list_payload_measured_only"
        assert result.projection["trimmed"] is False

    @pytest.mark.asyncio
    async def test_capability_without_contract_is_not_trimmed(self, monkeypatch):
        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        gateway, _ = _gateway(_plain, "demo.echo")
        result = await gateway.invoke("demo.echo", {"a": 1})
        assert result.value == {"echo": {"a": 1}, "debug": "x" * 400}
        assert result.projection["note"] == "no_retention_contract"


class TestFailurePath:
    @pytest.mark.asyncio
    async def test_failed_call_carries_no_projection(self, monkeypatch):
        async def boom(payload: Mapping[str, Any]) -> dict[str, Any]:
            raise RuntimeError("tool exploded")

        monkeypatch.setenv(TOOL_BUDGET_ENV, "trim")
        gateway, recorder = _gateway(boom, "ripple.predict_spread")
        result = await gateway.invoke("ripple.predict_spread", {})
        assert result.ok is False
        assert result.projection == {}
        assert "projection" not in recorder.events[0]
