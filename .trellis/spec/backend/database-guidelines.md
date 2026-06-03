# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

This project does not use a traditional ORM. Persistence is handled by LangGraph's checkpointer system:

- **Dev mode**: `MemorySaver` (in-process, no external DB)
- **Prod mode**: `AsyncPostgresSaver` (LangGraph-managed, requires `POSTGRES_URI`)

The checkpointer stores workflow state snapshots (thread-based). XHS does not define or manage tables/migrations — LangGraph handles that internally via `checkpointer.setup()`.

---

## Query Patterns

No direct SQL queries in the application code. All state reads/writes go through:

- `graph.aget_state(config)` — read current state snapshot
- `graph.aupdate_state(config, values)` — update state (used by API routes)
- `graph.ainvoke(initial_state, config)` — run workflow

The API persistence layer (`WorkflowRegistry` in `backend/api/routes/workflow.py`) uses a JSON file (`~/.xhs-growth/workflow_registry.json`) for dev mode, with `fcntl` locking for concurrency safety.

---

## Migrations

Not applicable — LangGraph manages the Postgres schema. The only setup call is:

```python
checkpointer = AsyncPostgresSaver.from_conn_string(db_uri)
await checkpointer.setup()  # Creates/updates LangGraph tables
```

---

## Naming Conventions

| Convention | Example |
|-----------|---------|
| Thread IDs | UUID format: `xhs-{uuid4}` |
| State keys | snake_case matching `XHSGrowthState` TypedDict fields |
| Registry files | `workflow_registry.json` |

---

## Common Mistakes

- **Don't** query the Postgres DB directly — always use LangGraph's state API
- **Don't** forget `await checkpointer.setup()` before first use
- **Don't** store secrets in state — `XHS_COOKIE`, `RIPPLE_API_TOKEN` go in env vars only
- **Don't** use `MemorySaver` in production — it's process-scoped and doesn't survive restarts