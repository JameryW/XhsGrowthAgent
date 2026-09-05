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

## Scenario: Creator Agent judgement and decision persistence

The Creator Agent adapter (`backend/db/creator_agent.py`) stores creator
judgement separately from derived Creative Memory. It supports PostgreSQL in
production and a process-memory fallback for tests/dev when no pool is ready.

### Contracts

- `creator_agent_models` is keyed by the independent `creator_id`; each write
  replaces the complete immutable model definition and increments `revision`.
- Writes accept `expected_revision` and must fail with a revision-conflict
  error when another writer has advanced the model. Never silently merge
  normative judgement.
- `creator_agent_decisions` stores the exact model revision, request context,
  ranked candidates, exclusions, evidence IDs, confidence, and status. A
  decision is an audit record, not a recomputation from the current model.
- `creator_agent_relationships` is scoped by `(account_id, audience_id)` and
  stores interaction count, accepted/rejected candidate IDs, latest correction,
  and last interaction time.
- Feedback is append-only and idempotent by `feedback_id`; it may update
  relationship memory and create a learning signal, but it must not mutate the
  Creator Model without an explicit creator-approved revision.
- All adapter operations are account-scoped at the route boundary and use
  parameterized SQL plus explicit transactions for Postgres writes.

### Initialization and fallback

`ensure_tables()` is called during the Postgres app lifespan. If no ready pool
exists, the in-memory repository remains usable and is reset only by the test
helper `_reset_memory_store()`; production code must not depend on that helper.

---

## Scenario: Creator Agent learning-signal review

Feedback-derived learning is durable and creator-controlled. The adapter keeps
`creator_agent_learning_signals` account-scoped with a primary key on
`(account_id, signal_id)` and a unique `(account_id, feedback_id)` constraint.

- `apply_feedback` appends feedback, updates Relationship Memory, and creates a
  signal in one transaction when the outcome is `dissatisfied` or a correction
  is supplied. Retrying the same feedback ID returns the original signal and
  never reinterprets the retry payload.
- `list_learning_signals` filters by account and optional lifecycle status and
  returns a stable newest-first ordering.
- `review_learning_signal` locks the signal and, for approval, the Creator
  Model row in the same transaction. Approval requires a complete model
  definition and `expected_revision`; stale revisions roll back both writes.
- Dismissal changes only the signal. Repeating the same disposition is
  idempotent; a different disposition after review is a typed conflict.
- The process-memory adapter mirrors the same invariants under its shared
  asyncio lock and is test/dev-only.

## Scenario: Creator Agent Evidence Graph projection

Evidence Graph is a read projection over the current Creator Model and the
account's immutable Decision Record and Learning Signal snapshots. It does not
introduce an Evidence write table or mutate any source snapshot.

- `list_evidence` reads all three snapshot families inside one Postgres read
  transaction; the memory fallback copies its maps under `_mem_lock` before
  assembling the graph.
- The same pure projection helper is used after either read path. Nodes are
  deduplicated by `evidence_id`, references by `(reference_type, target_id,
  model_revision)`, and both node and reference ordering is deterministic.
- Learning Signal references resolve payloads through their original Decision
  Record evidence snapshot. The current model cannot rewrite that provenance.
- Both methods are account-scoped: `get_evidence` returns `None` for a missing
  node or a node owned by another account, while list filters are exact enum
  matches.

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

---

## Scenario: Durable Creator-Statistics Imports

### Contract

Live creator-statistics imports are a durable snapshot operation, not an
in-memory convenience path.

- `sync-stats --no-dry-run` explicitly initializes the app pool and ensures
  account, creator-statistics, and creative-memory tables before fetching data.
  If that preparation fails, it must stop before the remote pull; reporting a
  successful live import that disappears on process exit is incorrect.
- The fixture `--dry-run` path remains offline and may use the in-memory
  fallback, so tests and local smoke checks do not require PostgreSQL.
- The user-facing `POST /api/analytics/creator-stats/sync` route is
  browser-only: it resolves the selected account's bound CDP endpoint and
  passes `dry_run=False` with no cookie fallback to the service. Legacy
  `dry_run` and `cookie` request fields may be parsed for compatibility, but
  must never change that route's behavior. An unavailable endpoint returns an
  actionable failure without touching an existing durable snapshot.
- Persist an account overview and all imported note rows through one database
  transaction (`upsert_bundle`), so readers never observe a partially written
  creator-statistics snapshot.
- Assign that atomic import an opaque `snapshot_id` derived from the account,
  `data_as_of`, and a deterministic digest of the complete canonical note set.
  Persist the ID with the account raw snapshot. Readers of older rows may
  recompute the same digest without writing; they must never derive a page
  snapshot from only the selected rows. A metric overwrite at the same
  `synced_at` therefore remains observable as a new snapshot.

