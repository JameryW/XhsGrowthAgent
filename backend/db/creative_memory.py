"""Durable persistence for CreativeMemory (style DNA / playbook / materials).

Postgres when the app pool is ready; otherwise a process-local in-memory
fallback (same pattern as ``creator_stats``). LangGraph BaseStore remains
optional for semantic search — durable rows are the source of truth across
restarts and CLI/API paths without a graph store.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from backend.db.pool import get_pool, is_pool_ready

logger = logging.getLogger("xhs_growth.db.creative_memory")

# account_id -> id -> payload dict
_mem_styles: dict[str, dict[str, dict[str, Any]]] = {}
_mem_plays: dict[str, dict[str, dict[str, Any]]] = {}
_mem_materials: dict[str, dict[str, dict[str, Any]]] = {}
_mem_benchmarks: dict[str, dict[str, Any]] = {}  # niche -> payload


def _reset_memory_store() -> None:
    """Test helper: clear durable in-memory rows."""
    _mem_styles.clear()
    _mem_plays.clear()
    _mem_materials.clear()
    _mem_benchmarks.clear()


_CREATE_STYLE_SQL = """
CREATE TABLE IF NOT EXISTS creative_style_dna (
    account_id   TEXT NOT NULL,
    style_id     TEXT NOT NULL,
    tone         TEXT NOT NULL DEFAULT '',
    visual_style TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, style_id)
);
"""

_CREATE_PLAY_SQL = """
CREATE TABLE IF NOT EXISTS creative_playbook (
    account_id   TEXT NOT NULL,
    play_id      TEXT NOT NULL,
    niche        TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, play_id)
);
"""

_CREATE_MATERIAL_SQL = """
CREATE TABLE IF NOT EXISTS creative_material_vault (
    account_id   TEXT NOT NULL,
    material_id  TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT '',
    weight       DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, material_id)
);
"""

_CREATE_BENCHMARK_SQL = """
CREATE TABLE IF NOT EXISTS creative_niche_benchmark (
    niche        TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at   TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_creative_style_account
    ON creative_style_dna (account_id);
CREATE INDEX IF NOT EXISTS idx_creative_play_account
    ON creative_playbook (account_id);
CREATE INDEX IF NOT EXISTS idx_creative_material_account
    ON creative_material_vault (account_id, category);
"""


async def ensure_tables() -> None:
    if not is_pool_ready():
        logger.debug("creative_memory ensure_tables skipped: pool not ready")
        return
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_STYLE_SQL)
        await conn.execute(_CREATE_PLAY_SQL)
        await conn.execute(_CREATE_MATERIAL_SQL)
        await conn.execute(_CREATE_BENCHMARK_SQL)
        await conn.execute(_CREATE_INDEX_SQL)
    logger.info("creative_memory tables ensured")


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


# ── Style DNA ───────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def upsert_style(account_id: str, style_id: str, payload: dict[str, Any]) -> None:
    account_id = (account_id or "").strip()
    style_id = (style_id or "").strip()
    if not account_id or not style_id:
        return
    row = dict(payload)
    row["style_id"] = style_id
    tone = str(row.get("tone") or "")
    visual = str(row.get("visual_style") or "")
    updated_at = str(row.get("last_used") or row.get("updated_at") or "") or _now_iso()
    row.setdefault("last_used", updated_at)

    if not is_pool_ready():
        _mem_styles.setdefault(account_id, {})[style_id] = row
        return

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO creative_style_dna (
                account_id, style_id, tone, visual_style, payload_json, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, style_id) DO UPDATE SET
                tone = EXCLUDED.tone,
                visual_style = EXCLUDED.visual_style,
                payload_json = EXCLUDED.payload_json,
                updated_at = EXCLUDED.updated_at
            """,
            (account_id, style_id, tone, visual, _dumps(row), updated_at),
        )


async def get_style(account_id: str, style_id: str) -> dict[str, Any] | None:
    account_id = (account_id or "").strip()
    style_id = (style_id or "").strip()
    if not account_id or not style_id:
        return None
    if not is_pool_ready():
        return _mem_styles.get(account_id, {}).get(style_id)

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT payload_json FROM creative_style_dna WHERE account_id = %s AND style_id = %s",
            (account_id, style_id),
        )
        row = await cur.fetchone()
    if not row:
        return None
    raw = row["payload_json"] if isinstance(row, dict) else row[0]
    return _loads(raw) or None


