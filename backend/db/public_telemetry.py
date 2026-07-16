"""Privacy-safe storage and aggregation for public UX telemetry.

Only categorical interaction properties and bounded timings are retained. No
public-case identifiers, account identifiers, URLs, content, or raw errors are
accepted by the API layer that calls this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from psycopg.rows import dict_row

from backend.db.pool import get_pool, is_pool_ready

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public_ux_events (
    id              BIGSERIAL PRIMARY KEY,
    event_name      TEXT NOT NULL,
    event_version   INTEGER NOT NULL DEFAULT 1,
    viewport        TEXT NOT NULL DEFAULT 'desktop',
    source          TEXT,
    status          TEXT,
    mode            TEXT,
    phase           TEXT,
    error_type      TEXT,
    view_mode       TEXT,
    step_number     INTEGER,
    count_value     INTEGER,
    restored        BOOLEAN,
    cached          BOOLEAN,
    has_steps       BOOLEAN,
    has_result      BOOLEAN,
    authenticated   BOOLEAN,
    has_public_id   BOOLEAN,
    has_step        BOOLEAN,
    duration_ms     INTEGER,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_public_ux_events_received_at
    ON public_ux_events (received_at);
CREATE INDEX IF NOT EXISTS idx_public_ux_events_event_name
    ON public_ux_events (event_name, received_at);
"""

# ponytail: ADD COLUMN IF NOT EXISTS per column added after launch.
# CREATE TABLE IF NOT EXISTS won't backfill columns onto pre-existing tables,
# so summarize_events (which SELECTs these) would UndefinedColumn on old deploys.
# Append here when a new categorical dimension is added to _CREATE_TABLE_SQL.
_ADD_COLUMN_SQL = (
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS view_mode TEXT",
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS step_number INTEGER",
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS count_value INTEGER",
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS restored BOOLEAN",
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS cached BOOLEAN",
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS has_steps BOOLEAN",
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS has_result BOOLEAN",
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS authenticated BOOLEAN",
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS has_public_id BOOLEAN",
    "ALTER TABLE public_ux_events ADD COLUMN IF NOT EXISTS has_step BOOLEAN",
)


async def ensure_tables() -> None:
    """Create the telemetry table and indexes during the normal DB bootstrap."""

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_TABLE_SQL)
        await conn.execute(_CREATE_INDEX_SQL)
        for sql in _ADD_COLUMN_SQL:
            await conn.execute(sql)


async def record_event(event: Mapping[str, Any]) -> bool:
    """Persist one already-validated, privacy-safe event.

    The API deliberately passes a flat allowlisted mapping. This function
    still enumerates every column so a future caller cannot accidentally turn
    an arbitrary request field into SQL data.
    """

    if not is_pool_ready():
        return False

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO public_ux_events (
                event_name, event_version, viewport, source, status, mode,
                phase, error_type, view_mode, step_number, count_value,
                restored, cached, has_steps, has_result, authenticated,
                has_public_id, has_step, duration_ms
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                event.get("event"),
                event.get("event_version", 1),
                event.get("viewport", "desktop"),
                event.get("source"),
                event.get("status"),
                event.get("mode"),
                event.get("phase"),
                event.get("error_type"),
                event.get("view"),
                event.get("step"),
                event.get("count"),
                event.get("restored"),
                event.get("cached"),
                event.get("has_steps"),
                event.get("has_result"),
                event.get("authenticated"),
                event.get("has_public_id"),
                event.get("has_step"),
                event.get("duration_ms"),
            ),
        )
        # Keep the receiver bounded without retaining a visitor identifier.
        await conn.execute(
            "DELETE FROM public_ux_events "
            "WHERE received_at < CURRENT_TIMESTAMP - INTERVAL '30 days'"
        )
    return True


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


async def summarize_events(days: int = 7, event_name: str | None = None) -> list[dict[str, Any]]:
    """Return aggregate rows for an operator dashboard, never raw events."""

    if not is_pool_ready():
        return []

    days = max(1, min(int(days), 30))
    conditions = ["received_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')"]
    params: list[Any] = [days]
    if event_name:
        conditions.append("event_name = %s")
        params.append(event_name)

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
                SELECT
                    event_name,
                    viewport,
                    source,
                    status,
                    mode,
                    phase,
                    error_type,
                    view_mode,
                    cached,
                    COUNT(*)::INTEGER AS event_count,
                    COUNT(duration_ms)::INTEGER AS measured_count,
                    percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms)
                        FILTER (WHERE duration_ms IS NOT NULL) AS p50_duration_ms,
                    percentile_cont(0.75) WITHIN GROUP (ORDER BY duration_ms)
                        FILTER (WHERE duration_ms IS NOT NULL) AS p75_duration_ms
                FROM public_ux_events
                WHERE {" AND ".join(conditions)}
                GROUP BY event_name, viewport, source, status, mode, phase,
                         error_type, view_mode, cached
                ORDER BY event_count DESC, event_name ASC
                """,
            params,
        )
        rows = await cur.fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["p50_duration_ms"] = _number(item.get("p50_duration_ms"))
        item["p75_duration_ms"] = _number(item.get("p75_duration_ms"))
        result.append(item)
    return result
