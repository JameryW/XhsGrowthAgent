# Free agent guide: document publish-failure recovery (cross-audit sync)

## Problem

`xhs_free_guide` (the omp agent's orchestration guide, `omp_bridge.py` ~line
794) documents the create→evaluate→publish→analytics happy path but does NOT
mention publish failure or recovery:

- The publish rule says "After publish, call xhs_free_analytics to check
  engagement feedback" — implying publish always succeeds.
- No mention that `xhs_free_publish` can return a failure (`status == "failed"`
  / `"auth_expired"`) with an `error`/`error_type`/`recovery` payload (#239),
  or that the failed attempt is persisted as `last_publish` on the draft
  (#240) and surfaces as a `[publish failed]` badge in the draft list.

So an agent that reads the guide first (the documented discovery path) only
learns the happy path. When a real publish fails, it has no rule for what to
do — it may call `xhs_free_analytics` on a failed draft (which 400s, since no
post_id), or stall. The guide is the agent's discovery surface per the
cross-audit convention (spec free-creation.md lines 96-98: the guide text must
stay in sync with the renders' cues). #234 synced the evaluate→revise rule;
#239/#240 added the failure renders but never synced the guide.

## Fix

Add a publish-failure recovery rule to the `xhs_free_guide` text, mirroring
the evaluate→revise rule's style (#234):

```
- Publish can fail (status=failed/auth_expired): the render shows Error/Error
  Type/Recovery — read the recovery hint, fix the cause (e.g. re-login the
  account), then re-run xhs_free_publish (keep the same draft_id). Do NOT call
  xhs_free_analytics on a failed publish (no post_id → 400). A failed attempt
  is persisted as last_publish; the draft list shows a [publish failed] badge.
```

Keep the existing happy-path "After publish, call xhs_free_analytics" line but
gate it implicitly (analytics is for a successful publish; the new rule covers
failure).

Also add the `[publish failed]` + `last_publish` note to the draft-management
section so the agent knows the list badges it will see.

No backend route change. No frontend change (the guide is agent-facing plain
text). No i18n (guide is hardcoded English, like the renders).

## Scope

- `backend/services/omp_bridge.py` — `xhs_free_guide` text: publish-failure
  recovery rule (~4 lines) + draft-list `[publish failed]` badge note (~1 line).
- `.trellis/spec/backend/free-creation.md` — note that the guide documents the
  publish-failure recovery path (aligns with the #234 evaluate→revise guide
  rule + the cross-audit convention).
- `tests/unit/services/test_omp_bridge.py` — assert the guide text contains
  the failure-recovery cue (existing guide test likely only checks happy-path
  keywords).

## Verification

- `ruff check .` + `ruff format --check .` clean.
- `mypy backend` clean.
- full `pytest`.

## Non-goals (YAGNI)

- Guide for workflow-bound publish retry — free mode only.
- Full recovery-action enumeration (re-login / verify_account / retry_later)
  in the guide — the render already surfaces the specific recovery hint; the
  guide only needs the "read the recovery hint, fix, re-run" loop.
