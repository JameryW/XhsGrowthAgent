import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import * as workflowApi from '@/api/workflow'
import type {
  ContentPlan,
  CopyContent,
  TrendData,
  VisualPlan,
  WorkflowStateResponse,
  WorkflowPhase,
  WorkflowStatus,
  RippleProgress,
} from '@/types/workflow'
import type { BriefUploadResult } from '@/api/workflow'
import { useRealtimeStore } from './realtime'
import { useToastStore } from './toast'
import { useOfflineStore } from './offline'
import { EventType } from '@/realtime/events'
import { useLoading } from '@/composables/useLoading'
import i18n from '@/locales'

const { t } = i18n.global

// localStorage keys
const LS_ACTIVE_THREAD = 'activeThreadId'
const LS_OPEN_TABS = 'openTabIds'
const LS_TAB_LABELS = 'tabLabels'

function loadOpenTabs(): string[] {
  try {
    const raw = localStorage.getItem(LS_OPEN_TABS)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

function saveOpenTabs(ids: string[]) {
  localStorage.setItem(LS_OPEN_TABS, JSON.stringify(ids))
}

function loadTabLabels(): Record<string, string> {
  try {
    const raw = localStorage.getItem(LS_TAB_LABELS)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

function saveTabLabels(labels: Record<string, string>) {
  localStorage.setItem(LS_TAB_LABELS, JSON.stringify(labels))
}

function generateTabLabel(niche?: string, workflowMode?: string, createdAt?: string): string {
  const date = createdAt ? new Date(createdAt) : new Date()
  const dateStr = `${(date.getMonth() + 1).toString().padStart(2, '0')}/${date.getDate().toString().padStart(2, '0')}`
  const modeStr = workflowMode === 'brief' ? 'brief' : 'trend'
  const nicheStr = niche || ''
  return nicheStr ? `${nicheStr}-${modeStr}-${dateStr}` : `${modeStr}-${dateStr}`
}

export const useWorkflowStore = defineStore('workflow', () => {
  // ── Multi-workflow state ──
  const workflowStates = ref<Map<string, WorkflowStateResponse>>(new Map())
  const activeThreadId = ref<string | null>(localStorage.getItem(LS_ACTIVE_THREAD))
  const openTabIds = ref<string[]>(loadOpenTabs())
  const tabLabels = ref<Record<string, string>>(loadTabLabels())
  const rippleProgressMap = ref<Map<string, RippleProgress>>(new Map())

  // ── Backward-compatible single-workflow computed ──
  const workflowState = computed<WorkflowStateResponse | null>(() =>
    activeThreadId.value ? workflowStates.value.get(activeThreadId.value) ?? null : null
  )

  const currentThreadId = computed<string | null>(() => activeThreadId.value)

  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const progressPercent = ref(0)
  const isOverlayLoading = ref(false)

  // Computed
  const currentPhase = computed<WorkflowPhase>(() =>
    workflowState.value?.phase || 'idle'
  )

  const currentStatus = computed<WorkflowStatus>(() =>
    workflowState.value?.status || 'idle'
  )

  const nextNodes = computed(() => workflowState.value?.next_steps || [])

  const isRunning = computed(() =>
    currentStatus.value === 'running'
  )

  const isStale = computed(() =>
    currentStatus.value === 'stale'
  )

  const isAwaitingReview = computed(() =>
    currentStatus.value === 'awaiting_review'
  )

  const isAwaitingChoice = computed(() =>
    currentStatus.value === 'awaiting_choice'
  )

  const isAwaitingDraft = computed(() =>
    currentStatus.value === 'awaiting_draft'
  )

  const isAwaitingBrief = computed(() =>
    currentStatus.value === 'awaiting_brief'
  )

  const trendData = computed<Partial<TrendData>>(() => workflowState.value?.trend_data || {})
  const contentPlan = computed<Partial<ContentPlan>>(() => workflowState.value?.content_plan || {})
  const copyContent = computed<Partial<CopyContent>>(() => workflowState.value?.copy_content || {})
  const visualPlan = computed<Partial<VisualPlan>>(() => workflowState.value?.visual_plan || {})
  const agentTimeline = computed(() => workflowState.value?.agent_timeline || [])

  // Ripple CAS engine results
  const ripplePrediction = computed(() => workflowState.value?.ripple_prediction || {})
  const ripplePmf = computed(() => workflowState.value?.ripple_pmf || {})
  const rippleComparison = computed(() => workflowState.value?.ripple_comparison || {})
  const rippleReason = computed(() => workflowState.value?.ripple_reason || '')

  // Ripple progress for active thread
  const rippleProgress = computed<RippleProgress | null>(() =>
    activeThreadId.value ? rippleProgressMap.value.get(activeThreadId.value) ?? null : null
  )

  const hasRippleData = computed(() =>
    Object.keys(ripplePrediction.value).length > 0 ||
    Object.keys(ripplePmf.value).length > 0 ||
    Object.keys(rippleComparison.value).length > 0
  )

  // ── Tab management ──

  const TAB_FOLD_LIMIT = 8

  const workflowList = computed(() => {
    const items: Array<{ threadId: string; label: string; status: WorkflowStatus; phase: WorkflowPhase; progress: number }> = []
    for (const id of openTabIds.value) {
      const state = workflowStates.value.get(id)
      items.push({
        threadId: id,
        label: tabLabels.value[id] || id.slice(-8),
        status: state?.status || 'idle',
        phase: state?.phase || 'idle',
        progress: state?.progress_percent ?? 0,
      })
    }
    return items
  })

  const visibleTabs = computed(() => workflowList.value.slice(0, TAB_FOLD_LIMIT))
  const overflowTabs = computed(() => workflowList.value.slice(TAB_FOLD_LIMIT))
  const hasOverflow = computed(() => openTabIds.value.length > TAB_FOLD_LIMIT)

  function getTabLabel(threadId: string): string {
    return tabLabels.value[threadId] || threadId.slice(-8)
  }

  function getStatusForTab(threadId: string): WorkflowStatus {
    return workflowStates.value.get(threadId)?.status || 'idle'
  }

  function switchTab(threadId: string) {
    if (!workflowStates.value.has(threadId)) return
    activeThreadId.value = threadId
    localStorage.setItem(LS_ACTIVE_THREAD, threadId)
    // Update progress/overlay for the newly active tab
    const state = workflowStates.value.get(threadId)
    if (state) {
      updateProgressFromPhase(state.phase, state.progress_percent)
    }
  }

  function closeTab(threadId: string) {
    const idx = openTabIds.value.indexOf(threadId)
    if (idx < 0) return

    openTabIds.value.splice(idx, 1)
    workflowStates.value.delete(threadId)
    rippleProgressMap.value.delete(threadId)
    delete tabLabels.value[threadId]

    saveOpenTabs(openTabIds.value)
    saveTabLabels(tabLabels.value)

    // Unsubscribe WS for this thread
    realtimeStore.unsubscribeWorkflow(threadId)

    // If closing the active tab, switch to the nearest
    if (activeThreadId.value === threadId) {
      const newActive = openTabIds.value[Math.min(idx, openTabIds.value.length - 1)] ?? null
      activeThreadId.value = newActive
      if (newActive) {
        localStorage.setItem(LS_ACTIVE_THREAD, newActive)
        const state = workflowStates.value.get(newActive)
        if (state) updateProgressFromPhase(state.phase, state.progress_percent)
      } else {
        localStorage.removeItem(LS_ACTIVE_THREAD)
        progressPercent.value = 0
        isOverlayLoading.value = false
      }
    }
  }

  function renameTab(threadId: string, newLabel: string) {
    tabLabels.value[threadId] = newLabel
    saveTabLabels(tabLabels.value)
  }

  // ── Structured publish error ──

  const publishError = computed(() => {
    const pr = (workflowState.value as any)?.publish_result
    if (!pr || pr.status !== 'failed') return null
    return {
      message: pr.error || t('workflow.publishFailed'),
      type: pr.error_type || 'unknown',
      recovery: pr.recovery || null,
    }
  })

  // Dependencies
  const realtimeStore = useRealtimeStore()
  const toastStore = useToastStore()
  const offlineStore = useOfflineStore()
  const { phaseToPercent, isOverlayPhase } = useLoading()

  // Phases that should NOT reset progress — preserve last valid value
  const PRESERVE_PROGRESS_PHASES: WorkflowPhase[] = ['paused', 'cancelled']

  function updateProgressFromPhase(phase: WorkflowPhase, backendProgress?: number) {
    if (PRESERVE_PROGRESS_PHASES.includes(phase) && !backendProgress) {
      isOverlayLoading.value = false
      return
    }
    progressPercent.value = backendProgress ?? phaseToPercent(phase)
    isOverlayLoading.value = isOverlayPhase(phase)
  }

  // ── WebSocket event handlers (multi-thread aware) ──

  function updateWorkflowState(threadId: string, updates: Partial<WorkflowStateResponse>) {
    const existing = workflowStates.value.get(threadId)
    if (!existing) return
    workflowStates.value.set(threadId, { ...existing, ...updates })
  }

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_PHASE_CHANGED, (msg) => {
    if (!msg.thread_id) return
    const state = workflowStates.value.get(msg.thread_id)
    if (!state) return
    const p = msg.payload as { old_phase?: string; new_phase?: string; current_agent?: string }
    const newPhase = p.new_phase || state.phase
    updateWorkflowState(msg.thread_id, {
      phase: newPhase as WorkflowPhase,
      current_agent: p.current_agent,
    })
    if (msg.thread_id === activeThreadId.value) {
      updateProgressFromPhase(newPhase as WorkflowPhase)
    }
    if (newPhase === 'reviewing') {
      toastStore.info(t('workflow.awaitingReview'), t('workflow.awaitingReviewMessage'))
    } else {
      toastStore.info(`${t('workflow.phaseChange')}: ${p.old_phase} → ${newPhase}`, `${t('workflow.currentAgent')}: ${p.current_agent}`)
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_DATA_UPDATED, (msg) => {
    if (!msg.thread_id) return
    const state = workflowStates.value.get(msg.thread_id)
    if (!state) return
    const p = msg.payload as Partial<WorkflowStateResponse> & { data_type?: string; data?: unknown }

    if (p.data_type && p.data) {
      const updated = { ...state }
      ;(updated as any)[p.data_type] = p.data
      workflowStates.value.set(msg.thread_id, updated)
      return
    }

    const directKeys = [
      'phase', 'status', 'current_agent', 'next_steps', 'error', 'progress_percent',
      'trend_data', 'content_plan', 'copy_content', 'draft_content',
      'optimization_analysis', 'content_versions', 'visual_plan', 'publish_result',
      'analytics', 'ripple_prediction', 'ripple_pmf', 'ripple_comparison',
      'ripple_reason', 'workflow_mode', 'brief_content', 'brief_clarification', 'shooting_plan',
    ] as const
    const updates: Partial<WorkflowStateResponse> = {}
    for (const key of directKeys) {
      if (Object.prototype.hasOwnProperty.call(p, key)) {
        ;(updates as Record<string, unknown>)[key] = p[key]
      }
    }

    if (Object.keys(updates).length > 0) {
      updateWorkflowState(msg.thread_id, updates)
      if (msg.thread_id === activeThreadId.value) {
        const newState = workflowStates.value.get(msg.thread_id)!
        updateProgressFromPhase(newState.phase, newState.progress_percent)
      }
    }
  })

  realtimeStore.wsService.onEvent(EventType.RIPPLE_PROGRESS, (msg) => {
    if (!msg.thread_id) return
    rippleProgressMap.value.set(msg.thread_id, msg.payload as RippleProgress)
  })

  watch(() => workflowState.value?.ripple_prediction, (val) => {
    if (val && Object.keys(val).length > 0 && activeThreadId.value) {
      rippleProgressMap.value.delete(activeThreadId.value)
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_COMPLETED, (msg) => {
    if (!msg.thread_id) return
    const state = workflowStates.value.get(msg.thread_id)
    if (!state) return
    const p = msg.payload as Record<string, unknown>
    const contentKeys = [
      'copy_content', 'trend_data', 'content_plan', 'visual_plan',
      'publish_result', 'analytics', 'ripple_prediction', 'ripple_pmf', 'ripple_comparison',
    ] as const
    const contentUpdates: Record<string, unknown> = {}
    for (const key of contentKeys) {
      if (p[key] !== undefined && p[key] !== null) {
        contentUpdates[key] = p[key]
      }
    }
    updateWorkflowState(msg.thread_id, {
      ...contentUpdates,
      phase: 'completed',
      status: 'completed',
      next_steps: [],
    } as Partial<WorkflowStateResponse>)
    if (msg.thread_id === activeThreadId.value) {
      updateProgressFromPhase('completed')
    }
    toastStore.success(t('workflow.completed'), `${t('workflow.thread')}: ${msg.thread_id}`)
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_ERROR, (msg) => {
    if (!msg.thread_id) return
    const state = workflowStates.value.get(msg.thread_id)
    if (!state) return
    const p = msg.payload as { error?: string; agent?: string }
    if (msg.thread_id === activeThreadId.value) {
      error.value = p.error || t('workflow.error')
    }
    updateWorkflowState(msg.thread_id, {
      phase: 'error',
      status: 'error',
      error: p.error,
    } as Partial<WorkflowStateResponse>)
    if (msg.thread_id === activeThreadId.value) {
      updateProgressFromPhase('error')
    }
    toastStore.error(t('workflow.error'), `${t('workflow.currentAgent')}: ${p.agent} - ${p.error}`)
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_STARTED, (msg) => {
    if (!msg.thread_id) return
    const state = workflowStates.value.get(msg.thread_id)
    if (!state) return
    const p = msg.payload as { phase?: string; account_id?: string; dry_run?: boolean }
    updateWorkflowState(msg.thread_id, {
      phase: (p.phase || 'scouting') as WorkflowPhase,
      current_agent: 'orchestrator',
    })
    if (msg.thread_id === activeThreadId.value) {
      updateProgressFromPhase((p.phase || 'scouting') as WorkflowPhase)
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_AGENT_STARTED, (msg) => {
    if (!msg.thread_id) return
    const state = workflowStates.value.get(msg.thread_id)
    if (!state) return
    const p = msg.payload as { agent?: string }
    updateWorkflowState(msg.thread_id, {
      current_agent: p.agent || state.current_agent,
    })
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_AGENT_COMPLETED, (msg) => {
    if (!msg.thread_id) return
    const state = workflowStates.value.get(msg.thread_id)
    if (!state) return
    const p = msg.payload as { agent?: string; status?: string }
    const timeline = state.agent_timeline || []
    const existing = timeline.find((e: any) => e.agent === p.agent && !e.completed_at)
    if (existing) {
      existing.completed_at = new Date().toISOString()
      existing.status = (p.status === 'error' ? 'error' : 'success') as 'success' | 'error'
      // Trigger reactivity
      updateWorkflowState(msg.thread_id, { agent_timeline: [...timeline] })
    }
  })

  // ── Actions ──

  async function startWorkflow(accountId: string, phase: WorkflowPhase = 'scouting', options?: { dryRun?: boolean; autoPublish?: boolean; topic?: string; niche?: string; workflowMode?: 'trend' | 'brief'; briefText?: string }) {
    if (!offlineStore.isOnline) {
      offlineStore.queueAction(
        `start-${accountId}`,
        async () => { await startWorkflow(accountId, phase, options) },
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
        workflow_mode: options?.workflowMode,
        brief_text: options?.briefText,
      })

      const threadId = result.thread_id

      // Add to workflow states map
      workflowStates.value.set(threadId, {
        thread_id: threadId,
        phase,
        status: 'running',
        progress_percent: 0,
        next_steps: [],
        agent_timeline: [],
      } as WorkflowStateResponse)

      // Add tab
      if (!openTabIds.value.includes(threadId)) {
        openTabIds.value.push(threadId)
      }

      // Auto-generate label
      const label = generateTabLabel(options?.niche, options?.workflowMode)
      tabLabels.value[threadId] = label

      // Make it the active tab
      activeThreadId.value = threadId
      localStorage.setItem(LS_ACTIVE_THREAD, threadId)
      saveOpenTabs(openTabIds.value)
      saveTabLabels(tabLabels.value)

      updateProgressFromPhase(phase)

      // Fetch full status from backend
      try {
        const fullState = await workflowApi.getWorkflowStatus(threadId)
        workflowStates.value.set(threadId, fullState)
        if (threadId === activeThreadId.value) {
          updateProgressFromPhase(fullState.phase, fullState.progress_percent)
        }
      } catch {
        // Status fetch failed, we already have a basic state
      }

      // Connect WebSocket and subscribe
      realtimeStore.connect()
      realtimeStore.subscribeWorkflow(threadId)
      toastStore.success(t('workflow.startSuccess'), `${t('workflow.thread')}: ${threadId}`)
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
    if (!activeThreadId.value) return
    if (!offlineStore.isOnline) {
      offlineStore.queueAction(
        `refresh-${activeThreadId.value}`,
        async () => { await refreshStatus() },
        t('workflow.statusRefreshFailed')
      )
      return
    }

    isLoading.value = true
    error.value = null
    try {
      const state = await workflowApi.getWorkflowStatus(activeThreadId.value)
      workflowStates.value.set(activeThreadId.value, state)
      const status = state?.status || 'running'
      const phase = state?.phase || 'idle'
      const backendProgress = state?.progress_percent
      updateProgressFromPhase(phase as WorkflowPhase, backendProgress)
      if (status === 'error') {
        error.value = state?.error || t('workflow.error')
        return
      }
      if (status === 'stale') {
        toastStore.warning(t('workflow.staleDetected'), t('workflow.staleHint'))
      }
    } catch (e: any) {
      if (e.code === 'ERROR_WORKFLOW_NOT_FOUND' || e.message?.includes('not found')) {
        closeTab(activeThreadId.value!)
      } else {
        error.value = e.message
        toastStore.warning(t('workflow.statusRefreshFailed'), e.message)
      }
    } finally {
      isLoading.value = false
    }
  }

  /** Refresh status for all open tabs */
  async function refreshAllTabs() {
    const ids = openTabIds.value
    const promises = ids.map(async (id) => {
      try {
        const state = await workflowApi.getWorkflowStatus(id)
        workflowStates.value.set(id, state)
      } catch {
        // Individual tab refresh failure is non-critical
      }
    })
    await Promise.allSettled(promises)
    // Update active tab progress
    if (activeThreadId.value) {
      const state = workflowStates.value.get(activeThreadId.value)
      if (state) {
        updateProgressFromPhase(state.phase, state.progress_percent)
      }
    }
  }

  async function pauseWorkflow() {
    if (!activeThreadId.value) return
    const threadId = activeThreadId.value
    isLoading.value = true
    try {
      realtimeStore.unsubscribeWorkflow(threadId)
      await workflowApi.pauseWorkflow(threadId)
      // Update state in map
      const state = workflowStates.value.get(threadId)
      if (state) {
        workflowStates.value.set(threadId, { ...state, status: 'paused', phase: 'paused' })
        updateProgressFromPhase('paused')
      }
      toastStore.info(t('workflow.paused'), `${t('workflow.thread')}: ${threadId}`)
    } catch (e: any) {
      error.value = e.message
      toastStore.error(t('workflow.pauseFailed'), e.message)
    } finally {
      isLoading.value = false
    }
  }

  async function resumeWorkflow() {
    if (!activeThreadId.value) return
    const threadId = activeThreadId.value
    isLoading.value = true
    error.value = null
    try {
      const result = await workflowApi.resumeWorkflow(threadId)
      const state = workflowStates.value.get(threadId)
      if (state) {
        workflowStates.value.set(threadId, { ...state, status: 'running' })
        updateProgressFromPhase(state.phase, state.progress_percent)
      }
      realtimeStore.subscribeWorkflow(threadId)
      toastStore.success(t('workflow.resumed'), `${t('workflow.currentPhase')}: ${state?.phase}`)
      return result
    } catch (e: any) {
      error.value = e.message
      toastStore.error(t('workflow.resumeFailed'), e.message)
    } finally {
      isLoading.value = false
    }
  }

  async function cancelWorkflow() {
    if (!activeThreadId.value) return
    const threadId = activeThreadId.value
    isLoading.value = true
    try {
      realtimeStore.unsubscribeWorkflow(threadId)
      await workflowApi.cancelWorkflow(threadId)
      updateWorkflowState(threadId, {
        phase: 'cancelled',
        status: 'cancelled',
        next_steps: [],
      } as Partial<WorkflowStateResponse>)
      updateProgressFromPhase('cancelled')
      toastStore.info(t('workflow.paused'), `${t('workflow.thread')}: ${threadId}`)
    } catch (e: any) {
      error.value = e.message
      toastStore.error(t('workflow.cancelFailed'), e.message)
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
    if (!workflowStates.value.has(threadId)) return
    activeThreadId.value = threadId
    localStorage.setItem(LS_ACTIVE_THREAD, threadId)
    if (!openTabIds.value.includes(threadId)) {
      openTabIds.value.push(threadId)
      saveOpenTabs(openTabIds.value)
    }
    const state = workflowStates.value.get(threadId)
    if (state) {
      updateProgressFromPhase(state.phase, state.progress_percent)
    }
  }

  // Brief PDF upload state
  const briefUploadedText = ref<string | null>(null)
  const briefSourceType = ref<string | null>(null)
  const isBriefUploading = ref(false)

  async function uploadBriefPdf(threadId: string, file: File): Promise<BriefUploadResult | null> {
    const MAX_SIZE = 10 * 1024 * 1024
    if (file.size > MAX_SIZE) {
      toastStore.error(t('brief.fileTooLarge'), t('brief.fileTooLargeDesc'))
      return null
    }
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      toastStore.error(t('brief.unsupportedFormat'), t('brief.unsupportedFormatDesc'))
      return null
    }

    isBriefUploading.value = true
    try {
      const result = await workflowApi.uploadBriefFile(threadId, file)
      briefUploadedText.value = result.brief_text
      briefSourceType.value = result.source_type
      toastStore.success(t('brief.uploadSuccess'))
      return result
    } catch (e: any) {
      toastStore.error(t('brief.uploadFailed'), e.message)
      briefUploadedText.value = null
      return null
    } finally {
      isBriefUploading.value = false
    }
  }

  function clearBriefUpload() {
    briefUploadedText.value = null
    briefSourceType.value = null
  }

  return {
    // Multi-workflow state
    activeThreadId,
    currentThreadId,
    workflowStates,
    openTabIds,
    tabLabels,
    workflowList,
    visibleTabs,
    overflowTabs,
    hasOverflow,
    switchTab,
    closeTab,
    renameTab,
    getTabLabel,
    getStatusForTab,
    refreshAllTabs,

    // Single-workflow state (backward compatible)
    workflowState,
    isLoading,
    error,
    progressPercent,
    isOverlayLoading,
    currentPhase,
    currentStatus,
    nextNodes,
    isRunning,
    isStale,
    isAwaitingReview,
    isAwaitingChoice,
    isAwaitingDraft,
    isAwaitingBrief,
    trendData,
    contentPlan,
    copyContent,
    visualPlan,
    agentTimeline,
    publishError,
    ripplePrediction,
    ripplePmf,
    rippleComparison,
    rippleReason,
    rippleProgress,
    hasRippleData,

    // Actions
    startWorkflow,
    refreshStatus,
    pauseWorkflow,
    resumeWorkflow,
    cancelWorkflow,
    startPolling,
    stopPolling,
    setThreadId,
    updateProgressFromPhase,
    briefUploadedText,
    briefSourceType,
    isBriefUploading,
    uploadBriefPdf,
    clearBriefUpload,
  }
})
