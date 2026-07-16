"""Workflow metadata table — CRUD operations for the workflows table."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.db.pool import get_pool

logger = logging.getLogger("xhs_growth.db.workflows")

# ── Data model ──


@dataclass
class WorkflowRow:
    thread_id: str
    account_id: str = ""
    status: str = "running"
    phase: str = "scouting"
    progress_percent: int = 0
    label: str = ""
    workflow_mode: str = "trend"
    showcase_visibility: str = "private"
    public_id: str | None = None
    showcase_featured: bool = False
    dry_run: bool = False
    auto_publish: bool = False
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    # Fields carried from the old JSON registry that may be null
    task_error: str | None = None
    task_done_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "account_id": self.account_id,
            "status": self.status,
            "phase": self.phase,
            "progress_percent": self.progress_percent,
            "label": self.label,
            "workflow_mode": self.workflow_mode,
            "showcase_visibility": self.showcase_visibility,
            "public_id": self.public_id,
            "showcase_featured": self.showcase_featured,
            "dry_run": self.dry_run,
            "auto_publish": self.auto_publish,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ── Table creation (run once at startup) ──

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS workflows (
    thread_id       TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'running',
    phase           TEXT NOT NULL DEFAULT 'scouting',
    progress_percent INTEGER NOT NULL DEFAULT 0,
    label           TEXT NOT NULL DEFAULT '',
    workflow_mode   TEXT NOT NULL DEFAULT 'trend',
    showcase_visibility TEXT NOT NULL DEFAULT 'private',
    public_id       TEXT UNIQUE,
    showcase_featured BOOLEAN NOT NULL DEFAULT FALSE,
    dry_run         BOOLEAN NOT NULL DEFAULT FALSE,
    auto_publish    BOOLEAN NOT NULL DEFAULT FALSE,
    error           TEXT DEFAULT NULL,
    task_error      TEXT DEFAULT NULL,
    task_done_at    TEXT DEFAULT NULL,
    created_at      TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_workflows_account_id ON workflows (account_id);
CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows (status);
CREATE INDEX IF NOT EXISTS idx_workflows_created_at ON workflows (created_at);
"""


async def ensure_table() -> None:
    """Create workflows table + indexes if they don't exist yet."""
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_TABLE_SQL)
        # Additive migration for databases created before the public Showcase
        # contract.  Public visibility is intentionally private by default.
        await conn.execute(
            "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS showcase_visibility "
            "TEXT NOT NULL DEFAULT 'private'"
        )
        await conn.execute("ALTER TABLE workflows ADD COLUMN IF NOT EXISTS public_id TEXT")
        await conn.execute(
            "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS showcase_featured "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )
        await conn.execute(_CREATE_INDEX_SQL)
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_workflows_public_id "
            "ON workflows (public_id) WHERE public_id IS NOT NULL"
        )
    logger.info("workflows table ensured")


# ── CRUD ──


async def create_workflow(row: WorkflowRow) -> WorkflowRow:
    now = datetime.now(UTC).isoformat()
    if not row.created_at:
        row.created_at = now
    if not row.updated_at:
        row.updated_at = now

    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO workflows
                (thread_id, account_id, status, phase, progress_percent,
                 label, workflow_mode, showcase_visibility, public_id, showcase_featured,
                 dry_run, auto_publish, error, task_error, task_done_at, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (thread_id) DO UPDATE SET
                account_id      = EXCLUDED.account_id,
                status          = EXCLUDED.status,
                phase           = EXCLUDED.phase,
                progress_percent = EXCLUDED.progress_percent,
                label           = EXCLUDED.label,
                workflow_mode   = EXCLUDED.workflow_mode,
                showcase_visibility = EXCLUDED.showcase_visibility,
                public_id       = COALESCE(EXCLUDED.public_id, workflows.public_id),
                showcase_featured = EXCLUDED.showcase_featured,
                dry_run         = EXCLUDED.dry_run,
                auto_publish    = EXCLUDED.auto_publish,
                error           = EXCLUDED.error,
                updated_at      = EXCLUDED.updated_at
            """,
            (
                row.thread_id,
                row.account_id,
                row.status,
                row.phase,
                row.progress_percent,
                row.label,
                row.workflow_mode,
                row.showcase_visibility,
                row.public_id,
                row.showcase_featured,
                row.dry_run,
                row.auto_publish,
                row.error,
                row.task_error,
                row.task_done_at,
                row.created_at,
                row.updated_at,
            ),
        )
    return row


async def get_workflow(thread_id: str) -> WorkflowRow | None:
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM workflows WHERE thread_id = %s", (thread_id,))
            row = await cur.fetchone()
    if row is None:
        return None
    return _row_from_dict(row)


async def get_workflow_by_public_id(public_id: str) -> WorkflowRow | None:
    """Look up a workflow by its opaque public identifier."""
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM workflows WHERE public_id = %s", (public_id,))
            row = await cur.fetchone()
    if row is None:
        return None
    return _row_from_dict(row)


async def update_workflow(thread_id: str, **fields: Any) -> WorkflowRow | None:
    """Update selected fields. Automatically sets updated_at."""
    if not fields:
        return await get_workflow(thread_id)

    fields["updated_at"] = datetime.now(UTC).isoformat()
    set_clause = ", ".join(f"{k} = %s" for k in fields)
    values = list(fields.values()) + [thread_id]

    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"UPDATE workflows SET {set_clause} WHERE thread_id = %s RETURNING *",
                values,
            )
            row = await cur.fetchone()
    if row is None:
        return None
    return _row_from_dict(row)


async def list_workflows(
    account_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[WorkflowRow], int]:
    """Return (workflows, total_count) filtered and paginated."""
    conditions: list[str] = []
    params: list[Any] = []

    if account_id:
        conditions.append("account_id = %s")
        params.append(account_id)
    if status:
        conditions.append("status = %s")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            # Count
            await cur.execute(f"SELECT COUNT(*) AS cnt FROM workflows {where}", params)
            count_row = await cur.fetchone()
            total = count_row["cnt"] if count_row else 0

            # Rows
            order_and_limit = "ORDER BY created_at DESC LIMIT %s OFFSET %s"
            await cur.execute(
                f"SELECT * FROM workflows {where} {order_and_limit}",
                params + [limit, offset],
            )
            rows = await cur.fetchall()

    return [_row_from_dict(r) for r in rows], total


async def delete_workflow(thread_id: str) -> bool:
    pool = get_pool()
    async with pool.connection() as conn:
        tag = await conn.execute("DELETE FROM workflows WHERE thread_id = %s", (thread_id,))
    return tag == "DELETE 1"  # type: ignore[comparison-overlap]


def _row_from_dict(d: dict[str, Any]) -> WorkflowRow:
    return WorkflowRow(
        thread_id=d["thread_id"],
        account_id=d.get("account_id", ""),
        status=d.get("status", "running"),
        phase=d.get("phase", "scouting"),
        progress_percent=d.get("progress_percent", 0),
        label=d.get("label", ""),
        workflow_mode=d.get("workflow_mode", "trend"),
        showcase_visibility=d.get("showcase_visibility", "private"),
        public_id=d.get("public_id"),
        showcase_featured=bool(d.get("showcase_featured", False)),
        dry_run=d.get("dry_run", False),
        auto_publish=d.get("auto_publish", False),
        error=d.get("error"),
        task_error=d.get("task_error"),
        task_done_at=d.get("task_done_at"),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )
