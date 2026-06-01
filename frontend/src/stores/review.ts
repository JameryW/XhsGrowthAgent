import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as reviewApi from '@/api/review'
import type { PendingReview, ContentStatus, ReviewDecision, Revision, PublishOptions } from '@/types'
import type { ContentPlan, CopyContent, VisualPlan, ContentVersion } from '@/types/workflow'
import { useRealtimeStore } from './realtime'
import { useWorkflowStore } from './workflow'
import { useToastStore } from './toast'
import { EventType } from '@/realtime/events'
import i18n from '@/locales'

const { t } = i18n.global

export const useReviewStore = defineStore('review', () => {
  // State
  const threadId = ref<string | null>(null)
  const pendingReview = ref<PendingReview | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const decision = ref<ContentStatus | null>(null)
  const comments = ref('')
  const revisions = ref<Revision[]>([])

  // Computed
  const hasPendingReview = computed(() =>
    pendingReview.value?.status === 'awaiting_review'
  )

  // Helper to parse raw_content if fields are missing
  function parseCopyContent(raw: CopyContent | undefined): CopyContent | undefined {
    if (!raw) return undefined
    // If expected fields exist, return as-is
    if (raw.selected_title || raw.body_text) return raw
    // If raw_content exists, try to parse it
    if (raw.raw_content) {
      try {
        // Remove markdown code block markers if present
        let jsonStr = raw.raw_content.trim()
        if (jsonStr.includes('```json')) {
          jsonStr = jsonStr.split('```json')[1].split('```')[0].trim()
        } else if (jsonStr.includes('```')) {
          const parts = jsonStr.split('```')
          jsonStr = parts[1]?.trim() || jsonStr
        }
        // Find JSON object boundaries
        const start = jsonStr.indexOf('{')
        const end = jsonStr.lastIndexOf('}')
        if (start !== -1 && end !== -1 && end > start) {
          jsonStr = jsonStr.slice(start, end + 1)
        }
        const parsed = JSON.parse(jsonStr)
        return parsed as CopyContent
      } catch {
        return raw
      }
    }
    return raw
  }

  const contentPlan = computed(() => pendingReview.value?.content_plan)
  const copyContent = computed(() => parseCopyContent(pendingReview.value?.copy_content))
  const visualPlan = computed(() => pendingReview.value?.visual_plan)
  const versionHistory = computed(() => pendingReview.value?.version_history || [])

  // WebSocket event handlers
  const realtimeStore = useRealtimeStore()
  const workflowStore = useWorkflowStore()
  const toastStore = useToastStore()

  // 注册审核事件处理器 - 收到待审核内容时显示醒目通知
  realtimeStore.wsService.onEvent(EventType.REVIEW_PENDING, (msg) => {
    if (msg.thread_id === workflowStore.currentThreadId) {
      const p = msg.payload as {
        content_plan?: ContentPlan
        copy_content?: CopyContent
        visual_plan?: VisualPlan
        version_history?: ContentVersion[]
      }
      // Update pendingReview with incoming content (enriched by backend)
      pendingReview.value = {
        status: 'awaiting_review',
        content_plan: p.content_plan,
        copy_content: p.copy_content,
        visual_plan: p.visual_plan,
        version_history: p.version_history || [],
      }
      // 醒目通知: 内容已准备好，等待审核
      toastStore.info(t('workflow.awaitingReview'), t('workflow.awaitingReviewMessage'))
    }
  })

  realtimeStore.wsService.onEvent(EventType.REVIEW_APPROVED, () => {
    toastStore.success(t('review.success'), t('workflow.completedMessage'))
  })

  realtimeStore.wsService.onEvent(EventType.REVIEW_REJECTED, () => {
    toastStore.warning(t('review.reject'), t('review.rejectDesc'))
  })

  realtimeStore.wsService.onEvent(EventType.REVIEW_NEEDS_REVISION, () => {
    toastStore.info(t('review.revise'), t('review.reviseDesc'))
  })

  // Actions
  async function fetchPendingReview(tid: string) {
    threadId.value = tid
    isLoading.value = true
    error.value = null
    try {
      pendingReview.value = await reviewApi.getPendingReview(tid)
    } catch (e: any) {
      // No pending review is normal — not an error worth showing
      if (e.code === 'ERROR_REVIEW_NOT_PENDING' || e.code === 'ERROR_WORKFLOW_NOT_FOUND') {
        pendingReview.value = null
      } else {
        error.value = e.message
      }
    } finally {
      isLoading.value = false
    }
  }

  async function submitDecision(dec: ContentStatus, comment?: string, revs?: Revision[], pubOptions?: PublishOptions) {
    if (!threadId.value) return
    isLoading.value = true
    error.value = null
    try {
      const result = await reviewApi.submitReview(threadId.value, {
        decision: dec as ReviewDecision,
        comments: comment || '',
        revisions: revs || [],
        publish_options: pubOptions,
      })
      decision.value = dec
      pendingReview.value = null
      return result
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      isLoading.value = false
    }
  }

  function setComments(comment: string) {
    comments.value = comment
  }

  function addRevision(rev: Revision) {
    revisions.value.push(rev)
  }

  function clearRevisions() {
    revisions.value = []
  }

  return {
    threadId,
    pendingReview,
    isLoading,
    error,
    decision,
    comments,
    revisions,
    hasPendingReview,
    contentPlan,
    copyContent,
    visualPlan,
    versionHistory,
    fetchPendingReview,
    submitDecision,
    setComments,
    addRevision,
    clearRevisions,
  }
})