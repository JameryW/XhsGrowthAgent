// EV-17: EvaluationView view-level acceptance tests.
// Covers: detail deep-link context (EV-01), decision action CTA (EV-03),
// no-score rendering as '—' not 0 (EV-05), trend three states (EV-02).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import EvaluationView from '@/views/EvaluationView.vue'
import i18n from '@/locales'
import { listAccounts } from '@/api/accounts'

const tt = (key: string, params?: Record<string, any>) => i18n.global.t(key, params as any)

const baseResult = {
  thread_id: 't-detail',
  has_evaluation: true,
  evaluation_result: {
    overall_score: 72,
    dimensions: [
      { dimension: 'copywriting', score: 80, rationale: '', issues: [], is_blocking: false, bias_severity: undefined },
      { dimension: 'bias_check', score: 90, rationale: '', issues: [], is_blocking: false, bias_severity: 0.2 },
    ],
    decision: 'approved',
    revision_hints: [],
    bias_warning: '',
    summary: 'ok',
  },
}

vi.mock('@/api/evaluation', () => ({
  getEvaluationList: vi.fn(),
  getEvaluationResult: vi.fn(),
  getEvaluationTrend: vi.fn(),
  evaluateNote: vi.fn(),
}))

vi.mock('@/api/accounts', () => ({
  KNOWN_NICHES: [],
  listAccounts: vi.fn().mockResolvedValue([]),
  getActiveAccount: vi.fn().mockResolvedValue(null),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
  resolveAccountNiche: vi.fn(),
  getAccountLoginStatus: vi.fn(),
  startQrLogin: vi.fn(),
  getQrLoginStatus: vi.fn(),
}))

// The overview band fetches the creator-quality report for the selected account;
// keep the call inside the mock graph so no real HTTP fires mid-test.
vi.mock('@/api/analytics', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/analytics')>()
  return {
    ...actual,
    getCreatorQuality: vi.fn().mockResolvedValue(null),
    getCreatorStats: vi.fn().mockResolvedValue({ notes: [] }),
    // Keep view tests on the legacy-compatible adapter path; the canonical
    // endpoint is covered by API tests and should not attempt localhost I/O.
    getCreatorNotes: vi.fn().mockRejectedValue(new Error('canonical reader unavailable')),
  }
})

