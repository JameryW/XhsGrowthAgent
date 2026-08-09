// AN-18: Analytics view-level acceptance tests.
// Covers: three states (loading/empty/data), stale-error notice (AN-09),
// show-all table expansion (AN-11), and the fans card (AN-05).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import Analytics from '@/views/Analytics.vue'
import i18n from '@/locales'

// i18n renders translated values, so compare against those, not key names.
const tt = (key: string, params?: Record<string, any>) => i18n.global.t(key, params as any)

// Stub heavy async/chart children so the view's own logic is what we assert.
const stubs = {
  CreatorStatsPanel: { template: '<div />' },
  CreatorNoteQualityPanel: { template: '<div />' },
  MetricCard: { props: ['title', 'value', 'subtitle', 'delta', 'variant'], template: '<div class="metric"><span class="title">{{ title }}</span><span class="value">{{ value }}</span><span v-if="delta" class="delta">{{ delta }}</span></div>' },
}
const TrendChartStub = { template: '<div />' }
const EngagementChartStub = { template: '<div />' }

vi.mock('@/api/analytics', () => ({
  getDashboard: vi.fn(),
  getPerformance: vi.fn(),
  getGrowthReport: vi.fn().mockResolvedValue(null),
  getCosts: vi.fn().mockResolvedValue(null),
  getCreatorStats: vi.fn().mockResolvedValue({ account: null, notes: [] }),
  getCreatorNotes: vi.fn(),
  getCreatorNote: vi.fn(),
  getCreatorNoteQuality: vi.fn(),
}))

// accountsStore.fetchAccounts hits the network (listAccounts); stub it so
// onMounted doesn't hang.
vi.mock('@/api/accounts', () => ({
  KNOWN_NICHES: [],
  listAccounts: vi.fn().mockResolvedValue([{ id: 'acct1', name: 'Account 1', is_active: true, created_at: '' }]),
  getActiveAccount: vi.fn().mockResolvedValue({ id: 'acct1', name: 'Account 1', is_active: true, created_at: '' }),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
  resolveAccountNiche: vi.fn(),
  getAccountLoginStatus: vi.fn(),
  startQrLogin: vi.fn(),
  getQrLoginStatus: vi.fn(),
}))

async function mountAnalytics(options: { settle?: boolean } = {}) {
  const settle = options.settle ?? true
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/analytics', name: 'analytics', component: Analytics }],
  })
  router.push({ name: 'analytics' })
  await router.isReady()
  const wrapper = mount(Analytics, {
    global: {
      plugins: [router],
      stubs: {
        ...stubs,
        TrendChart: TrendChartStub,
        EngagementChart: EngagementChartStub,
      },
    },
  })
  if (settle) {
    await flushPromises()
    await flushPromises()
  }
  return wrapper
}

function makePost(title: string, views: number) {
  return {
    id: title,
    title,
    views,
    likes: 10,
    comments: 2,
    collects: 3,
    shares: 1,
    engagement_rate: 0.05,
    published_at: new Date().toISOString(),
  }
}

function makeDashboard(posts = [makePost('post-1', 100)]) {
  return {
    report: null,
    performance: { account_id: 'acct1', posts },
    period_summary: {
      period: 'weekly',
      current: { posts: 4, views: 300, likes: 20, comments: 4, collects: 6, shares: 2, engagement: 32, avg_engagement_rate: 0.05 },
      previous: { posts: 2, views: 200, likes: 10, comments: 2, collects: 3, shares: 1, engagement: 16, avg_engagement_rate: 0.04 },
    },
    costs: null,
  }
}

