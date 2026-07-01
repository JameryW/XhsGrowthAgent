# Database Guidelines

## Architecture Overview

Two separate PostgreSQL usage patterns coexist:

1. **App-level DB** (`backend/db/`) — workflow metadata (workflows table)
   - Managed by `AsyncConnectionPool` in `backend/db/pool.py`
   - CRUD operations in `backend/db/workflows.py`
   - Initialized/closed in `app.py` lifespan

2. **LangGraph checkpointer** — graph state snapshots (checkpoints, checkpoint_blobs, checkpoint_writes tables)
   - Managed by `AsyncPostgresSaver` with its own `AsyncConnectionPool`
   - Configured in `compile_graph_prod()` in `backend/graph/builder.py`
   - Shares the same `POSTGRES_URI`

Both pools are initialized in `app.py` lifespan and closed on shutdown.

---

## Scenario: Workflow Metadata Persistence

### 1. Scope / Trigger

- Replacing JSON file registry (`workflow_registry.json`) with PostgreSQL `workflows` table
- All workflow metadata (status, phase, progress, labels) now lives in DB
- Required for: parallel workflows, container restart resilience, multi-instance scaling

### 2. Signatures

```python
# Pool management (backend/db/pool.py)
async def init_pool() -> AsyncConnectionPool
async def close_pool() -> None
def get_pool() -> AsyncConnectionPool  # raises RuntimeError if not initialized
def is_pool_ready() -> bool

# CRUD (backend/db/workflows.py)
async def ensure_table() -> None
async def create_workflow(row: WorkflowRow) -> WorkflowRow
async def get_workflow(thread_id: str) -> WorkflowRow | None
async def update_workflow(thread_id: str, **fields: Any) -> WorkflowRow | None
async def list_workflows(account_id=None, status=None, limit=20, offset=0) -> tuple[list[WorkflowRow], int]
async def delete_workflow(thread_id: str) -> bool

# Convenience (used by _runner.py and workflow.py)
async def _db_upsert(thread_id: str, **fields: Any) -> None  # create-or-update, no-ops if DB unavailable
```

### 3. Contracts

#### WorkflowRow Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| thread_id | str | (required) | PK, format: `xhs_{account_id}_{8char_hex}` |
| account_id | str | "" | Account identifier |
| status | str | "running" | Derived workflow status |
| phase | str | "scouting" | Current workflow phase |
| progress_percent | int | 0 | 0-100 progress |
| label | str | "" | Human-readable workflow name |
| dry_run | bool | False | Dry-run mode flag |
| auto_publish | bool | False | Auto-publish after review |
| error | str \| None | None | Error message if any |
| task_error | str \| None | None | Background task error |
| task_done_at | str \| None | None | ISO timestamp when bg task finished |
| created_at | str | "" | ISO timestamp |
| updated_at | str | "" | ISO timestamp, auto-updated on every update |

#### Environment Keys

| Key | Required | Description |
|-----|----------|-------------|
| POSTGRES_URI | Yes (prod) | PostgreSQL connection string |
| XHS_REGISTRY_PATH | No | Base dir for history files (default: `.xhs`) |

#### Status Values (stored as strings in DB)

`running` | `stale` | `paused` | `cancelled` | `awaiting_review` | `awaiting_choice` | `awaiting_draft` | `completed` | `error`

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| POSTGRES_URI not set | Falls back to MemorySaver, workflows table unavailable |
| DB connection lost mid-request | `_db_upsert` catches exception, logs, continues (graceful degradation) |
| `is_pool_ready() == False` | All DB ops no-op, `/list` returns empty, `/status` falls back to history file |
| Duplicate thread_id INSERT | `ON CONFLICT DO UPDATE` (upsert) |
| Delete running workflow | ValidationError: "Cannot delete a running or stale workflow" |

### 5. Good/Base/Bad Cases

- **Good**: POSTGRES_URI configured, pool initializes, workflows table auto-created, all CRUD works
- **Base**: No POSTGRES_URI, MemorySaver used, workflow metadata only in-memory (lost on restart)
- **Bad**: POSTGRES_URI set but DB unreachable at startup — falls back to MemorySaver with warning log

### 6. Tests Required

