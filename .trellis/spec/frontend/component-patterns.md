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

Derived visibility for backend-driven controls must combine the explicit
capability/requirement flag with lifecycle status. A non-terminal state alone
is not sufficient to render an action or form; component tests should cover
both flag values and the terminal state.

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

## Evidence-First Public Workspaces

Public showcase and replay routes are evidence-led workspaces, not marketing
canvas pages. Keep the DOM reading order aligned with the user's decision
path: compact context/filters, real workflow or checkpoint result, then
decorative process explanation. Decorative animation must be secondary and
must not push the primary evidence below the first mobile viewport.

Do not apply a viewport-ratio IntersectionObserver reveal to a primary results
container whose height is larger than the mobile viewport. The visible slice
may never reach the observer threshold, leaving the entire evidence panel
transparent on first paint. Reveal secondary cards individually, or render the
primary result shell immediately.

Use semantic `RouterLink` elements for workflow entry actions so keyboard
users and browser new-tab behavior work without custom click handlers. When a
route is opened from a filtered list, pass a safe return path plus a short
session context; restore that context on return rather than relying on a
component-local scroll position.

For async cards and replay panels, render distinct loading, unavailable/empty,
and error states. Preserve the stable identity/status shell while a detail
request fails and expose a local retry action. A responsive layout must keep
touch targets at least 44px high and avoid page-level horizontal overflow at
320px and above.

Replay pages should start independent live-status and checkpoint-history reads
concurrently after the thread is known; a live-status failure must not hide
usable historical data. Result panels that are selected by checkpoint/agent
may be `defineAsyncComponent` chunks, but they must share a compact local
loading fallback with `aria-busy` so the detail shell remains stable while the
panel chunk arrives.

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

Destructive actions in settings and other route-level management surfaces use
`ConfirmModal` with a localized title/message and explicit cancel/confirm
events. The trigger must remain keyboard reachable, expose an accessible name
for icon-only actions, and preserve the 44px minimum touch target.

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

## Tailwind Class Names Must Be Static (No Dynamic Interpolation)

> **Forbidden**: composing utility class names by interpolation, e.g.
> `` `shadow-${color}-500/20` `` or `` `border-${variant}-200/30` ``. Tailwind
> scans source files as plain text at build time; interpolated fragments are
> never seen, so the class is purged silently and the style simply never
> renders — no build error, no warning.

Use a static lookup map with every class name written out in full:

```vue
<script setup lang="ts">
// Correct — full class names visible to Tailwind's content scan
const variantStyles = {
  pink: { iconShadow: 'shadow-rose-500/20', border: 'border-rose-200/30' },
  cyan: { iconShadow: 'shadow-teal-500/20', border: 'border-teal-200/30' },
  purple: { iconShadow: 'shadow-violet-500/20', border: 'border-violet-200/30' },
} as const
</script>

<template>
  <!-- Wrong — purged at build time, shadow never renders -->
  <!-- <div :class="`shadow-${variantColor}-500/20`"> -->

  <div :class="variantStyles[props.variant].iconShadow">...</div>
</template>
```

Fixed under this rule: `MetricCard.vue`, `MiniProgress.vue`,
`skeletons/ContentCardSkeleton.vue`, `charts/TrendChart.vue`,
`charts/EngagementChart.vue`. When adding a variant-driven style, audit the
template for interpolated class fragments in the same commit.

---

## Dark Mode Convention: explicit `dark:` variants + `dark-explicit`

`src/styles/main.css` ends with a **legacy fallback layer** (~900 lines of
`html.dark` selectors) that remaps exact light utility tokens with `!important`
for older views and scoped styles that have no `dark:` variant of their own.

Rules for new code:

1. **New components must use their own explicit `dark:` variants.** Do not rely
   on the global remap layer to fix your colors.
2. **Exemption mechanism**: the remap layer carries `!important`, so it beats a
   component-level `dark:` variant for the same property. If an element has both
   a remapped base class and its own `dark:` intent, add the `dark-explicit`
   marker class to that element — every generic utility-token remap rule ends in
   `:not(.dark-explicit)`, so the marker opts the element out and lets the
   component's own `dark:` variants win. (Migrated examples: Navbar,
   MobileTabBar, Toast, ConnectionStatus, PageHeader.) The exemption only covers
   the generic utility-token remaps; component-specific dark overrides in
   `main.css` (`.card`, `.liquid-glass`, showcase/replay, etc.) are unaffected.
3. **Do not add rules to the remap layer** unless the change comments explain
   which legacy pages without `dark:` variants it serves. The layer is a
   fallback to shrink, not to grow.
4. Elements without `dark-explicit` render exactly as before the exemption
   existed, so marking is always opt-in and safe.

### Gotcha: `:global(html.dark) .x` in scoped styles never matches

In this toolchain, a scoped-style selector written as
`:global(html.dark) .x` compiles to bare `html.dark` — the trailing class is
dropped, so the rule matches nothing and silently never applies. All known
instances were repaired (2026-08-02): `Navbar.vue` and `EvaluationView.vue`
now use plain `html.dark .x` scoped selectors; `WorkflowTabBar.vue`'s
duplicates of the main.css remap rules were removed.

For dark overrides either write the component's own `dark:` utility variants
(preferred), or use a plain `html.dark .x` selector inside the scoped block
(which Vue scopes correctly), or rely on the `dark-explicit` mechanism above.

