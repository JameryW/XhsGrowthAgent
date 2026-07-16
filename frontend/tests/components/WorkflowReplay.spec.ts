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

const steps = [
  { public_id: 'step-1', step: 1, phase: 'scouting', title: '趋势洞察', summary: '找到方向', created_at: null, has_result: true, result_kind: 'scouting', result: { topic: '测试主题' } },
  { public_id: 'step-2', step: 2, phase: 'creating', title: '内容产出', summary: '完成标题和正文', created_at: null, has_result: true, result_kind: 'creating', result: { title: '测试标题', summary: '测试产出' } },
]

describe('WorkflowReplay public UX contract', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeMock.params = { publicId: 'case-1' }
    routeMock.query = {}
    getManifestMock.mockResolvedValue({
      public_id: 'case-1',
      view: 'key',
      steps,
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
        },
      },
    })

    await flushPromises()
    expect(getManifestMock).toHaveBeenCalledWith('case-1', false, { suppressToast: true })
    expect(getCheckpointMock).toHaveBeenCalledWith('case-1', 'step-1', false, { suppressToast: true })
    expect(wrapper.find('#replay-steps-heading').exists()).toBe(true)
    expect(wrapper.findAll('[aria-current="step"]')).toHaveLength(1)
  })

  it('moves to the next key step and updates the deep link', async () => {
    const wrapper = mount(WorkflowReplay, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
          PublicReplayResult: { template: '<div />' },
        },
      },
    })
    await flushPromises()

    const next = wrapper.findAll('button').find(button => button.text().includes('下一步'))
    await next?.trigger('click')
    await flushPromises()
    expect(routerMock.replace).toHaveBeenCalledWith({ query: { step: 'step-2' } })
    expect(getCheckpointMock).toHaveBeenLastCalledWith('case-1', 'step-2', false, { suppressToast: true })
  })
})
