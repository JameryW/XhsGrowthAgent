# Free Creation Mode Contract

> Thread-less standalone creation/evaluation/publish/draft-management for the
> `/tui?mode=free` free creation mode. Backs the omp agent's free-mode host tools.

---

## Scope / Trigger

- Any route in `backend/api/routes/free.py`
- Any omp host tool named `xhs_free_*`
- Any frontend logic gated by `isFreeCreationEntry` (`route.query.mode === 'free'`)
- The free creation entry (`/tui?mode=free`) and its TUI commands (`/start`, `/drafts`)

Free mode lets the omp agent drive creation conversationally **without a LangGraph
workflow thread**. It is fully isolated from the fixed trend/brief workflow:
drafts never enter the checkpoint, and the workflow slash commands stay disabled.

---

## Signatures

### Backend routes (`backend/api/routes/free.py`, mounted at `/api/free`)

| Method | Path | Body / Query | Response (`data`) |
|--------|------|--------------|-------------------|
| POST | `/draft` | `FreeDraft` (account_id, title, body, hashtags, image_paths, niche, content_angle, target_audience) | `{draft_id, draft}` |
| POST | `/evaluate` | `FreeDraftRef` (account_id, draft_id) | `{draft_id, account_id, evaluation_result}` |
| POST | `/publish` | `FreeDraftRef` (account_id, draft_id) | `{draft_id, account_id, publish_result}` |
| GET | `/drafts/{account_id}` | — | `{account_id, drafts: [{draft_id, title, hashtags}]}` |
| PATCH | `/draft/{draft_id}` | query `account_id`; body `FreeDraftUpdate` (all fields optional) | `{draft_id, draft}` |
| DELETE | `/draft/{draft_id}` | query `account_id` | `{draft_id, deleted: true}` |

### omp host tools (`backend/services/omp_bridge.py`)

Registered in `XHS_HOST_TOOLS`, auto-executed by `_execute_xhs_host_tool` via
internal httpx to `/api/free/*` (the `url` already includes `/api`, so paths are
`/free/...`). Agent reaches them over the WebSocket.

- `xhs_free_draft_create` → POST `/free/draft`
- `xhs_free_evaluate` → POST `/free/evaluate`
- `xhs_free_publish` → POST `/free/publish`
- `xhs_free_draft_list` → GET `/free/drafts/{account_id}`
- `xhs_free_draft_update` → PATCH `/free/draft/{draft_id}?account_id=...`
- `xhs_free_draft_delete` → DELETE `/free/draft/{draft_id}?account_id=...`

---

## Contracts

### Persistence — BaseStore, no checkpoint

Free drafts live in the LangGraph `BaseStore` under namespace
`("accounts", account_id, "free_drafts")`, keyed by `draft_id` (uuid4).

- `store.aput(ns, key=draft_id, value=record)` — create / overwrite (update reuses the same key)
- `store.aget(ns, key=draft_id)` → `Item | None` (`.value` is the record dict)
- `store.adelete(ns, key=draft_id)` — real delete, idempotent
- `store.alist(namespace_prefix=ns, limit=100)` — list items; **not on the `BaseStore` ABC**, only on `InMemoryStore` / `AsyncPostgresStore` concrete classes → must wrap in `try/except` + `# type: ignore[attr-defined]` (same pattern as `system.py` health check)

Drafts never enter the LangGraph checkpoint. Free mode has no `thread_id`. Drafts
do NOT participate in workflow resume/retry.

### Reuse — no reimplementation