async def find_style_by_tone_visual(
    account_id: str, tone: str, visual_style: str
) -> tuple[str, dict[str, Any]] | None:
    """Exact tone+visual match for merge-on-deposit."""
    account_id = (account_id or "").strip()
    if not account_id:
        return None
    tone = (tone or "").strip()
    visual_style = (visual_style or "").strip()

    if not is_pool_ready():
        for sid, payload in _mem_styles.get(account_id, {}).items():
            if payload.get("tone") == tone and payload.get("visual_style") == visual_style:
                return sid, dict(payload)
        return None

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT style_id, payload_json FROM creative_style_dna
            WHERE account_id = %s AND tone = %s AND visual_style = %s
            LIMIT 1
            """,
            (account_id, tone, visual_style),
        )
        row = await cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return str(row["style_id"]), _loads(row["payload_json"])
    return str(row[0]), _loads(row[1])


async def list_styles(account_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    account_id = (account_id or "").strip()
    if not account_id:
        return []
    limit = max(1, min(int(limit or 20), 100))

    if not is_pool_ready():
        items = list(_mem_styles.get(account_id, {}).values())
        items.sort(key=lambda x: float(x.get("engagement_rate") or 0), reverse=True)
        return [dict(x) for x in items[:limit]]

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT payload_json FROM creative_style_dna
            WHERE account_id = %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (account_id, limit),
        )
        rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows or []:
        raw = row["payload_json"] if isinstance(row, dict) else row[0]
        payload = _loads(raw)
        if payload:
            out.append(payload)
    # Prefer higher engagement when timestamps equal / empty
    out.sort(key=lambda x: float(x.get("engagement_rate") or 0), reverse=True)
    return out[:limit]


# ── Playbook ────────────────────────────────────────────────────────────────


async def upsert_play(account_id: str, play_id: str, payload: dict[str, Any]) -> None:
    account_id = (account_id or "").strip()
    play_id = (play_id or "").strip()
    if not account_id or not play_id:
        return
    row = dict(payload)
    row["play_id"] = play_id
    niche = str(row.get("niche") or "")
    updated_at = str(row.get("last_proven") or row.get("updated_at") or "") or _now_iso()
    row.setdefault("last_proven", updated_at)

    if not is_pool_ready():
        _mem_plays.setdefault(account_id, {})[play_id] = row
        return

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO creative_playbook (
                account_id, play_id, niche, payload_json, updated_at
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (account_id, play_id) DO UPDATE SET
                niche = EXCLUDED.niche,
                payload_json = EXCLUDED.payload_json,
                updated_at = EXCLUDED.updated_at
            """,
            (account_id, play_id, niche, _dumps(row), updated_at),
        )


async def get_play(account_id: str, play_id: str) -> dict[str, Any] | None:
    account_id = (account_id or "").strip()
    play_id = (play_id or "").strip()
    if not account_id or not play_id:
        return None
    if not is_pool_ready():
        return _mem_plays.get(account_id, {}).get(play_id)

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT payload_json FROM creative_playbook WHERE account_id = %s AND play_id = %s",
            (account_id, play_id),
        )
        row = await cur.fetchone()
    if not row:
        return None
    raw = row["payload_json"] if isinstance(row, dict) else row[0]
    return _loads(raw) or None


async def list_plays(account_id: str, *, niche: str = "", limit: int = 20) -> list[dict[str, Any]]:
    account_id = (account_id or "").strip()
    if not account_id:
        return []
    limit = max(1, min(int(limit or 20), 100))
    niche = (niche or "").strip()

    if not is_pool_ready():
        items = list(_mem_plays.get(account_id, {}).values())
        if niche:
            items = [p for p in items if not p.get("niche") or p.get("niche") == niche]
        items.sort(key=lambda x: float(x.get("avg_engagement_rate") or 0), reverse=True)
        return [dict(x) for x in items[:limit]]

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        if niche:
            await cur.execute(
                """
                SELECT payload_json FROM creative_playbook
                WHERE account_id = %s AND (niche = %s OR niche = '')
                ORDER BY updated_at DESC LIMIT %s
                """,
                (account_id, niche, limit),
            )
        else:
            await cur.execute(
                """
                SELECT payload_json FROM creative_playbook
                WHERE account_id = %s
                ORDER BY updated_at DESC LIMIT %s
                """,
                (account_id, limit),
            )
        rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows or []:
        raw = row["payload_json"] if isinstance(row, dict) else row[0]
        payload = _loads(raw)
        if payload:
            out.append(payload)
    return out[:limit]


