import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ref } from 'vue'
import {
  HISTORY_VIEW_ACCOUNT_KEY,
  HISTORY_LIST_CACHE_TTL_MS,
  pickPreferredViewAccount,
  persistViewAccount,
  readStoredViewAccount,
  isOwnedAccount,
  useHistoryAccountScope,
} from '@/composables/useHistoryAccountScope'

vi.mock('@/api/workflow', () => ({
  listWorkflows: vi.fn(),
}))

describe('useHistoryAccountScope helpers', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })
  afterEach(() => {
    sessionStorage.clear()
  })

  it('persists and reads the view account from sessionStorage', () => {
    persistViewAccount('acct-b')
    expect(readStoredViewAccount()).toBe('acct-b')
    expect(sessionStorage.getItem(HISTORY_VIEW_ACCOUNT_KEY)).toBe('acct-b')
    persistViewAccount(null)
    expect(readStoredViewAccount()).toBeNull()
  })

  it('picks URL over session over workspace among owned accounts', () => {
    const accounts = [
      { id: 'acct-a', name: 'A', is_active: true, created_at: '' },
      { id: 'acct-b', name: 'B', is_active: false, created_at: '' },
    ]
    persistViewAccount('acct-b')
    const route = {
      query: { account: 'acct-a' },
    } as any
    expect(pickPreferredViewAccount(route, accounts as any, 'acct-b')).toBe('acct-a')

    const routeNoQuery = { query: {} } as any
    expect(pickPreferredViewAccount(routeNoQuery, accounts as any, 'acct-a')).toBe('acct-b')
  })

  it('rejects non-owned account ids', () => {
    const accounts = [{ id: 'acct-a', name: 'A', is_active: true, created_at: '' }]
    expect(isOwnedAccount(accounts as any, 'acct-b')).toBe(false)
    expect(isOwnedAccount(accounts as any, 'acct-a')).toBe(true)
  })
})

describe('useHistoryAccountScope cache', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.useFakeTimers()
  })
  afterEach(() => {
    sessionStorage.clear()
    vi.useRealTimers()
  })

  it('stores list cache and reports freshness by TTL', () => {
    const route = { query: {} } as any
    const router = { replace: vi.fn().mockResolvedValue(undefined) } as any
    const accountsStore = {
      accounts: [
        { id: 'acct-a', name: 'A', is_active: true, created_at: '' },
        { id: 'acct-b', name: 'B', is_active: false, created_at: '' },
      ],
      activeAccount: { id: 'acct-a', name: 'A', is_active: true, created_at: '' },
      activeAccountId: 'acct-a',
    }
    const scope = useHistoryAccountScope({
      route,
      router,
      accountsStore: accountsStore as any,
      locale: ref('zh-CN'),
    })

    scope.setCachedList('acct-a', [{ thread_id: 't1' } as any], 1)
    expect(scope.getCachedList('acct-a')?.total).toBe(1)
    expect(scope.isCacheFresh(scope.getCachedList('acct-a'))).toBe(true)

    vi.advanceTimersByTime(HISTORY_LIST_CACHE_TTL_MS + 1)
    expect(scope.isCacheFresh(scope.getCachedList('acct-a'))).toBe(false)

    scope.invalidateCachedList('acct-a')
    expect(scope.getCachedList('acct-a')).toBeNull()
  })

  it('prefetches a non-viewing account into the list cache', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    ;(listWorkflows as any).mockResolvedValue({
      workflows: [{ thread_id: 'xhs_b', account_id: 'acct-b', label: 'pre' }],
      total: 1,
      limit: 50,
      offset: 0,
    })

    const route = { query: {} } as any
    const router = { replace: vi.fn().mockResolvedValue(undefined) } as any
    const accountsStore = {
      accounts: [
        { id: 'acct-a', name: 'A', is_active: true, created_at: '' },
        { id: 'acct-b', name: 'B', is_active: false, created_at: '' },
      ],
      activeAccount: { id: 'acct-a', name: 'A', is_active: true, created_at: '' },
      activeAccountId: 'acct-a',
    }
    const scope = useHistoryAccountScope({
      route,
      router,
      accountsStore: accountsStore as any,
      locale: ref('zh-CN'),
    })
    scope.applyViewAccount('acct-a', { syncUrl: false })

    await scope.prefetchAccount('acct-b')
    expect(listWorkflows).toHaveBeenCalledWith(
      expect.objectContaining({ account_id: 'acct-b', limit: 50 }),
      expect.objectContaining({ suppressToast: true }),
    )
    expect(scope.getCachedList('acct-b')?.workflows[0]?.label).toBe('pre')
  })
})
