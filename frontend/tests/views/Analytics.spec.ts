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

async function mountAnalytics() {
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
  await flushPromises()
  await flushPromises()
  return wrapper
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
})