### Scheduled Import Operations

The FastAPI lifespan starts one process-local creator-statistics scheduler only
when PostgreSQL is ready and `CREATOR_STATS_SYNC_INTERVAL_HOURS` is positive.
The scheduler performs its first active-account import immediately after
startup, then sleeps for the configured interval.  `/health` exposes only a
sanitized summary (`enabled`, `status`, run counters, timestamps, counts, and
the next run time); it must not include raw account payloads, cookies, or
request signatures.  The deployment script must pass the interval environment
variable into the backend container so a host setting is not silently replaced
by the default.
- When the authenticated Creator Center page emits `/api/galaxy/user/info`,
  capture its public account identity in the same snapshot and persist only the
  explicit allowlist: platform user ID, nickname, RED ID, avatar URL, bio,
  creator role, and region. The profile response is an enrichment, so a missing
  profile response must not roll back successfully fetched metrics or notes.
- After a successful **real browser** Creator Center import, mirror a non-empty
  allowlisted `creator_name` into `accounts.name` when it differs. Account
  selectors must then show the imported XHS nickname consistently. This
  best-effort display update happens after the durable statistics upsert, never
  lets an empty profile erase an existing name, and is forbidden on fixture
  imports.
- Schema upgrades for those profile columns must use `ADD COLUMN IF NOT EXISTS`
  and the profile fields must be included in the same account upsert as the
  metric snapshot. This keeps old deployments upgrade-safe and readers
  consistent after a sync.
- Style-DNA deposits merge by `(account_id, tone, visual_style)`. Use both the
  in-process identity lock and `style_merge_transaction`'s PostgreSQL advisory
  transaction lock around the read/merge/write sequence; a primary key on a
  generated `style_id` alone does not protect that logical identity.
- Historical creative-quality reports read the account's complete durable note
  history through `list_all_note_stats(account_id)`, not the bounded
  `list_note_stats()` display reader. The quality route must never start a
  browser sync or write a database row.
- `GET /api/analytics/creator-stats/{account_id}/quality?locale=zh-CN|en`
  returns a deterministic report over the complete durable history. The
  response envelope and deterministic analyzer report use
  `scope="account_history"`. Fewer
  than three imported notes is an insufficient-data response: `overall_score`
  is `null`, `grade="insufficient_data"`, and the only recommendation is to
  collect more real history. The locale controls generated summary, evidence,
  and recommendation copy; unsupported values fall back to `zh-CN`.

### Do Not

- Do not let a standalone CLI rely on FastAPI's lifespan to initialize its
  database pool.
- Do not expose a fixture-backed import through a user-facing HTTP route, even
  as a default or compatibility fallback. Seed fixture data through the service
  or CLI test path instead.
- Do not split the account overview and note upserts into independent commits.
- Do not store `phone`, permission maps, real-name verification, cookies,
  tokens, or other non-allowlisted current-user fields from Creator Center.
- Do not use a generated style ID as the only concurrency guard for a
  tone/visual merge.
- Do not reuse the normal note-list pagination limit for account-wide quality
  analysis, or turn a low-sample response into a numeric quality judgement.

### Read-only Single-Note Detail and Quality

Imported historical notes can be read without starting a browser sync. The
detail route reads one persisted NoteStats DTO, while the quality route passes
that DTO to the deterministic analyze_note_quality service.

- GET /api/analytics/creator-stats/{account_id}/notes/{note_id} returns one
  safe note DTO, including the body snippet and optional detail/audience fields.
- GET /api/analytics/creator-stats/{account_id}/notes/{note_id}/quality returns
  the single-note quality report.

Both endpoints are read-only. They must not call sync_account_stats, open CDP,
write creator-statistics rows, or deposit Creative Memory. The single-note
quality report reuses the historical analyzer's rate normalization, dimensions,
thresholds, evidence, and recommendations. A dimension that requires multiple
notes (currently consistency) is returned with available=false; it must not be
converted into a fabricated score. Missing imported notes return the structured
ERROR_CREATOR_NOTE_NOT_FOUND 404 response.

## Scenario: Canonical history reader and durable evaluation runs

### 1. Scope / Trigger
- Trigger: Analytics and Evaluation need the same imported-note collection, or
  a historical note evaluation must survive refresh and be auditable.

### 2. Signatures
- `list_note_stats_page(account_id, *, cursor, limit, published_from, published_to) -> NoteStatsPage`
- `GET /api/analytics/creator-stats/{account_id}/notes`
- `quality_evaluations.ensure_tables()`, `get_cached(...)`, `create_run(...)`,
  `update_run(...)`, `get_latest_for_subject(...)`

### 3. Contracts
- History ordering is `(published_at DESC, note_id DESC)`; cursor is opaque and
  `total` is the full filtered count, independent of the cursor remainder.
