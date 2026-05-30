import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  DraftContent,
  ViralPost,
  OptimizationAnalysis,
  ContentVersion,
  VersionChoice,
} from '@/types/optimization'
import { useRealtimeStore } from './realtime'
import { EventType } from '@/realtime/events'

export const useOptimizationStore = defineStore('optimization', () => {
  // State
  const draftContent = ref<DraftContent | null>(null)
  const viralPosts = ref<ViralPost[]>([])
  const userViralLinks = ref<string[]>([])
  const optimizationAnalysis = ref<OptimizationAnalysis | null>(null)
  const contentVersions = ref<ContentVersion[]>([])
  const selectedVersion = ref<string | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Computed
  const hasViralPosts = computed(() => viralPosts.value.length > 0)
  const hasOptimization = computed(() => optimizationAnalysis.value !== null)
  const hasVersions = computed(() => contentVersions.value.length > 0)
  const selectedVersionData = computed(() =>
    contentVersions.value.find(v => v.version_id === selectedVersion.value)
  )

  // Get parent workflow store's thread ID
  const getThreadId = (): string | null => {
    const workflowStore = useWorkflowStore()
    return workflowStore.currentThreadId
  }

  // WebSocket event handlers
  const realtimeStore = useRealtimeStore()

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_DATA_UPDATED, (msg) => {
    const threadId = getThreadId()
    if (msg.thread_id === threadId) {
      const p = msg.payload as { data_type?: string; data?: unknown }
      if (p.data_type && p.data) {
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
    const threadId = getThreadId()
    if (!threadId) {
      error.value = 'No active workflow thread'
      return
    }

    isLoading.value = true
    error.value = null
    try {
      // Store draft locally
      draftContent.value = draft
      userViralLinks.value = viralLinks || []

      // Submit to backend (would need new API endpoint)
      // For now, we update state via WebSocket events
      // await workflowApi.submitDraft({ thread_id: threadId, draft, viral_links: viralLinks })
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function selectVersion(choice: VersionChoice) {
    const threadId = getThreadId()
    if (!threadId) {
      error.value = 'No active workflow thread'
      return
    }

    isLoading.value = true
    error.value = null
    try {
      // Store selection locally
      selectedVersion.value = choice.version_id

      // Submit to backend (would need new API endpoint)
      // For now, we update state via WebSocket events
      // await workflowApi.selectVersion({ thread_id: threadId, choice })
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

// Import workflow store for thread ID access
import { useWorkflowStore } from './workflow'