// Fail-closed pause on Review: human CTAs even when review_gate payload is gone.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { nextTick } from 'vue'
import Review from '@/views/Review.vue'
import i18n from '@/locales'
import { useAccountsStore } from '@/stores/accounts'

const tt = (key: string) => String(i18n.global.t(key))

vi.mock('@/api/workflow', () => ({
  listWorkflows: vi.fn().mockResolvedValue({ workflows: [], total: 0 }),
  getWorkflowStatus: vi.fn().mockResolvedValue({
    thread_id: 'thr-fail-closed',
    account_id: 'acc-1',
    phase: 'paused',
    status: 'paused',
    pause_reason: 'evaluator_fail_closed',
    progress_percent: 85,
    next_steps: [],
    agent_timeline: [],
    label: 'fail-closed',
    dry_run: false,
    auto_publish: false,
    workflow_mode: 'trend',
    created_at: '2026-10-27T00:00:00Z',
    updated_at: '2026-10-27T00:00:00Z',
  }),
  uploadImages: vi.fn(),
  resumeWorkflow: vi.fn().mockResolvedValue({
    status: 'running',
    human_decision: 'approve',
    message: '人工已批准继续发布',
  }),
}))

vi.mock('@/api/review', () => ({
  getPendingReview: vi.fn().mockRejectedValue({ code: 'ERROR_REVIEW_NOT_PENDING', message: 'not pending' }),
  updateCopy: vi.fn(),
  submitReview: vi.fn(),
}))

vi.mock('@/api/evaluation', () => ({
  getEvaluationResult: vi.fn().mockResolvedValue({
    thread_id: 'thr-fail-closed',
    has_evaluation: true,
    evaluation_result: {
      overall_score: 55,
      dimensions: [],
      decision: 'needs_revision',
      revision_hints: ['tighten hook'],
      bias_warning: '',
      summary: 'advisory',
    },
  }),
}))

vi.mock('@/api/accounts', () => ({
  listAccounts: vi.fn().mockResolvedValue([{ id: 'acc-1', name: 'A1', is_active: true }]),
  getActiveAccount: vi.fn().mockResolvedValue({ id: 'acc-1', name: 'A1', is_active: true }),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
}))

vi.mock('@/utils/routePrefetch', () => ({
  navigateToStart: vi.fn(),
  prefetchStartWorkspace: vi.fn(),
}))

vi.mock('@/stores/crossAccountHints', () => ({
  useCrossAccountHintsStore: () => ({
    reviewAwaitingTotals: {},
    refreshReviewAwaitingTotals: vi.fn().mockResolvedValue(undefined),
    setReviewAwaitingTotals: vi.fn(),
  }),
}))

describe('Review evaluator fail-closed CTAs', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('surfaces human-decision CTAs for deep-linked fail-closed without pending review', async () => {
    const accounts = useAccountsStore()
    await accounts.fetchAccounts({ force: true })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/review/:threadId?', name: 'review', component: Review },
        { path: '/start', name: 'start', component: { template: '<div />' } },
      ],
    })
    await router.push({ name: 'review', params: { threadId: 'thr-fail-closed' }, query: { account: 'acc-1' } })
    await router.isReady()

    const wrapper = mount(Review, {
      global: {
        plugins: [router],
        stubs: {
          AppIcon: true,
          PageHeader: true,
          ConfirmModal: true,
          CelebrationEffect: true,
          WorkflowCardBody: true,
          AccountScopeBar: true,
          AccountViewNotice: true,
          EvaluationRadar: true,
          ReviewSkeleton: true,
          NeonButton: {
            props: ['loading', 'disabled', 'title', 'ariaLabel'],
            emits: ['click'],
            template: '<button type="button" :aria-label="ariaLabel" :title="title" @click="$emit(\'click\')"><slot /></button>',
          },
        },
      },
    })

    await flushPromises()
    await nextTick()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain(tt('dashboard.actionButtons.evaluatorGateHint'))
    expect(text).toContain(tt('dashboard.actionButtons.evaluatorGateApprove'))
    expect(text).toContain(tt('dashboard.actionButtons.evaluatorGateRevise'))
    expect(text).not.toContain(tt('review.emptyState.notReached'))
    expect(text.toLowerCase()).not.toContain('override')
    expect(text).not.toContain('质量门')
  })
})
