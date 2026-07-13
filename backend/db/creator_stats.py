"""Local persistence for creator-center account/note statistics.

Uses Postgres when the app pool is ready; falls back to a process-local
in-memory store so dry-run/fixture paths work without a database.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.db.pool import get_pool, is_pool_ready
from backend.services.creator_stats.types import AccountStatsOverview, NoteStats

logger = logging.getLogger("xhs_growth.db.creator_stats")

# ── In-memory fallback (tests / no Postgres) ────────────────────────────────

_mem_accounts: dict[str, dict[str, Any]] = {}
_mem_notes: dict[str, dict[str, dict[str, Any]]] = {}  # account_id -> note_id -> row


def _reset_memory_store() -> None:
    """Test helper: clear in-memory rows."""
    _mem_accounts.clear()
    _mem_notes.clear()


_CREATE_ACCOUNT_SQL = """
CREATE TABLE IF NOT EXISTS creator_account_stats (
    account_id   TEXT PRIMARY KEY,
    views        INTEGER NOT NULL DEFAULT 0,
    likes        INTEGER NOT NULL DEFAULT 0,
    comments     INTEGER NOT NULL DEFAULT 0,
    collects     INTEGER NOT NULL DEFAULT 0,
    shares       INTEGER NOT NULL DEFAULT 0,
    fans         INTEGER NOT NULL DEFAULT 0,
    note_count   INTEGER NOT NULL DEFAULT 0,
    period       TEXT NOT NULL DEFAULT '30d',
    synced_at    TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT 'creator_statistics',
    raw_json     TEXT NOT NULL DEFAULT '{}'
);
"""

_CREATE_NOTE_SQL = """
CREATE TABLE IF NOT EXISTS creator_note_stats (
    account_id      TEXT NOT NULL,
    note_id         TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    body_text       TEXT NOT NULL DEFAULT '',
    views           INTEGER NOT NULL DEFAULT 0,
    likes           INTEGER NOT NULL DEFAULT 0,
    comments        INTEGER NOT NULL DEFAULT 0,
    collects        INTEGER NOT NULL DEFAULT 0,
    shares          INTEGER NOT NULL DEFAULT 0,
    published_at    TEXT NOT NULL DEFAULT '',
    content_type    TEXT NOT NULL DEFAULT 'note',
    tags_json       TEXT NOT NULL DEFAULT '[]',
    cover_url       TEXT NOT NULL DEFAULT '',
    engagement_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    synced_at       TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'creator_statistics',
    raw_json        TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (account_id, note_id)
);
"""

_CREATE_NOTE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_creator_note_stats_account
    ON creator_note_stats (account_id);
CREATE INDEX IF NOT EXISTS idx_creator_note_stats_engagement
    ON creator_note_stats (account_id, engagement_rate DESC);
"""

_ADD_BODY_TEXT_COL_SQL = (
    "ALTER TABLE creator_note_stats ADD COLUMN IF NOT EXISTS body_text TEXT NOT NULL DEFAULT ''"
)

_UPSERT_ACCOUNT_SQL = """
INSERT INTO creator_account_stats (
    account_id, views, likes, comments, collects, shares,
    fans, note_count, period, synced_at, source, raw_json
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (account_id) DO UPDATE SET
    views = EXCLUDED.views,
    likes = EXCLUDED.likes,
    comments = EXCLUDED.comments,
    collects = EXCLUDED.collects,
    shares = EXCLUDED.shares,
    fans = EXCLUDED.fans,
    note_count = EXCLUDED.note_count,
    period = EXCLUDED.period,
    synced_at = EXCLUDED.synced_at,
    source = EXCLUDED.source,
    raw_json = EXCLUDED.raw_json
"""

_UPSERT_NOTE_SQL = """
INSERT INTO creator_note_stats (
    account_id, note_id, title, body_text, views, likes, comments, collects,
    shares, published_at, content_type, tags_json, cover_url,
    engagement_rate, synced_at, source, raw_json
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (account_id, note_id) DO UPDATE SET
    title = EXCLUDED.title,
    body_text = EXCLUDED.body_text,
    views = EXCLUDED.views,
    likes = EXCLUDED.likes,
    comments = EXCLUDED.comments,
    collects = EXCLUDED.collects,
    shares = EXCLUDED.shares,
    published_at = EXCLUDED.published_at,
    content_type = EXCLUDED.content_type,
    tags_json = EXCLUDED.tags_json,
    cover_url = EXCLUDED.cover_url,
    engagement_rate = EXCLUDED.engagement_rate,
    synced_at = EXCLUDED.synced_at,
    source = EXCLUDED.source,
    raw_json = EXCLUDED.raw_json
"""


async def ensure_tables() -> None:
    """Create creator stats tables when Postgres is available."""
    if not is_pool_ready():
        logger.debug("creator_stats ensure_tables skipped: pool not ready")
        return
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_ACCOUNT_SQL)
        await conn.execute(_CREATE_NOTE_SQL)
        await conn.execute(_CREATE_NOTE_INDEX_SQL)
        # Upgrade path for pre-body_text tables
        await conn.execute(_ADD_BODY_TEXT_COL_SQL)
    logger.info("creator_stats tables ensured")


