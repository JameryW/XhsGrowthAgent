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
  RippleThreadProgress,
  CheckpointSnapshot,
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
const REPLAY_CACHE_VERSION = 1
const REPLAY_CACHE_TTL_MS = 30_000
const REPLAY_CACHE_PREFIX = 'replay:snapshot:v1:'

type ReplayCacheSnapshot = {
  version: number
  savedAt: number
  threadId: string
  state?: WorkflowStateResponse
  checkpoints: CheckpointSnapshot[]
  hasMore: boolean
}

function replayCacheKey(threadId: string): string {
  return `${REPLAY_CACHE_PREFIX}${encodeURIComponent(threadId)}`
}

function readReplayCache(threadId: string): ReplayCacheSnapshot | null {
  try {
    const raw = sessionStorage.getItem(replayCacheKey(threadId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<ReplayCacheSnapshot>
    const age = Date.now() - Number(parsed.savedAt)
    if (
      parsed.version !== REPLAY_CACHE_VERSION
      || parsed.threadId !== threadId
      || !Number.isFinite(parsed.savedAt)
      || age < 0
      || age > REPLAY_CACHE_TTL_MS
      || !Array.isArray(parsed.checkpoints)
      || typeof parsed.hasMore !== 'boolean'
    ) {
      sessionStorage.removeItem(replayCacheKey(threadId))
      return null
    }
    return {
      version: REPLAY_CACHE_VERSION,
      savedAt: parsed.savedAt as number,
      threadId,
      state: parsed.state as WorkflowStateResponse | undefined,
      checkpoints: parsed.checkpoints as CheckpointSnapshot[],
      hasMore: parsed.hasMore as boolean,
    }
  } catch {
    return null
  }
}

function writeReplayCache(snapshot: ReplayCacheSnapshot): void {
  try {
    sessionStorage.setItem(replayCacheKey(snapshot.threadId), JSON.stringify(snapshot))
  } catch {
    // Storage can be unavailable or full; the live request path remains valid.
  }
}

function clearReplayCache(threadId: string): void {
  try {
    sessionStorage.removeItem(replayCacheKey(threadId))
  } catch {
    // Ignore unavailable storage; there is no live state to invalidate.
  }
}

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

/** Keep only the latest checkpoint per agent (first occurrence = most recent in LangGraph history).
 *  Also filters out empty-agent checkpoints (e.g. Step -1 with no current_agent). */
function deduplicateCheckpoints(cps: CheckpointSnapshot[]): CheckpointSnapshot[] {
  const seen = new Set<string>()
  return cps.filter(cp => {
    const agent = cp.current_agent
    if (!agent) return false
    if (seen.has(agent)) return false
    seen.add(agent)
    return true
  })
}

export const useWorkflowStore = defineStore('workflow', () => {
  // ── Multi-workflow state ──
  const workflowStates = ref<Map<string, WorkflowStateResponse>>(new Map())
  const activeThreadId = ref<string | null>(localStorage.getItem(LS_ACTIVE_THREAD))
  const openTabIds = ref<string[]>(loadOpenTabs())
  const tabLabels = ref<Record<string, string>>(loadTabLabels())
  const rippleProgressMap = ref<Map<string, Record<string, RippleProgress>>>(new Map())

  // ── Replay mode state ──
  const isReplayMode = ref(false)
  const replayCheckpoints = ref<CheckpointSnapshot[]>([])
  const activeCheckpointId = ref<string | null>(null)
  const hasMoreCheckpoints = ref(false)
  const isLoadingCheckpoints = ref(false)
  const replayCheckpointsError = ref<string | null>(null)
  const notifiedCheckpointLost = ref<Set<string>>(new Set())

  // Replay state: selected checkpoint's data, or null when not in replay
  const replayState = computed<WorkflowStateResponse | null>(() => {
    if (!isReplayMode.value || !activeCheckpointId.value) return null
    const cp = replayCheckpoints.value.find(c => c.checkpoint_id === activeCheckpointId.value)
    if (!cp) return null
    // Derive progress from checkpoint phase instead of hardcoding 0
    const cpProgress = phaseToPercent(cp.phase)
    return {
      thread_id: activeThreadId.value || '',
      phase: cp.phase,
      status: 'completed' as WorkflowStatus,
      current_agent: cp.current_agent,
      next_steps: cp.next_nodes,
      progress_percent: cpProgress,
      agent_timeline: [],
      trend_data: cp.trend_data,
      content_plan: cp.content_plan,
      copy_content: cp.copy_content,
      draft_content: cp.draft_content,
      optimization_analysis: cp.optimization_analysis,
      content_versions: cp.content_versions,
      visual_plan: cp.visual_plan,
      publish_result: cp.publish_result,
      analytics: cp.analytics,
      ripple_prediction: cp.ripple_prediction,
      ripple_pmf: cp.ripple_pmf,
      ripple_comparison: cp.ripple_comparison,
      workflow_mode: cp.workflow_mode,
      brief_content: cp.brief_content,
      shooting_plan: cp.shooting_plan,
    } as WorkflowStateResponse
  })

  // Effective state: replay overrides live when in replay mode
  const effectiveState = computed<WorkflowStateResponse | null>(() =>
    replayState.value || workflowState.value
  )

  // DB-03: unified display progress. Replay shows the inspected checkpoint's
  // progress; live workflow uses the high-water mark (progressPercent) so a
  // phase regression (reangle/retopic) never animates the bar backward.
  const displayProgress = computed(() =>
    isReplayMode.value && replayState.value
      ? replayState.value.progress_percent ?? 0
      : progressPercent.value
  )

  // ── Backward-compatible single-workflow computed ──
  const workflowState = computed<WorkflowStateResponse | null>(() =>
    activeThreadId.value ? workflowStates.value.get(activeThreadId.value) ?? null : null
  )

  // Replay deliberately exposes the live state separately from the selected
  // checkpoint.  Consumers that render workflow status (rather than the
  // historical result being inspected) must use this source.
  const liveWorkflowState = computed<WorkflowStateResponse | null>(() => workflowState.value)

  const currentThreadId = computed<string | null>(() => activeThreadId.value)

  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const progressPercent = ref(0)
  // High-water mark — progress bar never goes backward, even when phase
  // regresses (e.g. ripple reangle → planning, retopic → scouting).
  const _maxProgress = ref(0)

  // Computed
  const currentPhase = computed<WorkflowPhase>(() =>
    effectiveState.value?.phase || 'idle'
  )

  const currentStatus = computed<WorkflowStatus>(() =>
    effectiveState.value?.status || 'idle'
  )

  const nextNodes = computed(() => effectiveState.value?.next_steps || [])

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

  const isAwaitingRippleDecision = computed(() =>
    currentStatus.value === 'awaiting_ripple_decision'
  )

  const isAwaitingBloggerSelection = computed(() =>
    currentStatus.value === 'awaiting_blogger_selection'
  )

  const bloggerCandidates = computed(() =>
    (effectiveState.value as any)?.blogger_candidates || []
  )

  const reselectCount = computed(() =>
    (effectiveState.value as any)?.reselect_count ?? 0
  )

  const trendData = computed<Partial<TrendData>>(() => effectiveState.value?.trend_data || {})
  const contentPlan = computed<Partial<ContentPlan>>(() => effectiveState.value?.content_plan || {})
  const copyContent = computed<Partial<CopyContent>>(() => effectiveState.value?.copy_content || {})
  const visualPlan = computed<Partial<VisualPlan>>(() => effectiveState.value?.visual_plan || {})
  const agentTimeline = computed(() => effectiveState.value?.agent_timeline || [])

  // Ripple CAS engine results
  const ripplePrediction = computed(() => effectiveState.value?.ripple_prediction || {})
  const ripplePmf = computed(() => effectiveState.value?.ripple_pmf || {})
  const rippleComparison = computed(() => effectiveState.value?.ripple_comparison || {})
  const rippleReason = computed(() => effectiveState.value?.ripple_reason || '')

  // Ripple progress for active thread — aggregated across active jobs only
  // Completed jobs are excluded to prevent regression when new jobs start after reangle/retopic
  const rippleProgress = computed<RippleThreadProgress | null>(() => {
    if (!activeThreadId.value) return null
    const jobs = rippleProgressMap.value.get(activeThreadId.value)
    if (!jobs || Object.keys(jobs).length === 0) return null
    const entries = Object.values(jobs)
    const active = entries.filter(j => j.status !== 'completed' && j.status !== 'done' && j.status !== 'finished')
    // Only average active jobs for progress — completed jobs don't contribute
    // When all jobs are completed, show 100% (simulation finished)
    const avgProgress = active.length > 0
      ? active.reduce((sum, j) => sum + (j.progress || (j.total_waves > 0 ? j.current_wave / j.total_waves : 0)), 0) / active.length
      : entries.length > 0 ? 1 : 0
    return {
      jobs,
      overall_progress: avgProgress,
      active_jobs: active.length,
      total_jobs: entries.length,
    }
  })

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
      // Skip tabs with no state data (workflow may have been deleted)
      if (!state) continue
      const label = tabLabels.value[id] || state.label || generateTabLabel(
        (state as any).trend_data?.selected_topic || (state as any).brief_content?.brand_name,
        (state as any).workflow_mode,
        state.created_at,
      )
      items.push({
        threadId: id,
        label,
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
      _resetMaxProgressForTab(state.progress_percent, state.phase)
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
        if (state) {
          _resetMaxProgressForTab(state.progress_percent, state.phase)
          updateProgressFromPhase(state.phase, state.progress_percent)
        }
      } else {
        localStorage.removeItem(LS_ACTIVE_THREAD)
        progressPercent.value = 0
        _maxProgress.value = 0
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
  const { phaseToPercent } = useLoading()

  // Phases that should NOT reset progress — preserve last valid value
  const PRESERVE_PROGRESS_PHASES: WorkflowPhase[] = ['paused', 'cancelled']
  // Phases that must reset the high-water mark (error = 0%, completed = 100%)
  const RESET_PROGRESS_PHASES: WorkflowPhase[] = ['error', 'completed']

  /** Reset high-water mark to match a tab's current progress.
   *  Call before switching tabs so the new tab's progress isn't
   *  clipped to the old tab's high-water mark. */
  function _resetMaxProgressForTab(backendProgress?: number, phase?: WorkflowPhase) {
    _maxProgress.value = backendProgress ?? (phase ? phaseToPercent(phase) : 0)
  }

  function updateProgressFromPhase(phase: WorkflowPhase, backendProgress?: number) {
    if (PRESERVE_PROGRESS_PHASES.includes(phase) && !backendProgress) {
      return
    }
    const target = backendProgress ?? phaseToPercent(phase)
    // Error/completed reset the high-water mark — they're terminal states
    if (RESET_PROGRESS_PHASES.includes(phase)) {
      _maxProgress.value = target
      progressPercent.value = target
      return
    }
    const next = Math.max(target, _maxProgress.value)
    _maxProgress.value = next
    progressPercent.value = next
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
    // Show contextual toast for gate interrupts (status from DATA_UPDATED event
    // arrives separately, so we detect gates by phase+agent combination)
    const agent = p.current_agent || ''
    if (newPhase === 'reviewing') {
      toastStore.info(t('workflow.awaitingReview'), t('workflow.awaitingReviewMessage'))
    } else if (agent === 'blogger_gate' || agent === 'blogger_scout') {
      toastStore.info(t('workflow.awaitingBloggerSelection'), t('workflow.awaitingBloggerSelectionMessage'))
    } else if (agent === 'ripple_gate') {
      toastStore.info(t('workflow.awaitingRippleDecision'), t('workflow.awaitingRippleDecisionMessage'))
    } else if (agent === 'draft_gate') {
      toastStore.info(t('workflow.awaitingDraft'), t('workflow.awaitingDraftMessage'))
    } else if (agent === 'brief_gate') {
      toastStore.info(t('workflow.awaitingBrief'), t('workflow.awaitingBriefMessage'))
    } else if (agent === 'choice_gate') {
      toastStore.info(t('workflow.awaitingChoice'), t('workflow.awaitingChoiceMessage'))
    } else {
      toastStore.info(`${t('workflow.phaseChange')}: ${p.old_phase} → ${newPhase}`, `${t('workflow.currentAgent')}: ${agent}`)
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
      'blogger_candidates', 'selected_blogger', 'blogger_notes', 'reselect_count',
      'blogger_candidate_limit', 'blogger_note_limit',
    ] as const
    const updates: Partial<WorkflowStateResponse> = {}
    if (p.data && typeof p.data === 'object') {
      const gateData = p.data as {
        versions?: unknown
        draft?: unknown
        analysis?: unknown
      }
      if (Array.isArray(gateData.versions)) updates.content_versions = gateData.versions as any
      if (gateData.draft && typeof gateData.draft === 'object') updates.draft_content = gateData.draft as any
      if (gateData.analysis && typeof gateData.analysis === 'object') updates.optimization_analysis = gateData.analysis as any
    }
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

  realtimeStore.wsService.onEvent(EventType.REVIEW_PENDING, (msg) => {
    if (!msg.thread_id) return
    const state = workflowStates.value.get(msg.thread_id)
    if (!state) return
    const p = msg.payload as Partial<WorkflowStateResponse> & {
      version_history?: WorkflowStateResponse['content_versions']
    }
    updateWorkflowState(msg.thread_id, {
      status: 'awaiting_review',
      phase: (p.phase || 'reviewing') as WorkflowPhase,
      current_agent: p.current_agent || 'review_gate',
      next_steps: p.next_steps || ['review_gate'],
      progress_percent: p.progress_percent ?? state.progress_percent,
      content_plan: p.content_plan || state.content_plan,
      copy_content: p.copy_content || state.copy_content,
      visual_plan: p.visual_plan || state.visual_plan,
      content_versions: p.version_history || state.content_versions,
    })
    if (msg.thread_id === activeThreadId.value) {
      const newState = workflowStates.value.get(msg.thread_id)!
      updateProgressFromPhase(newState.phase, newState.progress_percent)
    }
  })

  realtimeStore.wsService.onEvent(EventType.RIPPLE_PROGRESS, (msg) => {
    if (!msg.thread_id) return
    const progress = msg.payload as RippleProgress
    const current = rippleProgressMap.value.get(msg.thread_id) || {}
    // When a new job starts (low progress) after reangle/retopic,
    // clear completed old jobs to prevent progress regression
    if (progress.progress <= 0.05 && progress.status === 'running') {
      const otherKeys = Object.keys(current).filter(k => k !== progress.job_id)
      const hasCompleted = otherKeys.some(k =>
        current[k].status === 'completed' || current[k].status === 'done' || current[k].status === 'finished'
      )
      if (hasCompleted) {
        // Remove old completed jobs — new simulation starting
        for (const k of otherKeys) {
          if (current[k].status === 'completed' || current[k].status === 'done' || current[k].status === 'finished') {
            delete current[k]
          }
        }
      }
    }
    current[progress.job_id] = progress
    rippleProgressMap.value.set(msg.thread_id, { ...current })
  })

  watch(() => workflowState.value?.ripple_prediction, (val, oldVal) => {
    if (!activeThreadId.value) return
    // When ripple_prediction is cleared (retopic/reangle resets), clear stale progress
    const wasCleared = oldVal && Object.keys(oldVal).length > 0 && (!val || Object.keys(val).length === 0)
    if (wasCleared) {
      rippleProgressMap.value.delete(activeThreadId.value)
      return
    }
    if (val && Object.keys(val).length > 0) {
      // Only clear progress when ALL jobs are done
      const jobs = rippleProgressMap.value.get(activeThreadId.value)
      if (jobs) {
        const hasActive = Object.values(jobs).some(
          j => j.status !== 'completed' && j.status !== 'done' && j.status !== 'finished'
        )
        if (!hasActive) {
          rippleProgressMap.value.delete(activeThreadId.value)
        }
      }
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
        phase: result.phase || phase,
        status: result.status || 'running',
        progress_percent: result.progress_percent ?? 0,
        next_steps: [],
        agent_timeline: [],
        workflow_mode: options?.workflowMode,
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

      // New workflow starts from 0 — reset high-water mark
      _maxProgress.value = 0
      updateProgressFromPhase((result.phase || phase) as WorkflowPhase, result.progress_percent)

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
      // Sync backend label to tab label (only if no user rename)
      if (state.label && !tabLabels.value[activeThreadId.value]) {
        tabLabels.value[activeThreadId.value] = state.label
        saveTabLabels(tabLabels.value)
      }
      // Sync Ripple progress from status API (fills gap when WebSocket events missed)
      if (state.ripple_progress && Object.keys(state.ripple_progress).length > 0) {
        const rp = state.ripple_progress as { jobs?: Record<string, RippleProgress> }
        if (rp.jobs) {
          const existing = rippleProgressMap.value.get(activeThreadId.value) || {}
          rippleProgressMap.value.set(activeThreadId.value, { ...existing, ...rp.jobs })
        }
      }
      const status = state?.status || 'running'
      const phase = state?.phase || 'idle'
      const backendProgress = state?.progress_percent
      updateProgressFromPhase(phase as WorkflowPhase, backendProgress)
      if (status === 'error') {
        error.value = state?.error || t('workflow.error')
        return
      }
      if (state?.checkpoint_lost) {
        const tid = activeThreadId.value
        if (tid && !notifiedCheckpointLost.value.has(tid)) {
          notifiedCheckpointLost.value.add(tid)
          toastStore.warning(t('workflow.checkpointLostTitle'), t('workflow.checkpointLost'))
        }
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
    const failedIds: string[] = []
    const promises = ids.map(async (id) => {
      try {
        const state = await workflowApi.getWorkflowStatus(id)
        workflowStates.value.set(id, state)
        // Sync backend label to tab label (only if no user rename)
        if (state.label && !tabLabels.value[id]) {
          tabLabels.value[id] = state.label
        }
        // Sync Ripple progress from status API (fills gap when WebSocket events missed)
        if (state.ripple_progress && Object.keys(state.ripple_progress).length > 0) {
          const rp = state.ripple_progress as { jobs?: Record<string, RippleProgress> }
          if (rp.jobs) {
            const existing = rippleProgressMap.value.get(id) || {}
            rippleProgressMap.value.set(id, { ...existing, ...rp.jobs })
          }
        }
      } catch {
        // 404 or other error — workflow no longer exists
        failedIds.push(id)
      }
    })
    await Promise.allSettled(promises)
    // Auto-close tabs for workflows that no longer exist
    for (const id of failedIds) {
      // ponytail: reuse closeTab logic — it also fixes activeThreadId and unsubscribes WS
      closeTab(id)
    }
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

  async function resumeWorkflow(resumeValue?: Record<string, unknown>) {
    if (!activeThreadId.value) return
    const threadId = activeThreadId.value
    isLoading.value = true
    error.value = null
    try {
      const result = await workflowApi.resumeWorkflow(threadId, resumeValue)
      const state = workflowStates.value.get(threadId)
      if (state) {
        const nextState = {
          ...state,
          status: result.status || 'running',
          phase: result.phase || state.phase,
        } as WorkflowStateResponse
        workflowStates.value.set(threadId, nextState)
        updateProgressFromPhase(nextState.phase, nextState.progress_percent)
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

  // 重试发布：用现有内容重跑发布步骤（不重走创作链路）。仅发布失败时用。
  async function retryPublish() {
    if (!activeThreadId.value) return
    const threadId = activeThreadId.value
    isLoading.value = true
    error.value = null
    try {
      const result = await workflowApi.retryPublish(threadId)
      const state = workflowStates.value.get(threadId)
      if (state) {
        const nextState = {
          ...state,
          status: result.status || 'running',
          phase: state.phase,
        } as WorkflowStateResponse
        workflowStates.value.set(threadId, nextState)
      }
      realtimeStore.subscribeWorkflow(threadId)
      if (result.status === 'skipped') {
        toastStore.warning(t('workflow.retryPublishSkipped', '重试已跳过'), result.message)
      } else {
        toastStore.success(t('workflow.retryPublishStarted', '正在重新发布'), result.message)
      }
      return result
    } catch (e: any) {
      error.value = e.message
      toastStore.error(t('workflow.retryPublishFailed', '重试发布失败'), e.message)
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
      toastStore.info(t('workflow.cancelled'), `${t('workflow.thread')}: ${threadId}`)
    } catch (e: any) {
      error.value = e.message
      toastStore.error(t('workflow.cancelFailed'), e.message)
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

  async function extractBriefPdf(file: File): Promise<{ brief_text: string; source_type: string } | null> {
    const MAX_SIZE = 20 * 1024 * 1024
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
      const result = await workflowApi.extractBriefFile(file)
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

  async function uploadBriefPdf(threadId: string, file: File): Promise<BriefUploadResult | null> {
    const MAX_SIZE = 20 * 1024 * 1024
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
    isBriefUploading.value = false
  }

  // ── Replay mode actions ──

  function checkpointHasBusinessData(cp: CheckpointSnapshot): boolean {
    const values = [
      cp.trend_data,
      cp.content_plan,
      cp.copy_content,
      cp.draft_content,
      cp.optimization_analysis,
      cp.content_versions,
      cp.visual_plan,
      cp.publish_result,
      cp.analytics,
      cp.ripple_prediction,
      cp.ripple_pmf,
      cp.ripple_comparison,
      cp.brief_content,
      cp.shooting_plan,
    ]
    return values.some((value) => {
      if (!value) return false
      if (Array.isArray(value)) return value.length > 0
      if (typeof value === 'object') return Object.keys(value as Record<string, unknown>).length > 0
      return true
    })
  }

  async function enterReplayMode(preferredCheckpointId?: string) {
    if (!activeThreadId.value) return
    const threadId = activeThreadId.value
    isReplayMode.value = true
    replayCheckpointsError.value = null
    isLoadingCheckpoints.value = true
    const cached = hydrateReplayCache(threadId, preferredCheckpointId)
    if (!cached) {
      replayCheckpoints.value = []
      activeCheckpointId.value = null
      hasMoreCheckpoints.value = false
    }
    try {
      const result = await workflowApi.getCheckpointHistory(threadId, { limit: 20 }, { suppressToast: true })
      const deduplicated = deduplicateCheckpoints(result.checkpoints)
      // A shared link may target an older checkpoint for the same agent. Keep
      // that explicitly requested snapshot available even though the rail
      // normally collapses duplicate-agent history.
      const linkedCheckpoint = preferredCheckpointId
        ? result.checkpoints.find(cp => cp.checkpoint_id === preferredCheckpointId)
        : undefined
      if (linkedCheckpoint && !deduplicated.some(cp => cp.checkpoint_id === linkedCheckpoint.checkpoint_id)) {
        deduplicated.unshift(linkedCheckpoint)
      }
      replayCheckpoints.value = deduplicated
      hasMoreCheckpoints.value = result.has_more
      // A shared link wins when it points at a loaded checkpoint. Otherwise
      // prefer the most recent checkpoint with a real business result, then
      // fall back to the most recent checkpoint (the API is newest-first).
      const preferred = preferredCheckpointId
        ? replayCheckpoints.value.find(cp => cp.checkpoint_id === preferredCheckpointId)
        : undefined
      const meaningful = replayCheckpoints.value.find(checkpointHasBusinessData)
      activeCheckpointId.value = (preferred || meaningful || replayCheckpoints.value[0])?.checkpoint_id || null
      writeReplayCache({
        version: REPLAY_CACHE_VERSION,
        savedAt: Date.now(),
        threadId,
        state: workflowStates.value.get(threadId),
        checkpoints: replayCheckpoints.value,
        hasMore: hasMoreCheckpoints.value,
      })
    } catch (e: any) {
      replayCheckpointsError.value = e?.message || t('workflow.replayLoadFailed')
    } finally {
      isLoadingCheckpoints.value = false
    }
  }

  function hydrateReplayCache(threadId: string, preferredCheckpointId?: string): ReplayCacheSnapshot | null {
    const cached = readReplayCache(threadId)
    if (!cached) return null
    if (cached.state) workflowStates.value.set(threadId, cached.state)
    isReplayMode.value = true
    const deduplicated = deduplicateCheckpoints(cached.checkpoints)
    const linkedCheckpoint = preferredCheckpointId
      ? cached.checkpoints.find(cp => cp.checkpoint_id === preferredCheckpointId)
      : undefined
    if (linkedCheckpoint && !deduplicated.some(cp => cp.checkpoint_id === linkedCheckpoint.checkpoint_id)) {
      deduplicated.unshift(linkedCheckpoint)
    }
    replayCheckpoints.value = deduplicated
    hasMoreCheckpoints.value = cached.hasMore
    const preferred = preferredCheckpointId
      ? replayCheckpoints.value.find(cp => cp.checkpoint_id === preferredCheckpointId)
      : undefined
    const meaningful = replayCheckpoints.value.find(checkpointHasBusinessData)
    activeCheckpointId.value = (preferred || meaningful || replayCheckpoints.value[0])?.checkpoint_id || null
    return cached
  }

  function saveReplayLiveState(threadId: string, state: WorkflowStateResponse): void {
    const cached = readReplayCache(threadId)
    writeReplayCache({
      version: REPLAY_CACHE_VERSION,
      savedAt: Date.now(),
      threadId,
      state,
      checkpoints: cached?.checkpoints || replayCheckpoints.value,
      hasMore: cached?.hasMore ?? hasMoreCheckpoints.value,
    })
  }

  function clearReplaySnapshot(threadId: string): void {
    clearReplayCache(threadId)
  }

  function exitReplayMode() {
    isReplayMode.value = false
    activeCheckpointId.value = null
    replayCheckpoints.value = []
    hasMoreCheckpoints.value = false
    replayCheckpointsError.value = null
  }

  function selectCheckpoint(checkpointId: string) {
    if (!replayCheckpoints.value.find(c => c.checkpoint_id === checkpointId)) return
    activeCheckpointId.value = checkpointId
  }

  async function loadMoreCheckpoints() {
    if (!activeThreadId.value || !hasMoreCheckpoints.value || isLoadingCheckpoints.value) return
    const threadId = activeThreadId.value
    isLoadingCheckpoints.value = true
    replayCheckpointsError.value = null
    try {
      // Use oldest checkpoint as cursor
      const oldest = replayCheckpoints.value[replayCheckpoints.value.length - 1]
      const result = await workflowApi.getCheckpointHistory(threadId, {
        limit: 20,
        before: oldest?.checkpoint_id,
      }, { suppressToast: true })
      // Append older checkpoints, then deduplicate
      const merged = [...replayCheckpoints.value, ...result.checkpoints]
      replayCheckpoints.value = deduplicateCheckpoints(merged)
      hasMoreCheckpoints.value = result.has_more
      writeReplayCache({
        version: REPLAY_CACHE_VERSION,
        savedAt: Date.now(),
        threadId,
        state: workflowStates.value.get(threadId),
        checkpoints: replayCheckpoints.value,
        hasMore: hasMoreCheckpoints.value,
      })
    } catch (e: any) {
      replayCheckpointsError.value = e?.message || t('workflow.replayLoadFailed')
    } finally {
      isLoadingCheckpoints.value = false
    }
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
    liveWorkflowState,
    isLoading,
    error,
    progressPercent,
    currentPhase,
    currentStatus,
    nextNodes,
    isRunning,
    isStale,
    isAwaitingReview,
    isAwaitingChoice,
    isAwaitingDraft,
    isAwaitingBrief,
    isAwaitingRippleDecision,
    isAwaitingBloggerSelection,
    bloggerCandidates,
    reselectCount,
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
    retryPublish,
    cancelWorkflow,
    startPolling,
    stopPolling,
    setThreadId,
    updateProgressFromPhase,
    briefUploadedText,
    briefSourceType,
    isBriefUploading,
    extractBriefPdf,
    uploadBriefPdf,
    clearBriefUpload,

    // Replay mode
    isReplayMode,
    replayCheckpoints,
    activeCheckpointId,
    hasMoreCheckpoints,
    isLoadingCheckpoints,
    replayCheckpointsError,
    replayState,
    effectiveState,
    displayProgress,
    enterReplayMode,
    hydrateReplayCache,
    saveReplayLiveState,
    clearReplaySnapshot,
    exitReplayMode,
    selectCheckpoint,
    loadMoreCheckpoints,
  }
})
