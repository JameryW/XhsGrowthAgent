# Free Creation Mode Contract

> Thread-less standalone creation/evaluation/publish/draft-management for the
> `/tui?mode=free` free creation mode. Backs the omp agent's free-mode host tools.

---

## Scope / Trigger

- Any route in `backend/api/routes/free.py`
- Any omp host tool named `xhs_free_*`
- Any frontend logic gated by `isFreeCreationEntry` (`route.query.mode === 'free'`)
- The free creation entry (`/tui?mode=free`) and its TUI commands (`/start`, `/drafts`, `/draft <id>`, `/delete <id>`)

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
| GET | `/drafts/{account_id}` | — | `{account_id, drafts: [{draft_id, title, hashtags, created_at, updated_at, last_evaluation, published}]}` (sorted newest-first by `updated_at`; metadata fields optional — see Draft Status Metadata) |
| GET | `/draft/{draft_id}` | query `account_id` | `{draft_id, draft}` |
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
- `xhs_free_guide` → no backend call (local); returns the orchestration guide text

### Discovery — no system prompt on the bridge path

The Web TUI free mode goes through the Python RPC bridge (`OmpSession`), NOT
the TS extension. The omp RPC protocol has **no `set_system_prompt` command**
and no `before_agent_start` hook (that hook is TS-extension-API only). So the
bridge **cannot inject a system prompt** — the agent discovers the free tool
chain via:

1. Each `xhs_free_*` tool's `description` carries step numbering + chain hints
   (e.g. "Step 1 of 3 (create) ... feed draft_id to xhs_free_evaluate (step 2)").
