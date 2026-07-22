# Frontend State Management

> Pinia store conventions for this project.

---

## Stores

| Store | File | Purpose |
|-------|------|---------|
| `useWorkflowStore` | `stores/workflow.ts` | Workflow lifecycle, phase, status, progress |
| `useRealtimeStore` | `stores/realtime.ts` | WebSocket connection, event recovery |
| `useToastStore` | `stores/toast.ts` | Success/error/warning/info notifications |
| `useThemeStore` | `stores/theme.ts` | Browser-local light/dark/system preference and root theme application |

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
- `connectionStatus: WsStatus` (`"disconnected" | "connecting" | "connected" | "reconnecting"`) is the **canonical backend-connectivity signal** for UI, not `navigator.onLine`

### OfflineRecovery bar — WS-driven, not browser-driven

`OfflineRecovery.vue` 黄条 must run in **controlled mode**: `App.vue` passes `:is-online` derived from realtime store:

```ts
const isBackendOnline = computed(
  () => !authStore.isAuthenticated || realtimeStore.connectionStatus !== "disconnected"
)
```

- `navigator.onLine` 误报频繁（容器 recreate / VPN / 远程访问触发 `offline` 后不复位），常驻黄条但后端实际正常 → never use it to drive the bar.
- `connecting`/`reconnecting` 算在线（宽限，不闪黄）；仅已认证且 `disconnected` 才亮.
- 未认证短路为 `true`，但 `showChrome=false` 时组件本就不渲染，分支无害.
- 组件 `isOffline = !(props.isOnline ?? internal)` — prop 存在优先 prop，浏览器事件只改 `internal` 不影响显示. 故受控模式**只传 prop 即生效，勿改 onMounted 跳过 listener**（缺失可选 prop 的 `!== undefined` 判定在 Vue/jsdom 不稳，会破坏 spec 且无收益）.

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

## Theme Store Pattern

`useThemeStore` owns only browser-local presentation state. It reads a validated
`light` / `dark` / `system` preference from `localStorage`, applies the
`dark` class and `color-scheme` metadata to `document.documentElement`, and
subscribes to `prefers-color-scheme` while in `system` mode. Call `init()` from
the application shell and call `dispose()` when that shell is unmounted so the
media-query listener cannot leak across test mounts or embedded shells.

Theme switching must feel immediate. Explicit mode changes should apply the
root theme synchronously, temporarily add a `theme-switching` guard for the
first painted frames, and disable surface transitions during that guard. Dark
compatibility CSS should use exact utility class selectors (or component-scoped
selectors); avoid broad [class*="..."] rules because changing the root theme
class forces those selectors to re-match the whole document.

---

## State ↔ Backend Sync

Frontend state mirrors backend `XHSGrowthState`. The sync flow:

1. API call (`POST /start`, `POST /resume`, etc.) returns `thread_id`
2. WebSocket streams `WORKFLOW_PROGRESS` events with full state
3. Store updates local refs from event payload
4. Components react to store computed properties

No polling — all updates are push-based via WebSocket/SSE.

### Public evidence-page cache

Public showcase/replay pages may use a versioned `sessionStorage` snapshot to
avoid a blank first view when the network is slow. Keep this cache short-lived
(30 seconds or less), validate its version and shape before hydrating reactive
state, and always issue a background refresh after a cache hit. If the refresh
fails, retain the usable snapshot, expose a retry action, and back off retries
so an expired cache cannot create a tight request loop. Cache only the JSON
display data; never move authenticated or mutation state into storage, and
clear refresh timers when the page unmounts.

Replay snapshots should be keyed by `threadId` and owned by the workflow store
so status and checkpoint state hydrate together. A history refresh must replace
the cached snapshot, while `loadMoreCheckpoints` merges and rewrites the same
thread's entry; exiting replay clears reactive state but does not delete the
short-lived session snapshot needed for a quick return.

### Live State vs Replay Selection

Replay-aware screens keep the live workflow snapshot separate from the
currently selected historical checkpoint. `workflowStore.liveWorkflowState`
answers “where is the workflow now?”, while `effectiveState` remains the
backwards-compatible display source for panels whose content should follow
the selected checkpoint. Checkpoint loading errors are stored independently
from the live status so a temporary history failure does not hide a healthy
current workflow. Deep-linked checkpoint selection must prefer the requested
ID, then the latest checkpoint containing business data, then the newest
checkpoint.

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

Public route shells should import only the store modules they use (for example,
`stores/auth` and `stores/realtime`) instead of importing the aggregate
`stores/index` barrel. The barrel is convenient inside authenticated feature
code, but it can pull unrelated workspace stores into the public entry chunk.

## Scenario: Account-scoped paginated history with stale guards

### 1. Scope / Trigger
- Trigger: an account selector changes while Analytics/Evaluation requests a
  canonical note page, workflow list, trend, report, or latest note evaluation.

### 2. Signatures
- `loadNotes(accountId, reset=true)` and `loadList(reset, accountId)` own local
  request generations and cursors.
- `analyticsStore.fetchDashboard(accountId, period, limit)` owns dashboard
  generation; API clients receive the same account ID explicitly.

### 3. Contracts
- Account is the single query boundary. On change, clear/reset rows, totals,
  cursors and data-as-of before loading the new scope.
- A response may commit only if its generation and account ID still match the
  active request. Late responses are discarded, never merged into the new account.
- Store/component state exposes `loaded / total`, `next_cursor`, `data_as_of` and
  stale/loading/error status; compact previews never imply completeness.
- Analytics historical pages compare their canonical page `snapshot_id` with
  the dashboard snapshot before appending; a mismatch stops pagination and
  exposes retry rather than merging two imports.

### 4. Validation & Error Matrix
- No active account → clear state and no request; do not use `default`.
- Cursor exhausted → no more request; retain stable loaded/total metadata.
- API error → keep the account shell, show local retry and do not resurrect rows
  from a previous account.
- Route unmount/account switch → invalidate generation; in-flight work may finish
  but cannot mutate state.

### 5. Good/Base/Bad Cases
- Good: A→B switch immediately clears A, B response wins, A late response is ignored.
- Base: old backend fallback returns one bounded page with an explicit total.
- Bad: appending B rows to A, double-counting offset after load-more, or retaining
  A's `data_as_of` while showing B.

### 6. Tests Required
- Assert account switch reset, stale response suppression, cursor traversal,
  loaded/total display, and stale dashboard generation.
- Assert the same selected account is passed to list/trend/report APIs.

### 7. Wrong vs Correct
```ts
// Wrong: any late response overwrites the currently selected account.
rows.value = await getCreatorNotes(accountId)

// Correct: commit only the request that still owns the account scope.
const generation = ++requestGeneration
const page = await getCreatorNotes(accountId, query)
if (generation === requestGeneration && accountId === selectedAccountId.value) {
  rows.value = page.items
}
```
