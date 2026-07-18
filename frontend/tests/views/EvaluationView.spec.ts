// EV-17: EvaluationView view-level acceptance tests.
// Covers: detail deep-link context (EV-01), decision action CTA (EV-03),
// no-score rendering as '—' not 0 (EV-05), trend three states (EV-02).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import EvaluationView from '@/views/EvaluationView.vue'
import i18n from '@/locales'

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
    global: { plugins: [router], stubs: { TrendChart: { template: '<div />' }, EvaluationRadar: { template: '<div />' }, CreatorQualityWorkspace: { template: '<div />' } } },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

describe('EvaluationView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
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
    ;(getEvaluationList as any).mockResolvedValue({ workflows: [], total: 0 })
    ;(getEvaluationTrend as any).mockRejectedValue(new Error('network'))
    const wrapper = await mountEval({}, { tab: 'workflow' })
    // loadTrend fires from the activeTab watcher after mount; let it reject.
    for (let i = 0; i < 5; i++) await flushPromises()
    expect(wrapper.text()).toContain(tt('evaluation.trend.failed'))
    expect(wrapper.text()).toContain(tt('evaluation.trend.retry'))
  })
})
