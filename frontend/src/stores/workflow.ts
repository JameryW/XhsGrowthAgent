import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as workflowApi from '@/api/workflow'
import type { WorkflowStateResponse, WorkflowPhase } from '@/types/workflow'
import { useRealtimeStore } from './realtime'
import { useToastStore } from './toast'
import { EventType } from '@/realtime/events'

export const useWorkflowStore = defineStore('workflow', () => {
  // State
  const currentThreadId = ref<string | null>(null)
  const workflowState = ref<WorkflowStateResponse | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const progressPercent = ref(0)

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

  // Dependencies
  const realtimeStore = useRealtimeStore()
  const toastStore = useToastStore()

  // Phase progress mapping (synced with backend)
  const PHASE_PROGRESS: Record<string, number> = {
    idle: 0,
    scouting: 10,
    planning: 20,
    creating: 40,
    reviewing: 60,
    publishing: 80,
    analyzing: 90,
    engaging: 95,
    completed: 100,
    error: 0,
  }

  // WebSocket event handlers
  realtimeStore.wsService.onEvent(EventType.WORKFLOW_PHASE_CHANGED, (payload: unknown) => {
    const p = payload as { thread_id?: string; old_phase?: string; new_phase?: string; current_agent?: string }
    if (p.thread_id === currentThreadId.value && workflowState.value) {
      const newPhase = p.new_phase || workflowState.value.values.phase
      workflowState.value = {
        ...workflowState.value,
        values: {
          ...workflowState.value.values,
          phase: newPhase as WorkflowPhase,
          current_agent: p.current_agent,
        },
      }
      // Update progress
      progressPercent.value = PHASE_PROGRESS[newPhase] || 0
      // Special notification for reviewing phase - requires user action
      if (newPhase === 'reviewing') {
        toastStore.info('等待审核', '工作流已暂停，请前往审核页面查看并决定')
      } else {
        toastStore.info(`阶段切换: ${p.old_phase} → ${newPhase}`, `当前 Agent: ${p.current_agent}`)
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
      progressPercent.value = 100
      toastStore.success('工作流完成', `Thread: ${p.thread_id}`)
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_ERROR, (payload: unknown) => {
    const p = payload as { thread_id?: string; error?: string; agent?: string }
    if (p.thread_id === currentThreadId.value && workflowState.value) {
      workflowState.value = {
        ...workflowState.value,
        values: {
          ...workflowState.value.values,
          phase: 'error',
          error: p.error,
        },
      }
      progressPercent.value = 0
      toastStore.error('工作流错误', `Agent: ${p.agent} - ${p.error}`)
    }
  })

  // Actions
  async function startWorkflow(accountId: string, phase: WorkflowPhase = 'scouting') {
    isLoading.value = true
    error.value = null
    try {
      const result = await workflowApi.startWorkflow({ account_id: accountId, phase })
      currentThreadId.value = result.thread_id
      progressPercent.value = PHASE_PROGRESS[phase] || 0
      await refreshStatus()
      // Connect WebSocket and subscribe
      realtimeStore.connect()
      realtimeStore.subscribeWorkflow(result.thread_id)
      toastStore.success('工作流启动成功', `Thread: ${result.thread_id}`)
      return result
    } catch (e: any) {
      error.value = e.message
      toastStore.error('启动失败', e.message)
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
      // Update progress from state
      const phase = workflowState.value?.values?.phase || 'idle'
      progressPercent.value = PHASE_PROGRESS[phase] || 0
    } catch (e: any) {
      error.value = e.message
      toastStore.warning('状态刷新失败', e.message)
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
      toastStore.info('工作流已暂停', `Thread: ${currentThreadId.value}`)
    } catch (e: any) {
      error.value = e.message
      toastStore.error('暂停失败', e.message)
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
      toastStore.success('工作流已恢复', `当前阶段: ${workflowState.value?.values?.phase}`)
      return result
    } catch (e: any) {
      error.value = e.message
      toastStore.error('恢复失败', e.message)
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
    progressPercent,
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