"""Retry wrapper for LLM calls — exponential backoff on transient errors.

langchain's ChatAnthropic / ChatOpenAI constructors do not accept a max_retries
param, so we wrap the model's ainvoke/invoke at the get_model() exit point.
Retryable: 429 / 5xx / network / timeout. Non-retryable: 4xx (auth, bad request,
content policy) — short-circuit to avoid burning quota.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # BaseChatModel only appears in annotations; importing it at module load
    # pulls langchain_core.language_models → langsmith (~1s) on every import of
    # backend.models.retry (pulled by router.py). Deferred to TYPE_CHECKING.
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger("xhs_growth.models.retry")

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_DELAY = 1.0
_DEFAULT_MAX_DELAY = 30.0

# ponytail: provider SDK exceptions are optional installs and vary by provider.
# Match by class-name substring + status_code int — avoids importing every SDK.
_RETRYABLE_NAME_HINTS = (
    "ratelimit",
    "connection",
    "timeout",
    "internalserver",
    "apierror",  # generic; refined by status check below
    "transport",
)
_NON_RETRYABLE_NAME_HINTS = ("authentication", "badrequest", "permissiondenied", "notfound")


def _retry_config() -> tuple[int, float, float]:
    return (
        int(os.environ.get("XHS_LLM_MAX_RETRIES", str(_DEFAULT_MAX_RETRIES))),
        float(os.environ.get("XHS_LLM_RETRY_BASE_DELAY", str(_DEFAULT_BASE_DELAY))),
        float(os.environ.get("XHS_LLM_RETRY_MAX_DELAY", str(_DEFAULT_MAX_DELAY))),
    )


def _status_of(exc: BaseException) -> int | None:
    """Extract HTTP status code from a provider/httpx exception, if present."""

    for attr in ("status_code", "statusCode"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    # openai/anthropic APIStatusError expose .response.status_code
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _is_retryable(exc: BaseException) -> bool:
    """Decide if an exception is worth retrying.

    Status code takes precedence (429/5xx → retry, other 4xx → no). Falls back
    to class-name hints for SDK errors that don't carry a status (connection /
    timeout / transport).
    """

    status = _status_of(exc)
    if status is not None:
        if status == 429 or status >= 500:
            return True
        if 400 <= status < 500:
            return False  # client error, retrying won't help

    name = type(exc).__name__.lower()
    if any(hint in name for hint in _NON_RETRYABLE_NAME_HINTS):
        return False
    return any(hint in name for hint in _RETRYABLE_NAME_HINTS)


def _backoff_seconds(attempt: int, base: float, max_delay: float) -> float:
    delay = min(max_delay, base * (2**attempt))
    # ponytail: full jitter avoids thundering herd on shared rate limits
    return random.uniform(0, delay)


async def _sleep(attempt: int, base: float, max_delay: float) -> None:
    await asyncio.sleep(_backoff_seconds(attempt, base, max_delay))


class _RetryChatModel:
    """Delegate-everything wrapper that retries ainvoke/invoke."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        max_retries, base, max_delay = _retry_config()
        last_exc: BaseException | None = None
        for attempt in range(max_retries + 1):
            try:
                return await self._model.ainvoke(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc) or attempt == max_retries:
                    raise
                delay = _backoff_seconds(attempt, base, max_delay)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.2fs: %s: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    type(exc).__name__,
                    exc,
                )
                await asyncio.sleep(delay)
        assert last_exc is not None  # pragma: no cover
        raise last_exc  # pragma: no cover

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        max_retries, base, max_delay = _retry_config()
        last_exc: BaseException | None = None
        for attempt in range(max_retries + 1):
            try:
                return self._model.invoke(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc) or attempt == max_retries:
                    raise
                delay = _backoff_seconds(attempt, base, max_delay)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.2fs: %s: %s",
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    type(exc).__name__,
                    exc,
                )
                time.sleep(delay)
        assert last_exc is not None  # pragma: no cover
        raise last_exc  # pragma: no cover

    def __getattr__(self, name: str) -> Any:
        # Delegate stream / bind / stream_messages / anything else to the model.
        return getattr(self._model, name)


def with_retry(model: BaseChatModel) -> BaseChatModel:
    """Wrap a chat model so ainvoke/invoke retry on transient errors.

    Returns a duck-typed object that proxies every attribute to the underlying
    model but overrides ainvoke/invoke with backoff. Typed as BaseChatModel so
    existing call sites keep their annotations.
    """

    return _RetryChatModel(model)  # type: ignore[return-value]
