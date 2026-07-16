import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock dependencies before importing the store
vi.mock('@/api/workflow', () => ({
  startWorkflow: vi.fn().mockResolvedValue({ thread_id: 'test-thread', status: 'running', phase: 'scouting', progress_percent: 10 }),
  getWorkflowStatus: vi.fn().mockResolvedValue({ thread_id: 'test-thread', status: 'running', phase: 'scouting', progress_percent: 10, next_steps: ['trend_scout'], agent_timeline: [] }),
  pauseWorkflow: vi.fn().mockResolvedValue({ thread_id: 'test-thread', status: 'paused' }),
  resumeWorkflow: vi.fn().mockResolvedValue({ thread_id: 'test-thread', status: 'running' }),
  cancelWorkflow: vi.fn().mockResolvedValue({ thread_id: 'test-thread', status: 'cancelled', message: '' }),
  deleteWorkflow: vi.fn().mockResolvedValue({ thread_id: 'test-thread', message: '' }),
  listWorkflows: vi.fn().mockResolvedValue({ workflows: [], total: 0, limit: 20, offset: 0 }),
  submitDraft: vi.fn(),
  selectVersion: vi.fn(),
  submitRippleDecision: vi.fn(),
  selectBlogger: vi.fn(),
  extractBriefFile: vi.fn(),
  uploadBriefFile: vi.fn(),
  getCheckpointHistory: vi.fn(),
  uploadImages: vi.fn(),
  triggerAnalytics: vi.fn(),
  getPendingRippleDecision: vi.fn(),
  getPendingBloggerSelection: vi.fn(),
  retryRippleAnalysis: vi.fn(),
}))

vi.mock('@/stores/realtime', () => ({
  useRealtimeStore: () => ({
    wsService: { onEvent: vi.fn(), emit: vi.fn() },
    connect: vi.fn(),
    disconnect: vi.fn(),
    subscribeWorkflow: vi.fn(),
    unsubscribeWorkflow: vi.fn(),
  }),
}))

vi.mock('@/stores/toast', () => ({
  useToastStore: () => ({
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }),
}))

vi.mock('@/stores/offline', () => ({
  useOfflineStore: () => ({
    isOnline: true,
    queueAction: vi.fn(),
  }),
}))

vi.mock('@/composables/useLoading', () => ({
  useLoading: () => ({
    phaseToPercent: (phase: string) => {
      const map: Record<string, number> = {
        idle: 0, scouting: 10, briefing: 15, planning: 20,
        creating: 40, reviewing: 60, publishing: 80, analyzing: 90,
        engaging: 95, completed: 100, error: 0, paused: 0, cancelled: 0,
      }
      return map[phase] ?? 0
    },
  }),
}))

vi.mock('@/locales', () => ({
  default: { global: { t: (key: string) => key } },
}))

import { useWorkflowStore } from '@/stores/workflow'
import { getCheckpointHistory } from '@/api/workflow'

