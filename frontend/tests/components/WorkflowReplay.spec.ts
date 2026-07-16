import { describe, expect, it, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import WorkflowReplay from '@/views/WorkflowReplay.vue'

const routerMock = vi.hoisted(() => ({
  push: vi.fn(() => Promise.resolve()),
  replace: vi.fn(() => Promise.resolve()),
  resolve: vi.fn(() => ({ href: '/replay/case-1' })),
}))
const routeMock = vi.hoisted(() => ({ params: { publicId: 'case-1' }, query: {} as Record<string, string>, fullPath: '/replay/case-1' }))
const getManifestMock = vi.hoisted(() => vi.fn())
const getCheckpointMock = vi.hoisted(() => vi.fn())
const getSummaryMock = vi.hoisted(() => vi.fn())

vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => routeMock,
}))
vi.mock('@/api/publicShowcase', () => ({
  getPublicReplayManifest: getManifestMock,
  getPublicReplayCheckpoint: getCheckpointMock,
  getPublicFinalSummary: getSummaryMock,
}))
vi.mock('@/stores', () => ({
  useAuthStore: () => ({ isAuthenticated: false, isInitialized: true, initialize: vi.fn() }),
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ isAuthenticated: false, isInitialized: true, initialize: vi.fn() }),
}))

const steps = [
  { public_id: 'step-1', step: 1, phase: 'scouting', title: '趋势洞察', summary: '找到方向', created_at: null, has_result: true, result_kind: 'scouting', result: { topic: '测试主题' } },
  { public_id: 'step-2', step: 2, phase: 'creating', title: '内容产出', summary: '完成标题和正文', created_at: null, has_result: true, result_kind: 'creating', result: { title: '测试标题', summary: '测试产出' } },
]

describe('WorkflowReplay public UX contract', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    routeMock.params = { publicId: 'case-1' }
    routeMock.query = {}
    getManifestMock.mockResolvedValue({
      public_id: 'case-1',
      view: 'key',
      steps,
      offset: 0,
      limit: 20,
      total_steps: steps.length,
      key_step_count: steps.length,
      technical_step_count: steps.length,
      has_more: false,
      technical_steps_available: false,
      workflow: {
        public_id: 'case-1',
        title: '公开案例',
        summary: '案例摘要',
        status: 'completed',
        phase: 'completed',
        workflow_mode: 'trend',
        created_at: '2026-07-16T10:00:00Z',
        updated_at: '2026-07-16T10:00:00Z',
        featured: true,
        replay_available: true,
        result_preview: { title: '测试标题' },
      },
    })
    getCheckpointMock.mockImplementation(async (_publicId: string, stepId: string) => steps.find(step => step.public_id === stepId))
    getSummaryMock.mockResolvedValue({ public_id: 'case-1', status: 'completed', result: { title: '最终标题' }, stable: true })
  })

  it('loads the public manifest and first result together', async () => {
    const wrapper = mount(WorkflowReplay, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
          PublicReplayResult: { template: '<div class="public-result-stub" />' },
          ThemeToggle: { template: '<button aria-label="theme" />' },
        },
      },
    })

    await flushPromises()
    expect(getManifestMock).toHaveBeenCalledWith('case-1', false, expect.objectContaining({ suppressToast: true, limit: 20, offset: 0, signal: expect.any(AbortSignal) }))
    expect(getCheckpointMock).toHaveBeenCalledWith('case-1', 'step-1', false, expect.objectContaining({ suppressToast: true, signal: expect.any(AbortSignal) }))
    expect(wrapper.find('#replay-steps-heading').exists()).toBe(true)
    expect(wrapper.findAll('[data-step-id][aria-current="step"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-phase-index]')).toHaveLength(2)
    expect(wrapper.find('[data-phase-index="0"]').attributes('tabindex')).toBe('0')
    expect(wrapper.find('[data-phase-index="1"]').attributes('tabindex')).toBe('-1')
  })

  it('moves to the next key step and updates the deep link', async () => {
    const wrapper = mount(WorkflowReplay, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
          PublicReplayResult: { template: '<div />' },
          ThemeToggle: { template: '<button aria-label="theme" />' },
        },
      },
    })
    await flushPromises()

    const next = wrapper.findAll('button').find(button => button.text().includes('下一步'))
    await next?.trigger('click')
    await flushPromises()
    expect(routerMock.replace).toHaveBeenCalledWith({ query: { step: 'step-2' } })
    expect(getCheckpointMock).toHaveBeenLastCalledWith('case-1', 'step-2', false, expect.objectContaining({ suppressToast: true, signal: expect.any(AbortSignal) }))
  })

  it('renders the selected result before a slow URL update completes', async () => {
    let resolveRoute!: () => void
    const routeUpdate = new Promise<void>(resolve => { resolveRoute = resolve })
    routerMock.replace.mockReturnValueOnce(routeUpdate)
    const wrapper = mount(WorkflowReplay, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
          PublicReplayResult: { template: '<div />' },
          ThemeToggle: { template: '<button aria-label="theme" />' },
        },
      },
    })
    await flushPromises()

    const next = wrapper.findAll('button').find(button => button.text().includes('下一步'))
    let selectionSettled = false
    const selection = next!.trigger('click').then(() => { selectionSettled = true })
    await flushPromises()

    expect(wrapper.find('#step-detail-heading').text()).toContain('内容产出')
    expect(selectionSettled).toBe(true)
    resolveRoute()
    await selection
  })

  it('paginates replay steps and keeps the first page visible while loading more', async () => {
    const firstPage = {
      public_id: 'case-1',
      view: 'key' as const,
      steps: [steps[0]],
      offset: 0,
      limit: 1,
      total_steps: 2,
      key_step_count: 2,
      technical_step_count: 2,
      has_more: true,
      technical_steps_available: false,
      workflow: {
        public_id: 'case-1',
        title: '公开案例',
        summary: '案例摘要',
        status: 'completed' as const,
        phase: 'completed',
        workflow_mode: 'trend' as const,
        created_at: '2026-07-16T10:00:00Z',
        updated_at: '2026-07-16T10:00:00Z',
        featured: true,
        replay_available: true,
        result_preview: { title: '测试标题' },
      },
    }
    const secondPage = { ...firstPage, steps: [steps[1]], offset: 1, has_more: false }
    getManifestMock.mockImplementation(async (_publicId: string, _technical: boolean, options: { offset?: number }) => options.offset ? secondPage : firstPage)

    const wrapper = mount(WorkflowReplay, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
          PublicReplayResult: { template: '<div />' },
          ThemeToggle: { template: '<button aria-label="theme" />' },
        },
      },
    })
    await flushPromises()
    expect(wrapper.findAll('[data-step-id]')).toHaveLength(1)

    const loadMore = wrapper.findAll('button').find(button => button.text().includes('加载更多'))
    await loadMore?.trigger('click')
    await flushPromises()

    expect(getManifestMock).toHaveBeenLastCalledWith('case-1', false, expect.objectContaining({ suppressToast: true, limit: 20, offset: 1, signal: expect.any(AbortSignal) }))
    expect(wrapper.findAll('[data-step-id]')).toHaveLength(2)
    expect(wrapper.find('[data-step-id="step-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-step-id="step-2"]').exists()).toBe(true)
  })
})
