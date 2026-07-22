<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch, type WatchStopHandle } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import PageHeader from '@/components/PageHeader.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import CelebrationEffect from '@/components/CelebrationEffect.vue'
import WorkflowCardBody from '@/components/WorkflowCardBody.vue'
import EvaluationRadar from '@/components/charts/EvaluationRadar.vue'
import { ReviewSkeleton } from '@/components/skeletons'
import { useReviewStore, useToastStore, useAccountsStore } from '@/stores'
import { listWorkflows, getWorkflowStatus, uploadImages } from '@/api/workflow'
import { updateCopy } from '@/api/review'
import { getEvaluationResult } from '@/api/evaluation'
import type { ContentStatus } from '@/types'
import type { WorkflowListItem, WorkflowStateResponse } from '@/types/workflow'
import type { EvaluationResult } from '@/types/evaluation'
import { SCORE_THRESHOLDS, scoreTier, type ScoreThresholds, DIMENSION_LABEL_KEYS } from '@/constants/evaluation'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const reviewStore = useReviewStore()
const toastStore = useToastStore()
const accountsStore = useAccountsStore()

// ── Queue state ──
const destroyed = ref(false)
const workflows = ref<WorkflowListItem[]>([])
const workflowDetails = ref<Map<string, WorkflowStateResponse>>(new Map())
const loadingDetailIds = ref<Set<string>>(new Set())
const listLoaded = ref(false)
const error = ref<string | null>(null)
const expandedThreadId = ref<string | null>(null)

// Detail lazy-load pump (same pattern as Showcase)
const pendingDetailIds = new Set<string>()
let activeDetailLoads = 0
let detailPumpTimer: number | null = null
const DETAIL_CONCURRENCY = 3

function queueDetail(threadId: string) {
  if (workflowDetails.value.has(threadId) || loadingDetailIds.value.has(threadId)) return
  pendingDetailIds.add(threadId)
  loadingDetailIds.value.add(threadId)
  scheduleDetailPump()
}

function scheduleDetailPump() {
  if (detailPumpTimer !== null || destroyed.value) return
  detailPumpTimer = window.setTimeout(() => {
    detailPumpTimer = null
    if (!destroyed.value) pumpDetailQueue()
  }, 24)
}

function pumpDetailQueue() {
  while (activeDetailLoads < DETAIL_CONCURRENCY && pendingDetailIds.size > 0) {
    const tid = pendingDetailIds.values().next().value as string
    pendingDetailIds.delete(tid)
    activeDetailLoads += 1
    getWorkflowStatus(tid, { suppressToast: true })
      .then((state) => { if (!destroyed.value) workflowDetails.value.set(tid, state) })
      .catch(() => {})
      .finally(() => {
        loadingDetailIds.value.delete(tid)
        activeDetailLoads -= 1
        if (!destroyed.value && pendingDetailIds.size > 0) scheduleDetailPump()
      })
  }
}

// Also lazy-load review content when expanded
function loadReviewIfExpanded(tid: string) {
  if (!reviewStore.pendingReviews.has(tid) && !reviewStore.isQueueItemLoading(tid)) {
    reviewStore.fetchQueueReview(tid)
  }
  // Initialize edit fields from loaded copy content (deferred to next tick
  // to allow fetchQueueReview to populate the store first)
  if (!cardEditInitialized.value.has(tid)) {
    // Try immediately; if copy not loaded yet, the watch below will catch it
    initEditFields(tid)
  }
  // Load evaluation result for this thread
  loadEvaluation(tid)
}

function loadVisibleDetails() {
  // Always load the expanded one first
  if (expandedThreadId.value) {
    queueDetail(expandedThreadId.value)
    loadReviewIfExpanded(expandedThreadId.value)
  }
  for (const wf of workflows.value) {
    queueDetail(wf.thread_id)
  }
}

function workflowItemFromState(state: WorkflowStateResponse): WorkflowListItem {
  const source = state as WorkflowStateResponse & Partial<WorkflowListItem>
  const now = new Date().toISOString()
  return {
    thread_id: state.thread_id,
    account_id: source.account_id || '',
    phase: state.phase || 'reviewing',
    status: 'awaiting_review',
    dry_run: source.dry_run ?? false,
    auto_publish: source.auto_publish ?? false,
    progress_percent: state.progress_percent ?? 0,
    workflow_mode: state.workflow_mode || 'trend',
    label: state.label || state.thread_id.slice(-8),
    created_at: state.created_at || now,
    updated_at: state.updated_at || state.created_at || now,
    error: state.error ?? null,
  }
}

function fallbackWorkflowItem(threadId: string): WorkflowListItem {
  const now = new Date().toISOString()
  return {
    thread_id: threadId,
    account_id: '',
    phase: 'reviewing',
    status: 'awaiting_review',
    dry_run: false,
    auto_publish: false,
    progress_percent: 80,
    workflow_mode: 'trend',
    label: threadId.slice(-8),
    created_at: now,
    updated_at: now,
    error: null,
  }
}

function upsertWorkflow(item: WorkflowListItem) {
  workflows.value = [
    item,
    ...workflows.value.filter(w => w.thread_id !== item.thread_id),
  ]
}

async function ensureWorkflowInQueue(threadId: string) {
  if (workflows.value.some(w => w.thread_id === threadId)) {
    queueDetail(threadId)
    return
  }

  let state = workflowDetails.value.get(threadId)
  try {
    if (!state) {
      state = await getWorkflowStatus(threadId, { suppressToast: true })
      if (destroyed.value) return
      workflowDetails.value.set(threadId, state)
    }
  } catch {
    // The websocket event is enough to show the queue card; details remain lazy.
  }

  if (destroyed.value) return
  upsertWorkflow(state ? workflowItemFromState(state) : fallbackWorkflowItem(threadId))
  listLoaded.value = true
  queueDetail(threadId)
}

// ── Fetch review queue ──
async function fetchReviewQueue() {
  error.value = null
  try {
    const result = await listWorkflows({ status: 'awaiting_review', limit: 50 }, { suppressToast: true })
    if (destroyed.value) return
    workflows.value = result.workflows
    listLoaded.value = true
    for (const threadId of reviewStore.pendingReviews.keys()) {
      void ensureWorkflowInQueue(threadId)
    }
  } catch (e: any) {
    if (!destroyed.value) error.value = e.message
  }
}

onMounted(async () => {
  const threadId = route.params.threadId
  if (typeof threadId === 'string' && threadId) {
    expandedThreadId.value = threadId
  }
  await fetchReviewQueue()
  if (typeof threadId === 'string' && threadId && !workflows.value.some((wf) => wf.thread_id === threadId)) {
    await ensureWorkflowInQueue(threadId)
  }
})
onUnmounted(() => {
  destroyed.value = true
  if (detailPumpTimer !== null) window.clearTimeout(detailPumpTimer)
  for (const stop of watchStops) stop()
})

