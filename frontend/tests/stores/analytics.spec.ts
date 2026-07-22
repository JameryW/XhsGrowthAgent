import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  getGrowthReport: vi.fn(),
  getPerformance: vi.fn(),
}))

vi.mock('@/api/analytics', () => ({
  getGrowthReport: mocks.getGrowthReport,
  getPerformance: mocks.getPerformance,
}))

vi.mock('@/stores/realtime', () => ({
  useRealtimeStore: () => ({ wsService: { onEvent: vi.fn() } }),
}))

vi.mock('@/stores/toast', () => ({
  useToastStore: () => ({ info: vi.fn(), warning: vi.fn(), error: vi.fn() }),
}))

import { useAccountsStore } from '@/stores/accounts'
import { useAnalyticsStore } from '@/stores/analytics'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(res => {
    resolve = res
  })
  return { promise, resolve }
}

function account(id: string) {
  return { id, name: id, is_active: true } as any
}

function report(accountId: string, snapshotId: string) {
  return {
    account_id: accountId,
    period: 'weekly' as const,
    snapshot_id: snapshotId,
    data_as_of: '2026-07-22T10:00:00Z',
  }
}

describe('analytics standalone actions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.getGrowthReport.mockReset()
    mocks.getPerformance.mockReset()
  })

  it('drops a report response after the selected account changes', async () => {
    const accounts = useAccountsStore()
    const analytics = useAnalyticsStore()
    accounts.activeAccount = account('acc-a')
    const pending = deferred<ReturnType<typeof report>>()
    mocks.getGrowthReport.mockReturnValueOnce(pending.promise)

    const request = analytics.fetchReport()
    accounts.activeAccount = account('acc-b')
    pending.resolve(report('acc-a', 'snapshot:a'))
    await request

    expect(analytics.growthReport).toBeNull()
    expect(analytics.snapshotId).toBeNull()
  })

  it('drops a performance response after the selected period changes', async () => {
    const accounts = useAccountsStore()
    const analytics = useAnalyticsStore()
    accounts.activeAccount = account('acc-a')
    const pending = deferred<any>()
    mocks.getPerformance.mockReturnValueOnce(pending.promise)

    const request = analytics.fetchPerformance()
    analytics.period = 'monthly'
    pending.resolve({
      account_id: 'acc-a',
      posts: [],
      snapshot_id: 'snapshot:weekly',
      data_as_of: '2026-07-22T10:00:00Z',
    })
    await request

    expect(analytics.performanceData).toBeNull()
    expect(analytics.snapshotId).toBeNull()
  })

  it('lets only the latest standalone action own the snapshot state', async () => {
    const accounts = useAccountsStore()
    const analytics = useAnalyticsStore()
    accounts.activeAccount = account('acc-a')
    const reportPending = deferred<ReturnType<typeof report>>()
    const performancePending = deferred<any>()
    mocks.getGrowthReport.mockReturnValueOnce(reportPending.promise)
    mocks.getPerformance.mockReturnValueOnce(performancePending.promise)

    const reportRequest = analytics.fetchReport()
    const performanceRequest = analytics.fetchPerformance()
    reportPending.resolve(report('acc-a', 'snapshot:report'))
    await reportRequest
    expect(analytics.growthReport).toBeNull()

    performancePending.resolve({
      account_id: 'acc-a',
      posts: [],
      snapshot_id: 'snapshot:performance',
      data_as_of: '2026-07-22T10:00:00Z',
    })
    await performanceRequest
    expect(analytics.performanceData?.snapshot_id).toBe('snapshot:performance')
    expect(analytics.growthReport).toBeNull()
  })

  it('does not request a report without an active account', async () => {
    const analytics = useAnalyticsStore()
    await analytics.fetchReport()

    expect(mocks.getGrowthReport).not.toHaveBeenCalled()
    expect(analytics.growthReport).toBeNull()
    expect(analytics.performanceData).toBeNull()
  })
})
