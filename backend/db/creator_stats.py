"""Local persistence for creator-center account/note statistics.

Uses Postgres when the app pool is ready; falls back to a process-local
in-memory store so dry-run/fixture paths work without a database.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from backend.db.pool import get_pool, is_pool_ready
from backend.services.creator_stats.types import AccountStatsOverview, NoteStats, NoteStatsPage
from backend.services.quality_consistency import snapshot_id as build_snapshot_id
from backend.services.quality_consistency import version_digest

logger = logging.getLogger("xhs_growth.db.creator_stats")

# ── In-memory fallback (tests / no Postgres) ────────────────────────────────

_mem_accounts: dict[str, dict[str, Any]] = {}
_mem_notes: dict[str, dict[str, dict[str, Any]]] = {}  # account_id -> note_id -> row

_PROFILE_FIELD_NAMES = (
    "creator_user_id",
    "creator_name",
    "red_id",
    "avatar_url",
    "bio",
    "creator_role",
    "zone",
)


_CREATE_ACCOUNT_SQL = """
CREATE TABLE IF NOT EXISTS creator_account_stats (
    account_id       TEXT PRIMARY KEY,
    creator_user_id  TEXT NOT NULL DEFAULT '',
    creator_name     TEXT NOT NULL DEFAULT '',
    red_id           TEXT NOT NULL DEFAULT '',
    avatar_url       TEXT NOT NULL DEFAULT '',
    bio              TEXT NOT NULL DEFAULT '',
    creator_role     TEXT NOT NULL DEFAULT '',
    zone             TEXT NOT NULL DEFAULT '',
    views            INTEGER NOT NULL DEFAULT 0,
    likes            INTEGER NOT NULL DEFAULT 0,
    comments         INTEGER NOT NULL DEFAULT 0,
    collects         INTEGER NOT NULL DEFAULT 0,
    shares           INTEGER NOT NULL DEFAULT 0,
    fans             INTEGER NOT NULL DEFAULT 0,
    note_count       INTEGER NOT NULL DEFAULT 0,
    period           TEXT NOT NULL DEFAULT '30d',
    synced_at        TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL DEFAULT 'creator_statistics',
    raw_json         TEXT NOT NULL DEFAULT '{}'
);
"""

_CREATE_SCHEDULER_STATE_SQL = """
CREATE TABLE IF NOT EXISTS creator_stats_scheduler_state (
    key_name   TEXT PRIMARY KEY,
    value_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT ''
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
CREATE INDEX IF NOT EXISTS idx_creator_note_stats_published
    ON creator_note_stats (account_id, published_at DESC, note_id DESC);
"""

_ADD_BODY_TEXT_COL_SQL = (
    "ALTER TABLE creator_note_stats ADD COLUMN IF NOT EXISTS body_text TEXT NOT NULL DEFAULT ''"
)

_ADD_PROFILE_COLUMNS_SQL = (
    "ALTER TABLE creator_account_stats "
    "ADD COLUMN IF NOT EXISTS creator_user_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE creator_account_stats "
    "ADD COLUMN IF NOT EXISTS creator_name TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE creator_account_stats ADD COLUMN IF NOT EXISTS red_id TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE creator_account_stats "
    "ADD COLUMN IF NOT EXISTS avatar_url TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE creator_account_stats ADD COLUMN IF NOT EXISTS bio TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE creator_account_stats "
    "ADD COLUMN IF NOT EXISTS creator_role TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE creator_account_stats ADD COLUMN IF NOT EXISTS zone TEXT NOT NULL DEFAULT ''",
)

_UPSERT_ACCOUNT_SQL = """
INSERT INTO creator_account_stats AS stored (
    account_id, creator_user_id, creator_name, red_id, avatar_url, bio, creator_role, zone,
    views, likes, comments, collects, shares, fans, note_count, period, synced_at, source,
    raw_json
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (account_id) DO UPDATE SET
    creator_user_id = COALESCE(NULLIF(EXCLUDED.creator_user_id, ''), stored.creator_user_id),
    creator_name = COALESCE(NULLIF(EXCLUDED.creator_name, ''), stored.creator_name),
    red_id = COALESCE(NULLIF(EXCLUDED.red_id, ''), stored.red_id),
    avatar_url = COALESCE(NULLIF(EXCLUDED.avatar_url, ''), stored.avatar_url),
    bio = COALESCE(NULLIF(EXCLUDED.bio, ''), stored.bio),
    creator_role = COALESCE(NULLIF(EXCLUDED.creator_role, ''), stored.creator_role),
    zone = COALESCE(NULLIF(EXCLUDED.zone, ''), stored.zone),
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

_ACCOUNT_STATS_SELECT_SQL = """
SELECT account_id, creator_user_id, creator_name, red_id, avatar_url, bio,
       creator_role, zone, views, likes, comments, collects, shares,
       fans, note_count, period, synced_at, source, raw_json
FROM creator_account_stats WHERE account_id = %s
"""

_NOTE_STATS_SELECT_SQL = """
SELECT account_id, note_id, title, body_text, views, likes, comments, collects,
       shares, published_at, content_type, tags_json, cover_url,
       engagement_rate, synced_at, source, raw_json
FROM creator_note_stats
WHERE account_id = %s
ORDER BY published_at ASC, note_id ASC
"""

# A transaction-level snapshot is required because READ COMMITTED would give
# each SELECT its own statement snapshot even when the same connection is
# reused.  Page rows and their complete-population metadata must be one fact.
_REPEATABLE_READ_SQL = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"


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
        await conn.execute(_CREATE_SCHEDULER_STATE_SQL)
        # Upgrade path for pre-body_text tables
        await conn.execute(_ADD_BODY_TEXT_COL_SQL)
        for sql in _ADD_PROFILE_COLUMNS_SQL:
            await conn.execute(sql)
    logger.info("creator_stats tables ensured")


# ── Scheduler durable state (anti-risk budget across restarts) ───────────────

_SCHEDULER_SUCCESS_KEY = "success_history"
_mem_scheduler_state: dict[str, dict[str, Any]] = {}


def _normalize_scheduler_state(data: dict[str, Any] | None) -> dict[str, Any]:
    """Coerce durable scheduler JSON into a stable shape."""
    empty: dict[str, Any] = {
        "timestamps": [],
        "last_success_local_hour": None,
        "last_period": None,
        "risk_failures": [],
        "pause_until": None,
        "quiet_cycles_remaining": 0,
        "soft_risk_signals": [],
    }
    if not isinstance(data, dict):
        return empty
    timestamps = data.get("timestamps")
    if not isinstance(timestamps, list):
        timestamps = []
    hour = data.get("last_success_local_hour")
    if hour is not None:
        try:
            hour = int(hour)
        except (TypeError, ValueError):
            hour = None
    risk = data.get("risk_failures")
    if not isinstance(risk, list):
        risk = []
    soft = data.get("soft_risk_signals")
    if not isinstance(soft, list):
        soft = []
    last_period = data.get("last_period")
    if last_period not in {"7d", "30d"}:
        last_period = None
    pause_until = data.get("pause_until")
    if pause_until is not None:
        pause_until = str(pause_until).strip() or None
    quiet = data.get("quiet_cycles_remaining")
    try:
        quiet_cycles = max(0, int(quiet or 0))
    except (TypeError, ValueError):
        quiet_cycles = 0
    return {
        "timestamps": [str(t) for t in timestamps if t],
        "last_success_local_hour": hour,
        "last_period": last_period,
        "risk_failures": [str(t) for t in risk if t],
        "pause_until": pause_until,
        "quiet_cycles_remaining": quiet_cycles,
        "soft_risk_signals": [str(t) for t in soft if t],
    }


async def load_scheduler_success_history() -> dict[str, Any]:
    """Load durable scheduler anti-risk state for the active-account crawler.

    Returns timestamps, last success hour, last period, risk failures,
    pause_until, quiet_cycles_remaining, soft_risk_signals.
    """
    empty = _normalize_scheduler_state(None)
    if not is_pool_ready():
        raw = _mem_scheduler_state.get(_SCHEDULER_SUCCESS_KEY)
        return _normalize_scheduler_state(raw if isinstance(raw, dict) else None)
    try:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT value_json FROM creator_stats_scheduler_state WHERE key_name = %s",
                (_SCHEDULER_SUCCESS_KEY,),
            )
            row = await cur.fetchone()
        if not row:
            return empty
        payload = row[0] if not isinstance(row, dict) else row.get("value_json")
        if isinstance(payload, str):
            data = json.loads(payload or "{}")
        elif isinstance(payload, dict):
            data = payload
        else:
            return empty
        return _normalize_scheduler_state(data if isinstance(data, dict) else None)
    except Exception:
        logger.debug("load_scheduler_success_history failed", exc_info=True)
        return empty


async def save_scheduler_success_history(
    timestamps: list[str],
    *,
    last_success_local_hour: int | None = None,
    last_period: str | None = None,
    risk_failures: list[str] | None = None,
    pause_until: str | None = None,
    quiet_cycles_remaining: int | None = None,
    soft_risk_signals: list[str] | None = None,
    merge_existing: bool = True,
) -> None:
    """Persist scheduler anti-risk state across deploy restarts."""
    from datetime import UTC, datetime

    existing: dict[str, Any] = {}
    if merge_existing:
        existing = await load_scheduler_success_history()
    payload = _normalize_scheduler_state(
        {
            "timestamps": list(timestamps),
            "last_success_local_hour": last_success_local_hour
            if last_success_local_hour is not None
            else existing.get("last_success_local_hour"),
            "last_period": last_period if last_period is not None else existing.get("last_period"),
            "risk_failures": list(risk_failures)
            if risk_failures is not None
            else list(existing.get("risk_failures") or []),
            "pause_until": pause_until if pause_until is not None else existing.get("pause_until"),
            "quiet_cycles_remaining": quiet_cycles_remaining
            if quiet_cycles_remaining is not None
            else existing.get("quiet_cycles_remaining"),
            "soft_risk_signals": list(soft_risk_signals)
            if soft_risk_signals is not None
            else list(existing.get("soft_risk_signals") or []),
        }
    )
    if not is_pool_ready():
        _mem_scheduler_state[_SCHEDULER_SUCCESS_KEY] = payload
        return
    try:
        now = datetime.now(UTC).isoformat()
        pool = get_pool()
        async with pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO creator_stats_scheduler_state (key_name, value_json, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (key_name) DO UPDATE SET
                    value_json = EXCLUDED.value_json,
                    updated_at = EXCLUDED.updated_at
                """,
                (_SCHEDULER_SUCCESS_KEY, json.dumps(payload, ensure_ascii=False), now),
            )
    except Exception:
        logger.debug("save_scheduler_success_history failed", exc_info=True)


def _reset_memory_store() -> None:
    """Test helper: clear in-memory rows."""
    _mem_accounts.clear()
    _mem_notes.clear()
    _mem_scheduler_state.clear()


def _account_values(overview: AccountStatsOverview) -> tuple[Any, ...]:
    row = overview.to_dict()
    return (
        overview.account_id,
        overview.creator_user_id,
        overview.creator_name,
        overview.red_id,
        overview.avatar_url,
        overview.bio,
        overview.creator_role,
        overview.zone,
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


async def _upsert_notes_batch_on_conn(conn: Any, valid_notes: list[NoteStats]) -> tuple[int, int]:
    """Batched upsert of pre-validated notes through an existing connection.

    Collapses the per-note SELECT+UPSERT (2N round trips) to one account-grouped
    existence SELECT plus a single ``executemany`` upsert. ``valid_notes`` must be
    pre-filtered (normalized, non-blank account_id/note_id) by each caller.
    Returns ``(imported_new, updated)`` via set diff against the existing rows.
    """
    if not valid_notes:
        return 0, 0

    # Group by account_id so the existence query stays a simple account-scoped
    # ``note_id = ANY(%s)`` (same idiom as _delete_stale_notes_on_conn).
    by_account: dict[str, list[str]] = {}
    for note in valid_notes:
        by_account.setdefault(note.account_id, []).append(note.note_id)

    # Single existence SELECT across all accounts in the batch (was one SELECT
    # per account → A round trips on multi-account imports). PK is
    # (account_id, note_id), so note_id is not globally unique — track existing
    # rows as (account_id, note_id) pairs, not bare note_ids, to keep the
    # membership check account-scoped and equivalent to the per-account loop.
    account_ids = list(by_account)
    all_note_ids = [nid for nids in by_account.values() for nid in nids]

    existing_pairs: set[tuple[str, str]] = set()
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT account_id, note_id FROM creator_note_stats "
            "WHERE account_id = ANY(%s) AND note_id = ANY(%s)",
            (account_ids, all_note_ids),
        )
        rows = await cur.fetchall()
        existing_pairs.update((str(row[0]), str(row[1])) for row in rows if row)
        await cur.executemany(_UPSERT_NOTE_SQL, [_note_values(n) for n in valid_notes])

    imported = sum(1 for n in valid_notes if (n.account_id, n.note_id) not in existing_pairs)
    updated = len(valid_notes) - imported
    return imported, updated


async def upsert_account_stats(overview: AccountStatsOverview) -> None:
    """Upsert account-level overview (idempotent by account_id)."""
    account_id = (overview.account_id or "").strip()
    if not account_id:
        logger.warning("upsert_account_stats skipped: empty account_id")
        return
    overview.account_id = account_id
    row = overview.to_dict()
    if not is_pool_ready():
        existing = _mem_accounts.get(overview.account_id)
        if existing:
            for field in _PROFILE_FIELD_NAMES:
                if not row[field]:
                    row[field] = str(existing.get(field) or "")
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
    valid_notes: list[NoteStats] = []
    for note in notes:
        account_id = (note.account_id or "").strip()
        note_id = (note.note_id or "").strip()
        if not account_id or not note_id:
            continue
        note.account_id = account_id
        note.note_id = note_id
        valid_notes.append(note)
    if not valid_notes:
        return 0, 0
    async with pool.connection() as conn:
        return await _upsert_notes_batch_on_conn(conn, valid_notes)


async def _delete_stale_notes_on_conn(conn: Any, account_id: str, keep_note_ids: set[str]) -> int:
    """Remove local notes missing from an account-wide snapshot (same transaction)."""
    async with conn.cursor() as cur:
        if keep_note_ids:
            await cur.execute(
                """
                DELETE FROM creator_note_stats
                WHERE account_id = %s
                  AND NOT (note_id = ANY(%s))
                """,
                (account_id, list(keep_note_ids)),
            )
        else:
            # Empty remote snapshot ⇒ every local note is stale.
            await cur.execute(
                "DELETE FROM creator_note_stats WHERE account_id = %s",
                (account_id,),
            )
        return int(cur.rowcount or 0)


def _delete_stale_notes_mem(account_id: str, keep_note_ids: set[str]) -> int:
    """In-memory counterpart of ``_delete_stale_notes_on_conn``."""
    bucket = _mem_notes.get(account_id)
    if not bucket:
        return 0
    stale = [note_id for note_id in list(bucket) if note_id not in keep_note_ids]
    for note_id in stale:
        del bucket[note_id]
    if not bucket:
        _mem_notes.pop(account_id, None)
    return len(stale)


async def upsert_bundle(
    bundle_account: AccountStatsOverview, notes: list[NoteStats]
) -> tuple[int, int, int]:
    """Atomically persist an account snapshot and reconcile its note rows.

    A successful fetch used to write the account row and every note through
    separate implicit transactions.  A failure halfway through left a current
    account overview paired with a partial note set.  The live Note Manager
    response is an account-wide snapshot, so these writes must commit together.

    Notes present locally but absent from the incoming snapshot are treated as
    deleted on Creator Center and removed from durable storage (same transaction
    as the upserts). Returns ``(imported_new, updated, deleted)``.
    """
    account_id = (bundle_account.account_id or "").strip()
    if not account_id:
        logger.warning("upsert_bundle skipped: empty account_id")
        return 0, 0, 0
    bundle_account.account_id = account_id

    keep_note_ids: set[str] = set()
    valid_notes_by_id: dict[str, NoteStats] = {}
    for note in notes:
        note_account_id = (note.account_id or "").strip() or account_id
        note_id = (note.note_id or "").strip()
        if not note_account_id or not note_id:
            continue
        # Snapshot ownership is the bundle account; ignore mis-tagged rows.
        if note_account_id != account_id:
            logger.warning(
                "upsert_bundle skipped foreign note: account_id=%r note_id=%r expected=%r",
                note_account_id,
                note_id,
                account_id,
            )
            continue
        note.account_id = account_id
        note.note_id = note_id
        keep_note_ids.add(note_id)
        # A page-boundary or API replay can expose the same note twice. Keep
        # the last payload while making import counts and snapshot size stable.
        valid_notes_by_id[note_id] = note
    valid_notes = list(valid_notes_by_id.values())

    # Snapshot truth: account.note_count must equal the notes we persist, not a
    # misleading overview alias that can outrun Note Manager / list length.
    bundle_account.note_count = len(valid_notes)
    # Build identity from the canonical snapshot, not a raw payload that may
    # contain duplicate page-boundary rows.
    bundle_account.snapshot_id = build_creator_stats_snapshot_id(bundle_account, valid_notes)

    if not is_pool_ready():
        await upsert_account_stats(bundle_account)
        imported, updated = await upsert_notes(valid_notes)
        deleted = _delete_stale_notes_mem(account_id, keep_note_ids)
        return imported, updated, deleted

    pool = get_pool()
    async with pool.connection() as conn, conn.transaction():
        await _upsert_account_on_conn(conn, bundle_account)
        imported, updated = await _upsert_notes_batch_on_conn(conn, valid_notes)
        deleted = await _delete_stale_notes_on_conn(conn, account_id, keep_note_ids)
    return imported, updated, deleted


def _account_from_row(row: Any) -> AccountStatsOverview | None:
    if not row:
        return None
    if isinstance(row, dict):
        data = dict(row)
        raw_json_value = data.get("raw_json")
        if isinstance(raw_json_value, str):
            try:
                raw_json_value = json.loads(raw_json_value)
            except (TypeError, json.JSONDecodeError):
                raw_json_value = {}
        if isinstance(raw_json_value, dict):
            for key in (
                "audience_sources",
                "audience_view_periods",
                "audience_profile",
                "detail_metrics",
                "snapshot_id",
            ):
                if not data.get(key) and raw_json_value.get(key) is not None:
                    data[key] = raw_json_value[key]
        return AccountStatsOverview.from_dict(data)
    raw_account: dict[str, Any] = {}
    if len(row) > 18 and row[18]:
        try:
            parsed = json.loads(row[18]) if isinstance(row[18], str) else row[18]
            if isinstance(parsed, dict):
                raw_account = parsed
        except (TypeError, json.JSONDecodeError):
            raw_account = {}
    return AccountStatsOverview(
        account_id=row[0],
        creator_user_id=row[1],
        creator_name=row[2],
        red_id=row[3],
        avatar_url=row[4],
        bio=row[5],
        creator_role=row[6],
        zone=row[7],
        views=row[8],
        likes=row[9],
        comments=row[10],
        collects=row[11],
        shares=row[12],
        fans=row[13],
        note_count=row[14],
        period=row[15],
        synced_at=row[16],
        snapshot_id=raw_account.get("snapshot_id"),
        source=row[17],
        audience_sources=raw_account.get("audience_sources") or [],
        audience_view_periods=raw_account.get("audience_view_periods") or [],
        audience_profile=raw_account.get("audience_profile") or [],
        detail_metrics=raw_account.get("detail_metrics") or {},
    )


async def _fetch_account_stats(cur: Any, account_id: str) -> AccountStatsOverview | None:
    """Fetch and parse one account row using a caller-owned cursor."""

    await cur.execute(_ACCOUNT_STATS_SELECT_SQL, (account_id,))
    row: Any = await cur.fetchone()
    return _account_from_row(row)


async def get_account_stats(account_id: str) -> AccountStatsOverview | None:
    account_id = (account_id or "").strip()
    if not account_id:
        return None
    if not is_pool_ready():
        mem = _mem_accounts.get(account_id)
        return AccountStatsOverview.from_dict(mem) if mem else None
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        return await _fetch_account_stats(cur, account_id)


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
        if data.get("raw_json"):
            # Fallback: older rows may only have body in raw_json payload
            try:
                note_raw_value = data["raw_json"]
                if isinstance(note_raw_value, str):
                    note_raw_value = json.loads(note_raw_value)
                if isinstance(note_raw_value, dict):
                    if note_raw_value.get("body_text"):
                        data["body_text"] = note_raw_value["body_text"]
                    for key in (
                        "view_sources",
                        "audience_profile",
                        "audience_trend",
                        "detail_metrics",
                    ):
                        if not data.get(key) and note_raw_value.get(key) is not None:
                            data[key] = note_raw_value[key]
            except (TypeError, json.JSONDecodeError):
                pass
        return NoteStats.from_dict(data)
    # Tuple order must match list/get SELECT columns.  The final raw_json
    # column carries optional fields introduced after the initial migration.
    tags_raw = row[11]
    if isinstance(tags_raw, str):
        try:
            tags = json.loads(tags_raw)
        except json.JSONDecodeError:
            tags = []
    else:
        tags = tags_raw or []
    raw_payload: dict[str, Any] = {}
    if len(row) > 16 and row[16]:
        try:
            parsed = json.loads(row[16]) if isinstance(row[16], str) else row[16]
            if isinstance(parsed, dict):
                raw_payload = parsed
        except (TypeError, json.JSONDecodeError):
            raw_payload = {}
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
        view_sources=raw_payload.get("view_sources") or [],
        audience_profile=raw_payload.get("audience_profile") or [],
        audience_trend=raw_payload.get("audience_trend") or [],
        detail_metrics=raw_payload.get("detail_metrics") or {},
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


async def list_all_note_stats(account_id: str) -> list[NoteStats]:
    """Read every persisted note for one account without the display-page cap.

    This intentionally has no ``LIMIT`` clause.  Account-level historical
    analysis needs a complete durable snapshot, whereas ``list_note_stats`` is
    a bounded reader for normal API/UI pages.
    """
    account_id = (account_id or "").strip()
    if not account_id:
        return []
    if not is_pool_ready():
        bucket = _mem_notes.get(account_id, {})
        # A stable order keeps pure consumers deterministic even when the
        # process-local test store was populated in a different order.
        return [NoteStats.from_dict(bucket[note_id]) for note_id in sorted(bucket)]

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        return await _fetch_all_note_stats(cur, account_id)


async def _fetch_all_note_stats(cur: Any, account_id: str) -> list[NoteStats]:
    """Fetch the complete account note population using a caller-owned cursor."""

    await cur.execute(_NOTE_STATS_SELECT_SQL, (account_id,))
    rows = await cur.fetchall()
    return [_note_from_row(row) for row in rows]


async def _set_repeatable_read(cur: Any) -> None:
    """Pin all following reads in the explicit transaction to one DB snapshot."""

    await cur.execute(_REPEATABLE_READ_SQL)


async def get_creator_stats_snapshot_bundle(account_id: str) -> dict[str, Any]:
    """Read account, complete notes and their snapshot in one read boundary.

    Analytics and quality consumers must calculate from the same note
    population that produced ``snapshot_id``.  The Postgres path therefore
    keeps both row readers inside one repeatable-read transaction; the memory
    fallback preserves the same response shape without opening a database.
    """

    normalized_account_id = (account_id or "").strip()
    if not normalized_account_id:
        return {
            "account_id": "",
            "account": None,
            "notes": [],
            "data_as_of": None,
            "snapshot_id": None,
            "note_count": 0,
        }
    if not is_pool_ready():
        account = await get_account_stats(normalized_account_id)
        notes = await list_all_note_stats(normalized_account_id)
    else:
        pool = get_pool()
        async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
            await _set_repeatable_read(cur)
            account = await _fetch_account_stats(cur, normalized_account_id)
            notes = await _fetch_all_note_stats(cur, normalized_account_id)
    return {
        "account_id": normalized_account_id,
        "account": account,
        "notes": notes,
        **build_creator_stats_snapshot_metadata(account, notes),
    }


async def get_creator_stats_snapshot(account_id: str) -> dict[str, Any]:
    """Read the account-wide snapshot identity without triggering a sync."""

    bundle = await get_creator_stats_snapshot_bundle(account_id)
    return {
        key: bundle[key]
        for key in ("account_id", "data_as_of", "snapshot_id", "note_count", "stored_snapshot_id")
        if key in bundle
    }


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
                   engagement_rate, synced_at, source, raw_json
            FROM creator_note_stats
            WHERE account_id = %s
            ORDER BY {order_sql}
            LIMIT %s
            """,
            (account_id, limit),
        )
        rows = await cur.fetchall()
    return [_note_from_row(r) for r in rows]


def encode_note_cursor(published_at: str, note_id: str) -> str:
    """Encode the canonical ``(published_at, note_id)`` sort key opaquely."""
    payload = json.dumps(
        {"v": 1, "published_at": str(published_at or ""), "note_id": str(note_id or "")},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_note_cursor(cursor: str) -> tuple[str, str]:
    """Decode and validate a canonical history cursor.

    A malformed token is rejected by the API as a validation error instead of
    silently starting from the first page, which makes stale/corrupt links
    visible to callers.
    """
    token = (cursor or "").strip()
    if not token:
        raise ValueError("cursor cannot be empty")
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError("invalid note cursor") from exc
    if not isinstance(raw, dict) or raw.get("v") != 1:
        raise ValueError("unsupported note cursor")
    published_at = raw.get("published_at")
    note_id = raw.get("note_id")
    if not isinstance(published_at, str) or not isinstance(note_id, str):
        raise ValueError("invalid note cursor fields")
    return published_at, note_id


def _max_data_as_of(notes: list[NoteStats], account: AccountStatsOverview | None = None) -> str:
    values = [str(note.synced_at or "") for note in notes if str(note.synced_at or "")]
    if account is not None and str(account.synced_at or ""):
        values.append(str(account.synced_at))
    return max(values, default="")


def _canonical_note(note: NoteStats) -> NoteStats:
    """Return a detached note whose engagement rate is always a fraction."""
    normalized = NoteStats.from_dict(note.to_dict())
    try:
        rate = float(normalized.engagement_rate or 0.0)
    except (TypeError, ValueError):
        rate = 0.0
    if rate > 1.0:
        rate /= 100.0
    normalized.engagement_rate = min(max(rate, 0.0), 1.0)
    return normalized


def _creator_note_snapshot_version(note: NoteStats) -> str:
    """Hash canonical note facts so equal timestamps cannot hide an overwrite."""

    return version_digest(_canonical_note(note).to_dict())


def build_creator_stats_snapshot_id(
    account: AccountStatsOverview | None,
    notes: list[NoteStats],
) -> str | None:
    """Build an account snapshot from the complete durable note population."""

    account_id = (account.account_id if account else "").strip()
    if not account_id:
        account_id = next(
            (
                str(note.account_id or "").strip()
                for note in notes
                if str(note.account_id or "").strip()
            ),
            "",
        )
    if not account_id:
        return None
    account_notes = [
        note
        for note in notes
        if str(note.account_id or "").strip() == account_id and str(note.note_id or "").strip()
    ]
    data_as_of = _max_data_as_of(account_notes, account)
    subject_versions = [
        (note.note_id, _creator_note_snapshot_version(note)) for note in account_notes
    ]
    return build_snapshot_id(
        account_id,
        data_as_of or None,
        subject_versions=subject_versions,
    )


def build_creator_stats_snapshot_metadata(
    account: AccountStatsOverview | None,
    notes: list[NoteStats],
) -> dict[str, Any]:
    """Return one read-only snapshot contract for all Creator Stats consumers."""

    data_as_of = _max_data_as_of(notes, account)
    derived_snapshot = build_creator_stats_snapshot_id(account, notes)
    # Persisted IDs identify the atomic import. Prefer them only when they
    # still agree with the complete durable rows; otherwise the derived digest
    # safely detects a legacy/manual overwrite without writing during a read.
    stored_snapshot = getattr(account, "snapshot_id", None) if account else None
    snapshot = (
        stored_snapshot
        if stored_snapshot and stored_snapshot == derived_snapshot
        else derived_snapshot or stored_snapshot
    )
    return {
        "data_as_of": data_as_of or None,
        "snapshot_id": snapshot,
        "note_count": len(notes),
        "stored_snapshot_id": stored_snapshot,
    }


def canonicalize_note_stats(note: NoteStats) -> NoteStats:
    """Return a detached note DTO using the canonical fraction rate unit.

    Detail/compatibility readers use the same boundary normalizer as the
    cursor reader so an older percent-scale import cannot disagree with the
    shared historical fact stream.
    """
    return _canonical_note(note)


async def list_note_stats_page(
    account_id: str,
    *,
    cursor: str | None = None,
    limit: int = 50,
    published_from: str | None = None,
    published_to: str | None = None,
) -> NoteStatsPage:
    """Read the canonical historical-note fact stream.

    The reader is deliberately separate from ``list_note_stats``.  The latter
    remains a bounded compatibility preview used by older UI surfaces, while
    this endpoint has a complete filtered ``total`` and stable cursor ordering
    by ``published_at DESC, note_id DESC``.  It never joins workflow rows and
    therefore cannot leak another account's notes.
    """
    normalized_account_id = (account_id or "").strip()
    try:
        page_limit = int(limit)
    except (TypeError, ValueError):
        page_limit = 50
    page_limit = max(1, min(page_limit, 500))
    from_value = str(published_from or "").strip() or None
    to_value = str(published_to or "").strip() or None
    decoded_cursor = decode_note_cursor(cursor) if cursor else None

    if not normalized_account_id:
        return NoteStatsPage(
            account_id="",
            total=0,
            limit=page_limit,
            published_from=from_value,
            published_to=to_value,
        )

    if not is_pool_ready():
        bucket = _mem_notes.get(normalized_account_id, {})
        notes = [NoteStats.from_dict(value) for value in bucket.values()]
        if from_value:
            notes = [note for note in notes if note.published_at >= from_value]
        if to_value:
            notes = [note for note in notes if note.published_at <= to_value]
        notes.sort(key=lambda note: (str(note.published_at or ""), str(note.note_id)), reverse=True)
        filtered_notes = notes
        total = len(filtered_notes)
        if decoded_cursor is not None:
            cursor_published, cursor_note_id = decoded_cursor
            notes = [
                note
                for note in notes
                if (
                    str(note.published_at or "") < cursor_published
                    or (
                        str(note.published_at or "") == cursor_published
                        and str(note.note_id) < cursor_note_id
                    )
                )
            ]
        selected = notes[: page_limit + 1]
        has_next = len(selected) > page_limit
        items = [_canonical_note(note) for note in selected[:page_limit]]
        next_cursor = (
            encode_note_cursor(items[-1].published_at, items[-1].note_id)
            if has_next and items
            else None
        )
        snapshot = await get_creator_stats_snapshot(normalized_account_id)
        return NoteStatsPage(
            account_id=normalized_account_id,
            items=items,
            total=total,
            limit=page_limit,
            next_cursor=next_cursor,
            data_as_of=snapshot["data_as_of"] or "",
            snapshot_id=snapshot["snapshot_id"],
            published_from=from_value,
            published_to=to_value,
        )

    pool = get_pool()
    conditions = ["account_id = %s"]
    params: list[Any] = [normalized_account_id]
    if from_value:
        conditions.append("published_at >= %s")
        params.append(from_value)
    if to_value:
        conditions.append("published_at <= %s")
        params.append(to_value)
    if decoded_cursor:
        cursor_published, cursor_note_id = decoded_cursor
        conditions.append("(published_at < %s OR (published_at = %s AND note_id < %s))")
        params.extend([cursor_published, cursor_published, cursor_note_id])
    where = " AND ".join(conditions)
    count_conditions = conditions[:]
    count_params = params[:]
    if decoded_cursor:
        # ``total`` describes the complete filtered stream, not the remainder
        # after a cursor.  Remove the cursor predicate from the count query.
        count_conditions = count_conditions[:-1]
        count_params = count_params[:-3]
    selected_rows: list[Any]
    account: AccountStatsOverview | None
    all_notes: list[NoteStats]
    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await _set_repeatable_read(cur)
        await cur.execute(
            f"SELECT COUNT(*) FROM creator_note_stats WHERE {' AND '.join(count_conditions)}",
            count_params,
        )
        count_row = await cur.fetchone()
        total = (
            int(next(iter(count_row.values()), 0) or 0)
            if isinstance(count_row, dict)
            else int((count_row[0] if count_row else 0) or 0)
        )
        await cur.execute(
            f"""SELECT account_id, note_id, title, body_text, views, likes, comments, collects,
                   shares, published_at, content_type, tags_json, cover_url,
                   engagement_rate, synced_at, source, raw_json
            FROM creator_note_stats WHERE {where}
            ORDER BY published_at DESC, note_id DESC LIMIT %s""",
            params + [page_limit + 1],
        )
        selected_rows = list(await cur.fetchall())
        # Keep page facts and snapshot metadata in this same repeatable
        # read transaction.  Calling the public snapshot reader here would
        # release this connection and re-read a later import.
        account = await _fetch_account_stats(cur, normalized_account_id)
        all_notes = await _fetch_all_note_stats(cur, normalized_account_id)
    selected_notes = [_note_from_row(row) for row in selected_rows]
    has_next = len(selected_notes) > page_limit
    items = [_canonical_note(note) for note in selected_notes[:page_limit]]
    snapshot = build_creator_stats_snapshot_metadata(account, all_notes)
    return NoteStatsPage(
        account_id=normalized_account_id,
        items=items,
        total=total,
        limit=page_limit,
        next_cursor=(
            encode_note_cursor(items[-1].published_at, items[-1].note_id)
            if has_next and items
            else None
        ),
        data_as_of=snapshot["data_as_of"] or "",
        snapshot_id=snapshot["snapshot_id"],
        published_from=from_value,
        published_to=to_value,
    )


# Explicit aliases make the canonical reader discoverable to service callers
# while retaining one implementation and one ordering contract.
list_note_stats_cursor = list_note_stats_page
list_note_stats_paginated = list_note_stats_page


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
                   engagement_rate, synced_at, source, raw_json
            FROM creator_note_stats
            WHERE account_id = %s AND note_id = %s
            """,
            (account_id, note_id),
        )
        row: Any = await cur.fetchone()
    if row is None:
        return None
    return _note_from_row(row)
