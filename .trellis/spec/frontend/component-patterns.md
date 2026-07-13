# Frontend Component Patterns

> Conventions for building Vue 3 + TypeScript components in this project.

---

## Tech Stack

- **Vue 3** Composition API (`<script setup lang="ts">`)
- **Pinia** stores (in `src/stores/`)
- **vue-i18n** for localization (`src/locales/`)
- **Vue Router** for navigation (`src/router/`)
- **TypeScript** strict mode

---

## Component Structure

```
<template>
  <!-- HTML -->
</template>

<script setup lang="ts">
// 1. Imports
// 2. Composables (stores, i18n)
// 3. Props & Emits
// 4. Computed properties
// 5. Methods
// 6. Lifecycle hooks
</script>

<style scoped>
/* Component styles */
</style>
```

---

## Dashboard Decomposition Pattern

`Dashboard.vue` was split from 1 monolith into 6 focused components:

| Component | Responsibility |
|-----------|---------------|
| `WorkflowHeader.vue` | Phase badge, status text, elapsed timer |
| `WorkflowTimeline.vue` | Phase progress steps with icons |
| `ContentCards.vue` | Copywriting + visual plan display |
| `OptimizationPanel.vue` | Pre-publish optimization analysis |
| `ShootingPlanPanel.vue` | Brief-mode shooting plan display |
| `ActionButtons.vue` | Start/Pause/Resume/Cancel buttons |

`Dashboard.vue` orchestrates via computed properties (`showOptimization`, `showShootingPlan`) — no logic in child components beyond display.

---

## Shared Components

Historical imported-note detail follows the same decomposition rule: a
dedicated panel owns list selection, stale-response guards, and detail
rendering, while the route workspace only supplies the selected account. The
panel calls the typed API client for note detail and quality separately; it
never starts an import. Detail cards use min-w-0/break-words and responsive
grid stacks so long note content and audience labels do not create page-level
horizontal overflow.

| Component | Purpose |
|-----------|---------|
| `AppIcon.vue` | SVG icon wrapper (name prop) |
| `NeonButton.vue` | Styled action button (variant, loading, disabled props) |
| `ConfirmStartModal.vue` | Workflow start confirmation dialog |
| `WorkflowStartForm.vue` | Mode selector + brief text + start trigger |
| `RipplePanel.vue` | Ripple simulation results + progress display |

---

## Route Component Roots

Route components rendered through `PageTransition` must have a single element root. Vue cannot animate fragment roots inside `<Transition mode="out-in">`, and warnings during route changes can obscure real navigation failures. Keep modals/teleports inside the route's root wrapper.

---

## Composables

- `useLoading.ts` — Loading state management for async operations
- Stores are accessed via `useWorkflowStore()`, `useToastStore()`, etc.

---

## Toast Notifications

All user-facing feedback uses `toastStore`:

```typescript
toastStore.success(t('workflow.started'))
toastStore.warning(t('workflow.staleDetected'), t('workflow.staleHint'))
toastStore.error(t('workflow.error'))
```

Never use `alert()` or `confirm()`.

---

## API Call Rules

> **Forbidden**: Raw `fetch()` for backend API calls. Always use `client.post()` / `client.get()` from `src/api/client.ts`.

Using raw `fetch()` bypasses:
- `ApiResponse` envelope unwrapping
- Automatic retry on network errors
- Consistent error handling and toast notifications

```typescript
// Wrong — silent failure, no retry, no unwrap
const res = await fetch(`/api/workflow/${threadId}/resume`, { method: 'POST', body: JSON.stringify({ resume_value }) })
toastStore.success(...)

// Correct — goes through axios client with retry + unwrap
await workflowApi.resumeWorkflow(threadId, resumeValue)
toastStore.success(...)
```

---

## Replay-Aware Data Access

Components displaying workflow data **must** check `workflowStore.isReplayMode` and read from `workflowStore.effectiveState` (replay-aware) instead of raw `workflowStore.workflowState` (live-only).

```typescript
// Wrong — shows live data during replay
const analytics = computed(() => workflowStore.workflowState?.analytics || {})

// Correct — shows checkpoint data during replay, live data otherwise
const es = computed(() => workflowStore.effectiveState as any)
const analytics = computed(() => es.value?.analytics || {})
```

`effectiveState` is the union of the replay checkpoint state (when in replay mode) or the live state. `progress_percent` in replay is derived from `phaseToPercent(cp.phase)`, never hardcoded.

---

## Mobile Overflow Pattern

For horizontal layouts that overflow on mobile (< 320px viewport):

1. Add `overflow-x-auto` on the scroll container
2. Use `shrink-0 md:shrink` on child nodes so they don't compress below `min-w-[56px]`
3. Add `scrollbar-thin` CSS class for thin scrollbar indicator (custom utility in `main.css`, no tailwindcss-scrollbar plugin)

```html
<!-- WorkflowTimeline, WorkflowReplay, etc. -->
<div class="overflow-x-auto scrollbar-thin">
  <div class="flex justify-between">
    <div v-for="..." class="shrink-0 md:shrink min-w-[56px]">...</div>
  </div>
</div>
```

---

## AgentTUI tool_result Display (Terminal TUI)

`AgentTUI.vue` renders tool results into an xterm.js terminal (not the Vue template), so it uses ANSI colors + `term.writeln` — **not** `t()` i18n keys or `<template>` strings. The terminal domain is exempt from the i18n rule above.

Tool results are formatted by `formatResultLines(result, isError)` and rendered under a `↳ ✓ toolName` header:

