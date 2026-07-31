"""Process-local exclusive lock for per-account CDP browser use.

Multiple features attach to the same persistent Chrome via ``connect_over_cdp``
(publisher, engagement, creator-stats, QR login). Concurrent attachments pile
up pages and look like automation. This module serializes CDP work per
account/endpoint inside one process.

Cross-process coordination still relies on Chrome's own target list + the
creator-stats advisory lock; this gate covers the common single-worker case.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("xhs_growth.cdp_session_lock")

_locks: dict[str, asyncio.Lock] = {}
_holders: dict[str, str] = {}
_lock_guard = asyncio.Lock()


class CdpSessionBusyError(RuntimeError):
    """Raised when another feature already holds the CDP session."""

    def __init__(self, key: str, holder: str = "") -> None:
        self.key = key
        self.holder = holder or "unknown"
        super().__init__(f"CDP session busy for {key!r} (held by {self.holder})")


def _normalize_key(*, account_id: str = "", cdp_endpoint: str = "") -> str:
    account_id = (account_id or "").strip()
    if account_id:
        return f"account:{account_id}"
    endpoint = (cdp_endpoint or "").strip()
    if not endpoint:
        return "default"
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port
        if port is not None:
            return f"cdp:{host}:{port}"
    except ValueError:
        pass
    return f"cdp:{endpoint}"


async def _get_lock(key: str) -> asyncio.Lock:
    async with _lock_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


def cdp_session_holder(*, account_id: str = "", cdp_endpoint: str = "") -> str | None:
    """Return the current holder label, or None when free."""
    key = _normalize_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    if key not in _holders:
        return None
    return _holders.get(key)


def is_cdp_session_busy(*, account_id: str = "", cdp_endpoint: str = "") -> bool:
    """Best-effort busy check (may race; use hold_cdp_session for exclusive use)."""
    key = _normalize_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    lock = _locks.get(key)
    return bool(lock is not None and lock.locked())


@asynccontextmanager
async def hold_cdp_session(
    *,
    account_id: str = "",
    cdp_endpoint: str = "",
    owner: str = "unknown",
    wait: bool = True,
    timeout: float | None = 300.0,
) -> AsyncIterator[str]:
    """Acquire exclusive CDP use for one account/endpoint.

    ``wait=False``: try briefly and raise ``CdpSessionBusyError`` if held
    (scheduler path — skip rather than queue a crawl behind publish).

    ``wait=True``: wait up to ``timeout`` seconds (publisher/engagement).
    """
    key = _normalize_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    lock = await _get_lock(key)
    owner_label = (owner or "unknown").strip() or "unknown"
    acquired = False
    try:
        if wait:
            wait_s = 300.0 if timeout is None else max(0.05, float(timeout))
            try:
                await asyncio.wait_for(lock.acquire(), timeout=wait_s)
            except TimeoutError as exc:
                holder = _holders.get(key) or "unknown"
                raise CdpSessionBusyError(key, holder) from exc
        else:
            # Non-blocking-ish: if already locked, fail fast; else short wait.
            if lock.locked():
                raise CdpSessionBusyError(key, _holders.get(key) or "unknown")
            try:
                await asyncio.wait_for(lock.acquire(), timeout=0.05)
            except TimeoutError as exc:
                raise CdpSessionBusyError(key, _holders.get(key) or "unknown") from exc
        acquired = True
        _holders[key] = owner_label
        logger.debug("cdp session acquired key=%s owner=%s", key, owner_label)
        yield key
    finally:
        if acquired:
            if _holders.get(key) == owner_label:
                _holders.pop(key, None)
            with contextlib.suppress(RuntimeError):
                lock.release()
            logger.debug("cdp session released key=%s owner=%s", key, owner_label)


def reset_cdp_session_locks_for_tests() -> None:
    """Test helper — drop all process-local CDP locks."""
    _locks.clear()
    _holders.clear()


__all__ = [
    "CdpSessionBusyError",
    "cdp_session_holder",
    "hold_cdp_session",
    "is_cdp_session_busy",
    "reset_cdp_session_locks_for_tests",
]
