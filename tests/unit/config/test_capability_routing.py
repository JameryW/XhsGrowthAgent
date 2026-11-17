"""Opt-in capability routing tests (default stays on magpie)."""

from __future__ import annotations

from backend.config.models import (
    CAPABILITY_ROUTING_ENV,
    MAGPIE_MODEL_ID,
    TaskType,
    resolve_model_id,
)


def test_capability_routing_defaults_to_magpie(monkeypatch):
    monkeypatch.delenv(CAPABILITY_ROUTING_ENV, raising=False)
    monkeypatch.setenv("XIAOMIMIMO_API_KEY", "test-key")

    assert resolve_model_id(TaskType.WRITING) == MAGPIE_MODEL_ID
    assert resolve_model_id(TaskType.ANALYSIS) == MAGPIE_MODEL_ID


def test_creative_tasks_route_to_mimo_when_enabled_and_key_present(monkeypatch):
    monkeypatch.setenv(CAPABILITY_ROUTING_ENV, "1")
    monkeypatch.setenv("XIAOMIMIMO_API_KEY", "test-key")

    assert resolve_model_id(TaskType.WRITING) == "mimo-v2.6-flash"
    assert resolve_model_id(TaskType.POLISH) == "mimo-v2.6-flash"
    assert resolve_model_id(TaskType.VERSION_GEN) == "mimo-v2.6-flash"


def test_non_creative_tasks_stay_on_magpie_when_enabled(monkeypatch):
    monkeypatch.setenv(CAPABILITY_ROUTING_ENV, "1")
    monkeypatch.setenv("XIAOMIMIMO_API_KEY", "test-key")

    assert resolve_model_id(TaskType.SCOUTING) == MAGPIE_MODEL_ID
    assert resolve_model_id(TaskType.ANALYSIS) == MAGPIE_MODEL_ID
    assert resolve_model_id(TaskType.PUBLISHING) == MAGPIE_MODEL_ID


def test_creative_route_requires_the_provider_key(monkeypatch):
    monkeypatch.setenv(CAPABILITY_ROUTING_ENV, "true")
    monkeypatch.delenv("XIAOMIMIMO_API_KEY", raising=False)

    assert resolve_model_id(TaskType.WRITING) == MAGPIE_MODEL_ID


def test_explicit_override_wins_over_capability_routing(monkeypatch):
    monkeypatch.setenv(CAPABILITY_ROUTING_ENV, "1")
    monkeypatch.setenv("XIAOMIMIMO_API_KEY", "test-key")

    assert (
        resolve_model_id(TaskType.WRITING, {"writing": "deepseek-v4-flash"}) == "deepseek-v4-flash"
    )


def test_model_router_uses_capability_route(monkeypatch):
    from backend.models.router import ModelRouter

    monkeypatch.setenv(CAPABILITY_ROUTING_ENV, "1")
    monkeypatch.setenv("XIAOMIMIMO_API_KEY", "test-key")

    candidates = ModelRouter()._candidate_model_ids(TaskType.WRITING)
    assert candidates[0] == "mimo-v2.6-flash"
    assert candidates[1] == MAGPIE_MODEL_ID
