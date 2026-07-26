import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCrossAccountHintsStore } from '@/stores/crossAccountHints'
import { REVIEW_AWAITING_TOTALS_KEY, readSessionTotals } from '@/utils/accountViewSession'
import { getWorkflowAccountTotals } from '@/api/workflow'

vi.mock('@/api/workflow', () => ({
  getWorkflowAccountTotals: vi.fn().mockResolvedValue({
    totals: { a: 1, b: 2 },
  }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ isAuthenticated: true }),
}))

vi.mock('@/stores/accounts', () => ({
  useAccountsStore: () => ({
    accounts: [
      { id: 'a', name: 'A' },
      { id: 'b', name: 'B' },
    ],
  }),
}))

describe('crossAccountHints store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.mocked(getWorkflowAccountTotals).mockClear()
  })
  afterEach(() => {
    sessionStorage.clear()
  })

  it('persists totals to session and exposes count', () => {
    const store = useCrossAccountHintsStore()
    store.setReviewAwaitingTotals({ a: 2, b: 3 })
    expect(store.reviewAwaitingCount).toBe(5)
    expect(readSessionTotals(REVIEW_AWAITING_TOTALS_KEY)).toEqual({ a: 2, b: 3 })
  })

  it('refreshes totals from the API', async () => {
    const store = useCrossAccountHintsStore()
    await store.refreshReviewAwaitingTotals(true)
    expect(store.reviewAwaitingCount).toBe(3)
    expect(getWorkflowAccountTotals).toHaveBeenCalledTimes(1)
  })

  it('skips network within TTL unless force=true', async () => {
    const store = useCrossAccountHintsStore()
    await store.refreshReviewAwaitingTotals()
    await store.refreshReviewAwaitingTotals()
    expect(getWorkflowAccountTotals).toHaveBeenCalledTimes(1)
    await store.refreshReviewAwaitingTotals(true)
    expect(getWorkflowAccountTotals).toHaveBeenCalledTimes(2)
  })
})
