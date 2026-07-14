# Free TUI /suggest + omp xhs_free_suggestions

## Problem
`GET /free/suggestions/{account_id}` route exists (free.py:702, calls
`get_suggestions_for_mode("free")`) but is wired to **neither** discovery surface:
- No `/suggest` TUI command in AgentTUI.vue (free user must leave TUI → Settings
  panel → CreatorStatsPanel to see suggestions; context switch).
- No `xhs_free_suggestions` omp host tool (free mode defaults to **agent mode**,
  so the agent — the primary driver — cannot fetch suggestions in-conversation).

The route is dead code as shipped. Free-mode creative suggestions are unreachable
inline, violating the "全面优化用户体验" goal for free mode.

## Scope
Wire the existing `/free/suggestions` route to both free-mode surfaces, mirroring
the established cue/discoverability patterns (#223 analytics, #225 edit, #230 evaluate).

### Backend
- Add `xhs_free_suggestions` host tool to `XHS_HOST_TOOLS` in omp_bridge.py:
  GET `/free/suggestions/{account_id}`, render header (`count`, `cold_start` flag)
  + per-suggestion lines (`category` badge, `title`, `advice`, `evidence` dim).
  Append `next:` cue pointing at `xhs_free_draft_create` (suggestions seed creation).
- No new route (reuse `/free/suggestions`).

### Frontend (AgentTUI.vue)
- Add `/suggest` to both dispatchers (`processAgentCommand` agent mode + 
  `processSlashCommand` command mode) — dispatch consistency per spec.
- `handleSuggest`: GET `/free/suggestions/{account_id}`, boxed render
  (count header, `cold_start` note when all cold_start, per-suggestion:
  category-colored badge + title + advice + dim evidence). 400 → red error.
- Add to `SLASH_COMMANDS` tab-completion + first-entry banner + `showHelp`
  free block (all 3 discoverability surfaces, per the "every command must land
  in banner" spec convention).
- i18n keys zh+en (suggestMissing, suggestColdStart, suggestCount, suggestCategory*).

### Spec (.trellis/spec/backend/free-creation.md)
- Scope line: add `/suggest`.
- Signatures table: `xhs_free_suggestions` host tool row.
- Agent-side render: add suggestions render subsection.
- First-entry banner block: add `/suggest` line.
- Dispatch consistency: 8 commands now (`/start /drafts /draft /edit /delete
  /evaluate /analytics /suggest`).

## Out of scope
- New suggestion logic / data source (reuse `get_suggestions_for_mode`).
- Pagination (suggestions are a small bounded list).
- TS extension prompt sync (suggestions are not a chain step; agent discovers
  via tool description like the other host tools — no cross-audit rule needed
  since suggestions aren't part of create→evaluate→publish→analytics chain).

## Tests
- `tests/unit/services/test_omp_bridge.py`: `xhs_free_suggestions` — assert
  GET path + render shape (count header, cold_start note, per-suggestion lines,
  next: cue).
- `tests/unit/api/test_free_routes.py`: suggestions route already exists;
  add/verify render assertion if missing.

## Validation
ruff check . + ruff format --check + mypy backend + pytest + vue-tsc --noEmit.
