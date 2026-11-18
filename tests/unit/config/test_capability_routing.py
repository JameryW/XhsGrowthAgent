"""Single-gateway routing tests: every task resolves to magpie."""

from __future__ import annotations

import pytest

from backend.config.models import MAGPIE_MODEL_ID, TaskType, resolve_model_id


@pytest.mark.parametrize("task_type", list(TaskType))
def test_all_tasks_default_to_magpie(monkeypatch, task_type):
    monkeypatch.setenv("XIAOMIMIMO_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    assert resolve_model_id(task_type) == MAGPIE_MODEL_ID


def test_model_router_candidates_are_magpie(monkeypatch):
    from backend.models.router import ModelRouter

    monkeypatch.setenv("XIAOMIMIMO_API_KEY", "test-key")

    candidates = ModelRouter()._candidate_model_ids(TaskType.WRITING)
    assert candidates[0] == MAGPIE_MODEL_ID
    assert all(candidate == MAGPIE_MODEL_ID for candidate in candidates)


def test_explicit_override_remains_available_for_benchmarks():
    assert (
        resolve_model_id(TaskType.WRITING, {"writing": "deepseek-v4-flash"}) == "deepseek-v4-flash"
    )
