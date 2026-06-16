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
