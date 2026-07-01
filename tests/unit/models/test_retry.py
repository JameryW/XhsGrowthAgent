"""Tests for the LLM ainvoke/invoke retry wrapper."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models import retry
from backend.models.retry import with_retry


class _FakeError(Exception):
    """Base for fake provider-style errors used in tests."""


class _RateLimitError(_FakeError):
    status_code = 429


class _ServerError(_FakeError):
    status_code = 503


class _AuthError(_FakeError):
    status_code = 401


class _BadRequestError(_FakeError):
    status_code = 400


class _ConnectionError(_FakeError):
    """Name-only connection error (no status)."""


def _make_model(ainvoke_side_effects: list, invoke_side_effects: list | None = None):
    model = MagicMock()
    model.ainvoke = AsyncMock(side_effect=ainvoke_side_effects)
    model.invoke = MagicMock(side_effect=invoke_side_effects or ainvoke_side_effects)
    model.bind.return_value = "bound"
    return model


def test_retryable_429_then_success(monkeypatch):
    monkeypatch.setenv("XHS_LLM_MAX_RETRIES", "3")
    monkeypatch.setenv("XHS_LLM_RETRY_BASE_DELAY", "0")
    monkeypatch.setenv("XHS_LLM_RETRY_MAX_DELAY", "0")
    monkeypatch.setattr(retry.random, "uniform", lambda a, b: 0)

    model = _make_model([_RateLimitError("slow down"), "ok"])
    wrapped = with_retry(model)

    result = asyncio.run(wrapped.ainvoke([]))
    assert result == "ok"
    assert model.ainvoke.await_count == 2


def test_non_retryable_4xx_short_circuits(monkeypatch):
    monkeypatch.setenv("XHS_LLM_MAX_RETRIES", "3")
    monkeypatch.setattr(retry.random, "uniform", lambda a, b: 0)

    model = _make_model([_AuthError("bad key")])
    wrapped = with_retry(model)

    with pytest.raises(_AuthError):
        asyncio.run(wrapped.ainvoke([]))
    assert model.ainvoke.await_count == 1  # no retries


def test_exhausts_retries_on_persistent_5xx(monkeypatch):
    monkeypatch.setenv("XHS_LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("XHS_LLM_RETRY_BASE_DELAY", "0")
    monkeypatch.setattr(retry.random, "uniform", lambda a, b: 0)

    model = _make_model([_ServerError("down"), _ServerError("down"), _ServerError("down")])
    wrapped = with_retry(model)

    with pytest.raises(_ServerError):
        asyncio.run(wrapped.ainvoke([]))
    # initial + 2 retries
    assert model.ainvoke.await_count == 3


def test_connection_error_without_status_is_retryable(monkeypatch):
    monkeypatch.setenv("XHS_LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("XHS_LLM_RETRY_BASE_DELAY", "0")
    monkeypatch.setattr(retry.random, "uniform", lambda a, b: 0)

    model = _make_model([_ConnectionError("reset"), "recovered"])
    wrapped = with_retry(model)

    result = asyncio.run(wrapped.ainvoke([]))
    assert result == "recovered"
    assert model.ainvoke.await_count == 2


def test_sync_invoke_retries(monkeypatch):
    monkeypatch.setenv("XHS_LLM_MAX_RETRIES", "3")
    monkeypatch.setenv("XHS_LLM_RETRY_BASE_DELAY", "0")
    monkeypatch.setattr(retry.random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(retry.time, "sleep", lambda _: None)

    model = _make_model([_RateLimitError("429"), "ok"])
    wrapped = with_retry(model)

    assert wrapped.invoke([]) == "ok"
    assert model.invoke.call_count == 2


def test_delegates_other_attributes():
    model = _make_model(["ok"])
    wrapped = with_retry(model)
    # Non-ainvoke/invoke attrs proxy through.
    assert wrapped.bind() == "bound"