def _account_values(overview: AccountStatsOverview) -> tuple[Any, ...]:
    row = overview.to_dict()
    return (
        overview.account_id,
        overview.views,
        overview.likes,
        overview.comments,
        overview.collects,
        overview.shares,
        overview.fans,
        overview.note_count,
        overview.period,
        overview.synced_at,
        overview.source,
        json.dumps(row, ensure_ascii=False),
    )


def _note_values(note: NoteStats) -> tuple[Any, ...]:
    row = note.to_dict()
    return (
        note.account_id,
        note.note_id,
        note.title,
        note.body_text or "",
        note.views,
        note.likes,
        note.comments,
        note.collects,
        note.shares,
        note.published_at,
        note.content_type,
        json.dumps(note.tags, ensure_ascii=False),
        note.cover_url,
        note.engagement_rate,
        note.synced_at,
        note.source,
        json.dumps(row, ensure_ascii=False),
    )


async def _upsert_account_on_conn(conn: Any, overview: AccountStatsOverview) -> None:
    await conn.execute(_UPSERT_ACCOUNT_SQL, _account_values(overview))


async def _upsert_note_on_conn(conn: Any, note: NoteStats) -> bool:
    """Upsert a validated note through an existing transaction/connection."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT note_id FROM creator_note_stats WHERE account_id = %s AND note_id = %s",
            (note.account_id, note.note_id),
        )
        existing = await cur.fetchone()
    await conn.execute(_UPSERT_NOTE_SQL, _note_values(note))
    return existing is None


async def upsert_account_stats(overview: AccountStatsOverview) -> None:
    """Upsert account-level overview (idempotent by account_id)."""
    account_id = (overview.account_id or "").strip()
    if not account_id:
        logger.warning("upsert_account_stats skipped: empty account_id")
        return
    overview.account_id = account_id
    row = overview.to_dict()
    if not is_pool_ready():
        _mem_accounts[overview.account_id] = row
        return
    pool = get_pool()
    async with pool.connection() as conn:
        await _upsert_account_on_conn(conn, overview)


async def upsert_note_stats(note: NoteStats) -> bool:
    """Upsert a note stats row by (account_id, note_id).

    Returns True if this was an insert of a new note id (for import counts),
    False if it updated an existing row. Returns False without writing when
    account_id or note_id is blank (invalid row).
    """
    account_id = (note.account_id or "").strip()
    note_id = (note.note_id or "").strip()
    if not account_id or not note_id:
        logger.warning(
            "upsert_note_stats skipped: account_id=%r note_id=%r",
            note.account_id,
            note.note_id,
        )
        return False
    note.account_id = account_id
    note.note_id = note_id
    row = note.to_dict()
    if not is_pool_ready():
        bucket = _mem_notes.setdefault(note.account_id, {})
        is_new = note.note_id not in bucket
        bucket[note.note_id] = row
        return is_new

    pool = get_pool()
    async with pool.connection() as conn:
        return await _upsert_note_on_conn(conn, note)


async def upsert_notes(notes: list[NoteStats]) -> tuple[int, int]:
    """Upsert many notes. Returns (imported_new, updated).

    Invalid rows (blank account_id/note_id) are skipped and not counted.
    """
    if not is_pool_ready():
        imported = 0
        updated = 0
        for note in notes:
            if not (note.account_id or "").strip() or not (note.note_id or "").strip():
                continue
            is_new = await upsert_note_stats(note)
            if is_new:
                imported += 1
            else:
                updated += 1
        return imported, updated

    pool = get_pool()
    imported = 0
    updated = 0
    async with pool.connection() as conn:
        for note in notes:
            account_id = (note.account_id or "").strip()
            note_id = (note.note_id or "").strip()
            if not account_id or not note_id:
                continue
            note.account_id = account_id
            note.note_id = note_id
            if await _upsert_note_on_conn(conn, note):
                imported += 1
            else:
                updated += 1
    return imported, updated


async def upsert_bundle(
    bundle_account: AccountStatsOverview, notes: list[NoteStats]
) -> tuple[int, int]:
    """Atomically persist an account snapshot and its note rows.

    A successful fetch used to write the account row and every note through
    separate implicit transactions.  A failure halfway through left a current
    account overview paired with a partial note set.  The live Note Manager
    response is an account-wide snapshot, so these writes must commit together.
    """
    account_id = (bundle_account.account_id or "").strip()
    if not account_id:
        logger.warning("upsert_bundle skipped: empty account_id")
        return 0, 0
    bundle_account.account_id = account_id

    if not is_pool_ready():
        await upsert_account_stats(bundle_account)
        return await upsert_notes(notes)

    pool = get_pool()
    imported = 0
    updated = 0
    async with pool.connection() as conn, conn.transaction():
        await _upsert_account_on_conn(conn, bundle_account)
        for note in notes:
            note_account_id = (note.account_id or "").strip()
            note_id = (note.note_id or "").strip()
            if not note_account_id or not note_id:
                continue
            note.account_id = note_account_id
            note.note_id = note_id
            if await _upsert_note_on_conn(conn, note):
                imported += 1
            else:
                updated += 1
    return imported, updated


async def get_account_stats(account_id: str) -> AccountStatsOverview | None:
    account_id = (account_id or "").strip()
    if not account_id:
        return None
    if not is_pool_ready():
        mem = _mem_accounts.get(account_id)
        return AccountStatsOverview.from_dict(mem) if mem else None
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT account_id, views, likes, comments, collects, shares,
                   fans, note_count, period, synced_at, source
            FROM creator_account_stats WHERE account_id = %s
            """,
            (account_id,),
        )
        row: Any = await cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return AccountStatsOverview.from_dict(row)
    return AccountStatsOverview(
        account_id=row[0],
        views=row[1],
        likes=row[2],
        comments=row[3],
        collects=row[4],
        shares=row[5],
        fans=row[6],
        note_count=row[7],
        period=row[8],
        synced_at=row[9],
        source=row[10],
    )


