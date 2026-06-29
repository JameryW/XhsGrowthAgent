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

describe('workflow store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
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
})