async function mountEval(params: Record<string, string> = {}, query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/evaluation', name: 'evaluation', component: EvaluationView },
      { path: '/evaluation/:threadId', name: 'evaluation-detail', component: EvaluationView },
    ],
  })
  if (params.threadId) router.push({ name: 'evaluation-detail', params, query })
  else router.push({ name: 'evaluation', query })
  await router.isReady()
  const wrapper = mount(EvaluationView, {
    global: {
      plugins: [router],
      stubs: {
        TrendChart: { template: '<div />' },
        EvaluationRadar: { template: '<div />' },
        CreatorQualityPanel: { template: '<div data-testid="quality-panel" />' },
        CreatorNoteQualityPanel: { template: '<div data-testid="note-quality-panel" />' },
      },
    },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('EvaluationView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    // clearAllMocks preserves implementations. Reset the shared account
    // fixture so a prior account-scoped test cannot leak into the no-account
    // contract.
    ;(listAccounts as any).mockResolvedValue([])
  })

  it('detail shows the decision CTA for an approved result (EV-03)', async () => {
    const { getEvaluationResult, getEvaluationList, getEvaluationTrend } = await import('@/api/evaluation')
    ;(getEvaluationResult as any).mockResolvedValue(baseResult)
    ;(getEvaluationList as any).mockResolvedValue({ workflows: [], total: 0 })
    ;(getEvaluationTrend as any).mockResolvedValue({ db_ready: true, points: [], dim_averages: {} })
    const wrapper = await mountEval({ threadId: 't-detail' })
    expect(wrapper.text()).toContain(tt('evaluation.action.viewWorkflow'))
  })

  it('renders no-score as — not 0.0 (EV-05)', async () => {
    const { getEvaluationResult, getEvaluationList, getEvaluationTrend } = await import('@/api/evaluation')
    const noScore = JSON.parse(JSON.stringify(baseResult))
    noScore.evaluation_result.overall_score = null
    ;(getEvaluationResult as any).mockResolvedValue(noScore)
    ;(getEvaluationList as any).mockResolvedValue({ workflows: [], total: 0 })
    ;(getEvaluationTrend as any).mockResolvedValue({ db_ready: true, points: [], dim_averages: {} })
    const wrapper = await mountEval({ threadId: 't-detail' })
    const scoreEl = wrapper.find('.score-value')
    expect(scoreEl.exists()).toBe(true)
    expect(scoreEl.text()).toBe('—')
  })

  it('trend failure shows a retry, not "no data" (EV-02)', async () => {
    const { getEvaluationList, getEvaluationTrend } = await import('@/api/evaluation')
    const { listAccounts } = await import('@/api/accounts')
    ;(getEvaluationList as any).mockResolvedValue({ workflows: [], total: 0 })
    ;(getEvaluationTrend as any).mockRejectedValue(new Error('network'))
    ;(listAccounts as any).mockResolvedValue([{ id: 'acc-1', name: '测试账号', is_active: true }])
    const wrapper = await mountEval({}, { tab: 'workflow' })
    // loadTrend fires from the activeTab watcher after mount; let it reject.
    for (let i = 0; i < 5; i++) await flushPromises()
    expect(wrapper.text()).toContain(tt('evaluation.trend.failed'))
    expect(wrapper.text()).toContain(tt('evaluation.trend.retry'))
  })

  it('uses effective per-account thresholds for score tiers', async () => {
    const { getEvaluationResult, getEvaluationList, getEvaluationTrend } = await import('@/api/evaluation')
    const result = JSON.parse(JSON.stringify(baseResult))
    result.evaluation_result.overall_score = 72
    result.thresholds = { pass: 80, warn: 60 }
    ;(getEvaluationResult as any).mockResolvedValue(result)
    ;(getEvaluationList as any).mockResolvedValue({ workflows: [], total: 0 })
    ;(getEvaluationTrend as any).mockResolvedValue({ db_ready: true, points: [], dim_averages: {} })

    const wrapper = await mountEval({ threadId: 't-thresholds' })
    const score = wrapper.find('.score-value')
    expect(score.classes()).toContain('score-warn')
    expect(score.classes()).not.toContain('score-pass')
  })

  it('keeps loading more while the accumulated list is below total', async () => {
    const { getEvaluationList, getEvaluationTrend } = await import('@/api/evaluation')
    const { listAccounts } = await import('@/api/accounts')
    const firstPage = Array.from({ length: 20 }, (_, i) => ({
      thread_id: `t-${i}`,
      account_id: 'acc-1',
      status: 'completed',
      phase: 'reviewing',
      label: '',
      workflow_mode: 'trend',
      updated_at: '2026-07-01T00:00:00Z',
      selected_title: `标题${i}`,
      overall_score: 70,
      decision: 'approved',
    }))
    const secondPage = firstPage.map((item, i) => ({ ...item, thread_id: `t-${i + 20}`, selected_title: `标题${i + 20}` }))
    ;(getEvaluationList as any)
      .mockResolvedValueOnce({ workflows: firstPage, total: 40 })
      .mockResolvedValueOnce({ workflows: secondPage, total: 40 })
    ;(getEvaluationTrend as any).mockResolvedValue({ db_ready: true, points: [], dim_averages: {} })
    ;(listAccounts as any).mockResolvedValue([{ id: 'acc-1', name: '测试账号', is_active: true }])

    const wrapper = await mountEval({}, { tab: 'workflow' })
    const loadMore = () => wrapper.find('.load-more-btn')
    expect(loadMore().exists()).toBe(true)
    await loadMore().trigger('click')
    await flushPromises()
    expect(wrapper.find('.load-more-btn').exists()).toBe(false)
    expect(wrapper.text()).toContain('标题39')
  })

  it('renders the fused overview band and no-account hint on the list view', async () => {
    const { getEvaluationList, getEvaluationTrend } = await import('@/api/evaluation')
    ;(getEvaluationList as any).mockResolvedValue({ workflows: [], total: 0 })
    ;(getEvaluationTrend as any).mockResolvedValue({ db_ready: true, points: [], dim_averages: {} })
    const wrapper = await mountEval()
    expect(wrapper.text()).toContain(tt('evaluation.overview.title'))
    expect(wrapper.text()).toContain(tt('creatorQuality.page.noAccountTitle'))
    // No account → diagnosis section hidden, workflow segment still available.
    expect(wrapper.find('[data-testid="quality-panel"]').exists()).toBe(false)
  })

  it('shows the diagnosis panel for the default account', async () => {
    const { getEvaluationList, getEvaluationTrend } = await import('@/api/evaluation')
    const { listAccounts } = await import('@/api/accounts')
    ;(getEvaluationList as any).mockResolvedValue({ workflows: [], total: 0 })
    ;(getEvaluationTrend as any).mockResolvedValue({ db_ready: true, points: [], dim_averages: {} })
    ;(listAccounts as any).mockResolvedValue([{ id: 'acc-1', name: '测试账号', is_active: true }])
    const wrapper = await mountEval()
    expect(wrapper.find('[data-testid="quality-panel"]').exists()).toBe(true)
  })

  const workflowRow = {
    thread_id: 't-1', account_id: 'acc-1', status: 'completed', phase: 'reviewing', label: '',
    workflow_mode: 'trend', updated_at: '2026-07-10T00:00:00Z',
    selected_title: '工作流笔记', overall_score: 80, decision: 'approved',
  }
  const noteRow = {
    note_id: 'n-1', account_id: 'acc-1', title: '历史笔记', views: 1200, likes: 88,
    comments: 6, collects: 20, shares: 1, published_at: '2026-07-12T00:00:00Z',
    content_type: 'normal', tags: [], cover_url: '', engagement_rate: 0.08, synced_at: '', source: 'import',
  }

  it('keeps published history and workflow review in separate source tabs', async () => {
    const { getEvaluationList, getEvaluationTrend } = await import('@/api/evaluation')
    const { listAccounts } = await import('@/api/accounts')
    const { getCreatorStats } = await import('@/api/analytics')
    ;(getEvaluationList as any).mockResolvedValue({ workflows: [workflowRow], total: 1 })
    ;(getEvaluationTrend as any).mockResolvedValue({ db_ready: true, points: [], dim_averages: {} })
    ;(listAccounts as any).mockResolvedValue([{ id: 'acc-1', name: '测试账号', is_active: true }])
    ;(getCreatorStats as any).mockResolvedValue({ notes: [noteRow] })

    const wrapper = await mountEval({}, { tab: 'historical' })
    let titles = wrapper.findAll('.item-title').map((el) => el.text())
    expect(titles).toEqual(['历史笔记'])
    expect(wrapper.text()).not.toContain('工作流笔记')
    expect(wrapper.text()).toContain(tt('evaluation.stream.sourceImported'))

    const workflowTab = wrapper.findAll('.source-tab').find((el) => el.text().includes(tt('evaluation.stream.workflowTab')))
    await workflowTab!.trigger('click')
    titles = wrapper.findAll('.item-title').map((el) => el.text())
    expect(titles).toEqual(['工作流笔记'])
    expect(wrapper.text()).toContain(tt('evaluation.stream.sourceWorkflow'))

    // Clicking a note row opens the drill-down drawer with the quality panel.
    const historicalTab = wrapper.findAll('.source-tab').find((el) => el.text().includes(tt('evaluation.stream.historicalTab')))
    await historicalTab!.trigger('click')
    const note = wrapper.findAll('.eval-item').find((el) => el.text().includes('历史笔记'))
    expect(note).toBeTruthy()
    await note!.trigger('click')
    expect(document.body.querySelector('[data-testid="note-quality-panel"]')).toBeTruthy()
  })

  it('applies decision filters only inside workflow review tab', async () => {
    const { getEvaluationList, getEvaluationTrend } = await import('@/api/evaluation')
    const { listAccounts } = await import('@/api/accounts')
    const { getCreatorStats } = await import('@/api/analytics')
    ;(getEvaluationList as any).mockResolvedValue({ workflows: [workflowRow], total: 1 })
    ;(getEvaluationTrend as any).mockResolvedValue({ db_ready: true, points: [], dim_averages: {} })
    ;(listAccounts as any).mockResolvedValue([{ id: 'acc-1', name: '测试账号', is_active: true }])
    ;(getCreatorStats as any).mockResolvedValue({ notes: [noteRow] })

    const wrapper = await mountEval({}, { tab: 'workflow' })
    expect(wrapper.findAll('.item-title').map((el) => el.text())).not.toContain('历史笔记')
    const approvedChip = wrapper.findAll('.filter-chip').find((el) => el.text().includes(tt('evaluation.decision.approved')))
    await approvedChip!.trigger('click')
    const titles = wrapper.findAll('.item-title').map((el) => el.text())
    expect(titles).not.toContain('历史笔记')
    expect(titles).toContain('工作流笔记')
  })
})