def _note_from_row(row: Any) -> NoteStats:
    if isinstance(row, dict):
        tags = row.get("tags") or row.get("tags_json") or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []
        data = dict(row)
        data["tags"] = tags
        if not data.get("body_text") and data.get("raw_json"):
            # Fallback: older rows may only have body in raw_json payload
            try:
                raw = data["raw_json"]
                if isinstance(raw, str):
                    raw = json.loads(raw)
                if isinstance(raw, dict) and raw.get("body_text"):
                    data["body_text"] = raw["body_text"]
            except (TypeError, json.JSONDecodeError):
                pass
        return NoteStats.from_dict(data)
    # Tuple order must match list/get SELECT columns
    tags_raw = row[11]
    if isinstance(tags_raw, str):
        try:
            tags = json.loads(tags_raw)
        except json.JSONDecodeError:
            tags = []
    else:
        tags = tags_raw or []
    return NoteStats(
        account_id=row[0],
        note_id=row[1],
        title=row[2],
        body_text=str(row[3] or ""),
        views=row[4],
        likes=row[5],
        comments=row[6],
        collects=row[7],
        shares=row[8],
        published_at=row[9],
        content_type=row[10],
        tags=list(tags),
        cover_url=row[12],
        engagement_rate=float(row[13] or 0),
        synced_at=row[14],
        source=row[15],
    )


async def count_note_stats(account_id: str) -> int:
    """Total persisted notes for an account (ignores list limit)."""
    account_id = (account_id or "").strip()
    if not account_id:
        return 0
    if not is_pool_ready():
        return len(_mem_notes.get(account_id, {}))
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) FROM creator_note_stats WHERE account_id = %s",
            (account_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(next(iter(row.values()), 0) or 0)
    return int(row[0] or 0)


async def list_note_stats(
    account_id: str, *, limit: int = 100, order_by: str = "engagement"
) -> list[NoteStats]:
    """List persisted notes for an account."""
    account_id = (account_id or "").strip()
    if not account_id:
        return []
    # Clamp limit so callers cannot pass 0 / negative and get empty pages silently
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 500))

    if not is_pool_ready():
        bucket = _mem_notes.get(account_id, {})
        notes = [NoteStats.from_dict(v) for v in bucket.values()]
        if order_by == "published":
            notes.sort(key=lambda n: n.published_at, reverse=True)
        else:
            notes.sort(key=lambda n: n.engagement_rate, reverse=True)
        return notes[:limit]

    order_sql = (
        "published_at DESC" if order_by == "published" else "engagement_rate DESC, views DESC"
    )
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT account_id, note_id, title, body_text, views, likes, comments, collects,
                   shares, published_at, content_type, tags_json, cover_url,
                   engagement_rate, synced_at, source
            FROM creator_note_stats
            WHERE account_id = %s
            ORDER BY {order_sql}
            LIMIT %s
            """,
            (account_id, limit),
        )
        rows = await cur.fetchall()
    return [_note_from_row(r) for r in rows]


async def get_note_stats(account_id: str, note_id: str) -> NoteStats | None:
    account_id = (account_id or "").strip()
    note_id = (note_id or "").strip()
    if not account_id or not note_id:
        return None
    if not is_pool_ready():
        mem = _mem_notes.get(account_id, {}).get(note_id)
        return NoteStats.from_dict(mem) if mem else None
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT account_id, note_id, title, body_text, views, likes, comments, collects,
                   shares, published_at, content_type, tags_json, cover_url,
                   engagement_rate, synced_at, source
            FROM creator_note_stats
            WHERE account_id = %s AND note_id = %s
            """,
            (account_id, note_id),
        )
        row: Any = await cur.fetchone()
    if not row:
        return None
    return _note_from_row(row)
