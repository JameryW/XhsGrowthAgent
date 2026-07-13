# Frontend State Management

> Pinia store conventions for this project.

---

## Stores

| Store | File | Purpose |
|-------|------|---------|
| `useWorkflowStore` | `stores/workflow.ts` | Workflow lifecycle, phase, status, progress |
| `useRealtimeStore` | `stores/realtime.ts` | WebSocket connection, event recovery |
| `useToastStore` | `stores/toast.ts` | Success/error/warning/info notifications |

---

## Workflow Store Pattern

```typescript
export const useWorkflowStore = defineStore('workflow', () => {
  // State
  const currentPhase = ref<WorkflowPhase>('idle')
  const status = ref<WorkflowStatus>('idle')

  // Computed
  const isRunning = computed(() => status.value === 'running')
  const isStale = computed(() => status.value === 'stale')

  // Actions
  async function startWorkflow(params: StartParams) { ... }
  async function pauseWorkflow() { ... }

  return { currentPhase, status, isRunning, isStale, startWorkflow, ... }
})
```

Key patterns:
- Use Composition API (setup function) style, not options API
- Computed properties for derived state (never derive in templates)
- Async actions call API then update local state on success
- Toast notifications emitted from actions, not from API calls

---

## Realtime Store Pattern

```typescript
export const useRealtimeStore = defineStore('realtime', () => {
  const wsService = ref<WebSocketService>()

  function connect(threadId: string) {
    wsService.value = new WebSocketService(threadId)
    wsService.value.onEvent('WORKFLOW_PROGRESS', (payload) => {
      workflowStore.updateProgress(payload)
    })
    wsService.value.onEvent('RIPPLE_PROGRESS', (payload) => {
      rippleProgress.value = payload
    })
  }
})
```

Key patterns:
- WebSocket events update store state; components react to store changes
- Event recovery via `get_missed` endpoint on reconnect
- Connection lifecycle tied to workflow lifecycle

---

## Toast Store Pattern

```typescript
export const useToastStore = defineStore('toast', () => {
  const toasts = ref<Toast[]>([])

  function success(title: string, description?: string) { add('success', title, description) }
  function error(title: string, description?: string) { add('error', title, description) }
  function warning(title: string, description?: string) { add('warning', title, description) }

  return { toasts, success, error, warning }
})
```

---

## State ↔ Backend Sync

Frontend state mirrors backend `XHSGrowthState`. The sync flow:

1. API call (`POST /start`, `POST /resume`, etc.) returns `thread_id`
2. WebSocket streams `WORKFLOW_PROGRESS` events with full state
3. Store updates local refs from event payload
4. Components react to store computed properties

No polling — all updates are push-based via WebSocket/SSE.

---

## Account-Bound Form Defaults

Creation forms may derive a default from the selected durable account (for
example, its bound content niche). Treat that as a default only:

- an explicit route/query value wins over the account value;
- a user's in-form selection wins over both and must survive account changes;
- before a manual selection, changing the account recomputes the account-bound
  default; and
- an empty bound value falls back to the product default rather than retaining
  a previous account's niche.

Keep the chosen value in the component's submitted configuration, not as a
side-effectful mutation of a Pinia store.

---

## Common Mistakes

- **Don't** create new stores for data that belongs in `workflowStore` (e.g., ripple data is part of workflow state)
- **Don't** mutate store state directly — use actions
- **Don't** forget to clean up WebSocket connections on unmount
- **Don't** use `watch` for things that can be `computed`
- **Don't** call `useXStore()` from router guards or other module-level code without an explicit shared Pinia instance. Export one `pinia` instance and pass it to the store (`useAuthStore(pinia)`) so navigation never depends on an active component context.