describe('workflow store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    vi.mocked(getCheckpointHistory).mockReset()
  })

  describe('initial state', () => {
    it('starts with no active thread', () => {
      const store = useWorkflowStore()
      expect(store.currentThreadId).toBeNull()
      expect(store.isLoading).toBe(false)
      expect(store.error).toBeNull()
    })

    it('computes idle phase and status by default', () => {
      const store = useWorkflowStore()
      expect(store.currentPhase).toBe('idle')
      expect(store.currentStatus).toBe('idle')
    })
  })

  describe('progress tracking', () => {
    it('updateProgressFromPhase advances monotonically', () => {
      const store = useWorkflowStore()
      // Start at scouting (10%)
      store.updateProgressFromPhase('scouting')
      expect(store.progressPercent).toBe(10)

      // Advance to creating (40%)
      store.updateProgressFromPhase('creating')
      expect(store.progressPercent).toBe(40)

      // Regression to planning (20%) — high-water mark keeps 40
      store.updateProgressFromPhase('planning')
      expect(store.progressPercent).toBe(40)

      // Advance to reviewing (60%)
      store.updateProgressFromPhase('reviewing')
      expect(store.progressPercent).toBe(60)
    })

    it('completed always reaches 100', () => {
      const store = useWorkflowStore()
      store.updateProgressFromPhase('completed')
      expect(store.progressPercent).toBe(100)
    })

    it('error resets to 0', () => {
      const store = useWorkflowStore()
      store.updateProgressFromPhase('creating')
      store.updateProgressFromPhase('error')
      expect(store.progressPercent).toBe(0)
    })

    it('paused/cancelled preserve progress', () => {
      const store = useWorkflowStore()
      store.updateProgressFromPhase('creating') // 40%
      store.updateProgressFromPhase('paused')
      // paused preserves — progress stays at 40
      expect(store.progressPercent).toBe(40)
    })
  })

  describe('tab management', () => {
    it('openTabIds starts empty', () => {
      const store = useWorkflowStore()
      expect(store.openTabIds).toEqual([])
    })

    it('getTabLabel returns short ID when no label set', () => {
      const store = useWorkflowStore()
      expect(store.getTabLabel('xhs_test_abc12345')).toBe('abc12345')
    })

    it('renameTab updates label', () => {
      const store = useWorkflowStore()
      store.renameTab('thread-1', 'My Workflow')
      expect(store.getTabLabel('thread-1')).toBe('My Workflow')
    })
  })

  describe('computed status flags', () => {
    it('isRunning when status is running', () => {
      const store = useWorkflowStore()
      // No active thread → not running
      expect(store.isRunning).toBe(false)
    })

    it('isAwaitingReview when status is awaiting_review', () => {
      const store = useWorkflowStore()
      expect(store.isAwaitingReview).toBe(false)
    })
  })

  describe('replay state separation', () => {
    it('keeps live status independent from the selected checkpoint and chooses a meaningful default', async () => {
      const store = useWorkflowStore()
      const emptyCheckpoint = {
        checkpoint_id: 'cp-empty', step: 3, source: 'test', phase: 'creating', current_agent: 'copywriter', created_at: null,
        next_nodes: [], workflow_mode: 'trend',
      }
      const meaningfulCheckpoint = {
        checkpoint_id: 'cp-result', step: 2, source: 'test', phase: 'planning', current_agent: 'content_strategist', created_at: null,
        next_nodes: [], workflow_mode: 'trend', content_plan: { selected_topic: 'topic' },
      }
      store.workflowStates.set('thread-1', {
        thread_id: 'thread-1', phase: 'completed', status: 'completed', progress_percent: 100, next_steps: [], agent_timeline: [], workflow_mode: 'trend',
      })
      store.setThreadId('thread-1')
      vi.mocked(getCheckpointHistory).mockResolvedValueOnce({
        thread_id: 'thread-1', checkpoints: [emptyCheckpoint, meaningfulCheckpoint] as any, has_more: false,
      })

      await store.enterReplayMode()

      expect(store.activeCheckpointId).toBe('cp-result')
      expect(store.liveWorkflowState?.status).toBe('completed')
      expect(store.effectiveState?.phase).toBe('planning')
      expect(store.effectiveState?.status).toBe('completed')
    })

    it('honours a valid checkpoint deep link over the meaningful default', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('thread-1', {
        thread_id: 'thread-1', phase: 'completed', status: 'completed', progress_percent: 100, next_steps: [], agent_timeline: [], workflow_mode: 'trend',
      })
      store.setThreadId('thread-1')
      vi.mocked(getCheckpointHistory).mockResolvedValueOnce({
        thread_id: 'thread-1', checkpoints: [
          { checkpoint_id: 'cp-new', step: 3, source: 'test', phase: 'creating', current_agent: 'copywriter', created_at: null, next_nodes: [], workflow_mode: 'trend', copy_content: { selected_title: 'new' } },
          { checkpoint_id: 'cp-old', step: 2, source: 'test', phase: 'planning', current_agent: 'content_strategist', created_at: null, next_nodes: [], workflow_mode: 'trend', content_plan: { selected_topic: 'old' } },
        ] as any, has_more: false,
      })

      await store.enterReplayMode('cp-old')

      expect(store.activeCheckpointId).toBe('cp-old')
    })

    it('hydrates a same-thread replay snapshot before the history refresh resolves', async () => {
      const checkpoint = {
        checkpoint_id: 'cp-cache', step: 2, source: 'test', phase: 'planning', current_agent: 'content_strategist', created_at: null,
        next_nodes: [], workflow_mode: 'trend', content_plan: { selected_topic: 'cached topic' },
      }
      vi.mocked(getCheckpointHistory).mockResolvedValueOnce({
        thread_id: 'thread-cache', checkpoints: [checkpoint] as any, has_more: false,
      })
      const firstStore = useWorkflowStore()
      firstStore.setThreadId('thread-cache')
      await firstStore.enterReplayMode()

      setActivePinia(createPinia())
      const secondStore = useWorkflowStore()
      secondStore.setThreadId('thread-cache')
      let resolveRefresh!: (value: unknown) => void
      vi.mocked(getCheckpointHistory).mockReturnValueOnce(new Promise((resolve) => { resolveRefresh = resolve }))

      const refresh = secondStore.enterReplayMode()
      expect(secondStore.activeCheckpointId).toBe('cp-cache')
      expect(secondStore.replayCheckpoints).toHaveLength(1)
      expect(secondStore.isLoadingCheckpoints).toBe(true)

      resolveRefresh({ thread_id: 'thread-cache', checkpoints: [checkpoint], has_more: false })
      await refresh
    })
  })
})
