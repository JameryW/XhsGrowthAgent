"""Durable storage for anti-risk cool-downs (survives deploy restarts).

Reuses ``creator_stats_scheduler_state`` as a small JSON KV so we do not add
another migration path. Key: ``risk_gate_cooldowns``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from backend.db.pool import get_pool, is_pool_ready

logger = logging.getLogger("xhs_growth.db.risk_gates")

_RISK_GATE_KEY = "risk_gate_cooldowns"
_mem: dict[str, Any] = {}


def _empty() -> dict[str, Any]:
    return {
        "browser_action": {},  # key -> {at, owner}
        "publish": {},  # key -> at
        "engagement": {},  # key -> at
        "sync_auth": {},  # account_id -> {until, reason}
        "qr_risk": {},  # account_id -> {until, reason}
        "qr_last_attempt": {},  # account_id -> at
    }


def _normalize(data: dict[str, Any] | None) -> dict[str, Any]:
    base = _empty()
    if not isinstance(data, dict):
        return base
    for field in base:
        raw = data.get(field)
        if isinstance(raw, dict):
            base[field] = dict(raw)
    return base


async def load_risk_gate_state() -> dict[str, Any]:
    """Load durable risk-gate cool-downs (wall-clock ISO timestamps)."""
    if not is_pool_ready():
        return _normalize(_mem.get(_RISK_GATE_KEY) if isinstance(_mem.get(_RISK_GATE_KEY), dict) else None)
    try:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT value_json FROM creator_stats_scheduler_state WHERE key_name = %s",
                (_RISK_GATE_KEY,),
            )
            row = await cur.fetchone()
        if not row:
            return _empty()
        payload = row[0] if not isinstance(row, dict) else row.get("value_json")
        if isinstance(payload, str):
            data = json.loads(payload or "{}")
        elif isinstance(payload, dict):
            data = payload
        else:
            return _empty()
        return _normalize(data if isinstance(data, dict) else None)
    except Exception:
        logger.debug("load_risk_gate_state failed", exc_info=True)
        return _empty()


async def save_risk_gate_state(state: dict[str, Any]) -> None:
    """Persist risk-gate cool-downs (best-effort)."""
    payload = _normalize(state)
    if not is_pool_ready():
        _mem[_RISK_GATE_KEY] = payload
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
                (_RISK_GATE_KEY, json.dumps(payload, ensure_ascii=False), now),
            )
    except Exception:
        logger.debug("save_risk_gate_state failed", exc_info=True)


def reset_risk_gate_memory_for_tests() -> None:
    _mem.clear()


__all__ = [
    "load_risk_gate_state",
    "reset_risk_gate_memory_for_tests",
    "save_risk_gate_state",
]
