"""PostgreSQL connection pool management."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # AsyncConnectionPool is constructed only in init_pool; importing
    # psycopg_pool at module load pulls psycopg (~900ms) onto every app
    # cold start. Deferred — the class is resolved at first init_pool call.
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger("xhs_growth.db.pool")

_pool: AsyncConnectionPool | None = None


def _conn_string() -> str:
    return os.environ.get("POSTGRES_URI", "")


async def init_pool() -> AsyncConnectionPool:
    """Initialize the shared connection pool. Called once at app startup."""
    global _pool
    from psycopg_pool import AsyncConnectionPool

    conn_string = _conn_string()
    if not conn_string:
        raise RuntimeError("POSTGRES_URI is not configured")

    _pool = AsyncConnectionPool(conn_string, min_size=2, max_size=10, open=False)
    await _pool.open()
    logger.info("DB connection pool opened (min=2, max=10)")
    return _pool


async def close_pool() -> None:
    """Close the connection pool. Called at app shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("DB connection pool closed")


def get_pool() -> AsyncConnectionPool:
    """Return the active pool or raise if not initialized."""
    if _pool is None:
        raise RuntimeError("DB connection pool not initialized")
    return _pool


def is_pool_ready() -> bool:
    return _pool is not None and not _pool._closed
