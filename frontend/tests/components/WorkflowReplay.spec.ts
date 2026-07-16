import { describe, expect, it, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import WorkflowReplay from '@/views/WorkflowReplay.vue'

const routerMock = vi.hoisted(() => ({
  push: vi.fn(() => Promise.resolve()),
  replace: vi.fn(() => Promise.resolve()),
  resolve: vi.fn(() => ({ href: '/replay/thread-1' })),
}))
const routeMock = vi.hoisted(() => ({ params: { threadId: 'thread-1' }, query: {} as Record<string, string> }))
const getWorkflowStatusMock = vi.hoisted(() => vi.fn())
const workflowStoreMock = vi.hoisted(() => ({
  replayCheckpoints: [] as unknown[],
  replayCheckpointsError: null as string | null,
  isLoadingCheckpoints: false,
  hasMoreCheckpoints: false,
  workflowStates: new Map<string, unknown>(),
  setThreadId: vi.fn(),
  hydrateReplayCache: vi.fn(() => null),
  saveReplayLiveState: vi.fn(),
  clearReplaySnapshot: vi.fn(),
  enterReplayMode: vi.fn(),
  exitReplayMode: vi.fn(),
  selectCheckpoint: vi.fn(),
  loadMoreCheckpoints: vi.fn(() => Promise.resolve()),
}))
const authStoreMock = vi.hoisted(() => ({ isAuthenticated: false }))
const toastStoreMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))

vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => routeMock,
}))
vi.mock('@/api/workflow', () => ({ getWorkflowStatus: getWorkflowStatusMock }))
vi.mock('@/stores', () => ({
  useWorkflowStore: () => workflowStoreMock,
  useAuthStore: () => authStoreMock,
  useToastStore: () => toastStoreMock,
}))
vi.mock('@/composables/useWorkflowReplay', () => ({
  useWorkflowReplay: () => ({
    activeCheckpointId: ref<string | null>(null),
    replayCheckpoints: ref<unknown[]>([]),
    liveWorkflowState: ref(null),
    workflowLabel: ref(''),
    workflowMode: ref<'trend' | 'brief'>('trend'),
    pipelineSteps: ref<string[]>([]),
    selectedCheckpoint: ref(null),
    selectedAgent: ref(''),
    resolvedShootingPlan: ref(null),
    getNodeStatus: vi.fn(() => 'pending'),
    handleNodeClick: vi.fn(),
    isNodeSelected: vi.fn(() => false),
    hasDataForAgent: vi.fn(() => false),
    hasMeaningfulData: vi.fn(() => false),
    formatDate: vi.fn(() => ''),
    workflowStatus: ref('idle'),
    workflowProgress: ref(0),
    hasCheckpointForPhase: vi.fn(() => false),
  }),
}))

describe('WorkflowReplay initial loading', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    workflowStoreMock.workflowStates.clear()
    workflowStoreMock.enterReplayMode.mockReset()
    getWorkflowStatusMock.mockReset()
  })

  it('starts live status and checkpoint history requests together', async () => {
    let resolveStatus!: (value: unknown) => void
    let resolveHistory!: () => void
    getWorkflowStatusMock.mockReturnValue(new Promise((resolve) => { resolveStatus = resolve }))
    workflowStoreMock.enterReplayMode.mockReturnValue(new Promise<void>((resolve) => { resolveHistory = resolve }))

    const wrapper = mount(WorkflowReplay, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
          CheckpointRail: { template: '<div />' },
        },
      },
    })

    await flushPromises()
    expect(getWorkflowStatusMock).toHaveBeenCalledWith('thread-1', { suppressToast: true })
    expect(workflowStoreMock.enterReplayMode).toHaveBeenCalledWith(undefined)

    resolveStatus({ thread_id: 'thread-1', status: 'completed', phase: 'completed', progress_percent: 100 })
    resolveHistory()
    await flushPromises()
    expect(workflowStoreMock.saveReplayLiveState).toHaveBeenCalledWith('thread-1', expect.objectContaining({ status: 'completed' }))
    expect(workflowStoreMock.exitReplayMode).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