const watchStops: WatchStopHandle[] = []
watchStops.push(
  watch([workflows, expandedThreadId], () => { if (!destroyed.value) loadVisibleDetails() }, { immediate: true })
)
watchStops.push(
  watch(
    () => Array.from(reviewStore.pendingReviews.keys()),
    (threadIds) => {
      if (destroyed.value) return
      for (const threadId of threadIds) {
        void ensureWorkflowInQueue(threadId)
        // Initialize edit fields when review content arrives
        if (expandedThreadId.value === threadId) {
          initEditFields(threadId)
        }
      }
    },
    { immediate: true }
  )
)

// ── Per-card review state ──
// We keep per-thread review form state to avoid cross-card conflicts
const cardComments = ref(new Map<string, string>())
const cardRevisionReason = ref(new Map<string, string>())
const cardRejectReason = ref(new Map<string, string>())
const cardTitleIssue = ref(new Map<string, string>())
const cardBodyIssue = ref(new Map<string, string>())
const cardTagsIssue = ref(new Map<string, string>())
const cardVisualIssue = ref(new Map<string, string>())
const cardShowStructured = ref(new Map<string, boolean>())

function getMC(tid: string): string { return cardComments.value.get(tid) ?? '' }
function getMRR(tid: string): string { return cardRevisionReason.value.get(tid) ?? '' }
function getMRJR(tid: string): string { return cardRejectReason.value.get(tid) ?? '' }
function getMTI(tid: string): string { return cardTitleIssue.value.get(tid) ?? '' }
function getMBI(tid: string): string { return cardBodyIssue.value.get(tid) ?? '' }
function getMTGI(tid: string): string { return cardTagsIssue.value.get(tid) ?? '' }
function getMVI(tid: string): string { return cardVisualIssue.value.get(tid) ?? '' }
function getMSS(tid: string): boolean { return cardShowStructured.value.get(tid) ?? false }

function setMC(tid: string, v: string) { cardComments.value.set(tid, v); cardComments.value = new Map(cardComments.value) }
function setMRR(tid: string, v: string) { cardRevisionReason.value.set(tid, v); cardRevisionReason.value = new Map(cardRevisionReason.value) }
function setMRJR(tid: string, v: string) { cardRejectReason.value.set(tid, v); cardRejectReason.value = new Map(cardRejectReason.value) }
function setMTI(tid: string, v: string) { cardTitleIssue.value.set(tid, v); cardTitleIssue.value = new Map(cardTitleIssue.value) }
function setMBI(tid: string, v: string) { cardBodyIssue.value.set(tid, v); cardBodyIssue.value = new Map(cardBodyIssue.value) }
function setMTGI(tid: string, v: string) { cardTagsIssue.value.set(tid, v); cardTagsIssue.value = new Map(cardTagsIssue.value) }
function setMVI(tid: string, v: string) { cardVisualIssue.value.set(tid, v); cardVisualIssue.value = new Map(cardVisualIssue.value) }
function setMSS(tid: string, v: boolean) { cardShowStructured.value.set(tid, v); cardShowStructured.value = new Map(cardShowStructured.value) }

// ── Per-card copy editing state ──
// Editable fields initialized from reviewStore copy_content when expanded.
const cardEditTitle = ref(new Map<string, string>())
const cardEditBody = ref(new Map<string, string>())
const cardEditTags = ref(new Map<string, string>())
const cardEditInitialized = ref(new Set<string>())
const cardSavingCopy = ref(new Set<string>())
const cardRegenerating = ref(new Set<string>())

// ── Per-card evaluation result state ──
const cardEvaluation = ref(new Map<string, EvaluationResult | null>())
const cardEvaluationThresholds = ref(new Map<string, ScoreThresholds>())
const cardEvaluationLoading = ref(new Set<string>())

function getET(tid: string): string { return cardEditTitle.value.get(tid) ?? '' }
function getEB(tid: string): string { return cardEditBody.value.get(tid) ?? '' }
function getETG(tid: string): string { return cardEditTags.value.get(tid) ?? '' }

function setET(tid: string, v: string) { cardEditTitle.value.set(tid, v); cardEditTitle.value = new Map(cardEditTitle.value) }
function setEB(tid: string, v: string) { cardEditBody.value.set(tid, v); cardEditBody.value = new Map(cardEditBody.value) }
function setETG(tid: string, v: string) { cardEditTags.value.set(tid, v); cardEditTags.value = new Map(cardEditTags.value) }

function initEditFields(tid: string) {
  if (cardEditInitialized.value.has(tid)) return
  const copy = reviewStore.getQueueCopyContent(tid)
  if (!copy) return
  cardEditTitle.value.set(tid, copy.selected_title || '')
  cardEditBody.value.set(tid, copy.body_text || '')
  cardEditTags.value.set(tid, (copy.hashtags || []).join(', '))
  cardEditTitle.value = new Map(cardEditTitle.value)
  cardEditBody.value = new Map(cardEditBody.value)
  cardEditTags.value = new Map(cardEditTags.value)
  cardEditInitialized.value.add(tid)
}

// Parse comma-separated tags string into string[]
function parseTags(tagsStr: string): string[] {
  return tagsStr
    .split(',')
    .map(t => t.trim())
    .filter(t => t.length > 0)
}

// ── Evaluation helpers ──
async function loadEvaluation(tid: string) {
  if (cardEvaluation.value.has(tid) || cardEvaluationLoading.value.has(tid)) return
  cardEvaluationLoading.value.add(tid)
  try {
    const resp = await getEvaluationResult(tid, { suppressToast: true })
    cardEvaluation.value.set(tid, resp.has_evaluation ? resp.evaluation_result : null)
    cardEvaluation.value = new Map(cardEvaluation.value)
    cardEvaluationThresholds.value.set(tid, resp.thresholds ?? SCORE_THRESHOLDS)
    cardEvaluationThresholds.value = new Map(cardEvaluationThresholds.value)
  } catch {
    // Silently skip — evaluation may not exist yet
    cardEvaluation.value.set(tid, null)
    cardEvaluation.value = new Map(cardEvaluation.value)
    cardEvaluationThresholds.value.set(tid, SCORE_THRESHOLDS)
    cardEvaluationThresholds.value = new Map(cardEvaluationThresholds.value)
  } finally {
    cardEvaluationLoading.value.delete(tid)
  }
}

function getEvaluation(tid: string): EvaluationResult | null {
  return cardEvaluation.value.get(tid) ?? null
}

function getEvaluationThresholds(tid: string): ScoreThresholds {
  return cardEvaluationThresholds.value.get(tid) ?? SCORE_THRESHOLDS
}

// Decision badge color tier
const DECISION_KEYS: Record<string, string> = {
  approved: 'review.evaluation.decision.approved',
  needs_revision: 'review.evaluation.decision.needs_revision',
  rejected: 'review.evaluation.decision.rejected',
}

function decisionClass(d: string | null | undefined): string {
  if (d === 'approved') return 'decision-approved'
  if (d === 'needs_revision') return 'decision-revision'
  return 'decision-rejected'
}

function scoreClass(s: number | null | undefined, thresholds: ScoreThresholds = SCORE_THRESHOLDS): string {
  return `score-${scoreTier(s, thresholds)}`
}

// Dimension i18n label keys (mirror EvaluationView)
function dimLabel(dim: string): string {
  return t(DIMENSION_LABEL_KEYS[dim] ?? 'evaluation.dim.unknown', { dim })
}