# ── Materials ───────────────────────────────────────────────────────────────


async def upsert_material(account_id: str, material_id: str, payload: dict[str, Any]) -> None:
    account_id = (account_id or "").strip()
    material_id = (material_id or "").strip()
    if not account_id or not material_id:
        return
    row = dict(payload)
    row["material_id"] = material_id
    category = str(row.get("category") or "")
    weight = float(row.get("weight") or 1.0)
    updated_at = str(row.get("created_at") or row.get("updated_at") or "") or _now_iso()
    row.setdefault("created_at", updated_at)

    if not is_pool_ready():
        _mem_materials.setdefault(account_id, {})[material_id] = row
        return

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO creative_material_vault (
                account_id, material_id, category, weight, payload_json, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, material_id) DO UPDATE SET
                category = EXCLUDED.category,
                weight = EXCLUDED.weight,
                payload_json = EXCLUDED.payload_json,
                updated_at = EXCLUDED.updated_at
            """,
            (account_id, material_id, category, weight, _dumps(row), updated_at),
        )


async def get_material(account_id: str, material_id: str) -> dict[str, Any] | None:
    account_id = (account_id or "").strip()
    material_id = (material_id or "").strip()
    if not account_id or not material_id:
        return None
    if not is_pool_ready():
        return _mem_materials.get(account_id, {}).get(material_id)

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT payload_json FROM creative_material_vault
            WHERE account_id = %s AND material_id = %s
            """,
            (account_id, material_id),
        )
        row = await cur.fetchone()
    if not row:
        return None
    raw = row["payload_json"] if isinstance(row, dict) else row[0]
    return _loads(raw) or None


async def list_materials(
    account_id: str,
    *,
    category: str = "",
    tags: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    account_id = (account_id or "").strip()
    if not account_id:
        return []
    limit = max(1, min(int(limit or 20), 100))
    category = (category or "").strip()
    tags = tags or []

    if not is_pool_ready():
        items = list(_mem_materials.get(account_id, {}).values())
    else:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            if category:
                await cur.execute(
                    """
                    SELECT payload_json FROM creative_material_vault
                    WHERE account_id = %s AND category = %s
                    ORDER BY weight DESC LIMIT %s
                    """,
                    (account_id, category, limit * 2),
                )
            else:
                await cur.execute(
                    """
                    SELECT payload_json FROM creative_material_vault
                    WHERE account_id = %s
                    ORDER BY weight DESC LIMIT %s
                    """,
                    (account_id, limit * 2),
                )
            rows = await cur.fetchall()
        items = []
        for row in rows or []:
            raw = row["payload_json"] if isinstance(row, dict) else row[0]
            payload = _loads(raw)
            if payload:
                items.append(payload)

    if category:
        items = [m for m in items if (m.get("category") or "") == category]
    if tags:
        tag_set = set(tags)
        items = [m for m in items if tag_set.intersection(set(m.get("tags") or []))]
    items.sort(key=lambda x: float(x.get("weight") or 1.0), reverse=True)
    return [dict(x) for x in items[:limit]]


# ── Benchmarks ──────────────────────────────────────────────────────────────


async def upsert_benchmark(niche: str, payload: dict[str, Any]) -> None:
    niche = (niche or "").strip()
    if not niche:
        return
    row = dict(payload)
    row["niche"] = niche
    updated_at = str(row.get("updated_at") or "")

    if not is_pool_ready():
        _mem_benchmarks[niche] = row
        return

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO creative_niche_benchmark (niche, payload_json, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (niche) DO UPDATE SET
                payload_json = EXCLUDED.payload_json,
                updated_at = EXCLUDED.updated_at
            """,
            (niche, _dumps(row), updated_at),
        )


async def get_benchmark(niche: str) -> dict[str, Any] | None:
    niche = (niche or "").strip()
    if not niche:
        return None
    if not is_pool_ready():
        return _mem_benchmarks.get(niche)

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT payload_json FROM creative_niche_benchmark WHERE niche = %s",
            (niche,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    raw = row["payload_json"] if isinstance(row, dict) else row[0]
    return _loads(raw) or None
