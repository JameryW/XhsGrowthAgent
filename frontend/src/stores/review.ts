import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as reviewApi from '@/api/review'
import type { PendingReview, ContentStatus, ReviewDecision, Revision } from '@/types'

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