describe('Analytics view', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders the fans metric card on the first screen (AN-05)', async () => {
    const { getDashboard } = await import('@/api/analytics')
    ;(getDashboard as any).mockResolvedValue({
      report: null,
      performance: { account_id: 'default', posts: [{ title: 'p', views: 1, likes: 0, comments: 0, collects: 0, shares: 0, engagement_rate: 1, published_at: new Date().toISOString() }] },
      costs: null,
    })
    const wrapper = await mountAnalytics()
    const titles = wrapper.findAll('.metric .title').map(n => n.text())
    expect(titles).toContain(tt('analytics.fans'))
  })

  it('shows the empty state when there are no posts', async () => {
    const { getDashboard } = await import('@/api/analytics')
    ;(getDashboard as any).mockResolvedValue({ report: null, performance: { account_id: 'default', posts: [] }, costs: null })
    const wrapper = await mountAnalytics()
    expect(wrapper.text()).toContain(tt('analytics.empty.startWorkflow'))
  })

  it('renders post rows + the show-all control when posts > 10 (AN-11)', async () => {
    const { getDashboard } = await import('@/api/analytics')
    const posts = Array.from({ length: 15 }, (_, i) => ({
      title: `post-${i}`, views: 100 * i, likes: 0, comments: 0, collects: 0, shares: 0,
      engagement_rate: 1, published_at: new Date().toISOString(),
    }))
    ;(getDashboard as any).mockResolvedValue({ report: null, performance: { account_id: 'default', posts }, costs: null })
    const wrapper = await mountAnalytics()
    await flushPromises()
    // expand control present because 15 > 10
    expect(wrapper.text()).toContain(tt('analytics.showAll', { count: 15 }))
  })

  it('keeps the loading skeleton visible while the first request is pending', async () => {
    const { useAnalyticsStore } = await import('@/stores')
    const analyticsStore = useAnalyticsStore()
    analyticsStore.isLoading = true

    const wrapper = await mountAnalytics({ settle: false })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.skeleton-card').exists()).toBe(true)
    analyticsStore.isLoading = false
    wrapper.unmount()
  })

  it('renders the shared error state and retries the failed request', async () => {
    const { getDashboard } = await import('@/api/analytics')
    ;(getDashboard as any).mockRejectedValue(new Error('offline'))

    const wrapper = await mountAnalytics()
    expect(wrapper.text()).toContain(tt('analytics.error.title'))
    const callsBeforeRetry = (getDashboard as any).mock.calls.length

    const retry = wrapper.findAll('button').find(button => button.text().includes(tt('analytics.error.retry')))
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    await flushPromises()
    expect((getDashboard as any).mock.calls.length).toBe(callsBeforeRetry + 1)
  })

  it('switches period and renders server-owned deltas (AN-18)', async () => {
    const { getDashboard } = await import('@/api/analytics')
    ;(getDashboard as any)
      .mockResolvedValueOnce(makeDashboard())
      .mockResolvedValueOnce({ ...makeDashboard(), period_summary: { ...makeDashboard().period_summary, period: 'monthly' } })

    const wrapper = await mountAnalytics()
    expect(wrapper.text()).toContain('↑ 50%')

    const monthly = wrapper.findAll('[aria-pressed]').find(button => button.attributes('aria-label') === tt('analytics.thisMonth'))
    expect(monthly).toBeDefined()
    await monthly!.trigger('click')
    await flushPromises()
    expect((await import('@/stores')).useAnalyticsStore().period).toBe('monthly')
    expect(getDashboard).toHaveBeenLastCalledWith('acct1', 'monthly', 20)
  })

  it('sorts table rows by numeric views and opens the drill-down drawer (AN-18)', async () => {
    const { getDashboard } = await import('@/api/analytics')
    ;(getDashboard as any).mockResolvedValue(makeDashboard([makePost('low', 100), makePost('high', 900)]))

    const wrapper = await mountAnalytics()
    const viewsHeader = wrapper.findAll('[role="columnheader"] button').find(button => button.text().includes(tt('analytics.table.views')))
    expect(viewsHeader).toBeDefined()
    await viewsHeader!.trigger('click')
    let rows = wrapper.findAll('[role="row"]')
    expect(rows[0].text()).toContain('high')

    await viewsHeader!.trigger('click')
    rows = wrapper.findAll('[role="row"]')
    expect(rows[0].text()).toContain('low')

    await rows[0].trigger('click')
    await wrapper.vm.$nextTick()
    expect(document.body.querySelector('[role="dialog"]')).not.toBeNull()
    expect(document.body.textContent).toContain('low')
    wrapper.unmount()
  })

  it('keeps cached rows visible and surfaces a stale-data retry notice', async () => {
    const { getDashboard } = await import('@/api/analytics')
    ;(getDashboard as any)
      .mockResolvedValueOnce(makeDashboard())
      .mockRejectedValueOnce(new Error('temporary outage'))

    const wrapper = await mountAnalytics()
    const monthly = wrapper.findAll('[aria-pressed]').find(button => button.attributes('aria-label') === tt('analytics.thisMonth'))
    expect(monthly).toBeDefined()
    await monthly!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain(tt('analytics.staleNotice'))
    expect(wrapper.text()).toContain('post-1')
  })
})
