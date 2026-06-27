import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type {
  DraftContent,
  ViralPost,
  OptimizationAnalysis,
  ContentVersion,
  VersionChoice,
} from '@/types/optimization'
import { useRealtimeStore } from './realtime'
import { useWorkflowStore } from './workflow'
import { EventType } from '@/realtime/events'
import { submitDraft as apiSubmitDraft, selectVersion as apiSelectVersion } from '@/api/workflow'

export const useOptimizationStore = defineStore('optimization', () => {
  // State
  const draftContent = ref<DraftContent | null>(null)
  const viralPosts = ref<ViralPost[]>([])
  const userViralLinks = ref<string[]>([])
  const optimizationAnalysis = ref<OptimizationAnalysis | null>(null)
  const contentVersions = ref<ContentVersion[]>([])
  const selectedVersion = ref<string | null>(null)
  const activeThreadId = ref<string | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Computed
  const hasViralPosts = computed(() => viralPosts.value.length > 0)
  const hasOptimization = computed(() => optimizationAnalysis.value !== null)
  const hasVersions = computed(() => contentVersions.value.length > 0)
  const selectedVersionData = computed(() =>
    contentVersions.value.find(v => v.version_id === selectedVersion.value)
  )

  // Reset optimization state when active workflow tab changes
  // ponytail: global reset on tab switch — per-thread maps if many concurrent workflows matter
  const workflowStore = useWorkflowStore()
  watch(
    () => workflowStore.currentThreadId,
    (newThreadId, oldThreadId) => {
      if (newThreadId !== oldThreadId) {
        clearOptimization()
        // Re-hydrate from the new tab's workflow state
        if (newThreadId) {
          const state = workflowStore.workflowStates.get(newThreadId)
          if (state) {
            if ((state as any).draft_content) draftContent.value = (state as any).draft_content
            if ((state as any).optimization_analysis) optimizationAnalysis.value = (state as any).optimization_analysis
            if ((state as any).content_versions) contentVersions.value = (state as any).content_versions
          }
        }
      }
    },
  )

  // Get parent workflow store's thread ID
  const getThreadId = (): string | null => {
    return workflowStore.currentThreadId
  }

  // WebSocket event handlers
  const realtimeStore = useRealtimeStore()

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_DATA_UPDATED, (msg) => {
    const threadId = getThreadId()
    if (msg.thread_id === threadId) {
      activeThreadId.value = msg.thread_id
      const p = msg.payload as { data_type?: string; data?: unknown }
      if (!p.data_type && p.data && typeof p.data === 'object') {
        const choiceData = p.data as {
          versions?: ContentVersion[]
          draft?: DraftContent
          analysis?: OptimizationAnalysis
        }
        if (choiceData.versions) contentVersions.value = choiceData.versions
        if (choiceData.draft) draftContent.value = choiceData.draft
        if (choiceData.analysis) optimizationAnalysis.value = choiceData.analysis
      } else if (p.data_type && p.data) {
        switch (p.data_type) {
          case 'draft_content':
            draftContent.value = p.data as DraftContent
            break
          case 'viral_posts':
            viralPosts.value = p.data as ViralPost[]
            break
          case 'optimization_analysis':
            optimizationAnalysis.value = p.data as OptimizationAnalysis
            break
          case 'content_versions':
            contentVersions.value = p.data as ContentVersion[]
            break
          case 'choice_pending':
            const choiceData = p.data as { versions?: ContentVersion[]; draft?: DraftContent; analysis?: OptimizationAnalysis }
            if (choiceData.versions) contentVersions.value = choiceData.versions
            if (choiceData.draft) draftContent.value = choiceData.draft
            if (choiceData.analysis) optimizationAnalysis.value = choiceData.analysis
            break
        }
      }
    }
  })

  // Actions
  async function submitDraft(draft: DraftContent, viralLinks: string[]) {
    const threadId = workflowStore.currentThreadId
    if (!threadId) {
      error.value = 'No active workflow thread'
      return
    }

    isLoading.value = true
    error.value = null
    try {
      draftContent.value = draft
      userViralLinks.value = viralLinks || []
      activeThreadId.value = threadId

      await apiSubmitDraft(threadId, {
        title: draft.title || '',
        text: draft.text,
        hashtags: draft.hashtags || [],
        viral_links: viralLinks || [],
      })
      await workflowStore.refreshStatus()
      if (workflowStore.isRunning) workflowStore.startPolling()
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function selectVersion(choice: VersionChoice) {
    const threadId = workflowStore.currentThreadId
    if (!threadId) {
      error.value = 'No active workflow thread'
      return
    }

    isLoading.value = true
    error.value = null
    try {
      selectedVersion.value = choice.version_id
      activeThreadId.value = threadId

      await apiSelectVersion(threadId, {
        version_id: choice.version_id,
        version_type: choice.selected_version,
      })
      await workflowStore.refreshStatus()
      if (workflowStore.isRunning) workflowStore.startPolling()
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  function clearOptimization() {
    draftContent.value = null
    viralPosts.value = []
    userViralLinks.value = []
    optimizationAnalysis.value = null
    contentVersions.value = []
    selectedVersion.value = null
    activeThreadId.value = null
    error.value = null
  }

  return {
    // State
    draftContent,
    viralPosts,
    userViralLinks,
    optimizationAnalysis,
    contentVersions,
    selectedVersion,
    activeThreadId,
    isLoading,
    error,
    // Computed
    hasViralPosts,
    hasOptimization,
    hasVersions,
    selectedVersionData,
    // Actions
    submitDraft,
    selectVersion,
    clearOptimization,
  }
})