---

## z-index: semantic tokens only

All z-index values must come from the semantic scale in `tailwind.config.js`
(`theme.extend.zIndex`). **Forbidden**: `z-[...]` arbitrary values and bare
numeric utilities (`z-50`, `z-40`, ...).

| Token | Value | Use case |
|-------|-------|----------|
| `z-base` | 0 | Default document flow |
| `z-sticky` | 10 | In-flow surfaces above page background: main content layer, sticky action bars (Review), showcase/replay nav & footer |
| `z-overlay` | 20 | In-page overlay on a single surface (e.g. Analytics chart loading veil) |
| `z-dropdown` | 40 | Dropdown/overflow menus, tooltips, popovers (WorkflowTabBar overflow, MobileTabBar menu, HelpCenter, TooltipHelper, OfflineIndicator) |
| `z-modal` | 50 | Modals, drawers, dialogs and the toast stack (ConfirmModal, LoadingOverlay, EvaluationView drawer, Toast) |
| `z-toast` | 60 | Reserved for notifications above modals — currently unused; promoting notification components to this tier is a pending product decision |
| `z-chrome` | 80 | Floating app chrome above content (fixed ThemeToggle) |
| `z-max` | 100 | Topmost accessibility utilities (skip-to-content link) |

When a new surface needs a layer, pick the token whose semantics match; if none
fits, extend the config with a named token instead of inventing a number.

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

## Navigation & workflow UX

- Protected workflow surfaces support optional `threadId` route params for deep
  links (`/dashboard/:threadId?`, `/review/:threadId?`). History actions must
  preserve the selected thread in the route instead of relying only on a
  mutable store value.
- The help center is a real protected route (`/help`); shortcut visibility is
  owned by `useShortcutsStore`, not by onboarding state. Never bind a help
  action to `startTour()` or an unconfigured `mailto:` URL.
- Mobile navigation must expose every primary destination. Lower-frequency
  growth destinations can be grouped in the “More” menu, but they still need an
  active state and a route entry.
- Review cards keep the primary decision actions in a sticky action row while
  the card is expanded. Creation forms should keep advanced options collapsed
  by default and expose the current account context near the action surface.

Free Creation History deep links preserve `mode=free`, the selected
`account_id`, and `draft_id`. A primary action may add only the whitelisted
`action=publish` or `action=analytics` query value: publish actions must open
the existing `/publish <id>` preview without `confirm`, while analytics actions
are reserved for `published` drafts with a real `post_id` (never `mock_*`).
AgentTUI renders the draft detail first, then runs the safe follow-up command;
missing or unknown actions keep the ordinary draft-detail behavior.

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

## Scenario: Canonical historical notes and explicit score semantics

### 1. Scope / Trigger
- Trigger: Analytics, Evaluation, settings previews, or a note drawer renders
  imported history or an RQGM result.

### 2. Signatures
- `analyticsApi.getCreatorNotes(accountId, query, options)` is the canonical
  reader; compatibility fallback may call `getCreatorStats` only when the new
  route is unavailable.
- `CreatorNoteQualityPanel` consumes `evaluateNote` / `getLatestNoteEvaluation`;
  `EvaluationView` keeps historical and workflow source tabs separate.

### 3. Contracts
- Canonical note rows are scoped by account and carry `total`, cursor,
  `data_as_of`, `note_synced_at`, `assessment_type` and fraction engagement rate.
- Analytics report/performance/dashboard payloads declare
  `engagement_rate_unit`; use that explicit unit for store/table/CSV formatting,
  and keep the numeric fraction untouched outside presentation adapters.
- Label published performance as “发布后表现分” and RQGM as “RQGM 内容评审分”;
  never render an unqualified “综合质量分”.
- Null/degraded/failed scores render `—` and an unavailable/retry state; they
  do not map to zero or a green/approved badge. Threshold colors use response
  thresholds, falling back to one shared default constant only when absent.
- All user-visible additions require both locale files; async panels retain a
  stable shell, loading, empty/unavailable and retry states.

### 4. Validation & Error Matrix
- Missing account → clear empty/account-management state; never request a
  `default` pseudo-account.
- Malformed/late note response → local error/retry; stale response must not
  overwrite a newly selected account/note.
- Cursor exhaustion → show loaded/total counts and hide load-more; compact views
  may show a bounded preview only when the total is visible.

### 5. Good/Base/Bad Cases
- Good: switching account resets cursor and rows, then renders only the new account.
- Base: old backend fixture falls back to a bounded preview with an explicit count.
- Bad: showing the first imported note in a drawer for an unmatched workflow row,
  or mixing workflow updated time with note publish time in one unlabeled stream.

### 6. Tests Required
- View/component tests cover account switch, source tabs, cursor load-more,
  loaded/total, data-as-of, stale response and degraded null score.
- Assert both score labels and i18n key parity; run type-check/build/test/i18n check.

### 7. Wrong vs Correct
```vue
<!-- Wrong: a null score is coerced into a passing visual tier. -->
<span :class="scoreTierClass(score || 0)">{{ score || 0 }}</span>

<!-- Correct: preserve null semantics and explicit RQGM naming. -->
<span :class="scoreTierClass(score, thresholds)">
  {{ score == null || degraded ? '—' : score.toFixed(1) }}
</span>
```