- Every page returns `account_id`, `items`, `total`, `next_cursor`, `data_as_of`,
  query filters, and `engagement_rate_unit="fraction"`; item DTOs carry
  `subject_type="imported_note"`, `assessment_type="historical_performance"`,
  `scope="account_history"`, and `note_synced_at`.
- `get_creator_stats_snapshot(account_id)` is the storage-layer source for
  `data_as_of`/`snapshot_id` in canonical pages, Analytics, and quality/detail
  responses. It is read-only and must include the complete account population,
  including legacy Postgres rows where no account overview row exists.
- Consumers that both calculate from imported notes and return snapshot
  metadata should use the read-only `get_creator_stats_snapshot_bundle`
  contract (account + complete notes + metadata). They must not call
  `list_all_note_stats` and then `get_creator_stats_snapshot` independently;
  both values need the same repeatable-read boundary.
- A Postgres canonical page must read its filtered count, selected rows, account
  row and complete note population in one explicit `REPEATABLE READ` transaction.
  The snapshot metadata is derived before that transaction is released; it must
  not call a second-connection snapshot reader after the page query. This keeps
  `items` and `snapshot_id` from mixing two concurrent imports (READ COMMITTED
  creates a new statement snapshot for every SELECT, even on one connection).
- `quality_evaluation_runs` stores source/content/context hashes,
  evaluator fingerprint, status, result/coverage/threshold JSON and timestamps.
  Historical Creator Stats evaluations must persist the canonical bundle
  identity in `result_json.source.snapshot_id`; this is additive JSON metadata,
  so old rows remain readable through the timestamp-compatible fallback. The
  in-memory fallback is test/dev only; Postgres startup calls `ensure_tables`.

### 4. Validation & Error Matrix
- Blank account ID → structured validation error at the API boundary.
- Unsupported sort or malformed cursor → 400; never silently restart page one.
- Cursor pages over 500/600 rows must have no duplicate or skipped IDs.
- Historical report reads `list_all_note_stats`; it must not use the bounded
  display reader or trigger a browser sync/write.
- DB/cache failure → log and return the safe in-memory/empty fallback; never
  claim a newer `data_as_of` than the rows actually read.

### 5. Good/Base/Bad Cases
- Good: two clients traverse the same cursor stream and receive identical IDs,
  metrics and snapshot metadata.
- Base: old clients keep using bounded overview/detail routes with additive fields.
- Bad: Analytics sorts by engagement while Evaluation sorts by publish time and
  labels both as the complete historical list.

### 6. Tests Required
- Assert stable cursor traversal, complete `total`, fraction normalization and
  `data_as_of` for >500 rows and tied timestamps.
- Assert account isolation and read-only quality/detail routes.
- Assert cached runs are idempotent, forced runs retain prior versions, latest
  lookup includes stale/degraded audit records, and a changed Creator Stats
  bundle marks an older evaluation stale.

### 7. Wrong vs Correct
```python
# Wrong: reuse the 100-row display preview for a complete account report.
notes = await list_note_stats(account_id, limit=100)

# Correct: one canonical cursor reader for pages, full reader for aggregates.
page = await list_note_stats_page(account_id, cursor=cursor, limit=50)
all_notes = await list_all_note_stats(account_id)
```

## Scenario: Creator Agent Action Intent lifecycle

Action Intents use a unique `(account_id, idempotency_key)` in
`creator_agent_actions`. The memory adapter mirrors that constraint under its
existing lock. Creation returns the original payload on retry and never
overwrites candidate IDs or action kind. Resolution locks the intent, permits
only one transition from `pending_confirmation`, and stores `confirmed` or
`cancelled` without invoking an external executor.

## Scenario: Creator Agent Decision Dataset projection

The Decision Dataset is a read-only projection over the immutable
`creator_agent_decisions` and feedback-derived
`creator_agent_learning_signals` payloads. It introduces no table or migration.

- `list_decision_dataset` orders rows by `created_at DESC, decision_id DESC` and
  uses a versioned cursor containing only that canonical sort key. Filters are
  applied before both the complete `total` and cursor traversal.
- The memory fallback copies the account's decision and signal maps under
  `_mem_lock`, then delegates to the pure projection helper. The Postgres path
  reads both snapshot families inside one explicit `REPEATABLE READ` transaction
  before assembling the page. Both paths must return equivalent account-scoped
  rows and never expose another account's snapshots.
- A dataset entry returns the original `DecisionRecord` snapshot verbatim and
  only the stable ascending Learning Signal IDs linked by account and
  `decision_id`; signal payloads are not joined into the entry.
- Malformed cursors and limits outside `1..100` are validation failures. A
  cursor never silently restarts at page one.
