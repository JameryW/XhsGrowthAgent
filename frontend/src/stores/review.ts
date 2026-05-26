import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as reviewApi from '@/api/review'
import type { PendingReview, ContentStatus, ReviewDecision, Revision } from '@/types'
import type { ContentPlan, CopyContent, VisualPlan } from '@/types/workflow'
import { useRealtimeStore } from './realtime'
import { useWorkflowStore } from './workflow'
import { EventType } from '@/realtime/events'

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

  const contentPlan = computed(() => pendingReview.value?.content_plan)
  const copyContent = computed(() => pendingReview.value?.copy_content)
  const visualPlan = computed(() => pendingReview.value?.visual_plan)

  // WebSocket event handlers
  const realtimeStore = useRealtimeStore()
  const workflowStore = useWorkflowStore()

  // 注册审核事件处理器
  realtimeStore.wsService.onEvent(EventType.REVIEW_PENDING, (payload: unknown) => {
    const p = payload as {
      thread_id?: string
      content_plan?: ContentPlan
      copy_content?: CopyContent
      visual_plan?: VisualPlan
    }
    if (p.thread_id === workflowStore.currentThreadId) {
      // Update pendingReview with incoming content
      pendingReview.value = {
        status: 'awaiting_review',
        content_plan: p.content_plan,
        copy_content: p.copy_content,
        visual_plan: p.visual_plan,
      }
      // TODO: showToast("info", "收到新内容待审核") when Toast component created
    }
  })

  realtimeStore.wsService.onEvent(EventType.REVIEW_APPROVED, () => {
    // TODO: showToast("success", "审核通过，即将发布") when Toast component created
  })

  realtimeStore.wsService.onEvent(EventType.REVIEW_REJECTED, () => {
    // TODO: showToast("warning", "审核已拒绝") when Toast component created
  })

  realtimeStore.wsService.onEvent(EventType.REVIEW_NEEDS_REVISION, () => {
    // TODO: showToast("info", "内容需要修改") when Toast component created
  })

  // Actions
  async function fetchPendingReview(tid: string) {
    threadId.value = tid
    isLoading.value = true
    error.value = null
    try {
      pendingReview.value = await reviewApi.getPendingReview(tid)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function submitDecision(dec: ContentStatus, comment?: string, revs?: Revision[]) {
    if (!threadId.value) return
    isLoading.value = true
    error.value = null
    try {
      const result = await reviewApi.submitReview(threadId.value, {
        decision: dec as ReviewDecision,
        comments: comment || '',
        revisions: revs || [],
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
    fetchPendingReview,
    submitDecision,
    setComments,
    addRevision,
    clearRevisions,
  }
})