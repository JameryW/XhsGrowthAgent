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

## i18n Rules

1. All user-visible strings must use `t('key')`
2. Keys go in both `en.json` and `zh-CN.json`
3. Nested keys: `workflow.started`, `ripple.progressTitle`
4. New features require both locale files updated in the same PR

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