- **Short results** (primitives, single-key objects like `{draft_id}`): one line, 160-char cap with a dim `…` suffix — stays scannable.
- **Multi-line / structured results** (text with newlines, or JSON object/array with >1 member): pretty-printed across lines, each subsequent line indented 4 spaces under the `↳`. This is what makes `xhs_free_evaluate` (6-dimension scores + decision + revision_hints) and `xhs_free_guide` (orchestration steps) readable instead of flattened+truncated.
- **Line budget**: multi-line output capped at `MAX_RESULT_LINES` (12); overflow appends a dim `… (N more lines)` footer. **Errors bypass the cap** — full diagnostics must stay visible.
- **Detection is content-based**, never tool-name-based: any tool returning multi-line/structured JSON benefits; no per-tool formatters.
- **omp ToolResult envelope**: backend/extension tools return `{content:[{type:"text",text}], details?}`. The human-readable multi-line output (6-dim scores, guide steps) lives in `content[].text` — `formatResultLines` extracts it first via `_extractToolText()` (shape check, not tool name), so it renders as readable lines rather than a JSON dump that buries the text as an escaped single-line string. Values without that envelope (plain dicts, primitives, raw strings) fall through to the string/JSON path.

```ts
// tool_result render (AgentTUI.vue)
const lines = formatResultLines(event.result, isError)
const header = `  ${ANSI.DIM}↳${ANSI.RESET} ${mark} ${ANSI.DIM}${toolName}${ANSI.RESET}`
writeLine(`${header} ${lines[0]}`)
const indent = '    '
for (const ln of lines.slice(1)) writeLine(`${indent}${ln}`)  // 4-space indent aligns under ↳
```

Never collapse structured results to one line — that destroys the 6-dimension breakdown and guide steps the user needs.

---

## i18n Rules

1. All user-visible strings must use `t('key')`
2. Keys go in both `en.json` and `zh-CN.json`
3. Nested keys: `workflow.started`, `ripple.progressTitle`
4. New features require both locale files updated in the same PR
5. **Forbidden**: Hardcoded English or Chinese string literals in `<template>` or `<script>` — even for section headers, labels, or badges

```vue
<!-- Wrong -->
<span>Topic</span>
<span>商单解析步骤</span>

<!-- Correct -->
<span>{{ t('contentCards.topicLabel') }}</span>
<span>{{ t('dashboard.timeline.substepSections.briefParse') }}</span>
```

---

## Type Safety

Workflow types in `src/types/workflow.ts` mirror backend `XHSGrowthState`:

```typescript
export interface WorkflowState {
  phase: WorkflowPhase
  status: WorkflowStatus
  workflow_mode?: WorkflowMode
  brief_content?: BriefContent
  shooting_plan?: ShootingPlan
  ripple_prediction?: RipplePrediction
  ripple_pmf?: RipplePMFResult
  // ...
}
```

Keep frontend types in sync with backend `substates.py`.

---

## AgentTUI tool_result Display

The web TUI (`AgentTUI.vue`) renders omp tool results via `formatResultLines`, which pretty-prints structured JSON across lines (capped at 12 lines) and extracts human-readable text from the omp `{content:[{type:"text",text}]}` envelope first. Conventions governing tool result rendering:

### Multi-line rendering (content-based detection)

Detection of whether to render multi-line is **content-based, not tool-name-based**: explicit newlines in the extracted text, or a structured object/array with >1 member, triggers multi-line pretty-print. Single-key objects (`{draft_id: "x"}`) stay single-line and dim.

### Envelope text shape

The omp envelope `text` field (from `backend/services/omp_bridge.py` `_make_text_result` and `xhsagent-ext` `textResult`) is **human-readable pre-formatted text**, not a JSON string — e.g. `xhs_free_evaluate` emits `"Free Draft Evaluation — <id>\n  Overall: <n>  Decision: <verdict>\n  - <dim>: <score>…"` . `formatResultLines` still attempts `JSON.parse` on strings that trim to `{`/`[` (try/catch fallback to raw string) as a robustness path for any genuinely-JSON envelope text; free text and parse failures render as raw dim text unchanged.

### Semantic color convention

Result lines are colored by **content pattern** (content-based, never by tool name), so any tool result emitting these patterns benefits. The `colorizeResultLine` helper matches two line families:

**JSON-key form** (from `JSON.stringify(obj, null, 2)`: `<indent>"<key>": <value>,?`):

| Key pattern | Value | Color |
|-------------|-------|-------|
| `"decision"` | `"approved"` | `BRIGHT_GREEN` (success) |
| `"decision"` | `"needs_revision"` | `BRIGHT_YELLOW` (warning) |
| `"decision"` | `"rejected"` | `RED` (error) |
| `overall_score` / any key ending in `_score` | numeric | `BRIGHT_CYAN` |
| `bias_warning` | truthy (`true` / non-empty string) | `BRIGHT_MAGENTA` |
| `bias_warning` | falsy (`false` / `""` / `null`) | `DIM` (no alarm) |

**Human-readable form** (the omp bridge / xhsagent-ext evaluate output actually emits this):

| Line pattern | Colored element | Color |
|--------------|-----------------|-------|
| `  Overall: <num>  Decision: <verdict>` | `<num>` | `BRIGHT_CYAN` |
| `  Overall: <num>  Decision: <verdict>` | `<verdict>` approved/needs_revision/rejected | `BRIGHT_GREEN` / `BRIGHT_YELLOW` / `RED` |
| `  - <dimension>: <score>[…]` | `<score>` | `BRIGHT_CYAN` |
| `  ⚠ Bias: <text>` (only present when truthy) | `<text>` | `BRIGHT_MAGENTA` |
| (all other lines) | — | `DIM` (baseline) |

Indentation and surrounding punctuation/labels stay `DIM` so structure stays scannable while the verdict jumps out. Non-matching free-text lines (e.g. `xhs_free_guide` steps) get `DIM` per-line unchanged.
