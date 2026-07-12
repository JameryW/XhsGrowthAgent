# Free TS prompt: sync failure-path rules (cross-audit)

## Problem

The TS extension system prompt (`events.ts` `before_agent_start`) documents the
free-mode create→evaluate→publish→analytics happy path + the evaluate→revise
loop (#237 sync). But it does NOT document:

1. **Publish-failure recovery** (#241): publish can fail (status=failed/
   auth_expired); read the Error/Recovery, fix the cause, re-run
   xhs_free_publish; do NOT call xhs_free_analytics on a failed publish; the
   failed attempt persists as last_publish + the list shows [publish failed].
2. **Evaluate-degradation** (#242): evaluate can degrade on LLM timeout →
   pass-through fallback (degraded=True, fake 100/approved); do NOT publish
   on a degraded verdict; re-run xhs_free_evaluate; the list shows [degraded].

Both rules were synced to the bridge guide (`xhs_free_guide`, #241/#243) but
NOT to the TS extension prompt. The spec's cross-audit convention
(free-creation.md lines 109-111) says the TS prompt must stay in sync with the
bridge's tool descriptions — "both guide the agent to the same xhs_free_*
chain." An agent driven via the TS extension path (omp `/xhs` command TUI, a
distinct path from the web TUI bridge) only learns the happy path + revise
loop, not the failure recovery. On a real publish failure or evaluate
degradation, it has no rule and may call analytics on a failed draft (400) or
publish on a degraded verdict.

## Fix

Add both failure-path rules to the TS extension system prompt, mirroring the
bridge guide's wording (#241/#243):

- After the evaluate→revise line, add the evaluate-degradation rule.
- Replace the "After publish, call xhs_free_analytics" line with the
  publish-failure recovery rule + a gated happy-path analytics line.

No backend route/render change. No i18n (TS prompt is hardcoded English, like
the bridge guide). This is pure cross-audit text sync.

## Scope

- `backend/omp/extensions/xhsagent-ext/src/events.ts` — `before_agent_start`
  systemPrompt: +2 failure-path lines (publish-failure + evaluate-degradation).
- `.trellis/spec/backend/free-creation.md` — note the TS prompt documents the
  same failure-path rules (cross-audit sync with #241/#242/#243).
- TS typecheck (`npm run typecheck` / `vue-tsc` if applicable) clean.

## Verification

- `npm run typecheck` (OMP TS extension) clean.
- `ruff check .` clean (no Python change, but sanity).

## Non-goals (YAGNI)

- No new tool/route — only prompt-text sync.
- No re-stating every render cue — the prompt points at xhs_free_guide for the
  full guide; the 2 added lines just cover the failure paths the happy-path
  prompt omitted.
