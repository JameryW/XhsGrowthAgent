import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as workflowApi from '@/api/workflow'
import type { WorkflowStateResponse, WorkflowPhase } from '@/types/workflow'
import { useRealtimeStore } from './realtime'
import { EventType } from '@/realtime/events'

export const useWorkflowStore = defineStore('workflow', () => {
  // State
  const currentThreadId = ref<string | null>(null)
  const workflowState = ref<WorkflowStateResponse | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Computed
  const currentPhase = computed<WorkflowPhase>(() =>
    workflowState.value?.values?.phase || 'idle'
  )

  const nextNodes = computed(() => workflowState.value?.next || [])

  const isRunning = computed(() =>
    (workflowState.value?.next?.length ?? 0) > 0 && currentPhase.value !== 'completed'
  )

  const trendData = computed(() => workflowState.value?.values?.trend_data || {})
  const contentPlan = computed(() => workflowState.value?.values?.content_plan || {})
  const copyContent = computed(() => workflowState.value?.values?.copy_content || {})
  const visualPlan = computed(() => workflowState.value?.values?.visual_plan || {})

  // WebSocket event handlers
  const realtimeStore = useRealtimeStore()

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_PHASE_CHANGED, (payload: unknown) => {
    const p = payload as { thread_id?: string; old_phase?: string; new_phase?: string; current_agent?: string }
    if (p.thread_id === currentThreadId.value && workflowState.value) {
      workflowState.value = {
        ...workflowState.value,
        values: {
          ...workflowState.value.values,
          phase: (p.new_phase || workflowState.value.values.phase) as WorkflowPhase,
          current_agent: p.current_agent,
        },
      }
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_DATA_UPDATED, (payload: unknown) => {
    const p = payload as { thread_id?: string; data_type?: string; data?: unknown }
    if (p.thread_id === currentThreadId.value && workflowState.value && p.data_type && p.data) {
      workflowState.value = {
        ...workflowState.value,
        values: {
          ...workflowState.value.values,
          [p.data_type]: p.data,
        },
      }
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_COMPLETED, (payload: unknown) => {
    const p = payload as { thread_id?: string }
    if (p.thread_id === currentThreadId.value && workflowState.value) {
      workflowState.value = {
        ...workflowState.value,
        values: {
          ...workflowState.value.values,
          phase: 'completed',
        },
        next: [],
      }
    }
  })

  // Actions
  async function startWorkflow(accountId: string, phase: WorkflowPhase = 'scouting') {
    isLoading.value = true
    error.value = null
    try {
      const result = await workflowApi.startWorkflow({ account_id: accountId, phase })
      currentThreadId.value = result.thread_id
      await refreshStatus()
      // Connect WebSocket and subscribe
      realtimeStore.connect()
      realtimeStore.subscribeWorkflow(result.thread_id)
      return result
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function refreshStatus() {
    if (!currentThreadId.value) return
    isLoading.value = true
    error.value = null
    try {
      workflowState.value = await workflowApi.getWorkflowStatus(currentThreadId.value)
    } catch (e: any) {
      error.value = e.message
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
    } catch (e: any) {
      error.value = e.message
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
      return result
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
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
    currentPhase,
    nextNodes,
    isRunning,
    trendData,
    contentPlan,
    copyContent,
    visualPlan,
    startWorkflow,
    refreshStatus,
    pauseWorkflow,
    resumeWorkflow,
    startPolling,
    stopPolling,
    setThreadId,
  }
})