2. `xhs_free_guide` is a read-only host tool returning the full orchestration
   guide (create → evaluate → publish + draft management + "do not call
   thread-bound tools"). The agent can call it first to learn the loop.

The TS extension path (`events.ts` `before_agent_start`) DOES inject a system
prompt — kept in sync with the bridge's tool descriptions per the cross-audit
convention (both guide the agent to the same `xhs_free_*` chain).

---

## Contracts

### Persistence — BaseStore, no checkpoint

Free drafts live in the LangGraph `BaseStore` under namespace
`("accounts", account_id, "free_drafts")`, keyed by `draft_id` (uuid4).

- `store.aput(ns, key=draft_id, value=record)` — create / overwrite (update reuses the same key)
- `store.aget(ns, key=draft_id)` → `Item | None` (`.value` is the record dict)
- `store.adelete(ns, key=draft_id)` — real delete, idempotent
- `store.asearch(ns, query="", limit=100)` → list items; **on the `BaseStore` ABC**, portable across `InMemoryStore` / `AsyncPostgresStore` (no `# type: ignore`). An empty `query` returns all items in the namespace. Wrap in `try/except` — a store backend without a semantic index throws, degrading to an empty list (graceful). **Do NOT use `store.alist`** — it is not on the `BaseStore` ABC (see the Wrong-vs-Correct section below).

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
- Free-mode `/draft <id>` renders a single draft's full record; non-free mode shows `freeWorkflowOpDisabled`.
- Free-mode `/delete <id>` GETs the draft (to show its title — acts as confirmation, since there is no y/n state machine), then DELETEs it; non-free mode shows `freeWorkflowOpDisabled`. The DELETE route is idempotent, so re-running is safe. A GET 400 (draft not found) aborts the delete — no silent success on a bad id.
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
| Draft not found (get) | `_load_draft` raises `ValidationError` → 400 |
| Delete non-existent draft | `adelete` is idempotent → returns `{deleted: true}` (no 404) |
| `store.asearch` unsupported (no semantic index) / throws | caught → returns empty drafts list (graceful) |
| Corrupt draft value (non-dict) | `_load_draft` raises `ValidationError` → 400 |
| Free-mode account has no cookie / no CDP endpoint | `run_publish` returns structured `recovery` dict (fail fast) |

---

## Tests Required

- `tests/unit/api/test_free_routes.py`: create/evaluate/publish + list/get/update/delete (draft persistence, draft_id stability on update, delete empties list, missing-draft 400s)
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

### Wrong: calling `store.alist`

`alist` is not on the `BaseStore` ABC → mypy strict fails (`# type: ignore[attr-defined]` needed), and a store backend without it throws at runtime. It is only on concrete classes (`InMemoryStore` / `AsyncPostgresStore`), so it is not portable.

### Correct: use `store.asearch` (on the `BaseStore` ABC, portable)

`asearch` is on the `BaseStore` ABC — no `# type: ignore`, portable across store backends. An empty `query` lists all items in the namespace. Wrap in `try/except` because a backend without a semantic index throws (degrade to empty list):

```python
try:
    items = await store.asearch(_draft_ns(account_id), query="", limit=100)
except Exception:
    items = []
```

---

## Draft Status Metadata

Free draft records carry lightweight status metadata so the `/drafts` list can
surface which draft is newest, which has been evaluated (and its score/decision),
and which has been published. These are **server-set** (not client input) — they
do NOT appear on the `FreeDraft` input model; they are set on the `record` dict
after `model_dump()`, the same way `draft_id` is set.

### Fields

| Field | Type | Set by | Notes |
|-------|------|--------|-------|
| `created_at` | ISO 8601 UTC str | `create_draft` | Set once; never changed by update. |
| `updated_at` | ISO 8601 UTC str | `create_draft`, `update_draft`, `evaluate_draft`, `publish_draft` (on success) | Refreshed on every write-back. |
| `last_evaluation` | `{overall_score, decision} \| None` | `evaluate_draft` | Only the summary pair is persisted; the full `evaluation_result` is still returned to the agent but not stored on the draft. |
| `published` | `bool` | `publish_draft` (on success) | Set `True` only when `publish_result.status` ∈ `{"published", "mock_published"}`. |

### Write-back behavior

- **`evaluate_draft`**: after computing `evaluation`, loads the draft via
  `_load_draft`, sets `draft["last_evaluation"] = {"overall_score": ..., "decision": ...}`
  + refreshes `updated_at`, then `store.aput` back. The full `evaluation_result`
  is returned to the agent unchanged.
- **`publish_draft`**: only on success (`status` ∈ `{"published", "mock_published"}`)
  sets `draft["published"] = True` + refreshes `updated_at`. Failures (`status == "failed"`,
  `"auth_failed"`, etc.) do NOT mutate the draft.
- **`update_draft`**: refreshes `updated_at` on the merged record; `created_at` is preserved.

### `list_drafts` surface + sort

`list_drafts` returns `created_at`, `updated_at`, `last_evaluation`, `published`
alongside the existing `draft_id` / `title` / `hashtags`. Drafts are sorted
newest-first by `updated_at`:

```python
drafts.sort(key=lambda d: d.get("updated_at") or "", reverse=True)
```

ISO strings sort lexicographically = chronologically; drafts without `updated_at`
(old records) map to `""` and sort last.

### Graceful degradation

Existing stored drafts lack these fields. All reads use `value.get(field, default)`:
missing `last_evaluation` → `None` (no badge), missing `published` → `False` (no badge),
missing `updated_at` → sorts last. No migration is needed; fields are optional.

### TUI display

`handleDrafts` (AgentTUI.vue) renders one line per draft with status badges:

```
  <id>: <title>  [评估 <score> <decision>] [已发布]  <updated_at>
```

- Evaluation badge: only if `last_evaluation` present; decision colored
  (`approved`→green, `needs_revision`→yellow, `rejected`→red).
- Published badge: cyan `已发布` if `published`.
- `updated_at`: trimmed to `YYYY-MM-DDTHH:MM`, dim.
- Drafts with no metadata: title only (no badges).

---

## Related

- `backend/agents/evaluator.py` — `EvaluatorAgent.execute` (reused, not modified)
- `backend/agents/publisher.py` — `run_publish` (reused, not modified)
- `backend/api/routes/optimization.py` — the thread-bound draft route (free mode's counterpart, NOT reused)
- `.trellis/spec/backend/omp-integration.md` — host tool auto-execution mechanism
