"""Exclusive lock for per-account CDP browser use (process-local + optional PG).

Multiple features attach to the same persistent Chrome via ``connect_over_cdp``
(publisher, engagement, creator-stats, QR login). Concurrent attachments pile
up pages and look like automation.

Layers:
  1. Process-local ``asyncio.Lock`` — fast path for single-worker deployments.
  2. PostgreSQL session-level advisory lock — coordinates Uvicorn workers /
     multi-process hosts. Held connection is checked out for the lease duration
     so a crash auto-releases the lock when the backend disconnects.

When Postgres is unavailable the process-local lock still works (degraded).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("xhs_growth.cdp_session_lock")

# Namespace for two-int advisory locks (avoids colliding with other hashtext uses).
_PG_LOCK_CLASS = 8910

_locks: dict[str, asyncio.Lock] = {}
_holders: dict[str, str] = {}
_held_since_mono: dict[str, float] = {}
_held_since_wall: dict[str, str] = {}
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
    """Return the current *local* holder label, or None when free in this process."""
    key = _normalize_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    return _holders.get(key)


def snapshot_cdp_sessions() -> list[dict[str, Any]]:
    """Operator-facing snapshot of local CDP holds (this worker only)."""
    now_mono = time.monotonic()
    rows: list[dict[str, Any]] = []
    for key, holder in list(_holders.items()):
        since_mono = _held_since_mono.get(key)
        held_for = (
            round(max(0.0, now_mono - since_mono), 1) if since_mono is not None else None
        )
        rows.append(
            {
                "key": key,
                "holder": holder,
                "held_since": _held_since_wall.get(key),
                "held_for_seconds": held_for,
            }
        )
    rows.sort(key=lambda r: str(r.get("key") or ""))
    return rows


def is_cdp_session_busy(*, account_id: str = "", cdp_endpoint: str = "") -> bool:
    """Best-effort busy check (local lock only — use async probe for PG)."""
    key = _normalize_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    lock = _locks.get(key)
    return bool(lock is not None and lock.locked())


async def is_cdp_session_busy_async(
    *, account_id: str = "", cdp_endpoint: str = ""
) -> bool:
    """Busy check including a non-destructive Postgres advisory-lock probe."""
    key = _normalize_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    if is_cdp_session_busy(account_id=account_id, cdp_endpoint=cdp_endpoint):
        return True
    return await _pg_lock_held(key)


async def _pg_lock_held(key: str) -> bool:
    """True when another backend session holds the CDP advisory lock."""
    try:
        from backend.db.pool import get_pool, is_pool_ready

        if not is_pool_ready():
            return False
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            # Try to take and immediately release — if we cannot take, remote holds.
            await cur.execute(
                "SELECT pg_try_advisory_lock(%s, hashtext(%s))",
                (_PG_LOCK_CLASS, key),
            )
            row = await cur.fetchone()
            got = bool(row and row[0])
            if got:
                await cur.execute(
                    "SELECT pg_advisory_unlock(%s, hashtext(%s))",
                    (_PG_LOCK_CLASS, key),
                )
                return False
            return True
    except Exception:
        logger.debug("cdp pg busy-probe failed", exc_info=True)
        return False


class _PgAdvisoryHold:
    """Holds a pool connection that owns a session-level advisory lock."""

    def __init__(self, conn_cm: Any, conn: Any, key: str) -> None:
        self._conn_cm = conn_cm
        self._conn = conn
        self._key = key
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        with contextlib.suppress(Exception):
            async with self._conn.cursor() as cur:
                await cur.execute(
                    "SELECT pg_advisory_unlock(%s, hashtext(%s))",
                    (_PG_LOCK_CLASS, self._key),
                )
        with contextlib.suppress(Exception):
            await self._conn_cm.__aexit__(None, None, None)


async def _try_acquire_pg(key: str) -> tuple[str, _PgAdvisoryHold | None]:
    """Try once to take the distributed advisory lock.

    Returns ``(status, hold)`` where status is:
      - ``acquired`` — hold is non-None
      - ``busy`` — another session holds the lock
      - ``unavailable`` — pool down / probe failed (degrade to local-only)
    """
    try:
        from backend.db.pool import get_pool, is_pool_ready

        if not is_pool_ready():
            return "unavailable", None
        pool = get_pool()
        conn_cm = pool.connection()
        conn = await conn_cm.__aenter__()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT pg_try_advisory_lock(%s, hashtext(%s))",
                    (_PG_LOCK_CLASS, key),
                )
                row = await cur.fetchone()
                got = bool(row and row[0])
            if not got:
                await conn_cm.__aexit__(None, None, None)
                return "busy", None
            return "acquired", _PgAdvisoryHold(conn_cm, conn, key)
        except Exception:
            with contextlib.suppress(Exception):
                await conn_cm.__aexit__(None, None, None)
            raise
    except Exception:
        logger.debug("cdp pg lock acquire failed (degrade to local)", exc_info=True)
        return "unavailable", None


async def _acquire_pg_with_policy(
    key: str, *, wait: bool, timeout: float
) -> _PgAdvisoryHold | None:
    """Acquire PG lock per wait policy.

    Returns:
      - ``_PgAdvisoryHold`` when distributed lock acquired
      - ``None`` when pool unavailable (caller continues with local only)

    Raises:
      ``CdpSessionBusyError`` when pool is up but lock cannot be taken in time.
    """
    deadline = time.monotonic() + max(0.05, timeout)
    while True:
        status, hold = await _try_acquire_pg(key)
        if status == "acquired":
            return hold
        if status == "unavailable":
            return None
        # busy
        if not wait:
            raise CdpSessionBusyError(key, "remote")
        if time.monotonic() >= deadline:
            raise CdpSessionBusyError(key, "remote")
        await asyncio.sleep(0.15)


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

    ``wait=True``: wait up to ``timeout`` seconds (publisher/engagement/login).
    """
    key = _normalize_key(account_id=account_id, cdp_endpoint=cdp_endpoint)
    lock = await _get_lock(key)
    owner_label = (owner or "unknown").strip() or "unknown"
    wait_s = 300.0 if timeout is None else max(0.05, float(timeout))
    local_acquired = False
    session_entered = False
    pg_hold: _PgAdvisoryHold | None = None
    try:
        # 0) Cross-feature cool-down after the previous CDP session released.
        await _respect_browser_action_cooldown(
            account_id=account_id,
            cdp_endpoint=cdp_endpoint,
            owner=owner_label,
            wait=wait,
            timeout=wait_s,
        )

        # 1) Process-local lock first (cheap).
        if wait:
            try:
                await asyncio.wait_for(lock.acquire(), timeout=wait_s)
            except TimeoutError as exc:
                holder = _holders.get(key) or "unknown"
                raise CdpSessionBusyError(key, holder) from exc
        else:
            if lock.locked():
                raise CdpSessionBusyError(key, _holders.get(key) or "unknown")
            try:
                await asyncio.wait_for(lock.acquire(), timeout=0.05)
            except TimeoutError as exc:
                raise CdpSessionBusyError(key, _holders.get(key) or "unknown") from exc
        local_acquired = True
        _holders[key] = owner_label
        _held_since_mono[key] = time.monotonic()
        try:
            from datetime import UTC, datetime

            _held_since_wall[key] = datetime.now(UTC).isoformat()
        except Exception:
            _held_since_wall[key] = ""

        # 2) Distributed advisory lock (optional; required when pool is up).
        remaining = wait_s
        if wait:
            # Account for time already spent on local lock.
            remaining = max(0.05, wait_s * 0.9)
        pg_hold = await _acquire_pg_with_policy(key, wait=wait, timeout=remaining)

        logger.debug(
            "cdp session acquired key=%s owner=%s pg=%s",
            key,
            owner_label,
            pg_hold is not None,
        )
        session_entered = True
        yield key
    finally:
        if pg_hold is not None:
            with contextlib.suppress(Exception):
                await pg_hold.release()
        if local_acquired:
            if _holders.get(key) == owner_label:
                _holders.pop(key, None)
                _held_since_mono.pop(key, None)
                _held_since_wall.pop(key, None)
            with contextlib.suppress(RuntimeError):
                lock.release()
            # Cool-down only after a fully established exclusive session.
            if session_entered:
                with contextlib.suppress(Exception):
                    from backend.services.xhs_risk_gate import note_browser_action

                    note_browser_action(
                        account_id=account_id,
                        cdp_endpoint=cdp_endpoint,
                        owner=owner_label,
                    )
            logger.debug("cdp session released key=%s owner=%s", key, owner_label)


