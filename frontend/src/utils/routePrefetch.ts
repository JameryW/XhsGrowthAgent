/**
 * Intentional route / workspace warm-up.
 *
 * Hover/focus and idle time after login hide lazy-chunk download latency for
 * the start-creation path and common workspace destinations.
 */

export type ChunkName =
  | 'home'
  | 'tui'
  | 'dashboard'
  | 'review'
  | 'history'
  | 'analytics'
  | 'evaluation'
  | 'settings'
  | 'help'

const loaders: Record<ChunkName, () => Promise<unknown>> = {
  home: () => import('@/views/Home.vue'),
  tui: () => import('@/views/AgentTUI.vue'),
  dashboard: () => import('@/views/Dashboard.vue'),
  review: () => import('@/views/Review.vue'),
  history: () => import('@/views/History.vue'),
  analytics: () => import('@/views/Analytics.vue'),
  evaluation: () => import('@/views/EvaluationView.vue'),
  settings: () => import('@/views/Settings.vue'),
  help: () => import('@/views/HelpView.vue'),
}

/** Map app paths (and prefixes) → lazy chunks. */
const PATH_CHUNKS: Array<{ prefix: string; chunk: ChunkName }> = [
  { prefix: '/start', chunk: 'home' },
  { prefix: '/tui', chunk: 'tui' },
  { prefix: '/dashboard', chunk: 'dashboard' },
  { prefix: '/review', chunk: 'review' },
  { prefix: '/history', chunk: 'history' },
  { prefix: '/analytics', chunk: 'analytics' },
  { prefix: '/evaluation', chunk: 'evaluation' },
  { prefix: '/settings', chunk: 'settings' },
  { prefix: '/help', chunk: 'help' },
]

const loadedChunks = new Set<ChunkName>()
const chunkInFlight = new Map<ChunkName, Promise<void>>()

/** Prefetch a known lazy route chunk (idempotent). */
export function prefetchRouteChunk(name: ChunkName): Promise<void> {
  if (loadedChunks.has(name)) return Promise.resolve()
  const existing = chunkInFlight.get(name)
  if (existing) return existing

  const p = loaders[name]()
    .then(() => {
      loadedChunks.add(name)
    })
    .catch(() => {
      // Network flake — click path will load the chunk normally.
    })
    .finally(() => {
      chunkInFlight.delete(name)
    })

  chunkInFlight.set(name, p)
  return p
}

/** Resolve a router path to a chunk name (longest prefix match). */
export function chunkForPath(path: string): ChunkName | null {
  const bare = path.split('?')[0] || path
  for (const { prefix, chunk } of PATH_CHUNKS) {
    if (bare === prefix || bare.startsWith(`${prefix}/`)) return chunk
  }
  return null
}

/** Prefetch the lazy chunk for a workspace path (no-op if unknown). */
export function prefetchRouteByPath(path: string): Promise<void> {
  const chunk = chunkForPath(path)
  if (!chunk) return Promise.resolve()
  return prefetchRouteChunk(chunk)
}

let startWarmInFlight: Promise<void> | null = null
let startWarmDone = false
let startWarmDeepDone = false

export type PrefetchStartOptions = {
  /** Also pull free-mode TUI + dashboard (post-start) chunks. */
  deep?: boolean
  /** Warm accounts + system health caches (uses pinia/API). Default true. */
  data?: boolean
}

/**
 * Warm everything needed for a snappy /start navigation:
 * Home chunk, optional TUI/dashboard, accounts list, system health.
 */
export function prefetchStartWorkspace(options?: PrefetchStartOptions): Promise<void> {
  const deep = options?.deep === true
  const data = options?.data !== false

  if (startWarmDone && (!deep || startWarmDeepDone)) {
    return Promise.resolve()
  }

  // A non-deep call can share an in-flight warm. A deep call while a shallow
  // warm is running must still schedule the extra chunks afterwards.
  if (startWarmInFlight && !deep) {
    return startWarmInFlight
  }

  const prior = startWarmInFlight

  const run = async () => {
    if (prior) await prior

    const jobs: Promise<unknown>[] = []
    if (!startWarmDone) {
      jobs.push(prefetchRouteChunk('home'))
      if (data) {
        jobs.push(
          (async () => {
            try {
              const { useAccountsStore } = await import('@/stores/accounts')
              await useAccountsStore().fetchAccounts()
            } catch {
              // pinia not ready / API offline — ignore
            }
          })(),
          (async () => {
            try {
              const { getSystemHealth } = await import('@/api/system')
              await getSystemHealth()
            } catch {
              // ignore
            }
          })(),
        )
      }
    }

    if (deep && !startWarmDeepDone) {
      // Post-start destinations: free mode → TUI; trend/brief → dashboard.
      jobs.push(prefetchRouteChunk('tui'), prefetchRouteChunk('dashboard'))
    }

    if (jobs.length) await Promise.all(jobs)
    startWarmDone = true
    if (deep) startWarmDeepDone = true
  }

  startWarmInFlight = run().finally(() => {
    startWarmInFlight = null
  })
  return startWarmInFlight
}

/** Prefetch common workspace nav targets after login (cheap, parallel). */
export function prefetchWorkspaceNav(): Promise<void> {
  return Promise.all([
    prefetchRouteChunk('dashboard'),
    prefetchRouteChunk('review'),
    prefetchRouteChunk('history'),
  ]).then(() => undefined)
}

/**
 * Navigate to /start after kicking a warm (shared by History / Review / etc.).
 * Accepts a minimal router so views don't each re-implement warm+push.
 */
export function navigateToStart(router: { push: (to: string) => unknown }): void {
  void prefetchStartWorkspace({ deep: false, data: true })
  void router.push('/start')
}

/** Schedule start + nav warm-up when the browser is idle. */
export function scheduleIdleStartPrefetch(timeoutMs = 2500): void {
  if (typeof window === 'undefined') return
  const run = () => {
    void prefetchStartWorkspace({ deep: true, data: true })
    // Second idle tick: warmer nav without competing with start path.
    const nav = () => {
      void prefetchWorkspaceNav()
    }
    if ('requestIdleCallback' in window) {
      const idle = window.requestIdleCallback as (
        cb: () => void,
        opts?: { timeout: number },
      ) => number
      idle(nav, { timeout: timeoutMs })
    } else {
      window.setTimeout(nav, 400)
    }
  }
  if ('requestIdleCallback' in window) {
    const idle = window.requestIdleCallback as (
      cb: () => void,
      opts?: { timeout: number },
    ) => number
    idle(run, { timeout: timeoutMs })
  } else {
    window.setTimeout(run, Math.min(timeoutMs, 800))
  }
}

/** Test helper — reset module state. */
export function _resetRoutePrefetchStateForTests(): void {
  loadedChunks.clear()
  chunkInFlight.clear()
  startWarmInFlight = null
  startWarmDone = false
  startWarmDeepDone = false
}