// ── Save copy & re-evaluate ──
async function handleSaveCopy(tid: string) {
  cardSavingCopy.value.add(tid)
  try {
    const parsedTags = parseTags(getETG(tid))
    const resp = await updateCopy(tid, {
      title: getET(tid) || undefined,
      body_text: getEB(tid) || undefined,
      // Mirror title/body semantics: empty = "don't touch" (undefined),
      // so the backend skips the field instead of clearing existing hashtags.
      hashtags: parsedTags.length > 0 ? parsedTags : undefined,
    })
    // Update evaluation display from response
    const ev = (resp.evaluation_result && Object.keys(resp.evaluation_result).length > 0)
      ? resp.evaluation_result as EvaluationResult
      : null
    cardEvaluation.value.set(tid, ev)
    cardEvaluation.value = new Map(cardEvaluation.value)

    // Refresh workflow detail to reflect updated copy_content in state
    try {
      const state = await getWorkflowStatus(tid)
      if (!destroyed.value) workflowDetails.value.set(tid, state)
    } catch { /* non-critical */ }

    if (resp.warning) {
      toastStore.warning(t('review.editCopy.saveSuccess'), resp.warning)
    } else {
      toastStore.success(t('review.editCopy.saveSuccess'), '')
    }
  } catch (e: any) {
    toastStore.error(t('review.editCopy.saveFailed'), e.message)
  } finally {
    cardSavingCopy.value.delete(tid)
  }
}

// ── Regenerate from current copy ──
// Submits a needs_revision decision with the current edited copy as the
// revision hint, causing the copywriter to regenerate using it as reference.
async function handleRegenerate(tid: string) {
  cardRegenerating.value.add(tid)
  try {
    const hintParts: string[] = []
    if (getET(tid)) hintParts.push(`${t('review.titlePrefix')}: ${getET(tid)}`)
    if (getEB(tid)) hintParts.push(`${t('review.bodyPrefix')}: ${getEB(tid).slice(0, 200)}`)
    const tags = parseTags(getETG(tid))
    if (tags.length) hintParts.push(`${t('review.tagsPrefix')}: ${tags.join(', ')}`)
    const feedback = hintParts.length
      ? `${t('review.editCopy.regenerateHint')} ${hintParts.join('; ')}`
      : t('review.editCopy.regenerateHint')

    await reviewStore.submitQueueDecision(tid, 'needs_revision', feedback)
    toastStore.info(t('review.editCopy.regenerateSuccess'), '')

    // Remove from queue and collapse (workflow resumes to copywriter)
    workflows.value = workflows.value.filter(w => w.thread_id !== tid)
    if (expandedThreadId.value === tid) expandedThreadId.value = null
    // Clear edit state
    cardEditInitialized.value.delete(tid)
    cardEvaluation.value.delete(tid)
    cardEvaluation.value = new Map(cardEvaluation.value)
    cardEvaluationThresholds.value.delete(tid)
    cardEvaluationThresholds.value = new Map(cardEvaluationThresholds.value)
  } catch (e: any) {
    toastStore.error(t('review.editCopy.regenerateFailed'), e.message)
  } finally {
    cardRegenerating.value.delete(tid)
  }
}

// ── Confirmation modal (global — one at a time) ──
const showConfirmModal = ref(false)
const pendingDecision = ref<ContentStatus | null>(null)
const pendingDecisionThreadId = ref<string | null>(null)
const confirmModalTitle = ref('')
const confirmModalMessage = ref('')
const confirmModalAction = ref('')
const confirmModalVariant = ref<'danger' | 'warning' | 'info'>('warning')

// Publish confirmation
const showPublishConfirm = ref(false)
// ponytail: null = explicitly unset, forced choice before publish allowed.
// Resets to null every time the modal opens so each approval is a conscious decision.
type PublishMode = 'dry' | 'live' | null
const publishMode = ref<PublishMode>(null)
const publishAccountId = ref<string | null>(null)
// Celebration effect
const showCelebration = ref(false)

// ── Image upload state ──
const imageUploadMap = ref<Map<string, string[]>>(new Map())  // thread_id -> preview URLs
const imageUploading = ref<Map<string, boolean>>(new Map())

async function handleImageUpload(threadId: string, event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return
  const files = Array.from(input.files).slice(0, 9)
  if (!files.length) return

  imageUploading.value.set(threadId, true)
  imageUploading.value = new Map(imageUploading.value)

  try {
    // Show local previews immediately
    const previews = files.map(f => URL.createObjectURL(f))
    const existing = imageUploadMap.value.get(threadId) || []
    imageUploadMap.value.set(threadId, [...existing, ...previews])
    imageUploadMap.value = new Map(imageUploadMap.value)

    const result = await uploadImages(threadId, files)
    if (destroyed.value) return
    toastStore.success(t('common.success'), `${result.count} ${t('review.imagesUploaded')}`)

    // Refresh workflow detail to get updated visual_plan
    try {
      const state = await getWorkflowStatus(threadId)
      workflowDetails.value.set(threadId, state)
    } catch { /* non-critical */ }
  } catch (e: any) {
    toastStore.error(e.message || t('common.error'))
    // Remove failed previews
    imageUploadMap.value.delete(threadId)
    imageUploadMap.value = new Map(imageUploadMap.value)
  } finally {
    imageUploading.value.delete(threadId)
    imageUploading.value = new Map(imageUploading.value)
    input.value = ''  // reset for re-upload
  }
}

function removeImage(threadId: string, index: number) {
  const paths = imageUploadMap.value.get(threadId)
  if (paths) {
    URL.revokeObjectURL(paths[index])
    paths.splice(index, 1)
    imageUploadMap.value = new Map(imageUploadMap.value)
  }
}

function getUploadedImages(threadId: string): string[] {
  return imageUploadMap.value.get(threadId) || []
}

function getServerImageCount(threadId: string): number {
  const detail = workflowDetails.value.get(threadId)
  return (detail as any)?.visual_plan?.image_paths?.length || 0
}

// ── Helpers ──
const isEmpty = computed(() => listLoaded.value && workflows.value.length === 0)

