# free mode TUI help: list draft commands

## Goal

`showHelp` (AgentTUI.vue:1196) lists agent-mode commands (`/status` `/new` `/abort` `/mode`) and command-mode workflow commands, but **does not list the free-mode draft commands** `/drafts`, `/draft <id>`, `/delete <id>` added in #216/#218/#219. Free mode defaults to agent mode (AgentTUI.vue:1067), so the user's primary commands are the draft ones — yet `/help` never shows them. A user has no way to discover these commands except tab-completion. Add a free-mode draft-commands section to `showHelp`.

## What I already know

- `showHelp` (AgentTUI.vue:1196): renders a boxed help. Agent-mode branch (1208) lists `/status` `/new` `/abort` `/mode`. Command-mode + free branch (1221) lists only `/start` + `/mode`. Neither lists `/drafts` `/draft` `/delete`.
- Free mode defaults to **agent mode** on mount (AgentTUI.vue:1067) — so the draft commands are used in agent mode, but the agent-mode help section omits them.
- `SLASH_COMMANDS` (AgentTUI.vue:205) already includes `/drafts` `/draft` `/delete` (tab-completion works).
- The draft commands are free-mode-only (guarded by `isFreeCreationEntry` in `handleDrafts`/`handleDraft`/`handleDelete`).
- showHelp currently has many **hardcoded English strings** (pre-existing i18n debt, e.g. "Send message to AI agent", "Start workflow"). That debt is out of scope here — this task only ADDS the draft-commands listing, matching the existing (hardcoded-English) style of the surrounding help text to stay consistent + minimal. A separate i18n-ize-showHelp task can tackle the broader debt later.

## Open Questions (resolved)

- **Where to add**: In the agent-mode branch, add a "Free Draft Commands" sub-section that shows only when `isFreeCreationEntry.value` is true. (Free mode uses agent mode, so the draft commands belong under agent mode, gated by isFreeCreationEntry.) Also add to the command-mode + free branch (line 1221) for completeness — a free-mode user who switched to command mode should still see them.
- **Style**: match the existing hardcoded-English help format (`/cmd <arg>  Description`). Keep minimal — don't i18n-ize the new lines either, to stay consistent with the surrounding (non-i18n) help text. (If we i18n the new lines but not the old, it's inconsistent; if we i18n everything, it's scope creep. Match surroundings = hardcoded English, same as the rest of showHelp.)
- **Commands to list**: `/drafts` (list drafts), `/draft <id>` (view draft), `/delete <id>` (delete draft).

## Requirements

- `showHelp` agent-mode branch: when `isFreeCreationEntry.value`, add a "Free Draft Commands" sub-section listing `/drafts`, `/draft <id>`, `/delete <id>` with one-line descriptions.
- `showHelp` command-mode + free branch (line 1221): also list the three draft commands (free mode user in command mode should see them).
- Non-free mode: no draft-commands section (they're free-only).
- Style matches existing showHelp (hardcoded English, ANSI colors, box format).
- Tab-completion already has them — no SLASH_COMMANDS change needed.

## Acceptance Criteria

- [ ] In free mode, `/help` shows `/drafts`, `/draft <id>`, `/delete <id>` with descriptions.
- [ ] Non-free mode `/help` shows no draft-commands section.
- [ ] Draft commands appear in BOTH agent-mode and command-mode help (when free).
- [ ] `vue-tsc` clean; CI green.

## Definition of Done

- vue-tsc clean; CI green.
- (No spec change needed — showHelp format isn't a spec'd contract. component-patterns.md AgentTUI section already documents the tool_result display; help listing is internal UI.)

## Out of Scope

- i18n-izing the entire showHelp (pre-existing debt — separate task).
- Adding help entries for non-draft commands.
- Changing showHelp layout/box format.

## Technical Notes

- File: `frontend/src/views/AgentTUI.vue` — `showHelp` (1196).
- Add a helper or inline block: when `isFreeCreationEntry.value`, after the existing agent-mode (or command-mode free) command list, write a sub-header (e.g. `  Free Draft Commands`) + sep + the three lines.
- Match existing color usage: `G` (BRIGHT_GREEN) for the command, `D` (DIM) for args/descriptions, like `/start [topic]  Start workflow`.
- Descriptions: `/drafts` → "List free drafts"; `/draft <id>` → "View a draft"; `/delete <id>` → "Delete a draft".
- Conflict safety: additive (new lines inside showHelp, no edits to handleDraft/handleDelete/formatResult).