async def _respect_browser_action_cooldown(
    *,
    account_id: str,
    cdp_endpoint: str,
    owner: str,
    wait: bool,
    timeout: float,
) -> None:
    """Enforce cross-feature gap after previous CDP use on this profile."""
    try:
        from backend.services.xhs_risk_gate import check_browser_action_allowed
    except Exception:
        return
    block = check_browser_action_allowed(
        account_id=account_id, cdp_endpoint=cdp_endpoint, owner=owner
    )
    if block is None:
        return
    wait_s = int(block.retry_after_seconds or 0)
    if not wait:
        raise CdpSessionBusyError(
            _normalize_key(account_id=account_id, cdp_endpoint=cdp_endpoint),
            f"cooldown:{block.risk_code}",
        )
    # Cap sleep by the outer acquire timeout so callers still fail closed.
    sleep_s = min(float(max(0, wait_s)), max(0.0, timeout))
    if sleep_s > 0:
        logger.info(
            "cdp session cool-down owner=%s sleep=%.1fs reason=%s",
            owner,
            sleep_s,
            block.reason,
        )
        await asyncio.sleep(sleep_s)
    # Re-check once; if still blocked, fail rather than busy-loop.
    block2 = check_browser_action_allowed(
        account_id=account_id, cdp_endpoint=cdp_endpoint, owner=owner
    )
    if block2 is not None:
        raise CdpSessionBusyError(
            _normalize_key(account_id=account_id, cdp_endpoint=cdp_endpoint),
            f"cooldown:{block2.risk_code}",
        )


def reset_cdp_session_locks_for_tests() -> None:
    """Test helper — drop all process-local CDP locks."""
    _locks.clear()
    _holders.clear()
    _held_since_mono.clear()
    _held_since_wall.clear()


__all__ = [
    "CdpSessionBusyError",
    "cdp_session_holder",
    "hold_cdp_session",
    "is_cdp_session_busy",
    "is_cdp_session_busy_async",
    "reset_cdp_session_locks_for_tests",
    "snapshot_cdp_sessions",
]
