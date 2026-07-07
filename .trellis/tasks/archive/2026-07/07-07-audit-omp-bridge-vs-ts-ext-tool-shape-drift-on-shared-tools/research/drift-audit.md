# Research: omp Bridge vs TS Ext Tool Shape Drift Audit (Shared Tools)

- **Query**: Audit all ~27 SHARED omp tools for shape drift between TS extension, Python bridge, and backend API contract. Backend route is source of truth.
- **Scope**: internal (3-way comparison)
- **Date**: 2026-07-07

## Summary

Audited all 27 shared omp tools present in BOTH the TypeScript extension
(`backend/omp/extensions/xhsagent-ext/src/tools/*.ts`) and the Python bridge
(`backend/services/omp_bridge.py` `XHS_HOST_TOOLS` + `_execute_xhs_host_tool`).
Backend routes in `backend/api/routes/*.py` are the source of truth.

**Result: 25 of 27 shared tools are fully aligned (path / method / body / response / render).**
**2 tools have drift** — both response-field drift on `optimization_draft`,
and 1 cosmetic render difference on `system_health` (intentional brevity, not a bug).

The 4 evaluation sub-tools the bridge lacks (epochs/weights/samples/trend) are
TS-only and correctly skipped per the task scope.

## Drift Audit Table

| tool | TS path | bridge path | backend route | drift? | severity | fix needed |
|---|---|---|---|---|---|---|
| xhs_workflow_status | GET /workflow/status/{id} | GET /workflow/status/{id} | workflow.py:629 | none | — | no |
| xhs_workflow_pause | POST /workflow/pause/{id} | POST /workflow/pause/{id} | workflow.py:1003 | none | — | no |
| xhs_workflow_resume | POST /workflow/resume/{id} (json={}) | POST /workflow/resume/{id} (json={}) | workflow.py:1039 | none | — | no |
| xhs_workflow_cancel | POST /workflow/cancel/{id} | POST /workflow/cancel/{id} | workflow.py:1378 | none | — | no |
| xhs_workflow_list | GET /workflow/list (reads total) | GET /workflow/list (reads workflows) | workflow.py:1564 (returns total) | none | — | no (prior count→total fix confirmed) |
| xhs_workflow_delete | DELETE /workflow/{id} | DELETE /workflow/{id} | workflow.py:1612 | none | — | no |
| xhs_workflow_history | GET /workflow/history/{id}?limit | GET /workflow/history/{id}?limit | workflow.py:901 | none | — | no (checkpoints/has_more/step/source/next_nodes all present in CheckpointSnapshot) |
| xhs_workflow_trigger_analytics | POST /workflow/trigger-analytics/{id} | POST /workflow/trigger-analytics/{id} | workflow.py:2150 | none | — | no |
| xhs_publish_retry | POST /workflow/publish-retry/{id} | POST /workflow/publish-retry/{id} | workflow.py:2206 | none | — | no |
| xhs_review_approve | POST /review/submit/{id} {decision:approved, comments?} | POST /review/submit/{id} {decision:approved, comments?} | review.py:120 (ReviewDecision) | none | — | no |
| xhs_review_reject | POST /review/submit/{id} {decision:needs_revision, comments} | POST /review/submit/{id} {decision:needs_revision, comments} | review.py:120 | none | — | no |
| xhs_review_pending | GET /review/pending/{id} (reads version_history) | GET /review/pending/{id} (reads copy_content) | review.py:94 (returns version_history mapped from content_versions) | none | — | no (both read version_history; bridge doesn't render it but reads data blob) |
| xhs_review_versions | GET /review/versions/{id} (reads versions, current) | GET /review/versions/{id} (reads versions, current) | review.py:188 | none | — | no |
| xhs_ripple_pending | GET /review/ripple-pending/{id} | GET /review/ripple-pending/{id} | review.py:217 | none | — | no |
| xhs_ripple_decision | POST /review/ripple-decision/{id} {action} | POST /review/ripple-decision/{id} {action} | review.py:251 (RippleDecision) | none | — | no |
| xhs_ripple_retry | POST /workflow/ripple-retry/{id} | POST /workflow/ripple-retry/{id} | workflow.py:1661 | none | — | no |
| xhs_blogger_pending | GET /optimization/blogger-pending/{id} | GET /optimization/blogger-pending/{id} | blogger.py:43 (mounted under /api/optimization) | none | — | no |
| xhs_blogger_select | POST /optimization/blogger-select/{id} {skip, user_id?, nickname?} | POST /optimization/blogger-select/{id} {skip, user_id?, nickname?} | blogger.py:72 (BloggerSelection) | none | — | no |
| xhs_optimization_draft | POST /optimization/draft/{id} (reads draft_content, optimization_analysis) | POST /optimization/draft/{id} (reads draft_content) | optimization.py:29 (returns thread_id, status, [next_phase]) | **response-field** | **latent** | **yes — see Findings #1** |
| xhs_optimization_select | POST /optimization/select/{id} {version_id, version_type?} | POST /optimization/select/{id} {version_id, version_type?} | optimization.py:77 (VersionChoice) | none | — | no |
| xhs_evaluation_result | GET /evaluation/result/{id} (reads has_evaluation, evaluation_result) | GET /evaluation/result/{id} (reads has_evaluation, evaluation_result) | evaluation.py:137 | none | — | no |
| xhs_evaluation_run | POST /evaluation/run/{id} (reads evaluation_result) | POST /evaluation/run/{id} (reads evaluation_result) | evaluation.py:161 | none | — | no |
| xhs_analytics_dashboard | GET /analytics/dashboard/{acct} (reads report.metrics, costs, performance.posts) | GET /analytics/dashboard/{acct} (reads report.metrics, costs, performance.posts) | analytics.py:285 (returns report+performance+costs) | none | — | no |
| xhs_analytics_costs | GET /analytics/costs?period (reads total/period/today_cost, by_model, budget_remaining_usd) | GET /analytics/costs?period (reads total/period/today_cost, by_model, budget_remaining_usd) | analytics.py:226 (returns all + circuit_open + updated_at) | none | — | no |
| xhs_analytics_report | GET /analytics/report/{acct}?period (reads metrics, insights) | GET /analytics/report/{acct}?period (reads metrics, insights) | analytics.py:124 | none | — | no |
| xhs_analytics_performance | GET /analytics/performance/{acct}?period&limit (reads posts, total) | GET /analytics/performance/{acct}?period&limit (reads posts, total) | analytics.py:189 | none | — | no |
| xhs_system_health | GET /system/health (renders version, per-provider, embed_model) | GET /system/health (renders status, llm_providers.status, ripple, db mode, memory_store.status) | system.py:210 | **render** | **cosmetic** | no — intentional brevity, both read full data blob via details |

## Findings

### Finding #1 — optimization_draft response-field drift (latent)

**Both TS and bridge read `draft_content` / `optimization_analysis` from the
response, but the backend `/optimization/draft/{thread_id}` route never returns
those fields.** The route returns only `{"thread_id", "status"}` or
`{"thread_id", "status": "resumed", "next_phase": ...}`.

- **Backend** (`backend/api/routes/optimization.py:29-74`): `submit_draft` returns
  `{"thread_id": ..., "status": "resumed", "next_phase": ...}` when the graph is
  interrupted at `draft_gate`, or `{"thread_id": ..., "status": "draft_submitted"}`
  otherwise. It does NOT echo back `draft_content` or `optimization_analysis`.
- **TS** (`backend/omp/extensions/xhsagent-ext/src/tools/optimization_draft.ts:32-43`):
  reads `result.draft_content` and `result.optimization_analysis`, guards with
  `Object.keys(...).length` checks so undefined→empty→no crash, but the rendered
  Title/Body lines are always empty because the fields are absent.
- **Bridge** (`backend/services/omp_bridge.py:764-777`): reads
  `data.get("draft_content") or {}` then `draft.get("title")` / `draft.get("body")`.
  Same outcome — always empty because the backend doesn't return `draft_content`.

**Impact (latent, not blocker):** The tool never crashes (both use safe
null-guards), but the human-readable output for `xhs_optimization_draft` is
permanently degraded — it shows only "Status: draft_submitted" with no title/body
preview, even when the draft was just submitted with real content. The agent
and user lose the inline preview that the tool was designed to provide.

**Root cause:** The route was likely written before the omp tool expected a
content echo, or the omp tool was copy-pasted from `review_pending` (which DOES
return `copy_content`) without adjusting for the route's actual response shape.

**Concrete fix (backend side, NOT to be applied by this research task):**
In `optimization.py:submit_draft`, after `aupdate_state`, echo back the
submitted draft so the tool can render it:

```python
# In submit_draft, build response with the draft that was just written
return success(data={
    "thread_id": thread_id,
    "status": "resumed" if "draft_gate" in state.next else "draft_submitted",
    "next_phase": next_phase,  # only in resumed branch
    "draft_content": draft_data,            # echo back for tool rendering
    "optimization_analysis": values.get("optimization_analysis") or {},
})
```

Alternatively, if the route is intentionally minimal, the TS and bridge tools
should stop reading `draft_content`/`optimization_analysis` and instead render
only `status` + `next_phase` — but that loses the inline preview value.

**Severity: latent** — no crash, no wrong data, just a missing preview that
makes the tool less useful than designed. The `details` blob passed back to omp
is also missing these fields, so the agent can't reason about draft content
either.

### Finding #2 — system_health render divergence (cosmetic, intentional)

**The bridge renders fewer fields than TS, but both read the same backend
response and both pass the full `data` blob through as `details`.**

- **TS** (`system_health.ts:29-48`): renders `status`, `version`, per-provider
  breakdown (`info.configured ? "✓" : "✗"`), Ripple `configured` flag, db `mode`,
  memory_store `semantic_index` + `embed_model`.
- **Bridge** (`omp_bridge.py:862-876`): renders `status`, `llm_providers.status`,
  `ripple_cas.status`, db `status` + `mode`, `memory_store.status`. Omits version,
  per-provider breakdown, embed_model.

**Impact:** None functional. Both pass `data` (the full health payload) as
`details` to omp, so the agent has access to every field regardless of which
implementation rendered the text. The text summary differs in verbosity but
conveys the same top-level signal (overall status + which subsystems are up).

**This is intentional brevity on the bridge side, not a bug.** No fix needed.
If parity is desired for consistency, the bridge could add the per-provider
loop and embed_model line, but it's cosmetic.

## Verification of Prior-Pass "Clean" Tools (spot-checked, confirmed)

The task listed 26 tools as already-verified clean. This audit re-examined the
6 flagged for subtle drift and confirms:

1. **analytics_costs** — TS (`analytics_costs.ts:6-14`) and bridge
   (`omp_bridge.py:839-860`) both read `total_cost_usd`, `period_cost_usd`,
   `today_cost_usd`, `by_model`, `budget_remaining_usd`. Backend
   (`analytics.py:271-282`) returns all of these plus `circuit_open`,
   `period`, `updated_at`. **No drift** — both align with backend.

2. **workflow_history** — TS (`workflow_history.ts:6-20`) types `step`,
   `source`, `phase`, `current_agent`, `created_at`, `next_nodes`, `checkpoint_id`,
   `has_more`. Backend `CheckpointSnapshot` (`workflow.py:398-423`) and
   `CheckpointHistoryResponse` (`workflow.py:426-431`) return all of these.
   Bridge (`omp_bridge.py:878-899`) reads `checkpoints`, `has_more`, and per-
   checkpoint `step`/`phase`/`current_agent`/`created_at`. **No drift.** (Bridge
   doesn't render `source`/`next_nodes` but they're in the `details` blob.)

3. **system_health** — see Finding #2 above (cosmetic render divergence only).

4. **analytics_dashboard** — TS (`analytics_dashboard.ts:6-30`) and bridge
   (`omp_bridge.py:812-837`) both read `report.metrics`, `costs`, `performance`.
   Backend (`analytics.py:285-408`) returns exactly `{"report": {...},
   "performance": {...}, "costs": {...}}` with `metrics` nested under `report`.
   **No drift.**

5. **review_pending** — TS (`review_pending.ts:11`) types `version_history`.
   Backend (`review.py:111`) returns `version_history` (mapped from
   `content_versions`). Bridge (`omp_bridge.py:688-705`) reads `copy_content`
   and doesn't explicitly render `version_history`, but passes the full `data`
   blob as `details`. **No drift** — the key exists in the response and is
   available to the agent via `details` even if the bridge text doesn't call
   it out.

6. **Null-handling divergence** — Checked all tools for TS `?.`/`.optional()`
   vs bridge `.get(..., default)`. Both consistently use safe accessors; no
   case found where one crashes on undefined and the other doesn't. The
   `optimization_draft` fields are absent in both, and both handle absence
   gracefully (TS via `Object.keys().length` guard, bridge via `or {}`).

## Files Referenced

| File | Role |
|---|---|
| `backend/services/omp_bridge.py` | Python host-tool bridge (`XHS_HOST_TOOLS` + `_execute_xhs_host_tool`) |
| `backend/omp/extensions/xhsagent-ext/src/tools/*.ts` | TS extension tool implementations (27 shared + 4 TS-only) |
| `backend/omp/extensions/xhsagent-ext/src/api_client.ts` | TS HTTP client (base = `${config.apiBase}/api`) |
| `backend/api/routes/workflow.py` | Workflow routes (status/pause/resume/cancel/list/delete/history/trigger-analytics/publish-retry/ripple-retry) |
| `backend/api/routes/review.py` | Review routes (pending/submit/versions/ripple-pending/ripple-decision) |
| `backend/api/routes/optimization.py` | Optimization routes (draft/select) — **Finding #1 lives here** |
| `backend/api/routes/blogger.py` | Blogger routes (blogger-pending/blogger-select, mounted under /api/optimization) |
| `backend/api/routes/analytics.py` | Analytics routes (report/performance/costs/dashboard) |
| `backend/api/routes/evaluation.py` | Evaluation routes (result/run + list/weights/epochs/samples/trend [TS-only]) |
| `backend/api/routes/system.py` | System health route |
| `backend/api/app.py:180-193` | Router prefix mounting (blogger.py mounted under /api/optimization alongside optimization.py) |

## Caveats / Not Found

- The 4 evaluation sub-tools (`evaluation_epochs`, `evaluation_weights`,
  `evaluation_samples`, `evaluation_trend`) exist only in TS, not in the bridge's
  `XHS_HOST_TOOLS` list. Confirmed TS-only — correctly excluded from this shared-
  tool audit per task scope.
- `xhs_workflow_start` is intentionally disabled in the bridge
  (`omp_bridge.py:597-605`) and has no TS tool file — not a shared tool, excluded.
- This audit is read-only; no code was modified. The Finding #1 fix must be
  implemented by a separate `implement` agent (backend route change) or by
  aligning the TS/bridge tools to the route's actual minimal response.
