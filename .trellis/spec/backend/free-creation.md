# Free Creation Mode Contract

> Thread-less standalone creation/evaluation/publish/draft-management for the
> `/tui?mode=free` free creation mode. Backs the omp agent's free-mode host tools.

---

## Scope / Trigger

- Any route in `backend/api/routes/free.py`
- Any omp host tool named `xhs_free_*`
- Any frontend logic gated by `isFreeCreationEntry` (`route.query.mode === 'free'`)
- The free creation entry (`/tui?mode=free`) and its TUI commands (`/start`, `/drafts`, `/draft <id>`, `/edit <id> <field> <value>`, `/delete <id>`, `/evaluate <id>`, `/analytics <id>`, `/suggest`)

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
| GET | `/drafts/{account_id}` | query `status` (optional: all\|published\|unpublished\|publish_failed\|evaluated\|unevaluated), `q` (optional title substring) | `{account_id, drafts: [{draft_id, title, hashtags, created_at, updated_at, last_evaluation, last_publish, published}], count, truncated, status, q}` (sorted newest-first by `updated_at`; metadata fields optional — see Draft Status Metadata; `count`/`truncated` reflect filtered/total respectively — see Status filter + title search) |
| GET | `/draft/{draft_id}` | query `account_id` | `{draft_id, draft}` |
| PATCH | `/draft/{draft_id}` | query `account_id`; body `FreeDraftUpdate` (all fields optional) | `{draft_id, draft}` |
| DELETE | `/draft/{draft_id}` | query `account_id` | `{draft_id, deleted: true}` |
| GET | `/analytics/{draft_id}` | query `account_id` | `{draft_id, post_id, analytics}` (400 if not published / no post_id / no CDP endpoint / fetch failure) |
| GET | `/suggestions/{account_id}` | — | `{account_id, mode: "free", suggestions: [{mode, category, title, advice, priority, evidence}], count, cold_start}` (atomic data fetch — delegates to `get_suggestions_for_mode`; carries NO orchestration cue; the omp agent decides what to do with the advice) |

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
- `xhs_free_analytics` → GET `/free/analytics/{draft_id}?account_id=...` (post-publish engagement; thread-less — uses `XHSClient.get_post_analytics(post_id)`, not the thread-bound workflow analytics)
- `xhs_free_suggestions` → GET `/free/suggestions/{account_id}` (creative suggestions from imported Creator Center stats; thread-less, no draft_id — atomic data fetch; `cold_start` flag when no stats imported)
- `xhs_free_guide` → no backend call (local); returns the usage-rules reference text

