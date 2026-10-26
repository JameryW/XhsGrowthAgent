# Auto-load stamped publish eligibility at Action plan

## Goal

`plan_action(publish)` 在有 `thread_id` 时自动从工作流 checkpoint 读取已 stamp 的 `evaluation_result.publish_eligibility`（及 plan 可用的账号级字段），注入现有 `ActionPolicyContext`。仍不读 artifact。

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Direction | Plan auto-loads stamp from thread checkpoint |
| Missing stamp | **Allow** plan to continue (execute still runs full judgers) |
| Checkpoint / graph unreadable | **Fail-closed** deny (same spirit as risk-gate unavailable) |
| Explicit `policy_context` | **Overrides** auto-loader (tests / callers) |
| Artifact at plan | **Never** |

## Requirements (MVP)

1. Add a thin async loader (e.g. `load_action_policy_context_from_thread(thread_id, account_id)`) that:
   - `aget_state` for the thread
   - Reads `evaluation_result.publish_eligibility` when present
   - Optionally maps `niche` / `auto_publish` (and related) for `PLAN_TIME_JUDGERS`
   - On checkpointer/graph failure → raise or return a deny signal that becomes `ActionPolicyDeniedError` / risk-unavailable-style policy id (reuse or add stable `policy.action.eligibility_context_unavailable`)
   - On missing stamp → return context with `publish_eligibility=None` (not a deny)
2. Wire into production `plan_action` path (advisor and/or API) so publish with `thread_id` auto-loads unless `policy_context` was explicitly passed.
3. Keep plan free of artifact reads; do not run lexicon/disclosure at plan.
4. Tests: stamp deny without manual inject; missing stamp allows; load failure denies; explicit context overrides loader.
5. Update `docs/publish-action-protocol.md` + `.trellis/spec/backend/compliance-baseline.md` (remove “injectable only” honesty gap).

## Acceptance Criteria

* [ ] Publish plan + thread with stamped `allowed=False` → 403, no intent, no caller-injected context
* [ ] Publish plan + thread without stamp → policy may allow (account/risk permitting); execute still judges body
* [ ] Checkpoint unreadable → fail-closed deny at plan
* [ ] Explicit `policy_context=` overrides auto-load
* [ ] Unit tests + lint/mypy; CI green; specs/docs updated

## Definition of Done

* Tests/CI green; PR merged or ready; Trellis archive after merge

## Out of Scope

* Cap-force / medium residual
* Full judgers at plan
* UI
* Changing execute-layer judger placement

## Technical Notes

* Pattern: `graph.aget_state({"configurable": {"thread_id": ...}})` as in `_wf_application` / `evaluation.py`
* Existing: `ActionPolicyContext`, `build_action_policy_snapshot`, `PLAN_TIME_JUDGERS`
* Prior: #717, #718