- Unit: `WorkflowRow.to_dict()` round-trip
- Unit: `_db_upsert` with no pool (should no-op without error)
- Integration: create → get → update → list → delete lifecycle
- Integration: list with account_id/status filters and pagination
- Integration: concurrent create_workflow for same thread_id (upsert)

### 7. Wrong vs Correct

#### Wrong: from_conn_string without async context manager

```python
# BUG: from_conn_string is an @asynccontextmanager, not a direct constructor
checkpointer = AsyncPostgresSaver.from_conn_string(db_uri)
await checkpointer.setup()
# Connection is never properly opened/closed
```

#### Correct: AsyncConnectionPool + direct constructor

```python
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

pool = AsyncConnectionPool(db_uri, min_size=2, max_size=10, open=False)
await pool.open()
checkpointer = AsyncPostgresSaver(conn=pool)
await checkpointer.setup()
# Pool lifecycle managed by caller (app.py lifespan)
```

---

## Anti-patterns

### Don't: Use `loop.run_until_complete()` inside asyncio callbacks

Background task `add_done_callback` runs synchronously. You cannot call `await` inside it, and `loop.run_until_complete()` will raise `RuntimeError` because the event loop is already running.

```python
# BAD
def callback(task):
    loop = asyncio.get_running_loop()
    loop.run_until_complete(db_update(...))  # RuntimeError!
```

```python
# GOOD
def callback(task):
    asyncio.ensure_future(_do_db_update(...))  # Schedules on running loop
```

### Don't: Store workflow metadata in JSON files

The old pattern (`_persist_registry` / `_load_registry` / `workflow_registry.json`) has been removed. All workflow metadata must go through `backend/db/workflows.py`.

### Don't: Use `_workflow_registry` dict

The in-memory dict `_workflow_registry` has been removed. Use `db_get()`, `db_list()`, `db_update()` instead.

---

## Design Decisions

### Two separate connection pools (app + checkpointer)

**Context**: LangGraph's `AsyncPostgresSaver` accepts a pool via `conn=` parameter. The app-level DB also needs a pool for workflow table queries.

**Options considered**:
1. Single shared pool for both
2. Separate pools

**Decision**: Separate pools. The checkpointer manages its own schema (checkpoints/blobs/writes tables) and has different connection patterns (frequent small writes during graph execution). The app-level pool serves REST API queries (read-heavy, paginated). Separation avoids pool contention and keeps shutdown ordering clear.

### History files retained for completed results

**Context**: Completed workflow results (full state with trend_data, content_plan, etc.) are large JSON objects.

**Decision**: Keep `_save_history_file()` / `_load_history_file()` for now. The DB workflows table stores metadata only (not full state). Migrating full state to DB is a future task. History files serve as a fallback when DB is unavailable.

### Graceful degradation when DB is unavailable

**Context**: The app should still function (with reduced features) if PostgreSQL is down.

**Decision**: All DB ops go through `_db_upsert()` which catches exceptions and logs them. `is_pool_ready()` checks are used at API endpoints to return degraded responses (empty list, fallback to history files). The `/health` endpoint reports DB status.

---

## Common Mistakes

### Forgetting to await DB operations

All `db_*` functions are async. Forgetting `await` will return a coroutine object instead of the result.

```python
# BAD
row = db_get(thread_id)  # Returns coroutine, not WorkflowRow

# GOOD
row = await db_get(thread_id)
```

### Using wrong pool attribute for readiness check

```python
# BAD — _opened doesn't exist on AsyncConnectionPool
return _pool is not None and _pool._opened

# GOOD
return _pool is not None and not _pool._closed
```

---

## Scenario: Account-Scoped XHS Credentials

### Contract

XHS platform credentials are account-scoped DB data, not global system config.
Runtime code that performs XHS platform operations for a workflow should prefer
the workflow `account_id` and call:

```python
from backend.db.accounts import get_account_cookie

cookie, user_id = await get_account_cookie(account_id)
```

If the requested account has no cookie, tools may fall back to the active DB
account or environment-backed `Settings().platform` for backward compatibility.
This fallback must be graceful when `backend.db.pool.is_pool_ready()` is false.

### Do Not

- Do not gate XHS tool execution only on `os.environ["XHS_COOKIE"]`.
- Do not read account credentials directly with ad hoc SQL from agents/tools.
- Do not store LLM/Ripple/system keys in `account_credentials`; account rows
  only own `XHS_COOKIE` and `XHS_USER_ID`.
