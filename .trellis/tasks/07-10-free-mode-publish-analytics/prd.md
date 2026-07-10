# free mode publish analytics

## Goal

Free mode can publish a draft (`POST /free/publish`) but has **no way to view post-publish analytics**. The fixed workflow triggers analytics via `POST /workflow/trigger-analytics/{thread_id}` (thread-bound), but free mode is thread-less — `xhs_workflow_trigger_analytics` is disabled in free mode (system prompt line 35: "only when a thread_id exists"). A free user publishes and has no feedback loop on engagement. Add a thread-less analytics path: persist the publish `post_id` on the draft, add `GET /free/analytics/{draft_id}` that fetches engagement via `XHSClient.get_post_analytics`, and surface via an omp host tool `xhs_free_analytics` + optional TUI command.

## What I already know

- `backend/api/routes/free.py:publish_draft` (250-269): returns `publish_result` (incl. `post_id`, `post_url`). #216 persists `published=True` on success but **does NOT persist `post_id`/`post_url`** on the draft.
- `backend/services/xhs_client.py:401` `get_post_analytics(post_id) -> XHSAnalytics` — fetches `get_note_detail(note_id)` → views/likes/collects/comments/shares/engagement_rate. **Already exists**, takes only post_id (no thread_id). Has a TODO about creator-center data but returns basic engagement from note_detail.
- `XHSAnalytics` (xhs_client.py:127) — `post_id, views, likes, collects, comments, shares, engagement_rate, fetched_at`.
- Fixed workflow analytics (`backend/agents/analyst.py`, `backend/api/routes/analytics.py`) is thread-bound (`session_id`/`thread_id` for checkpoint + backfill_engagement). Free mode can't reuse it directly — but `get_post_analytics` is thread-agnostic.
- omp host tool `xhs_workflow_trigger_analytics` (omp_bridge.py:362, :1093) calls `POST /workflow/trigger-analytics/{thread_id}` — thread-bound, disabled in free mode.
- `XHSClient` construction in free mode: `run_publish` builds the client from CDP/account. A free analytics route needs its own `XHSClient` (from the account's CDP profile) — check how run_publish/system_health construct it.

## Open Questions (resolved)

- **Scope**: (1) persist `post_id`+`post_url` on the draft at publish success (extend #216's published write-back). (2) `GET /free/analytics/{draft_id}?account_id=` route: load draft → get post_id (400 if not published / no post_id) → `XHSClient.get_post_analytics(post_id)` → return analytics. (3) omp host tool `xhs_free_analytics(draft_id)` so the agent can fetch engagement. (4) TUI `/analytics <id>` command to render it (follows /draft pattern).
- **XHSClient construction**: reuse the same client factory `run_publish` uses (CDP endpoint from account config). Need a helper to build an `XHSClient` from account_id without running a full publish — check `run_publish`/publisher for the factory; extract or call the same.
- **Not published**: draft with `published=False` or no `post_id` → 400 "draft not published / no post_id". Mock-published (dry-run) drafts have no real post_id → same 400 (or return a clear "mock publish, no real analytics" message).
- **Don't block publish**: analytics is a separate read after publish; publish itself unchanged beyond persisting post_id.

## Requirements

- `publish_draft`: on success, persist `post_id` + `post_url` (from publish_result) on the draft alongside `published=True`.
- `GET /free/analytics/{draft_id}?account_id=`: load draft → if not published or no post_id → 400; build XHSClient (account CDP) → `get_post_analytics(post_id)` → return `{draft_id, post_id, analytics}`.
- omp host tool `xhs_free_analytics(draft_id)`: auto-executed via bridge → calls the new GET route → returns text result.
- TUI `/analytics <id>` command (free mode): renders views/likes/collects/comments/shares/engagement_rate with ANSI. Non-free → freeWorkflowOpDisabled.
- Graceful: errors (XHS unreachable, post deleted) → 400/error message, not crash.

## Acceptance Criteria

- [ ] After successful `xhs_free_publish`, the draft record has `post_id` + `post_url`.
- [ ] `GET /free/analytics/{draft_id}` returns engagement (views/likes/collects/comments/shares/engagement_rate).
- [ ] Unpublished draft → 400; mock-published (no real post_id) → clear error.
- [ ] `xhs_free_analytics` omp host tool fetches engagement for the agent.
- [ ] TUI `/analytics <id>` renders the engagement.
- [ ] `pytest` passes (+ new tests); `ruff`+`mypy` clean; `vue-tsc` clean; CI green.

## Definition of Done

- Tests pass; ruff+mypy clean; vue-tsc clean; CI green.
- Spec: add `GET /free/analytics/{draft_id}` to free-creation.md Signatures + the omp tool + the post_id persistence note + error matrix rows.
- omp tool registered in `_HOST_TOOL_DEFINITIONS` + the `_execute_xhs_host_tool` dispatch + system prompt (events.ts + bridge tool descriptions) updated to mention `xhs_free_analytics`.

## Out of Scope

- Full analyst agent (pattern_detector, report_generator) — free mode just surfaces raw engagement via get_post_analytics. YAGNI the full report pipeline.
- Historical analytics trends (multiple fetches over time) — single current fetch.
- Analytics for non-free workflows (unchanged).

## Technical Notes

- Backend `backend/api/routes/free.py`:
  - `publish_draft` (255): add `draft["post_id"] = publish_result.get("post_id", "")` + `draft["post_url"] = publish_result.get("post_url", "")` before `store.aput`.
  - New `@router.get("/analytics/{draft_id}")`: load draft via `_load_draft`; `post_id = draft.get("post_id")`; if not post_id → ValidationError 400; build XHSClient (find the factory run_publish uses — likely from account CDP config); `analytics = await client.get_post_analytics(post_id)`; return `success(data={draft_id, post_id, analytics: <dict>})`.
- XHSClient factory: trace `run_publish`/`PublisherAgent` for how it builds the client from account_id + CDP endpoint. Extract a shared helper `_build_xhs_client(account_id)` if needed (avoid duplicating CDP resolution).
- omp_bridge.py: add `xhs_free_analytics` to `_HOST_TOOL_DEFINITIONS` + dispatch in `_execute_xhs_host_tool` (GET `/free/analytics/{draft_id}?account_id=`).
- events.ts system prompt + bridge tool descriptions: mention `xhs_free_analytics (draft_id)` as post-publish engagement check.
- Frontend: `handleAnalytics(draftId)` in AgentTUI — GET `/free/analytics/{id}` → render engagement. i18n keys both locales. SLASH_COMMANDS + showHelp entry (but showHelp #220 pending — add to the free-draft-commands section once rebased).
- Tests: `test_analytics_requires_published`, `test_analytics_returns_engagement` (mock XHSClient), `test_publish_persists_post_id`.
- Conflict awareness: touches free.py (publish_draft body + new route) + AgentTUI (new handleAnalytics — not handleDraft/handleDrafts/showHelp bodies) + omp_bridge + events.ts. #220 (showHelp) — this adds a showHelp line; rebase-safe if #220 merges first. #221/#222 (spec/free.py) — rebase-safe (different regions).