function formatDate(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString(locale.value || undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function goDashboard() { router.push('/dashboard') }
function goHome() { router.push('/start') }

function toggleExpand(tid: string) {
  if (expandedThreadId.value === tid) {
    expandedThreadId.value = null
  } else {
    expandedThreadId.value = tid
    queueDetail(tid)
    loadReviewIfExpanded(tid)
  }
}

// ── Build feedback for a specific thread ──
function buildFeedback(tid: string, decision: ContentStatus): string {
  const parts: string[] = []
  const comment = getMC(tid)
  if (comment) parts.push(comment)

  if (decision === 'needs_revision' || decision === 'rejected') {
    const structured: string[] = []
    if (getMTI(tid)) structured.push(`${t('review.titlePrefix')}: ${getMTI(tid)}`)
    if (getMBI(tid)) structured.push(`${t('review.bodyPrefix')}: ${getMBI(tid)}`)
    if (getMTGI(tid)) structured.push(`${t('review.tagsPrefix')}: ${getMTGI(tid)}`)
    if (getMVI(tid)) structured.push(`${t('review.visualPrefix')}: ${getMVI(tid)}`)
    if (structured.length) parts.push(`${t('review.structuredPrefix')} ${structured.join('; ')}`)
  }

  if (decision === 'rejected') {
    const rr = getMRJR(tid)
    if (rr) parts.push(`${t('review.rejectPrefix')} ${rr}`)
  }
  if (decision === 'needs_revision') {
    const vrr = getMRR(tid)
    if (vrr) parts.push(`${t('review.revisionPrefix')} ${vrr}`)
  }

  return parts.join('\n')
}

function validateDecision(tid: string, decision: ContentStatus): string | null {
  if (decision === 'rejected' && !getMRJR(tid).trim()) {
    return t('review.rejectReason')
  }
  if (decision === 'needs_revision' && !getMRR(tid).trim()) {
    return t('review.revisionReason')
  }
  return null
}

// ── Decision flow ──
const requestDecision = async (tid: string, decision: ContentStatus) => {
  const validationError = validateDecision(tid, decision)
  if (validationError) {
    toastStore.warning(t('review.submitFailedTitle'), validationError)
    return
  }

  pendingDecisionThreadId.value = tid
  pendingDecision.value = decision

  if (decision === 'rejected') {
    confirmModalTitle.value = t('review.confirmReject.title')
    confirmModalMessage.value = t('review.confirmReject.message')
    confirmModalAction.value = t('review.confirmReject.action')
    confirmModalVariant.value = 'danger'
    showConfirmModal.value = true
  } else if (decision === 'approved') {
    // Load accounts for the publish-account picker; default to the active one
    await accountsStore.fetchAccounts().catch(() => {})
    publishAccountId.value = accountsStore.activeAccountId
    // Force explicit mode choice: reset to unset each time the modal opens.
    publishMode.value = null
    showPublishConfirm.value = true
  } else {
    executeDecision(tid, decision)
  }
}

const executeDecision = async (tid: string, decision: ContentStatus) => {
  showConfirmModal.value = false
  showPublishConfirm.value = false

  const feedback = buildFeedback(tid, decision)
  const publishOpts = decision === 'approved'
    ? { dry_run: publishMode.value === 'dry', account_id: publishAccountId.value }
    : undefined

  try {
    const result = await reviewStore.submitQueueDecision(tid, decision, feedback, undefined, publishOpts)
    const nextPhase = result?.next_phase || decision

    if (decision === 'approved') {
      if (result?.publish_skipped) {
        toastStore.warning(
          t('review.decisionApproved'),
          `${t('review.publishSkipped')}: ${result?.skip_reason || t('review.publishSkippedReason')}`
        )
      } else {
        const mode = publishMode.value === 'dry' ? t('review.dryRunMode') : t('review.liveMode')
        toastStore.success(
          t('review.decisionApproved'),
          `${t('review.decisionLabel')}: ${decision} · ${mode} → ${nextPhase}`
        )
      }
    } else if (decision === 'rejected') {
      toastStore.warning(t('review.decisionRejected'), `${t('review.decisionLabel')}: ${decision} → ${nextPhase}`)
    } else {
      toastStore.info(t('review.decisionRevision'), `${t('review.decisionLabel')}: ${decision} → ${nextPhase}`)
    }

    // Remove from queue and collapse
    workflows.value = workflows.value.filter(w => w.thread_id !== tid)
    if (expandedThreadId.value === tid) expandedThreadId.value = null

    if (nextPhase === 'completed') showCelebration.value = true
  } catch (e: any) {
    toastStore.error(t('review.submitFailedTitle'), e.message)
  } finally {
    pendingDecision.value = null
    pendingDecisionThreadId.value = null
  }
}

const confirmPublish = () => {
  showPublishConfirm.value = false
  if (pendingDecisionThreadId.value && pendingDecision.value) {
    executeDecision(pendingDecisionThreadId.value, pendingDecision.value)
  }
}

const handleConfirm = () => {
  if (pendingDecisionThreadId.value && pendingDecision.value) {
    executeDecision(pendingDecisionThreadId.value, pendingDecision.value)
  }
}

const handleCancelConfirm = () => {
  showConfirmModal.value = false
  pendingDecision.value = null
  pendingDecisionThreadId.value = null
  toastStore.info(t('review.cancelSuccess'), t('review.cancelMessage'))
}

// Version diff comparison state (reserved for future inline diff in expanded cards)
// const compareMode = ref(false)
// const selectedForCompare = ref<string[]>([])
// function toggleCompareVersion(versionId: string) { ... }
// function diffField(left: string, right: string): boolean { ... }
</script>

<template>
  <div class="app-page-content review-page space-y-4 md:space-y-6">
  <PageHeader
    :title="t('review.title')"
    :description="t('review.subtitle')"
    icon="Clock"
    tone="peach"
  >
    <template #meta>
      <span v-if="workflows.length">{{ t('review.pendingCount', { count: workflows.length }) }}</span>
    </template>
    <template #actions>
      <NeonButton variant="ghost" size="sm" class="min-h-11" @click="fetchReviewQueue" :aria-label="t('common.retry')">
        <AppIcon name="RefreshCw" size="sm" variant="cyan" />
        <span class="hidden sm:inline">{{ t('common.retry') }}</span>
      </NeonButton>
    </template>
  </PageHeader>
  <ReviewSkeleton v-if="!listLoaded" />

  <!-- Empty State -->
  <div v-else-if="isEmpty" class="flex items-center justify-center min-h-[60vh]">
    <div class="rounded-xl md:rounded-2xl p-6 md:p-10 max-w-md w-full liquid-glass text-center">
      <div class="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4 bg-amber-50">
        <AppIcon name="Inbox" size="xl" variant="peach" />
      </div>
      <h2 class="text-lg md:text-xl font-semibold text-slate-700 mb-2">{{ t('review.emptyState.title') }}</h2>
      <p class="text-xs md:text-sm text-slate-500 mb-4">{{ t('review.emptyState.noWorkflow') }}</p>
      <div class="flex gap-3 justify-center">
        <NeonButton variant="pink" size="sm" @click="goDashboard">
          {{ t('review.emptyState.goDashboard') }}
        </NeonButton>
        <NeonButton variant="ghost" size="sm" @click="goHome">
          {{ t('review.emptyState.goHome') }}
        </NeonButton>
      </div>
    </div>
  </div>

  <!-- Review Queue -->
  <div v-else class="space-y-3 md:space-y-4">
    <!-- Error -->
    <div v-if="error" class="rounded-xl p-4 liquid-glass-rose text-center">
      <p class="text-sm text-rose-700 font-medium">{{ error }}</p>
      <button type="button" @click="fetchReviewQueue" class="mt-2 min-h-11 px-4 py-1.5 rounded-lg bg-rose-600 text-white text-xs font-medium hover:bg-rose-700 transition-colors">{{ t('common.retry') }}</button>
    </div>

    <!-- Card list -->
    <div class="space-y-3">
      <div
        v-for="wf in workflows"
        :key="wf.thread_id"
        class="rounded-xl liquid-glass overflow-hidden transition-shadow hover:shadow-md"
        :class="expandedThreadId === wf.thread_id ? 'ring-1 ring-amber-200/60' : ''"
      >
        <!-- Card header: click to expand/collapse -->
        <div
          class="px-4 md:px-5 py-3 flex min-h-11 items-center justify-between cursor-pointer liquid-glass-inset border-b border-white/10"
          @click="toggleExpand(wf.thread_id)"
          role="button"
          tabindex="0"
          :aria-expanded="expandedThreadId === wf.thread_id"
          :aria-controls="`review-panel-${wf.thread_id}`"
          @keydown.enter.prevent="toggleExpand(wf.thread_id)"
          @keydown.space.prevent="toggleExpand(wf.thread_id)"
        >
          <div class="flex items-center gap-2 min-w-0 flex-1">
            <span class="w-2.5 h-2.5 rounded-full bg-amber-500 animate-pulse shrink-0" />
            <span class="text-sm font-semibold text-slate-800 truncate">{{ wf.label || t('review.emptyState.phaseReviewing') }}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-600 shrink-0">{{ t('review.emptyState.phaseReviewing') }}</span>
            <span v-if="wf.workflow_mode" class="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600 shrink-0">{{ wf.workflow_mode }}</span>
          </div>
          <div class="flex items-center gap-2 shrink-0 ml-2">
            <span class="text-[10px] text-slate-400">{{ formatDate(wf.updated_at || wf.created_at) }}</span>
            <AppIcon
              :name="expandedThreadId === wf.thread_id ? 'ChevronUp' : 'ChevronDown'"
              size="sm"
              variant="cyan"
            />
          </div>
        </div>

        <!-- Collapsed: workflow body summary (clickable to expand) -->
        <div v-if="expandedThreadId !== wf.thread_id" class="relative min-h-[40px]">
          <WorkflowCardBody
            v-if="workflowDetails.has(wf.thread_id)"
            :detail="workflowDetails.get(wf.thread_id)"
          />
          <div v-else-if="loadingDetailIds.has(wf.thread_id)" class="px-4 py-3 space-y-2">
            <div class="h-3 w-3/4 rounded bg-slate-100 animate-pulse dark:bg-slate-700" />
            <div class="h-3 w-1/2 rounded bg-slate-100 animate-pulse dark:bg-slate-700" />
          </div>
        </div>

        <!-- Expanded: full review panel -->
        <div v-else :id="`review-panel-${wf.thread_id}`" class="border-t border-white/5">
          <!-- Review content loading -->
          <div v-if="reviewStore.isQueueItemLoading(wf.thread_id) && !reviewStore.pendingReviews.has(wf.thread_id)" class="px-4 py-4 space-y-2">
            <div class="h-3 w-3/4 rounded bg-slate-100 animate-pulse dark:bg-slate-700" />
            <div class="h-3 w-full rounded bg-slate-100 animate-pulse dark:bg-slate-700" />
            <div class="h-3 w-2/3 rounded bg-slate-100 animate-pulse dark:bg-slate-700" />
          </div>

          <!-- Review content loaded -->
          <template v-else-if="reviewStore.pendingReviews.has(wf.thread_id)">
            <div class="p-4 md:p-5 space-y-3 md:space-y-4">
              <!-- Content preview: copy + visual side by side -->
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-3 md:gap-4">
                <!-- Copy content editor (editable while awaiting_review) -->
                <div class="rounded-lg p-3 md:p-4 liquid-glass-inset">
                  <div class="flex items-center gap-2 mb-2 md:mb-3">
                    <div class="w-6 h-6 md:w-7 md:h-7 rounded-md bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center">
                      <AppIcon name="Pencil" size="sm" variant="white" />
                    </div>
                    <span class="text-xs font-semibold text-slate-800">{{ t('review.copyContent') }}</span>
                    <span class="text-[10px] text-violet-400 ml-auto">{{ t('review.editCopy.title') }}</span>
                  </div>
                  <div class="space-y-2">
                    <!-- Title input -->
                    <div>
                      <label class="text-[10px] text-slate-500 font-medium block mb-0.5">{{ t('review.editCopy.titleLabel') }}</label>
                      <input
                        :value="getET(wf.thread_id)"
                        @input="setET(wf.thread_id, ($event.target as HTMLInputElement).value)"
                        :placeholder="t('review.editCopy.titlePlaceholder')"
                        class="w-full px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-rose-500 font-bold text-sm focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-rose-300"
                      />
                    </div>
                    <!-- Body textarea -->
                    <div>
                      <label class="text-[10px] text-slate-500 font-medium block mb-0.5">{{ t('review.editCopy.bodyLabel') }}</label>
                      <textarea
                        :value="getEB(wf.thread_id)"
                        @input="setEB(wf.thread_id, ($event.target as HTMLTextAreaElement).value)"
                        :placeholder="t('review.editCopy.bodyPlaceholder')"
                        rows="6"
                        class="w-full px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-slate-700 text-xs leading-relaxed resize-y focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
                      />
                    </div>
                    <!-- Tags input -->
                    <div>
                      <label class="text-[10px] text-slate-500 font-medium block mb-0.5">{{ t('review.editCopy.tagsLabel') }}</label>
                      <input
                        :value="getETG(wf.thread_id)"
                        @input="setETG(wf.thread_id, ($event.target as HTMLInputElement).value)"
                        :placeholder="t('review.editCopy.tagsPlaceholder')"
                        class="w-full px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600 text-xs focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-slate-300"
                      />
                      <p class="text-[9px] text-slate-400 mt-0.5">{{ t('review.editCopy.tagsHint') }}</p>
                    </div>
                  </div>
                  <!-- Edit action buttons -->
                  <div class="flex gap-2 mt-2.5">
                    <NeonButton
                      variant="cyan"
                      size="sm"
                      :loading="cardSavingCopy.has(wf.thread_id)"
                      :disabled="cardRegenerating.has(wf.thread_id) || reviewStore.isQueueItemSubmitting(wf.thread_id)"
                      @click="handleSaveCopy(wf.thread_id)"
                    >
                      <span class="inline-flex items-center gap-1.5">
                        <AppIcon name="Save" size="sm" variant="white" />
                        <span class="font-semibold text-xs">{{ t('review.editCopy.saveAndReevaluate') }}</span>
                      </span>
                    </NeonButton>
                    <NeonButton
                      variant="purple"
                      size="sm"
                      :loading="cardRegenerating.has(wf.thread_id)"
                      :disabled="cardSavingCopy.has(wf.thread_id) || reviewStore.isQueueItemSubmitting(wf.thread_id)"
                      @click="handleRegenerate(wf.thread_id)"
                    >
                      <span class="inline-flex items-center gap-1.5">
                        <AppIcon name="RefreshCw" size="sm" variant="white" />
                        <span class="font-semibold text-xs">{{ t('review.editCopy.regenerate') }}</span>
                      </span>
                    </NeonButton>
                  </div>
                </div>

                <!-- Visual plan preview -->
                <div class="rounded-lg p-3 md:p-4 liquid-glass-inset">
                  <div class="flex items-center gap-2 mb-2 md:mb-3">
                    <div class="w-6 h-6 md:w-7 md:h-7 rounded-md bg-gradient-to-br from-teal-400 to-teal-500 flex items-center justify-center">
                      <AppIcon name="Palette" size="sm" variant="white" />
                    </div>
                    <span class="text-xs font-semibold text-slate-800">{{ t('review.visualPlan') }}</span>
                  </div>
                  <div class="rounded-md p-2.5 md:p-3 bg-white/60 border-l-2 border-teal-400 dark:bg-slate-900/70">
                    <div v-if="reviewStore.getQueueVisualPlan(wf.thread_id)?.layout_style" class="text-teal-500 font-bold text-sm mb-1">
                      {{ reviewStore.getQueueVisualPlan(wf.thread_id)!.layout_style }}
                    </div>
                    <div v-if="reviewStore.getQueueVisualPlan(wf.thread_id)?.cover_prompt" class="text-slate-600 text-xs leading-relaxed line-clamp-4">
                      {{ reviewStore.getQueueVisualPlan(wf.thread_id)!.cover_prompt }}
                    </div>
                    <div v-if="reviewStore.getQueueVisualPlan(wf.thread_id)?.color_palette?.length" class="flex gap-1 mt-2">
                      <div v-for="color in reviewStore.getQueueVisualPlan(wf.thread_id)!.color_palette!.slice(0, 5)" :key="color" class="w-4 h-4 rounded-md border border-slate-200" :style="{ background: color }" :title="color" />
                    </div>
                    <div v-if="!reviewStore.getQueueVisualPlan(wf.thread_id)?.layout_style && !reviewStore.getQueueVisualPlan(wf.thread_id)?.cover_prompt" class="text-xs text-slate-400 italic">
                      {{ t('common.loadingState') }}
                    </div>
                  </div>
                </div>

                <!-- Image upload (before publish) -->
                <div class="rounded-lg p-3 md:p-4 liquid-glass-inset">
                  <div class="flex items-center gap-2 mb-2 md:mb-3">
                    <div class="w-6 h-6 md:w-7 md:h-7 rounded-md bg-gradient-to-br from-amber-400 to-orange-400 flex items-center justify-center">
                      <AppIcon name="Image" size="sm" variant="white" />
                    </div>
                    <span class="text-xs font-semibold text-slate-800">{{ t('review.imageUpload') }}</span>
                    <span v-if="getServerImageCount(wf.thread_id) > 0" class="text-[10px] text-emerald-500 font-medium ml-auto">
                      {{ getServerImageCount(wf.thread_id) }} {{ t('review.imagesSaved') }}
                    </span>
                  </div>
                  <!-- Preview grid -->
                  <div v-if="getUploadedImages(wf.thread_id).length > 0" class="grid grid-cols-3 gap-2 mb-2">
                    <div v-for="(url, idx) in getUploadedImages(wf.thread_id)" :key="idx"
                      class="relative aspect-square rounded-md overflow-hidden border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/80"
                    >
                      <img :src="url" class="w-full h-full object-cover" alt="" />
                      <button @click="removeImage(wf.thread_id, idx)"
                        class="absolute top-1 right-1 w-4 h-4 rounded-full bg-rose-500 text-white flex items-center justify-center text-[8px] leading-none shadow hover:bg-rose-600 transition-colors"
                      >×</button>
                    </div>
                  </div>
                  <!-- Upload trigger -->
                  <label v-if="getUploadedImages(wf.thread_id).length < 9"
                    class="flex items-center justify-center gap-1.5 py-2 rounded-md border border-dashed border-slate-300 hover:border-amber-400 hover:bg-amber-50/30 transition-colors cursor-pointer text-xs text-slate-400 hover:text-amber-600"
                    :class="imageUploading.get(wf.thread_id) ? 'opacity-50 pointer-events-none' : ''"
                  >
                    <AppIcon name="Upload" size="sm" variant="cyan" />
                    <span>{{ imageUploading.get(wf.thread_id) ? t('common.loadingState') : t('review.addImages') }}</span>
                    <input type="file" accept="image/jpeg,image/png,image/webp" multiple class="hidden" :disabled="imageUploading.get(wf.thread_id)"
                      @change="handleImageUpload(wf.thread_id, $event)" />
                  </label>
                </div>
              </div>

              <!-- Evaluation result (embedded from EvaluationView components) -->
              <div class="rounded-lg p-3 md:p-4 liquid-glass-inset">
                <div class="flex items-center gap-2 mb-2 md:mb-3">
                  <div class="w-6 h-6 md:w-7 md:h-7 rounded-md bg-gradient-to-br from-rose-400 to-pink-500 flex items-center justify-center">
                    <AppIcon name="BarChart3" size="sm" variant="white" />
                  </div>
                  <span class="text-xs font-semibold text-slate-800">{{ t('review.evaluation.sectionTitle') }}</span>
                  <span class="text-[10px] text-slate-400 ml-auto">{{ t('review.evaluation.sectionHint') }}</span>
                </div>

                <!-- Loading state -->
                <div v-if="cardEvaluationLoading.has(wf.thread_id) && !getEvaluation(wf.thread_id)" class="py-4 text-center">
                  <AppIcon name="Loader2" size="sm" variant="cyan" class="spin inline-block" />
                  <span class="text-xs text-slate-400 ml-1.5">{{ t('review.evaluation.loading') }}</span>
                </div>

                <!-- Empty state -->
                <div v-else-if="!getEvaluation(wf.thread_id)" class="py-4 text-center">
                  <AppIcon name="HelpCircle" size="lg" variant="cyan" class="inline-block mb-1" />
                  <p class="text-xs text-slate-400">{{ t('review.evaluation.empty') }}</p>
                </div>

                <!-- Evaluation result display -->
                <template v-else>
                  <div class="space-y-3">
                    <!-- Overview + radar -->
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <!-- Overall score + decision -->
                      <div class="rounded-md p-3 bg-white/60 border-l-2 border-rose-400 flex flex-col gap-2 dark:bg-slate-900/70">
                        <div class="flex items-baseline gap-1.5">
                          <span class="text-[10px] text-slate-500">{{ t('review.evaluation.overall') }}</span>
                          <span class="text-2xl font-extrabold leading-none" :class="scoreClass(getEvaluation(wf.thread_id)!.overall_score, getEvaluationThresholds(wf.thread_id))">
                            {{ getEvaluation(wf.thread_id)!.overall_score?.toFixed(1) }}
                          </span>
                        </div>
                        <div
                          class="inline-flex self-start px-2 py-0.5 rounded-full text-[10px] font-semibold"
                          :class="decisionClass(getEvaluation(wf.thread_id)!.decision)"
                        >
                          {{ t(DECISION_KEYS[getEvaluation(wf.thread_id)!.decision ?? ''] ?? 'review.evaluation.decision.unknown') }}
                        </div>
                        <p v-if="getEvaluation(wf.thread_id)!.summary" class="text-[10px] text-slate-500 leading-relaxed">
                          {{ getEvaluation(wf.thread_id)!.summary }}
                        </p>
                      </div>
                      <!-- Radar chart -->
                      <div class="rounded-md p-2 bg-white/40 dark:bg-slate-900/55">
                        <EvaluationRadar :dimensions="getEvaluation(wf.thread_id)!.dimensions || []" :height="220" />
                      </div>
                    </div>

                    <!-- Bias warning -->
                    <div v-if="getEvaluation(wf.thread_id)!.bias_warning" class="rounded-md p-2.5 bg-amber-50/60 border border-amber-200">
                      <div class="flex items-center gap-1.5 mb-1">
                        <AppIcon name="AlertTriangle" size="xs" variant="peach" />
                        <span class="text-[10px] font-semibold text-amber-700">{{ t('review.evaluation.biasTitle') }}</span>
                      </div>
                      <p class="text-[10px] text-amber-700 leading-relaxed">{{ getEvaluation(wf.thread_id)!.bias_warning }}</p>
                    </div>

                    <!-- Dimension details -->
                    <div class="rounded-md p-2.5 bg-white/40 dark:bg-slate-900/55">
                      <div class="text-[10px] font-semibold text-slate-700 mb-1.5">{{ t('review.evaluation.dimensionsTitle') }}</div>
                      <div v-for="d in getEvaluation(wf.thread_id)!.dimensions || []" :key="d.dimension" class="py-1.5 border-b border-slate-100 last:border-0">
                        <div class="flex items-center justify-between gap-2">
                          <span class="text-[11px] font-semibold text-slate-600 inline-flex items-center gap-1">
                            {{ dimLabel(d.dimension) }}
                            <span v-if="d.is_blocking" class="text-[8px] px-1 py-0.5 rounded bg-rose-100 text-rose-600 font-bold">{{ t('review.evaluation.blocking') }}</span>
                          </span>
                          <span class="text-xs font-bold" :class="scoreClass(d.score, getEvaluationThresholds(wf.thread_id))">{{ d.score?.toFixed(1) }}</span>
                        </div>
                        <p v-if="d.rationale" class="text-[10px] text-slate-500 mt-0.5 leading-relaxed">{{ d.rationale }}</p>
                        <ul v-if="d.issues?.length" class="mt-0.5 pl-3 space-y-0.5">
                          <li v-for="(issue, i) in d.issues" :key="i" class="text-[10px] text-slate-500">{{ issue }}</li>
                        </ul>
                      </div>
                    </div>

                    <!-- Revision hints -->
                    <div v-if="getEvaluation(wf.thread_id)!.revision_hints?.length" class="rounded-md p-2.5 bg-violet-50/50 border border-violet-200">
                      <div class="text-[10px] font-semibold text-violet-700 mb-1">{{ t('review.evaluation.hintsTitle') }}</div>
                      <ul class="pl-3 space-y-0.5">
                        <li v-for="(h, i) in getEvaluation(wf.thread_id)!.revision_hints" :key="i" class="text-[10px] text-slate-600 leading-relaxed">{{ h }}</li>
                      </ul>
                    </div>
                  </div>
                </template>
              </div>

              <!-- Version history (compact) -->
              <div v-if="reviewStore.getQueueVersionHistory(wf.thread_id).length > 0">
                <button
                  class="flex items-center gap-2 text-xs text-indigo-500 hover:text-indigo-600 transition-colors w-full text-left py-1"
                  @click="setMSS(wf.thread_id, !getMSS(wf.thread_id))"
                >
                  <AppIcon name="GitBranch" size="sm" variant="cyan" />
                  <span>{{ reviewStore.getQueueVersionHistory(wf.thread_id).length }} {{ t('review.versionHistory.count') }}</span>
                  <AppIcon :name="getMSS(wf.thread_id) ? 'ChevronUp' : 'ChevronDown'" size="xs" variant="cyan" />
                </button>
              </div>

              <!-- Feedback input -->
              <div class="rounded-lg p-3 liquid-glass-inset">
                <div class="flex items-center gap-1.5 mb-1.5">
                  <AppIcon name="MessageSquare" size="sm" variant="purple" />
                  <span class="text-[10px] text-violet-600 uppercase tracking-wide font-medium">{{ t('review.feedbackLabel') }}</span>
                </div>
                <textarea
                  :value="getMC(wf.thread_id)"
                  @input="setMC(wf.thread_id, ($event.target as HTMLTextAreaElement).value)"
                  :aria-label="t('review.feedbackAriaLabel')"
                  class="w-full bg-white rounded-md p-2.5 border border-slate-200 text-slate-700 text-xs resize-none focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 placeholder:text-slate-400 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:placeholder:text-slate-500"
                  rows="2"
                  :placeholder="t('review.feedbackPlaceholder')"
                />
              </div>

              <!-- Structured feedback toggle -->
              <div>
                <button
                  class="flex items-center gap-1.5 text-[10px] text-slate-500 hover:text-slate-600 transition-colors"
                  @click="setMSS(wf.thread_id, !getMSS(wf.thread_id))"
                >
                  <AppIcon name="List" size="xs" variant="cyan" />
                  {{ t('review.structuredFeedback') }}
                  <AppIcon :name="getMSS(wf.thread_id) ? 'ChevronUp' : 'ChevronDown'" size="xs" variant="cyan" />
                </button>

                <div v-if="getMSS(wf.thread_id)" class="mt-2 space-y-2">
                  <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <input
                      :value="getMRR(wf.thread_id)"
                      @input="setMRR(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.revisionReason')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
                    />
                    <input
                      :value="getMRJR(wf.thread_id)"
                      @input="setMRJR(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.rejectReason')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
                    />
                    <input
                      :value="getMTI(wf.thread_id)"
                      @input="setMTI(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.titleIssue')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
                    />
                    <input
                      :value="getMBI(wf.thread_id)"
                      @input="setMBI(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.bodyIssue')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
                    />
                    <input
                      :value="getMTGI(wf.thread_id)"
                      @input="setMTGI(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.tagsIssue')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
                    />
                    <input
                      :value="getMVI(wf.thread_id)"
                      @input="setMVI(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.visualIssue')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
                    />
                  </div>
                </div>
              </div>

              <!-- Action buttons -->
              <div class="sticky bottom-0 z-10 -mx-1 flex flex-wrap gap-2 border-t border-slate-200/70 bg-white/90 px-1 py-3 pt-3 backdrop-blur-sm dark:bg-slate-950/90 dark:border-slate-700/60">
                <NeonButton
                  variant="cyan"
                  size="sm"
                  :loading="reviewStore.isQueueItemSubmitting(wf.thread_id)"
                  :disabled="reviewStore.isLoading"
                  @click="requestDecision(wf.thread_id, 'approved')"
                >
                  <span class="inline-flex items-center gap-1.5">
                    <AppIcon name="CheckCircle" size="sm" variant="white" />
                    <span class="font-semibold text-xs">{{ t('review.approve') }}</span>
                  </span>
                </NeonButton>

                <NeonButton
                  variant="purple"
                  size="sm"
                  :loading="reviewStore.isQueueItemSubmitting(wf.thread_id)"
                  :disabled="reviewStore.isLoading"
                  @click="setMSS(wf.thread_id, true); requestDecision(wf.thread_id, 'needs_revision')"
                >
                  <span class="inline-flex items-center gap-1.5">
                    <AppIcon name="Edit3" size="sm" variant="white" />
                    <span class="font-semibold text-xs">{{ t('review.revise') }}</span>
                  </span>
                </NeonButton>

                <NeonButton
                  variant="ghost"
                  size="sm"
                  class="border border-rose-200 !text-rose-500 hover:bg-rose-50"
                  :disabled="reviewStore.isLoading"
                  @click="setMSS(wf.thread_id, true); requestDecision(wf.thread_id, 'rejected')"
                >
                  <span class="inline-flex items-center gap-1.5">
                    <AppIcon name="XCircle" size="sm" variant="pink" />
                    <span class="font-semibold text-xs">{{ t('review.reject') }}</span>
                  </span>
                </NeonButton>
              </div>
            </div>
          </template>

          <!-- No review content available (workflow moved out of review) -->
          <div v-else class="px-4 py-3 text-xs text-slate-400 text-center">
            {{ t('review.emptyState.notReached') }}
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Confirmation Modal -->
  <ConfirmModal
    :is-open="showConfirmModal"
    :title="confirmModalTitle"
    :message="confirmModalMessage"
    :confirm-action="confirmModalAction"
    :variant="confirmModalVariant"
    @confirm="handleConfirm"
    @cancel="handleCancelConfirm"
  />

  <!-- Publish Confirmation Modal -->
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="showPublishConfirm" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="showPublishConfirm = false" />
        <div class="relative liquid-glass-elevated rounded-xl md:rounded-2xl max-w-md w-full overflow-hidden">
          <div class="p-4 md:p-5 border-b border-slate-100">
            <div class="flex items-center gap-2 md:gap-3">
              <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg md:rounded-xl bg-gradient-to-br from-emerald-400 to-teal-400 flex items-center justify-center">
                <AppIcon name="CheckCircle" size="md" variant="white" />
              </div>
              <div>
                <h3 class="text-base md:text-lg font-semibold text-slate-800">{{ t('review.publishConfirm.title') }}</h3>
                <p class="text-xs text-slate-400">{{ t('review.publishConfirm.subtitle') }}</p>
              </div>
            </div>
          </div>

          <div class="p-4 md:p-5 space-y-3 md:space-y-4">
            <div class="flex items-center justify-between py-2">
              <span class="text-xs md:text-sm text-slate-500">{{ t('review.publishConfirm.target') }}</span>
              <span class="text-xs font-mono text-slate-400">{{ (pendingDecisionThreadId || '').slice(-8) }}</span>
            </div>

            <div class="py-2 px-3 rounded-lg liquid-glass-inset">
              <div class="flex items-center gap-1.5 mb-1.5">
                <AppIcon name="User" size="sm" variant="pink" />
                <span class="text-xs md:text-sm text-slate-700">{{ t('review.publishConfirm.account') }}</span>
              </div>
              <select
                v-model="publishAccountId"
                class="w-full px-2 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:border-rose-400 outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
              >
                <option v-for="acc in accountsStore.accounts" :key="acc.id" :value="acc.id">
                  {{ acc.name }}{{ acc.is_active ? ` · ${t('review.publishConfirm.activeSuffix')}` : '' }}
                </option>
              </select>
            </div>

            <div class="py-2 px-3 rounded-lg liquid-glass-inset">
              <div class="flex items-center gap-1.5 mb-2">
                <AppIcon name="Upload" size="sm" variant="pink" />
                <span class="text-xs md:text-sm text-slate-700">{{ t('review.publishConfirm.modeLabel') }}</span>
                <span class="text-[10px] text-rose-400">{{ t('review.publishConfirm.modeRequired') }}</span>
              </div>
              <div class="grid grid-cols-2 gap-2 md:gap-3">
                <button
                  type="button"
                  @click="publishMode = 'dry'"
                  :class="['p-3 rounded-lg border text-left transition-all duration-200', publishMode === 'dry' ? 'border-teal-400 bg-teal-50 ring-1 ring-teal-300 dark:bg-teal-950/40 dark:ring-teal-500/40' : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900/80 dark:hover:border-slate-600']"
                >
                  <div class="flex items-center gap-1.5 mb-1">
                    <AppIcon name="FlaskConical" size="sm" variant="cyan" />
                    <span class="text-xs md:text-sm font-medium text-slate-700">{{ t('review.publishConfirm.dryCardTitle') }}</span>
                  </div>
                  <p class="text-[10px] text-slate-400">{{ t('review.publishConfirm.dryCardDesc') }}</p>
                </button>
                <button
                  type="button"
                  @click="publishMode = 'live'"
                  :class="['p-3 rounded-lg border text-left transition-all duration-200', publishMode === 'live' ? 'border-rose-400 bg-rose-50 ring-1 ring-rose-300 dark:bg-rose-950/40 dark:ring-rose-500/40' : 'border-slate-200 bg-white hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900/80 dark:hover:border-slate-600']"
                >
                  <div class="flex items-center gap-1.5 mb-1">
                    <AppIcon name="Send" size="sm" variant="pink" />
                    <span class="text-xs md:text-sm font-medium text-slate-700">{{ t('review.publishConfirm.liveCardTitle') }}</span>
                  </div>
                  <p class="text-[10px] text-slate-400">{{ t('review.publishConfirm.liveCardDesc') }}</p>
                </button>
              </div>
            </div>

            <div v-if="publishMode === 'live'" class="p-3 rounded-lg liquid-glass-amber liquid-glass-hover">
              <div class="flex items-start gap-2">
                <AppIcon name="AlertTriangle" size="sm" variant="peach" />
                <p class="text-xs text-amber-700">{{ t('review.publishConfirm.liveWarning') }}</p>
              </div>
            </div>

          </div>

          <div class="p-4 md:p-5 border-t border-slate-100 flex gap-2 md:gap-3">
            <NeonButton variant="ghost" class="flex-1" @click="showPublishConfirm = false" :disabled="reviewStore.isLoading">
              {{ t('common.cancel') }}
            </NeonButton>
            <NeonButton variant="pink" class="flex-1" @click="confirmPublish" :loading="reviewStore.isLoading" :disabled="publishMode === null">
              <span class="inline-flex items-center gap-2">
                <AppIcon name="Send" size="sm" variant="white" />
                {{ t('review.publishConfirm.confirm') }}
              </span>
            </NeonButton>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <!-- Celebration Effect -->
  <div class="relative">
    <CelebrationEffect :is-active="showCelebration" type="confetti" :duration="3000" />
  </div>
  </div>
</template>

<style scoped>
/* Score color tiers (mirror EvaluationView) */
.score-pass { color: #16a34a; }
.score-warn { color: #d97706; }
.score-fail { color: #dc2626; }

/* Decision badge backgrounds */
.decision-approved { background: #dcfce7; color: #15803d; }
.decision-revision { background: #fef3c7; color: #b45309; }
.decision-rejected { background: #fee2e2; color: #b91c1c; }

/* Spinner for loading icons */
.spin { animation: review-spin 1s linear infinite; }
@keyframes review-spin { to { transform: rotate(360deg); } }
</style>
