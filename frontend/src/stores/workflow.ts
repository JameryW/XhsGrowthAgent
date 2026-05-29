import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as workflowApi from '@/api/workflow'
import type { WorkflowStateResponse, WorkflowPhase } from '@/types/workflow'
import { useRealtimeStore } from './realtime'
import { useToastStore } from './toast'
import { useOfflineStore } from './offline'
import { EventType } from '@/realtime/events'
import { useLoading } from '@/composables/useLoading'
import i18n from '@/locales'

const { t } = i18n.global

export const useWorkflowStore = defineStore('workflow', () => {
  // State - restore threadId from localStorage
  const currentThreadId = ref<string | null>(localStorage.getItem('currentThreadId'))
  const workflowState = ref<WorkflowStateResponse | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const progressPercent = ref(0)
  const isOverlayLoading = ref(false)

  // Computed
  const currentPhase = computed<WorkflowPhase>(() =>
    workflowState.value?.phase || 'idle'
  )

  const nextNodes = computed(() => workflowState.value?.next_steps || [])

  const isRunning = computed(() =>
    (workflowState.value?.next_steps?.length ?? 0) > 0 && currentPhase.value !== 'completed'
  )

  const trendData = computed(() => (workflowState.value as any)?.trend_data || {})
  const contentPlan = computed(() => (workflowState.value as any)?.content_plan || {})
  const copyContent = computed(() => (workflowState.value as any)?.copy_content || {})
  const visualPlan = computed(() => (workflowState.value as any)?.visual_plan || {})
  const agentTimeline = computed(() => workflowState.value?.agent_timeline || [])

  // Structured publish error info (when publish fails)
  const publishError = computed(() => {
    const pr = (workflowState.value as any)?.publish_result
    if (!pr || pr.status !== 'failed') return null
    return {
      message: pr.error || '发布失败',
      type: pr.error_type || 'unknown',
      recovery: pr.recovery || null,
    }
  })

  // Dependencies
  const realtimeStore = useRealtimeStore()
  const toastStore = useToastStore()
  const offlineStore = useOfflineStore()
  const { phaseToPercent, isOverlayPhase } = useLoading()

  /**
   * Update progress percent and overlay loading state from phase.
   * Uses backend progress_percent when available, falls back to local mapping.
   */
  function updateProgressFromPhase(phase: WorkflowPhase, backendProgress?: number) {
    progressPercent.value = backendProgress ?? phaseToPercent(phase)
    isOverlayLoading.value = isOverlayPhase(phase)
  }

  // WebSocket event handlers
  realtimeStore.wsService.onEvent(EventType.WORKFLOW_PHASE_CHANGED, (payload: unknown) => {
    const p = payload as { thread_id?: string; old_phase?: string; new_phase?: string; current_agent?: string }
    if (p.thread_id === currentThreadId.value && workflowState.value) {
      const newPhase = p.new_phase || workflowState.value.phase
      workflowState.value = {
        ...workflowState.value,
        phase: newPhase as WorkflowPhase,
        current_agent: p.current_agent,
      }
      // Update progress and overlay state
      updateProgressFromPhase(newPhase as WorkflowPhase)
      // Special notification for reviewing phase - requires user action
      if (newPhase === 'reviewing') {
        toastStore.info(t('workflow.awaitingReview'), t('workflow.awaitingReviewMessage'))
      } else {
        toastStore.info(`${t('workflow.phaseChange')}: ${p.old_phase} → ${newPhase}`, `${t('workflow.currentAgent')}: ${p.current_agent}`)
      }
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_DATA_UPDATED, (payload: unknown) => {
    const p = payload as { thread_id?: string; data_type?: string; data?: unknown }
    if (p.thread_id === currentThreadId.value && workflowState.value && p.data_type && p.data) {
      // Store data updates in a separate object since backend doesn't return values
      ;(workflowState.value as any)[p.data_type] = p.data
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_COMPLETED, (payload: unknown) => {
    const p = payload as { thread_id?: string }
    if (p.thread_id === currentThreadId.value && workflowState.value) {
      workflowState.value = {
        ...workflowState.value,
        phase: 'completed',
        next_steps: [],
      }
      updateProgressFromPhase('completed')
      toastStore.success(t('workflow.completed'), `${t('workflow.thread')}: ${p.thread_id}`)
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_ERROR, (payload: unknown) => {
    const p = payload as { thread_id?: string; error?: string; agent?: string }
    if (p.thread_id === currentThreadId.value && workflowState.value) {
      workflowState.value = {
        ...workflowState.value,
        phase: 'error',
        error: p.error,
      }
      updateProgressFromPhase('error')
      toastStore.error(t('workflow.error'), `${t('workflow.currentAgent')}: ${p.agent} - ${p.error}`)
    }
  })

  // Actions
  async function startWorkflow(accountId: string, phase: WorkflowPhase = 'scouting', options?: { dryRun?: boolean; autoPublish?: boolean; topic?: string; niche?: string }) {
    // Check offline status
    if (!offlineStore.isOnline) {
      offlineStore.queueAction(
        `start-${accountId}`,
        async () => {
          await startWorkflow(accountId, phase, options)
        },
        t('nav.startWorkflow')
      )
      return { thread_id: 'pending', status: 'queued' }
    }

    isLoading.value = true
    error.value = null
    try {
      const result = await workflowApi.startWorkflow({
        account_id: accountId,
        phase,
        dry_run: options?.dryRun,
        auto_publish: options?.autoPublish,
        topic: options?.topic,
        niche: options?.niche,
      })
      currentThreadId.value = result.thread_id
      localStorage.setItem('currentThreadId', result.thread_id)
      updateProgressFromPhase(phase)
      await refreshStatus()
      // Connect WebSocket and subscribe
      realtimeStore.connect()
      realtimeStore.subscribeWorkflow(result.thread_id)
      toastStore.success(t('workflow.startSuccess'), `${t('workflow.thread')}: ${result.thread_id}`)
      return result
    } catch (e: any) {
      error.value = e.message
      toastStore.error(t('workflow.startFailed'), e.message)
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function refreshStatus() {
    if (!currentThreadId.value) return
    // Skip if offline, queue for later
    if (!offlineStore.isOnline) {
      offlineStore.queueAction(
        `refresh-${currentThreadId.value}`,
        async () => {
          await refreshStatus()
        },
        t('workflow.statusRefreshFailed')
      )
      return
    }

    isLoading.value = true
    error.value = null
    try {
      workflowState.value = await workflowApi.getWorkflowStatus(currentThreadId.value)
      // Use backend progress_percent when available, fallback to local mapping
      const phase = workflowState.value?.phase || 'idle'
      const backendProgress = workflowState.value?.progress_percent
      updateProgressFromPhase(phase as WorkflowPhase, backendProgress)
    } catch (e: any) {
      // Workflow not found — clear stale threadId silently
      if (e.code === 'ERROR_WORKFLOW_NOT_FOUND' || e.message?.includes('not found')) {
        currentThreadId.value = null
        workflowState.value = null
        localStorage.removeItem('currentThreadId')
        updateProgressFromPhase('idle')
      } else {
        error.value = e.message
        toastStore.warning(t('workflow.statusRefreshFailed'), e.message)
      }
    } finally {
      isLoading.value = false
    }
  }

  async function pauseWorkflow() {
    if (!currentThreadId.value) return
    isLoading.value = true
    try {
      realtimeStore.unsubscribeWorkflow(currentThreadId.value)
      await workflowApi.pauseWorkflow(currentThreadId.value)
      await refreshStatus()
      toastStore.info(t('workflow.paused'), `${t('workflow.thread')}: ${currentThreadId.value}`)
    } catch (e: any) {
      error.value = e.message
      toastStore.error(t('workflow.pauseFailed'), e.message)
    } finally {
      isLoading.value = false
    }
  }

  async function resumeWorkflow() {
    if (!currentThreadId.value) return
    isLoading.value = true
    try {
      const result = await workflowApi.resumeWorkflow(currentThreadId.value)
      await refreshStatus()
      realtimeStore.subscribeWorkflow(currentThreadId.value)
      toastStore.success(t('workflow.resumed'), `${t('workflow.currentPhase')}: ${workflowState.value?.phase}`)
      return result
    } catch (e: any) {
      error.value = e.message
      toastStore.error(t('workflow.resumeFailed'), e.message)
    } finally {
      isLoading.value = false
    }
  }

  async function cancelWorkflow() {
    if (!currentThreadId.value) return
    isLoading.value = true
    try {
      realtimeStore.unsubscribeWorkflow(currentThreadId.value)
      await workflowApi.cancelWorkflow(currentThreadId.value)
      workflowState.value = {
        ...workflowState.value,
        phase: 'cancelled',
        next_steps: [],
      } as WorkflowStateResponse
      updateProgressFromPhase('cancelled')
      toastStore.info(t('workflow.paused'), `${t('workflow.thread')}: ${currentThreadId.value}`)
    } catch (e: any) {
      error.value = e.message
      toastStore.error('取消失败', e.message)
    } finally {
      isLoading.value = false
      isOverlayLoading.value = false
    }
  }

  // Polling
  let pollInterval: number | null = null

  function startPolling(intervalMs: number = 5000) {
    if (pollInterval) stopPolling()
    pollInterval = window.setInterval(() => {
      if (isRunning.value) {
        refreshStatus()
      } else {
        stopPolling()
      }
    }, intervalMs)
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }

  function setThreadId(threadId: string) {
    currentThreadId.value = threadId
  }

  return {
    currentThreadId,
    workflowState,
    isLoading,
    error,
    progressPercent,
    isOverlayLoading,
    currentPhase,
    nextNodes,
    isRunning,
    trendData,
    contentPlan,
    copyContent,
    visualPlan,
    agentTimeline,
    publishError,
    startWorkflow,
    refreshStatus,
    pauseWorkflow,
    resumeWorkflow,
    cancelWorkflow,
    startPolling,
    stopPolling,
    setThreadId,
    updateProgressFromPhase,
  }
})