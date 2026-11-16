"""Tests for durable workflow failure diagnostics."""

from __future__ import annotations

import pytest

from backend.services import workflow_diagnostics


@pytest.mark.asyncio
async def test_failure_event_carries_root_cause_and_token_cost(monkeypatch):
    captured: list[dict] = []

    async def _fake_load_perf_log(thread_id: str):
        assert thread_id == "thr1"
        return [
            {"payload": {"input_tokens": 1000, "output_tokens": 500}},
            {"payload": {"cost_usd": 0.012}},
        ]

    async def _fake_emit(thread_id: str, entries: list[dict]):
        captured.extend(entries)
        return len(entries)

    monkeypatch.setattr(workflow_diagnostics, "load_perf_log", _fake_load_perf_log)
    monkeypatch.setattr(workflow_diagnostics, "emit_events", _fake_emit)

    payload = await workflow_diagnostics.record_workflow_failure(
        "thr1",
        RuntimeError("signature_unavailable: browser login expired"),
        phase="publishing",
        source="resume",
    )

    assert payload["event"] == "workflow_failure"
    assert payload["source"] == "resume"
    assert payload["root_cause"]["bucket"] == "session_circuit_open"
    assert payload["root_cause"]["retryable"] is False
    assert payload["token_cost"]["input_tokens"] == 1000
    assert payload["token_cost"]["output_tokens"] == 500
    assert payload["token_cost"]["cost_usd"] == 0.012
    assert captured == [payload]


@pytest.mark.asyncio
async def test_failure_event_still_returns_when_telemetry_is_unavailable(monkeypatch):
    async def _broken_load(thread_id: str):
        raise RuntimeError("store down")

    async def _broken_emit(thread_id: str, entries: list[dict]):
        raise RuntimeError("store down")

    monkeypatch.setattr(workflow_diagnostics, "load_perf_log", _broken_load)
    monkeypatch.setattr(workflow_diagnostics, "emit_events", _broken_emit)

    payload = await workflow_diagnostics.record_workflow_failure(
        "thr2",
        TimeoutError("model timed out"),
        phase="creating",
    )

    assert payload["root_cause"]["bucket"] == "transient_model_or_network"
    assert payload["token_cost"]["total_tokens"] == 0
    assert payload["message"] == "model timed out"
