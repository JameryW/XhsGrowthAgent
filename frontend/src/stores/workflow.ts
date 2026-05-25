import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as workflowApi from '@/api/workflow'
import type { WorkflowStateResponse, WorkflowPhase } from '@/types/workflow'

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

  // Actions
  async function startWorkflow(accountId: string, phase: WorkflowPhase = 'scouting') {
    isLoading.value = true
    error.value = null
    try {
      const result = await workflowApi.startWorkflow({ account_id: accountId, phase })
      currentThreadId.value = result.thread_id
      await refreshStatus()
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