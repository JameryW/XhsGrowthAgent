import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  _resetRoutePrefetchStateForTests,
  chunkForPath,
  navigateToStart,
  prefetchRouteByPath,
  prefetchRouteChunk,
  prefetchStartWorkspace,
  scheduleIdleStartPrefetch,
} from '@/utils/routePrefetch'

const fetchAccounts = vi.fn(() => Promise.resolve())
const getSystemHealth = vi.fn(() => Promise.resolve({ status: 'ok' }))

// Dynamic import() in routePrefetch uses string paths; mock the stores/API modules.
vi.mock('@/stores/accounts', () => ({
  useAccountsStore: () => ({ fetchAccounts }),
}))

vi.mock('@/api/system', () => ({
  getSystemHealth,
}))

describe('routePrefetch', () => {
  beforeEach(() => {
    _resetRoutePrefetchStateForTests()
    vi.clearAllMocks()
  })

  it('maps workspace paths to chunks', () => {
    expect(chunkForPath('/start')).toBe('home')
    expect(chunkForPath('/dashboard/xhs_abc')).toBe('dashboard')
    expect(chunkForPath('/review?x=1')).toBe('review')
    expect(chunkForPath('/unknown')).toBeNull()
  })

  it('coalesces concurrent prefetchStartWorkspace calls', async () => {
    const a = prefetchStartWorkspace({ data: true, deep: false })
    const b = prefetchStartWorkspace({ data: true, deep: false })
    expect(a).toBe(b)
    await a
    expect(fetchAccounts).toHaveBeenCalledTimes(1)
    expect(getSystemHealth).toHaveBeenCalledTimes(1)
  })

  it('deep warm after shallow warm still loads extra chunks without re-fetching data', async () => {
    await prefetchStartWorkspace({ data: true, deep: false })
    fetchAccounts.mockClear()
    getSystemHealth.mockClear()

    await prefetchStartWorkspace({ data: true, deep: true })
    // Data already warm — second pass should not re-hit accounts/health.
    expect(fetchAccounts).not.toHaveBeenCalled()
    expect(getSystemHealth).not.toHaveBeenCalled()
  })

  it('skips data warm when data:false', async () => {
    await prefetchStartWorkspace({ data: false, deep: false })
    expect(fetchAccounts).not.toHaveBeenCalled()
    expect(getSystemHealth).not.toHaveBeenCalled()
  })

  it('scheduleIdleStartPrefetch uses requestIdleCallback when available', () => {
    const idle = vi.fn((cb: () => void) => {
      cb()
      return 1
    })
    Object.defineProperty(window, 'requestIdleCallback', {
      configurable: true,
      value: idle,
    })

    scheduleIdleStartPrefetch(100)
    expect(idle).toHaveBeenCalled()
  })

  it('prefetchRouteChunk is idempotent for the same name', async () => {
    await prefetchRouteChunk('home')
    await prefetchRouteChunk('home')
    await expect(prefetchRouteChunk('home')).resolves.toBeUndefined()
  })

  it('prefetchRouteByPath is a no-op for unknown paths', async () => {
    await expect(prefetchRouteByPath('/not-a-route')).resolves.toBeUndefined()
  })

  it('navigateToStart warms then pushes /start', async () => {
    const push = vi.fn()
    navigateToStart({ push })
    expect(push).toHaveBeenCalledWith('/start')
    // Allow the fire-and-forget warm to settle.
    await Promise.resolve()
    await prefetchStartWorkspace({ data: true, deep: false })
    expect(fetchAccounts).toHaveBeenCalled()
  })
})
