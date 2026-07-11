# free mode: first-entry command hints

## Goal

A user entering `/tui?mode=free` sees a banner + `freeWelcomeHint` ("describe
your goal, agent will orchestrate") + `freeAgentReady` ("type to create...").
Nowhere does it mention the free-mode TUI commands exist: `/drafts`, `/draft
<id>`, `/delete <id>`, `/analytics <id>`. A user creates+publishes
conversationally, then has no idea they can list/view/delete drafts or fetch
post-publish analytics without typing `/help` first. Same discoverability
class as the post_url hint (PR #223) — the capability ships but the entry
point doesn't surface it.

Surface the free-mode command list (dim, one line each) right after
`freeAgentReady` on first mount, so the user knows the draft-management +
analytics commands exist.

## What I already know

- `frontend/src/views/AgentTUI.vue:1500-1503` onMounted free-mode block:
  sets `mode.value='agent'` + writes `freeAgentReady`. No command list.
- `showHelp` (AgentTUI.vue ~1283) already renders the free-mode command block
  in a styled section — reusable structure, but showHelp is a full panel.
- Free-mode commands (on this branch, PR #223): `/start`, `/drafts`,
  `/draft <id>`, `/delete <id>`, `/analytics <id>`, `/mode`. (main without #223
  lacks `/analytics` — branch from main, guard the analytics line.)
- Spec `.trellis/spec/backend/free-creation.md` "TUI display" section covers
  `/drafts` list + `/draft <id>` detail + `/delete` + `/analytics` rendering,
  but NOT the first-entry banner. No contract for what the banner shows.
- i18n: existing `freeWelcomeHint`, `freeAgentReady`, `freeFlow`. No
  `freeCommandHints*` / `freeCommandsAvailable` key.

## Requirements

- onMounted free-mode block: after `freeAgentReady`, write a dim 1-line header
  + the free-mode commands, one per line, dim. Keep it short — not the full
  showHelp panel, just the command names + one-word purpose so the user knows
  they exist.
- i18n: `freeCommandsLabel` (header, e.g. "Commands:") + reuse existing per-
  command purpose keys where they exist (drafts/draft/delete/analytics already
  have help text in showHelp — but those are full sentences; for the entry
  list use the existing short labels or add `freeCmdDrafts` etc.). Simplest:
  reuse the showHelp inline strings pattern but compact.
- Non-free mode: unchanged (banner already shows `terminalHint` → /help).
- Graceful: if `/analytics` not present (main without #223), branch logic must
  not reference it — but this branch HAS #223, so list it. Document the #223
  dependency in the PR.

## Acceptance Criteria

- [ ] Free-mode first mount shows the command list (start/drafts/draft/delete/
      analytics/mode) dim, after freeAgentReady.
- [ ] Non-free mode banner unchanged.
- [ ] `vue-tsc --noEmit` clean; ruff+mypy clean (frontend-only but gate holds).
- [ ] Spec: add a "first-entry banner" note to free-creation.md TUI display
      section documenting the command list.

## Out of Scope

- Auto-running `/help` (just list commands inline, don't open the panel).
- Replacing showHelp (it stays for the full reference).
- Backend changes.

## Technical Notes

- onMounted free-mode block (AgentTUI.vue ~1500): after `freeAgentReady`
  writeln, add a dim command list. Mirror showHelp's free-mode section
  command names but compact (name + short purpose).
- i18n keys (both locales): `freeCommandsLabel` + compact purpose strings.
  Prefer reusing existing `freeNewSession` (for /start) etc. where they fit;
  add the rest.
- Spec "TUI display" section: add "First-entry banner" subsection: free mode
  shows `freeWelcomeHint` + `freeAgentReady` + a dim command list
  (start/drafts/draft/delete/analytics/mode); non-free shows `terminalHint`.
- Branch from main: this branch has #223's `/analytics`. If rebased onto main
  pre-#223-merge, the analytics line still renders (string exists) but the
  command wouldn't work until #223 merges — acceptable, document it. Better:
  ship into #223 if still open (same UX story) OR branch from main and let
  the command list be forward-compatible. Decide at implementation.
- Frontend gate = vue-tsc (vite build OOMs on low-RAM box; build left to CI).
