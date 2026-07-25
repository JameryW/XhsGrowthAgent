# PRD: Fix OMP session interruptions + daily creator-stats sync

## Background

Production logs showed `ValueError('Separator is found, but chunk is longer than limit')`
from `OmpSession._read_stdout` (3 occurrences) — asyncio's default 64 KiB StreamReader
limit killed the stdout reader on oversized NDJSON lines, silently freezing agent turns
mid-run. Code review found a family of related interruption causes across the bridge,
the WS route, and the frontend.

## Scope

### P0 — reader resilience (`backend/services/omp_bridge.py`)
- `create_subprocess_exec(..., limit=16 MiB)` for omp stdout/stderr.
- `_read_stdout` wrapped: EOF or reader error → `_handle_process_died` (fail pending
  futures, cancel host-tool tasks, clear busy, emit `error` + `session_end`, invoke
  manager `_drop_session`). CancelledError (stop path) is not treated as a crash.

### P1 — reconnect continuity
- Every emitted event gets a monotonic `seq`; per-session bounded ring buffer (1000).
- `agent.py`: `?session_id=&last_seq=` reconnect replays `events_after(last_seq)`
  only when the same live session is resumed (`resumed` flag in `connected` status).
- Frontend (`AgentTUI.vue`): persists `{sessionId, lastSeq}` per mode in
  sessionStorage, passes them on reconnect, resets cursor on `resumed: false`.
- Application-level heartbeat: backend sends `{"type":"ping"}` after 25s of silence;
  frontend replies `{"type":"pong"}` (backend ignores it).

### P2 — lifecycle robustness
- `OmpBridgeManager`: dead/zombie sessions replaced on `get_or_create_session`;
  `_drop_session` hook; idle timer defers while `session.is_busy`; `stop(grace_seconds=10)`
  lets in-flight turns finish before SIGTERM (bounded by podman's stop timeout).
- `OMP_IDLE_TIMEOUT` env var actually honored (was documented but unimplemented).
- `agent.py` sender logs instead of dying silently; ready timeout 30s → 60s (cold start).
- omp `auto_retry`/`auto_compaction` events forwarded as `retrying`/`compacting`
  status; frontend relabels the waiting spinner in place.

### Config — creator stats sync interval 6h → 24h
- `backend/config/settings.py`, `scripts/deploy.sh`, `.env.example`,
  `docs/deployment.md`, `docs/configuration.md`.

## Verification

- `pytest tests/unit` — 1533 passed
- `pytest tests/unit/api/test_agent_ws.py` — 3 passed (replay + pong contracts)
- `vitest run tests/views/AgentTUI.spec.ts` — 14 passed
- `vue-tsc --noEmit`, `mypy`, `ruff check` — clean
- Pre-existing unrelated failure: `EvaluationView.spec.ts > all-accounts workflow scope`
  (fails on clean tree too — confirmed via git stash)

## Learnings

- asyncio subprocess pipes default to a 64 KiB StreamReader limit; any NDJSON-ish
  protocol carrying accumulated text MUST pass an explicit `limit=` and wrap the
  reader loop — an unhandled reader-task exception is invisible until GC.
- A reconnect protocol needs both a session id and an event cursor (`seq`), plus a
  `resumed` flag: a fresh subprocess behind a familiar id must reset the cursor or
  replay silently drops events.
- Documented-but-unimplemented config (`OMP_IDLE_TIMEOUT`) is worse than no config —
  cross-check spec tables against code.
