import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as reviewApi from '@/api/review'
import type { PendingReview, ContentStatus, ReviewDecision, Revision, PublishOptions } from '@/types'
import type { ContentPlan, CopyContent, VisualPlan } from '@/types/workflow'
import type { ContentVersion } from '@/types/optimization'
import { useRealtimeStore } from './realtime'
import { useWorkflowStore } from './workflow'
import { useToastStore } from './toast'
import { EventType } from '@/realtime/events'
import i18n from '@/locales'

const { t } = i18n.global

export const useReviewStore = defineStore('review', () => {
  // ── Single-workflow state (legacy + focused review) ──
  const threadId = ref<string | null>(null)
  const pendingReview = ref<PendingReview | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const decision = ref<ContentStatus | null>(null)
  const comments = ref('')
  const revisions = ref<Revision[]>([])

  // ── Multi-workflow queue state ──
  const pendingReviews = ref<Map<string, PendingReview>>(new Map())
  const loadingReviewIds = ref<Set<string>>(new Set())
  const submittingThreadId = ref<string | null>(null)

  // Computed
  const hasPendingReview = computed(() =>
    pendingReview.value?.status === 'awaiting_review'
  )

  const queueCount = computed(() => pendingReviews.value.size)

  // Helper to parse raw_content if fields are missing
  function parseCopyContent(raw: CopyContent | undefined): CopyContent | undefined {
    if (!raw) return undefined
    if (raw.selected_title || raw.body_text) return raw
    if (raw.raw_content) {
      try {
        let jsonStr = raw.raw_content.trim()
        if (jsonStr.includes('```json')) {
          jsonStr = jsonStr.split('```json')[1].split('```')[0].trim()
        } else if (jsonStr.includes('```')) {
          const parts = jsonStr.split('```')
          jsonStr = parts[1]?.trim() || jsonStr
        }
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

  // ── Queue helpers: get parsed content for a specific thread ──
  function getQueueCopyContent(tid: string): CopyContent | undefined {
    return parseCopyContent(pendingReviews.value.get(tid)?.copy_content)
  }
  function getQueueVisualPlan(tid: string): VisualPlan | undefined {
    return pendingReviews.value.get(tid)?.visual_plan
  }
  function getQueueVersionHistory(tid: string): ContentVersion[] {
    return pendingReviews.value.get(tid)?.version_history || []
  }
  function isQueueItemLoading(tid: string): boolean {
    return loadingReviewIds.value.has(tid)
  }
  function isQueueItemSubmitting(tid: string): boolean {
    return submittingThreadId.value === tid
  }

  // WebSocket event handlers
  const realtimeStore = useRealtimeStore()
  const workflowStore = useWorkflowStore()
  const toastStore = useToastStore()

  // 注册审核事件处理器 - 收到待审核内容时更新对应 store
  realtimeStore.wsService.onEvent(EventType.REVIEW_PENDING, (msg) => {
    const p = msg.payload as {
      content_plan?: ContentPlan
      copy_content?: CopyContent
      visual_plan?: VisualPlan
      version_history?: ContentVersion[]
    }
    const review: PendingReview = {
      status: 'awaiting_review',
      content_plan: p.content_plan,
      copy_content: p.copy_content,
      visual_plan: p.visual_plan,
      version_history: p.version_history || [],
    }
    // Update multi-workflow queue
    if (msg.thread_id) {
      pendingReviews.value.set(msg.thread_id, review)
      // Force reactivity on Map
      pendingReviews.value = new Map(pendingReviews.value)
    }
    // Legacy: update single-workflow state if it matches
    if (msg.thread_id === workflowStore.currentThreadId) {
      pendingReview.value = review
    }
    toastStore.info(t('workflow.awaitingReview'), t('workflow.awaitingReviewMessage'))
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

  // ── Actions ──

  /** Fetch single pending review (legacy + focused mode) */
  async function fetchPendingReview(tid: string) {
    threadId.value = tid
    isLoading.value = true
    error.value = null
    try {
      pendingReview.value = await reviewApi.getPendingReview(tid)
    } catch (e: any) {
      if (e.code === 'ERROR_REVIEW_NOT_PENDING' || e.code === 'ERROR_WORKFLOW_NOT_FOUND') {
        pendingReview.value = null
      } else {
        error.value = e.message
      }
    } finally {
      isLoading.value = false
    }
  }

  /** Fetch review content for a specific thread into the queue map */
  async function fetchQueueReview(tid: string) {
    if (pendingReviews.value.has(tid) || loadingReviewIds.value.has(tid)) return
    loadingReviewIds.value.add(tid)
    try {
      const review = await reviewApi.getPendingReview(tid)
      pendingReviews.value.set(tid, review)
      pendingReviews.value = new Map(pendingReviews.value)
    } catch (e: any) {
      // Not pending or not found — skip silently
      if (e.code !== 'ERROR_REVIEW_NOT_PENDING' && e.code !== 'ERROR_WORKFLOW_NOT_FOUND') {
        console.warn(`Failed to fetch review for ${tid}:`, e.message)
      }
    } finally {
      loadingReviewIds.value.delete(tid)
    }
  }

  /** Submit decision for a specific thread (queue mode) */
  async function submitQueueDecision(
    tid: string,
    dec: ContentStatus,
    comment?: string,
    revs?: Revision[],
    pubOptions?: PublishOptions,
  ) {
    submittingThreadId.value = tid
    isLoading.value = true
    error.value = null
    try {
      const result = await reviewApi.submitReview(tid, {
        decision: dec as ReviewDecision,
        comments: comment || '',
        revisions: revs || [],
        publish_options: pubOptions,
      })
      decision.value = dec
      // Remove from queue on success
      pendingReviews.value.delete(tid)
      pendingReviews.value = new Map(pendingReviews.value)
      // Clear legacy if it matched
      if (threadId.value === tid) {
        pendingReview.value = null
      }
      return result
    } catch (e: any) {
      error.value = e.message
      throw e
    } finally {
      isLoading.value = false
      submittingThreadId.value = null
    }
  }

  /** Legacy submitDecision — delegates to current threadId */
  async function submitDecision(dec: ContentStatus, comment?: string, revs?: Revision[], pubOptions?: PublishOptions) {
    if (!threadId.value) return
    return submitQueueDecision(threadId.value, dec, comment, revs, pubOptions)
  }

  /** Remove a thread from the queue (e.g. no longer awaiting_review) */
  function removeFromQueue(tid: string) {
    pendingReviews.value.delete(tid)
    pendingReviews.value = new Map(pendingReviews.value)
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
    // Legacy single-workflow
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
    // Multi-workflow queue
    pendingReviews,
    loadingReviewIds,
    submittingThreadId,
    queueCount,
    getQueueCopyContent,
    getQueueVisualPlan,
    getQueueVersionHistory,
    isQueueItemLoading,
    isQueueItemSubmitting,
    fetchQueueReview,
    submitQueueDecision,
    removeFromQueue,
    parseCopyContent,
  }
})