- **evaluate**: synthesizes a minimal `XHSGrowthState` (`copy_content` + `content_plan` + `niche` + `account_id`) and calls `EvaluatorAgent.execute(state, store)`. The thread only mattered for checkpoint storage, not the evaluator logic. `EvaluatorAgent` tolerates `store=None` (skips memory recall).
- **publish**: synthesizes a minimal state (`copy_content` + `content_plan` + `visual_plan` + `publish_options.account_id`) and calls `run_publish(state, store)` — the same real-publish path `PublisherAgent` uses (CDP resolution, account validation, `XHSClient.publish_post`, `ContentHistory` recording). Publish results are recorded to account memory by `run_publish` itself.
- **helpers**: `_draft_ns(account_id)`, `_load_draft(request, account_id, draft_id)`, `_to_copy_content(draft)` shared across routes.

### Isolation — free mode does not touch the workflow

- Free drafts stay out of the LangGraph checkpoint.
- Free-mode `/start` = omp `new_session` (clears conversation), NOT `handleStart`.
- Free-mode `/drafts` lists free drafts; non-free mode shows `freeWorkflowOpDisabled`.
- Workflow slash commands (`/status` `/pause` `/resume` `/cancel` `/approve` `/reject`) stay disabled in free mode.
- AgentTUI free entry defaults to **agent mode** on mount (plain text → omp conversation); non-free (trend/brief) keeps command mode.

### Non-free behavior unchanged

All new logic is guarded by `isFreeCreationEntry` (`route.query.mode === 'free'` on the frontend; the backend routes are additive and never called by the fixed workflow). Trend/brief mode behavior is identical to before.

---

## Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| `store is None` (graph has no store) | POST/GET/PATCH/DELETE raise `ValidationError("store", ...)` → 400 |
| Empty `draft_id` on evaluate/publish/update/delete | `ValidationError("draft_id", ...)` → 400 |
| Draft not found (evaluate/publish/update) | `_load_draft` raises `ValidationError` → 400 |
| Delete non-existent draft | `adelete` is idempotent → returns `{deleted: true}` (no 404) |
| `store.alist` unsupported / throws | caught → returns empty drafts list (graceful) |
| Corrupt draft value (non-dict) | `_load_draft` raises `ValidationError` → 400 |
| Free-mode account has no cookie / no CDP endpoint | `run_publish` returns structured `recovery` dict (fail fast) |

---

## Tests Required

- `tests/unit/api/test_free_routes.py`: create/evaluate/publish + list/update/delete (draft persistence, draft_id stability on update, delete empties list, missing-draft 400s)
- `tests/unit/services/test_omp_bridge.py`: each `xhs_free_*` host tool — assert POST/GET/PATCH/DELETE path + json body + text result shape

---

## Wrong vs Correct

### Wrong: storing free drafts in the LangGraph checkpoint

Free mode has no thread. Trying to reuse `POST /optimization/draft/{thread_id}` (which writes to checkpoint state via `aupdate_state`) would force a fake thread and break isolation.

### Correct: thread-less BaseStore namespace

```python
await store.aput(("accounts", account_id, "free_drafts"), key=draft_id, value=record)
```

### Wrong: reimplementing publish logic for free mode

Duplicating CDP resolution + `XHSClient.publish_post` + `ContentHistory` recording would drift from the workflow's publish path.

### Correct: reuse `run_publish`

```python
pub_state = _build_publish_state(draft)  # synthesized minimal XHSGrowthState
result = await run_publish(pub_state, store)
```

### Wrong: calling `store.alist` without a guard

`alist` is not on the `BaseStore` ABC → mypy strict fails, and a store backend without it throws at runtime.

### Correct: wrap in try/except + type:ignore

```python
try:
    items = await store.alist(namespace_prefix=_draft_ns(account_id), limit=100)  # type: ignore[attr-defined]
except Exception:
    items = []
```

---

## Related

- `backend/agents/evaluator.py` — `EvaluatorAgent.execute` (reused, not modified)
- `backend/agents/publisher.py` — `run_publish` (reused, not modified)
- `backend/api/routes/optimization.py` — the thread-bound draft route (free mode's counterpart, NOT reused)
- `.trellis/spec/backend/omp-integration.md` — host tool auto-execution mechanism
