# Persist LangGraph State to Postgres

## Goal

Switch from MemorySaver to AsyncPostgresSaver so workflow state survives container restarts.

## Problem

1. `langgraph-checkpoint-postgres` is not installed — `compile_graph_prod` hits ImportError and silently falls back to MemorySaver
2. Health check hardcodes `"mode": "memory"` — doesn't reflect actual checkpointer type
3. `compile_graph_prod` doesn't pass `store` (InMemoryStore) — memory store is lost even with Postgres checkpoints

## Requirements

* Add `langgraph-checkpoint-postgres` to pyproject.toml dependencies
* Rebuild backend image with the new dependency
* Fix health check to dynamically report checkpointer mode
* Fix `compile_graph_prod` to also use a persistent store (or document the tradeoff)

## Acceptance Criteria

- [ ] `langgraph-checkpoint-postgres` is in pyproject.toml
- [ ] Container has `langgraph-checkpoint-postgres` installed
- [ ] App startup uses AsyncPostgresSaver (not MemorySaver)
- [ ] Health check reports `"mode": "postgres"` when using Postgres checkpointer
- [ ] Workflow state survives container restart (`deploy.sh restart`)

## Technical Notes

- `compile_graph_prod` already implemented in builder.py:257
- `app.py` already calls it when `POSTGRES_URI` is set
- Missing dep: `langgraph-checkpoint-postgres` (provides `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`)
- Need `langgraph-checkpoint-postgres>=2.0` (compatible with langgraph 1.2.4)