**Agent-side render** (`omp_bridge._execute_xhs_host_tool`): free mode defaults
to agent mode, so the omp agent reads these renders as plain text. The renders
align with the TUI surfaces, not duplicate the minimal backend response.
Renders carry **only guardrail `note:` cues** (mock/degraded/failure conditions
that would cause an incorrect subsequent call); they do **not** carry
orchestration `next:` cues — the omp agent decides the flow, not the tool:
- **`xhs_free_draft_create`**: `Free Draft Created — draft_id: <id>` + `Title`.
  No cue on success or failure (orchestration is the agent's job).
- **`xhs_free_draft_list`**: header with `count`, a `truncated` note when the
  route's 100-cap dropped older drafts, and per-draft badges —
  `[<score> <decision>]` when `last_evaluation` has a decision, `[degraded]`
  when `last_evaluation.degraded` is truthy (fake-approved fallback — shown
  instead of the misleading `[100 approved]`), `[published]` when published,
  `[publish failed]` when `last_publish.status` is a non-success
  (failed/auth_expired/...) — so the agent can see each draft's state at a
  glance without calling `xhs_free_draft` per item. Mirrors TUI `/drafts`
  (#216/#226/#227).
- **`xhs_free_publish`**: real publish (`status == "published"`, non-`mock_` post_id)
  → no cue. Mock publish (`mock_published` / `mock_*` post_id, dry-run) →
  `note: dry-run mock publish ... analytics not available` (guardrail: so the
  agent doesn't call analytics and 400 on a synthetic post_id). Failed publish
  (`status` not `published`/`mock_published` + an `error`) → surface the cause
  and recovery path `run_publish` returns: `Error: <error>`,
  `Error Type: <error_type>` (if present), `Recovery: <recovery.message>`
  (if present), `Hint: <recovery.hint>` (if present) — guardrail so the agent
  can tell the user why the publish failed and what to do.
  Mirrors the TUI post-publish hint (#223: mock_* → mock note).
- **`xhs_free_suggestions`**: rendered as a header line (`Free Creative Suggestions —
  <account_id>:`), a cold-start note when `cold_start` is true (limited-evidence
  advice), then one line per suggestion: `- [<category>] <title>: <advice> Evidence:
  <evidence>` (evidence omitted when empty). **Atomic data fetch only — no `next:`
  cue.** Per the free-mode atomic-tool principle, this tool surfaces suggestion data
  and nothing more; the omp agent owns all orchestration (whether/how to act on a
  suggestion is the agent's decision, not the tool's). Mirrors `xhs_creator_suggestions`
  minus the thread-bound mode param.
- **`xhs_free_evaluate`**: the verdict is rendered as plain text for the omp agent
  (overall/decision/bias/dimensions/hints). No `next:` cue on any decision
  (approved/needs_revision/rejected) — the agent decides whether to revise or
  publish. When `evaluation_result.degraded` is truthy (LLM timeout →
  pass-through fallback), the render prepends a `⚠ Evaluation degraded` marker +
  the cause — guardrail: the 100/approved is fake, not a real score; the agent
  must not publish on a degraded verdict. The guide text (`xhs_free_guide`)
  documents the same guardrails (thread-bound tools disabled, degraded verdict,
  publish failure) so an agent that reads the guide first also learns the
  guardrails. The guide also documents evaluate degradation: evaluate can return
  a pass-through fallback (`degraded=True`, fake `overall_score=100`/`approved`)
  on LLM timeout — the agent must NOT publish on a degraded verdict; the draft
  list shows a `[degraded]` badge (#242 sync). The guide also documents the
  publish-failure recovery: publish can fail (`status=failed`/`auth_expired`),
  the render surfaces `Error`/`Recovery`, the failed attempt persists as
  `last_publish` and the draft list shows a `[publish failed]` badge (#239/#240
  sync).

### Discovery — no system prompt on the bridge path

The Web TUI free mode goes through the Python RPC bridge (`OmpSession`), NOT
the TS extension. The omp RPC protocol has **no `set_system_prompt` command**
and no `before_agent_start` hook (that hook is TS-extension-API only). So the
bridge **cannot inject a system prompt** — the agent discovers the free tools
via:

1. Each `xhs_free_*` tool's `description` carries only its atomic capability
   (no step numbering, no chain hints — orchestration is the omp agent's job).
2. `xhs_free_guide` is a read-only host tool returning the usage-rules
   reference (tool list + guardrails: thread-bound tools disabled, degraded
   verdict, publish-failure recovery). The agent can call it to learn the
   rules.

### Mode-based tool isolation

Free mode registers **only** the free-mode tool subset (xhs_free_* + account-
bound general tools like xhs_analytics_*, xhs_system_health, xhs_creator_*).
Thread-bound workflow tools (xhs_workflow_*, xhs_review_*, xhs_optimization_*,
xhs_blogger_*, xhs_ripple_*, xhs_evaluation_*) are **not registered** — the
LLM never sees their descriptions. This is enforced at the bridge layer:

- `OmpSession.__init__(session_id, mode="workflow")` — session carries a mode.
- `OmpSession.start()` calls `register_host_tools(_tools_for_mode(self.mode))`
  — free mode gets the subset, workflow mode gets the full list.
- `OmpSession.set_mode(mode)` remains available for host-tool refreshes, but
  the manager restarts the subprocess when the mode changes so the TS
  extension's process-level tool registration cannot leak thread-bound tools.
- `OmpBridgeManager.get_or_create_session(session_id, mode="workflow")` — if
  an existing session's mode differs, replaces the session subprocess with
  the requested mode and re-registers the corresponding host-tool subset.
- The bridge sets `XHS_AGENT_MODE` for the subprocess; the TS extension skips
  thread-bound workflow/review/evaluation tools when it is `free`.
- `agent.py` WebSocket handler reads `mode` query param (default `"workflow"`)
  and passes it to `get_or_create_session`.
- Frontend `AgentTUI.vue` appends `?mode=free` to the WebSocket URL when
  `isFreeCreationEntry` (route.query.mode === 'free').

The TS extension path (`events.ts` `before_agent_start`) DOES inject a system
prompt — the bridge's tool descriptions and the TS prompt must stay aligned
per the cross-audit convention. The TS prompt documents the same failure-path
rules as the bridge guide: evaluate-degradation (#242 — don't publish on a
degraded verdict) and publish-failure recovery (#241 — read Error/Recovery,
fix the cause; don't call analytics on a failed publish). Both paths (bridge
guide + TS prompt) must stay aligned when a failure-path guardrail is added
or changed.

**Atomic-tool principle (free mode)**: free-mode host tools expose only atomic
data operations (create/evaluate/publish/analytics/draft CRUD). They carry no
orchestration — no step numbering, no `next:` chain cues, no "call X before Y"
sequencing in descriptions or renders. Tool descriptions describe only the
tool's own capability. Renders carry only guardrail `note:` cues (mock/degraded/
failure conditions that would cause an incorrect subsequent call). All flow
orchestration (which tool to call next, in what order) is the omp agent's
responsibility, not the tool's.

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

### Pattern — thread-less RQGM eval over a non-workflow entity

The free-draft `/evaluate` pattern generalizes to any content-bearing entity that
is NOT a LangGraph checkpoint. The historical-note evaluation
(`POST /api/evaluation/note`, `backend/api/routes/evaluation.py`) is the second
instance of this pattern. Reuse it — do not re-thread the entity.

**Problem**: `EvaluatorAgent.execute` reads `copy_content` / `visual_plan` /
`content_plan` / `niche` from `XHSGrowthState`. A historical note
(`NoteStats`, imported from Creator Center) has `title` / `body_text` / `tags` /
`cover_url` / `content_type` and NO `thread_id` / NO generation-side metadata
(`cover_prompt`, `layout_style`, `content_plan.selected_topic`).

**Solution — synthesize eval_state, call the same agent, do NOT checkpoint**:

```python
# backend/api/routes/evaluation.py:_build_note_eval_state
def _build_note_eval_state(
    note: NoteStats,
    niche: str,
    *,
    niche_source: str = "",
    niche_context_available: bool = False,
) -> XHSGrowthState:
    cover_url = (note.cover_url or "").strip()
    return cast("XHSGrowthState", {
        "account_id": note.account_id,
        "niche": niche or "",                    # no synthetic cold-start niche
        "niche_source": niche_source,
        "niche_context_available": niche_context_available,
        "visual_input_available": False,
        "historical_note": True,
        "copy_content": {
            "selected_title": note.title or "",
            "body_text": note.body_text or "",
            "hashtags": list(note.tags or []),
            "cta": "", "tone": "",                # notes lack these
        },
        "content_plan": {
            "selected_topic": "", "content_angle": "", "target_audience": "",
            "content_type": note.content_type or "note",
        },
        "visual_plan": {
            "cover_prompt": "",                   # no generation prompt
            "image_count": 1 if cover_url else 0,
            "image_prompts": [],
            "image_urls": [cover_url] if cover_url else [],  # real cover URL
            "layout_style": "", "color_palette": [],
        },
    })

# in the route:
eval_state = _build_note_eval_state(note, niche)
result = await _evaluator(eval_state, store=store)   # store may be None
# result returned to caller, NOT graph.aupdate_state — no thread to write to
```

**Why**: the evaluator's 10-dimension judge logic is thread-agnostic; only the
checkpoint persistence was thread-bound. Synthesizing the minimal state reuses
the exact same agent + weights + prompt epoch as the workflow `evaluator_gate`.

**Contracts**:
- Request: `POST /evaluation/note` body `{ account_id: str, note_id: str, force?: bool }`.
- Response `data` includes `evaluation_id`, `account_id`, `subject_type="imported_note"`,
  `subject_id`, `assessment_type="rqgm_content_review"`, `status`, `coverage`,
  `source` hashes/data timestamp, `evaluator_fingerprint`, `evaluated_at`,
  `thresholds`, and the nested `evaluation_result`.
- `status=ready|partial` may carry a score; `status=degraded|failed` MUST carry
  `overall_score=null`, `decision=null`, and `degraded=true`.
- Missing required dimensions (`copywriting`, `compliance`) or weighted coverage
  below `MIN_EVALUATION_COVERAGE` produces `partial` with no overall score;
  missing dimensions never receive a neutral 70.
- Historical visual/image-quality dimensions are unavailable until a multimodal
  evaluator actually reads image bytes. Missing niche context leaves audience/
  reach unavailable; it is never replaced by a synthetic `母婴` value.
- No checkpoint write (unlike `POST /evaluation/run/{thread_id}` which calls
  `graph.aupdate_state`). The note has no thread. Durable runs live in
  `quality_evaluation_runs`; unchanged input/fingerprint is idempotent and
  `force=true` creates a new auditable version.

**Validation & Error Matrix**:
| Condition | Error |
|-----------|-------|
| empty `account_id` | `ValidationError("account_id", ...)` → 400 |
| empty `note_id` | `ValidationError("note_id", ...)` → 400 |
| note not imported | `CreatorNoteNotFoundError(account_id, note_id)` → 404 |
| account has no `niche` | keeps `niche=""`, returns `niche_context_available=false`; audience/reach are unavailable |
| `store` is None | tolerated — `EvaluatorAgent` skips memory recall |
| LLM timeout (60s) / model error | `status=degraded`, null score/decision, retryable summary; never a fake pass |
| evaluator omits a dimension | dimension is `available=false`, `score=null`; coverage/threshold rules apply |
| same content/context/fingerprint and no `force` | return latest non-stale persisted run; do not call the model again |
| `force=true` or content/context changes | mark prior runs stale, create a new run, retain old versions |

**Wrong vs Correct — entity-specific error type**:

```python
# Wrong — WorkflowNotFoundError takes thread_id; a note is not a thread,
# and it returns the wrong ErrorCode (WORKFLOW_NOT_FOUND, not CREATOR_NOTE_NOT_FOUND)
raise WorkflowNotFoundError(f"{account_id}/notes/{note_id}")

# Correct — use the entity's own not-found error
raise CreatorNoteNotFoundError(account_id, note_id)
```

**Image input — text-only today, multimodal pre-wired**:
- `visual_plan.image_urls` is a new field threaded through `evaluator.yaml`
  user_template (`图片URL：{image_urls}`) and `EvaluatorAgent.execute`.
- Current model `astron-code-latest` (XUNFEI) is text-only — the URL is injected
  as text, so `visual` / `image_quality` dimensions are explicitly unavailable,
  not reference scores.
- When a multimodal model is routed to `TaskType.EVALUATION`, switch `ainvoke`
  to pass image+text messages; the `image_urls` field is already in place, no
  prompt-schema change needed.

**Tests required** (`tests/unit/api/test_evaluation_note.py`):
- note→state mapping asserts (title/body/hashtags/cover_url/content_type land in
  the right state sub-dicts).
- `cover_url=""` → `image_urls=[]`, `image_count=0`.
- account `niche=""` / account missing → empty niche + unavailable audience/reach.
- missing dimensions and timeout → partial/degraded null score; no 70/100/approved fallback.
- repeated unchanged request → same `evaluation_id` with `cache_hit`; `force=true` → new ID.
- note not found → 404, evaluator NOT called.
- empty account_id / note_id → 400.
- `store` from `graph.store` passed as positional arg #2 to `execute`.

**Frontend reuse**: `CreatorNoteQualityPanel.vue` keeps the existing
interaction-signal analyzer (`analyze_note_quality`) and adds the RQGM result as
an additive section — same `EvaluationRadar` component, same `evaluation.dim.*`
i18n keys. Trigger is a manual button (LLM call per note), not auto-on-select.
A `rqgmGeneration` counter is bumped on note/account switch so an in-flight eval
from the previous note no-ops instead of overwriting the new selection.

### Isolation — free mode does not touch the workflow

- Free drafts stay out of the LangGraph checkpoint.
- Free-mode `/start` = omp `new_session` (clears conversation), NOT `handleStart`.
- Free-mode `/drafts` lists free drafts; non-free mode shows `freeWorkflowOpDisabled`.
- Free-mode `/draft <id>` renders a single draft's full record; non-free mode shows `freeWorkflowOpDisabled`.
- Free-mode `/delete <id>` GETs the draft (to show its title — acts as confirmation, since there is no y/n state machine), then DELETEs it; non-free mode shows `freeWorkflowOpDisabled`. The DELETE route is idempotent, so re-running is safe. A GET 400 (draft not found) aborts the delete — no silent success on a bad id.
- Free-mode `/edit <id> <field> <value>` PATCHes `/free/draft/{id}` with `{<field>: <value>}` — single-line scalar-field edit. Allowed fields: `title`, `niche`, `content_angle`, `target_audience`. Unknown field → red error listing the allowed set; missing id/field/value → usage line. `body`/`hashtags`/`image_paths` are excluded (multi-line / list — agent handles those via `xhs_free_draft_update`). draft_id + created_at preserved, updated_at refreshed. Non-free mode shows `freeWorkflowOpDisabled`.
- Free-mode `/analytics <id>` GETs `/free/analytics/{draft_id}` and renders a boxed engagement table (views/likes/collects/comments/shares/engagement_rate/fetched_at); non-free mode shows `freeWorkflowOpDisabled`. Missing `<id>` prints `tui.analyticsMissing`; a 400 from the route (unpublished / mock-published / no CDP / fetch failure) prints the route's error message in red.
- Free-mode `/evaluate <id>` POSTs `/free/evaluate` (`{account_id, draft_id}`) and renders a boxed evaluation summary: `overall_score` (cyan), `decision` (approved→green / needs_revision→yellow / rejected→red), `dimensions` (`- dimension: score [BLOCKING]`, score cyan, BLOCKING tag red), `bias_warning` (magenta, only if non-empty), `revision_hints` (`•` list, only if non-empty). The route writes the `{overall_score, decision, revision_hints}` triple back onto the draft's `last_evaluation` + refreshes `updated_at`, so `/drafts` and `/draft <id>` reflect the new verdict after the command. Missing `<id>` prints `tui.evaluateMissing`; non-free mode shows `freeWorkflowOpDisabled`; a 400 (draft not found) prints the route's error in red. Closes the evaluate→edit loop — the `/draft <id>` revise hint points here.
- Workflow slash commands (`/status` `/pause` `/resume` `/cancel` `/approve` `/reject`) stay disabled in free mode.
- AgentTUI free entry defaults to **agent mode** on mount (plain text → omp conversation); non-free (trend/brief) keeps command mode.
- **Dispatch consistency:** all eight free slash commands (`/start`, `/drafts`, `/draft`, `/edit`, `/delete`, `/evaluate`, `/analytics`, `/suggest`) must be registered in **both** dispatchers — `processAgentCommand` (agent mode, the free default) and `processSlashCommand` (command mode, reachable via `/mode`). The handlers enforce the `isFreeCreationEntry` guard themselves, so both dispatchers just parse the trailing arg and forward. A command added to one dispatcher but not the other falls through to `unknownCommand` in the other mode — a past regression for `/evaluate` (agent mode) and `/drafts`/`/draft`/`delete` (command mode).
- **Atomic-tool principle (free mode):** free-mode host tools expose only atomic data operations — fetch suggestions, create/evaluate/publish a draft, list/get/update/delete. They carry **no orchestration**: no `next:` cue prescribing the next tool, no "use this to inform create" pointer, no step-numbering in descriptions. The omp agent owns all flow orchestration (create→evaluate→publish→analytics is the agent's decision, not the tool's). The exception is safety/handoff cues that prevent a wrong call (e.g. publish-failure `Recovery` hint, evaluate-`degraded` "do not publish" marker, mock-publish "analytics not available") — those are correctness guards, not flow prescription. `xhs_free_suggestions` follows this: it returns suggestion data + a count header + cold-start note, nothing more.

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
| Analytics on unpublished draft (no `post_id`) | `get_analytics` raises `ValidationError("post_id", ...)` → 400 (mock-published included — no real post_id) |
| Analytics with no CDP endpoint / fetch failure | `get_analytics` raises `ValidationError("cdp_endpoint"` / `"analytics", ...)` → 400 |
| `niche` empty/whitespace/null on create (POST `/draft`) | `FreeDraft._niche_normalize(mode="before")` normalizes empty/None/whitespace → `""` (auto-infer). `create_draft` then calls `resolve_account_niche(account_id, manual_niche="", cold_start_default="母婴", persist=True)`: manual non-empty wins; else inferred from imported creator-center note tags/titles; no history → `cold_start` 母婴. `niche_resolution` source (`manual`/`inferred`/`account_bound`/`cold_start`) returned in draft. Never silently forces 母婴 on a manual value. |
| `niche` empty/whitespace on update (PATCH `/draft/{id}`) | `FreeDraftUpdate._niche_fallback` normalizes empty to `""` (auto-infer on next evaluate); `None` (field omitted) = don't change (PATCH semantics). Prevents blanking niche via edit. |

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
| `updated_at` | ISO 8601 UTC str | `create_draft`, `update_draft`, `evaluate_draft`, `publish_draft` | Refreshed on every write-back — including failed publish attempts (a publish attempt is a meaningful update). |
| `last_evaluation` | `{overall_score, decision, revision_hints, degraded?, summary?} \| None` | `evaluate_draft` | The {overall_score, decision, revision_hints} triple + `degraded` + `summary` are persisted; the full `evaluation_result` (dimensions, bias_warning) is still returned to the agent but not stored on the draft. `degraded: True` marks a pass-through fallback (LLM timeout) — the 100/approved is fake, not a real score; `summary` carries the cause so `/draft <id>` + `/drafts` + the agent render can surface the degradation instead of showing a misleading "100 approved". |
| `last_publish` | `{status, error?, error_type?, at} \| None` | `publish_draft` (every attempt) | Persisted on **every** publish attempt — success writes `status` (`published`/`mock_published`) with error fields `None`; failure writes `status` (`failed`/`auth_expired`/...) + `error` + `error_type`. `at` is the attempt timestamp. Lets `/draft <id>` and the agent list render surface a failed publish's cause after the turn ends (#239 only surfaces it for the single tool call). A later success overwrites it. |
| `published` | `bool` | `publish_draft` (on success) | Set `True` only when `publish_result.status` ∈ `{"published", "mock_published"}`. Failures do NOT flip `published` (they only record via `last_publish`). |
| `post_id` | `str` | `publish_draft` (on success) | The XHS note id, from `publish_result.post_id`. Empty for mock-published. Used by `GET /free/analytics/{draft_id}` to fetch engagement. |
| `post_url` | `str` | `publish_draft` (on success) | The XHS note URL, from `publish_result.post_url`. |

### Write-back behavior

- **`evaluate_draft`**: after computing `evaluation`, loads the draft via
  `_load_draft`, sets `draft["last_evaluation"] = {"overall_score": ..., "decision": ..., "revision_hints": [...]}`
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

### Count + truncation

The response also carries `count` (len of the returned `drafts` list) and
`truncated` (bool). `list_drafts` caps `store.asearch` at `limit=100`; the
`asearch` limit is page size, not total — there is no portable total-count
API on `BaseStore`. So `truncated` is a **heuristic**: `true` when the
returned items hit the limit (`len(items) >= 100`), meaning more likely
exist. This is surfaced (not silently dropped) per the no-silent-caps
convention — the TUI renders a dim "showing first 100 — older drafts hidden"
line when `truncated`, and logs an info line server-side.

### Status filter + title search

`list_drafts` accepts two optional query params, both **post-filtered** over the
capped asearch page (no extra store call):

| param | values | semantics |
|-------|--------|-----------|
| `status` | `all` (default) \| `published` \| `unpublished` \| `publish_failed` \| `evaluated` \| `unevaluated` | `published` ↔ `published == True`; `publish_failed` ↔ `last_publish.status` present and not a success status (`published`/`mock_published`); `evaluated` ↔ `last_evaluation is not None`. Invalid value → 400 (whitelist fail-fast, not silent fallback). |
| `q` | title substring | case-insensitive `contains` against `title`; empty = no filter. |

`status` and `q` combine (AND). `count` reflects the **filtered** set; `truncated`
reflects the **pre-filter** 100-cap (whether the store likely holds >100 drafts
total) and is independent of the filter — a filtered-to-empty list can still
report `truncated=True`.

Why post-filter, not `asearch(filter=)`: BaseStore's `filter=` dict is exact
field-value match — it can't express "has `last_evaluation`" (presence check)
or substring match. Running both predicates over the already-returned page is
the portable call and costs nothing (the page is already in memory). This also
keeps `truncated` semantics honest (it measures the total set, not a filtered
slice). No-silent-caps: the filter narrows the view but never hides the fact
that older drafts beyond the 100-cap exist.

TUI `/drafts [status] [query…]`: first token matching the status whitelist is
the filter; the rest (or all, if no status token) is the title query. The title
line shows the active filter (e.g. `Free Drafts — acct (3, published):`). An
invalid status fails fast client-side with a localized message before the
request.

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

### `handleDraft` detail view

`/draft <id>` renders the full record, then a status block (after a `─` rule).
For published drafts, the block additionally shows the post URL + an action
hint, derived from the persisted `post_id`/`post_url` (see Draft Status
Metadata):

- `post_url` line (cyan) — only if `post_url` present.
- Real `post_id` (does not start with `mock_`): yellow hint
  `运行 /analytics <id> 查看互动数据` — points the user at the engagement
  command (closes the publish→analytics discoverability loop).
- Mock `post_id` (`mock_*`, from dry-run publish): yellow
  `mock-published (dry-run) — re-publish without dry-run for a real post`
  instead — mock-published drafts have no real note, so the analytics hint
  would mislead.
- Unpublished draft: no post lines (graceful).

The status block also renders `last_evaluation` (score/decision) and, when
present, `revision_hints` as a `•`-bulleted list. For `needs_revision` /
`rejected` drafts with non-empty hints, a yellow next-step hint follows the
list:

- `按上方建议用 /edit <id> <字段> <值> 修改后重新 /evaluate` (zh) /
  `Use /edit <id> <field> <value> to revise per the hints above, then /evaluate again` (en)
  — closes the evaluate→edit loop (approved drafts already get the analytics
  hint above; only revise-able drafts with concrete hints need this pointer).
  Suppressed when `decision == "approved"` or when `revision_hints` is
  empty/absent (nothing concrete to point at).

### First-entry banner (onMounted)

When `isFreeCreationEntry`, the TUI mounts into agent mode and writes a banner:
`freeWelcomeHint` + `freeAgentReady`, then a **dim command list** so the user
discovers draft management without typing `/help` first:

```
  Free creation chat mode is active — type to create, evaluate, and publish.
  Draft commands (also in /help):
    /start            clear the conversation (new session)
    /drafts [status] [q]  list/filter your free drafts (status: published/unpublished/publish_failed/evaluated/unevaluated) + status badges
    /draft <id>      view a draft's full record
    /edit <id> <field> <value>  edit a draft's scalar field (title/niche/content_angle/target_audience)
    /delete <id>    delete a draft
    /analytics <id> post-publish engagement
    /evaluate <id>  re-evaluate a draft (RQGM quality verdict)
    /suggest         creative suggestions (atomic data fetch, no orchestration)
    /mode            switch to command mode
```

- Dim, compact — the full styled reference stays in `/help` (showHelp).
- The banner must list **every** free-mode slash command (the full set in the
  Scope line above: `/start` `/drafts` `/draft` `/edit` `/delete` `/evaluate`
  `/analytics` `/mode`) so a new command added to the dispatchers also lands
  here — a past regression omitted `/edit` (and the spec block missed
  `/evaluate`).
- `/analytics <id>` is listed (shipped via the post-publish analytics PR).
- Non-free (trend/brief) banner is unchanged (`terminalHint` → `/help`).

### Agent dispatch and connection recovery

The free entry defaults to Agent mode, so command behavior must be correct in
that dispatcher before a user switches to command mode:

- `processAgentCommand` and `processSlashCommand` both recognize `/start` in
  free mode. It sends `new_session` and only reports the session reset after
  the WebSocket accepted the message. `/start` must not fall through to
  `unknownCommand` in the default Agent mode.
- Workflow commands (`/status`, `/pause`, `/resume`, `/cancel`, `/approve`,
  `/reject`) remain isolated in both dispatchers and show the localized
  `freeWorkflowOpDisabled` message.
- The status bar exposes three local connection states: connected, connecting
  (including an automatic-reconnect timer), and disconnected. Once automatic
  retries are exhausted, the free entry exposes a manual retry action. A retry
  must not open a second socket while an existing socket is CONNECTING or OPEN.
- Natural-language messages entered in free mode while the socket is not OPEN
  are held in a bounded, in-memory queue for the current TUI instance. The
  queue is flushed in entry order after the socket opens; it is not persisted
  across unmounts, accounts, or sessions. The UI tells the user when a message
  is queued and when queued messages are sent. Fixed workflow mode does not use
  this queue.
- On mobile, the free-mode input keeps creation/message wording while
  connecting or disconnected, and the send control is disabled for blank input.

## Scenario: Historical-note RQGM contract (thread-less and durable)

### 1. Scope / Trigger
- Trigger: a user manually evaluates an imported Creator Center note or refreshes its detail panel.

### 2. Signatures
- `POST /api/evaluation/note {account_id, note_id, force?}`
- `GET /api/evaluation/note/{account_id}/{note_id}/latest`
- `quality_evaluation_runs.get_cached(...)`, `create_run(...)`, `mark_subject_stale(...)`

### 3. Contracts
- Identity is `(account_id, subject_type="imported_note", subject_id=note_id,
  assessment_type="rqgm_content_review", source_content_hash, context_hash,
  evaluator_fingerprint)`.
- `ready|partial` may expose a score; `degraded|failed|running` expose no
  consumable score/decision. Every result carries coverage, thresholds,
  source/data timestamp and evaluation ID.
- `force=true` retains a new version; unchanged input returns the latest
  non-stale run without another model call.

### 4. Validation & Error Matrix
- Blank account/note IDs → `ValidationError` 400.
- Missing imported note → `CreatorNoteNotFoundError` 404.
- Missing niche/image/dimensions → explicit unavailable coverage, not a default score.
- Timeout/model failure → degraded/null result and retryable summary.

### 5. Good/Base/Bad Cases
- Good: refresh restores the same `evaluation_id` and score for unchanged content.
- Base: text-only historical evaluation marks visual/image-quality unavailable.
- Bad: writing a note result into a workflow checkpoint or returning `100/approved` on timeout.

### 6. Tests Required
- Assert note field mapping and account scope.
- Assert no neutral fill for omitted dimensions, no fake pass on timeout, and
  visual/niche coverage markers.
- Assert cache hit is idempotent, force creates a second ID, and latest returns
  stale/degraded audit records.

### 7. Wrong vs Correct
```python
# Wrong: invent context and treat a timeout as approval.
{"niche": "母婴", "overall_score": 100, "decision": "approved", "degraded": True}

# Correct: preserve missing context and make the result non-consumable.
{"niche": "", "niche_context_available": False,
 "overall_score": None, "decision": None, "status": "degraded"}
```

---

## Related

- `backend/agents/evaluator.py` — `EvaluatorAgent.execute` (reused, not modified)
- `backend/agents/publisher.py` — `run_publish` (reused, not modified)
- `backend/api/routes/optimization.py` — the thread-bound draft route (free mode's counterpart, NOT reused)
- `.trellis/spec/backend/omp-integration.md` — host tool auto-execution mechanism
