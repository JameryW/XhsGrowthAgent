<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch, type WatchStopHandle } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import CelebrationEffect from '@/components/CelebrationEffect.vue'
import WorkflowCardBody from '@/components/WorkflowCardBody.vue'
import { ReviewSkeleton } from '@/components/skeletons'
import { useReviewStore, useToastStore, useAccountsStore } from '@/stores'
import { listWorkflows, getWorkflowStatus, uploadImages } from '@/api/workflow'
import { getSystemHealth } from '@/api/system'
import type { ContentStatus } from '@/types'
import type { WorkflowListItem, WorkflowStateResponse } from '@/types/workflow'

const { t } = useI18n()
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
    getWorkflowStatus(tid)
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
      state = await getWorkflowStatus(threadId)
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
    const result = await listWorkflows({ status: 'awaiting_review', limit: 50 })
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

onMounted(fetchReviewQueue)
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
// Whether real publishing is possible in this environment (XHS_USE_BROWSER).
const canRealPublish = ref(true)

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
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
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
    // Detect whether the backend can actually publish (XHS_USE_BROWSER).
    getSystemHealth()
      .then((h) => { canRealPublish.value = h.checks.xhs_platform.use_browser })
      .catch(() => { canRealPublish.value = true })
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
  <div class="review-page">
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
    <!-- Queue header -->
    <div class="rounded-xl p-4 md:p-5 liquid-glass">
      <div class="flex items-center gap-3 md:gap-4">
        <div class="w-10 h-10 md:w-12 md:h-12 rounded-lg md:rounded-xl bg-gradient-to-br from-amber-400 to-rose-400 flex items-center justify-center shadow-sm shrink-0">
          <AppIcon name="Clock" size="lg" variant="white" />
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded bg-amber-50 text-amber-600 text-[10px] uppercase tracking-wide font-medium">{{ t('review.pendingApproval') }}</span>
            <span class="text-[10px] text-slate-400">{{ workflows.length }} {{ t('review.emptyState.reason1') }}</span>
          </div>
          <div class="text-lg md:text-xl font-semibold text-slate-800 mt-0.5">{{ t('review.title') }}</div>
          <div class="text-[10px] md:text-xs text-slate-400">{{ t('review.subtitle') }}</div>
        </div>
        <button @click="fetchReviewQueue" class="p-2 rounded-lg hover:bg-slate-100 transition-colors" :title="t('common.retry')">
          <AppIcon name="RefreshCw" size="sm" variant="cyan" />
        </button>
      </div>
    </div>

    <!-- Error -->
    <div v-if="error" class="rounded-xl p-4 liquid-glass-rose text-center">
      <p class="text-sm text-rose-700 font-medium">{{ error }}</p>
      <button @click="fetchReviewQueue" class="mt-2 px-4 py-1.5 rounded-lg bg-rose-600 text-white text-xs font-medium hover:bg-rose-700 transition-colors">{{ t('common.retry') }}</button>
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
          class="px-4 md:px-5 py-3 flex items-center justify-between cursor-pointer liquid-glass-inset border-b border-white/10"
          @click="toggleExpand(wf.thread_id)"
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
        <div v-if="expandedThreadId !== wf.thread_id" class="relative min-h-[40px] cursor-pointer" @click="toggleExpand(wf.thread_id)">
          <WorkflowCardBody
            v-if="workflowDetails.has(wf.thread_id)"
            :detail="workflowDetails.get(wf.thread_id)"
          />
          <div v-else-if="loadingDetailIds.has(wf.thread_id)" class="px-4 py-3 space-y-2">
            <div class="h-3 w-3/4 rounded bg-slate-100 animate-pulse" />
            <div class="h-3 w-1/2 rounded bg-slate-100 animate-pulse" />
          </div>
        </div>

        <!-- Expanded: full review panel -->
        <div v-else class="border-t border-white/5">
          <!-- Review content loading -->
          <div v-if="reviewStore.isQueueItemLoading(wf.thread_id) && !reviewStore.pendingReviews.has(wf.thread_id)" class="px-4 py-4 space-y-2">
            <div class="h-3 w-3/4 rounded bg-slate-100 animate-pulse" />
            <div class="h-3 w-full rounded bg-slate-100 animate-pulse" />
            <div class="h-3 w-2/3 rounded bg-slate-100 animate-pulse" />
          </div>

          <!-- Review content loaded -->
          <template v-else-if="reviewStore.pendingReviews.has(wf.thread_id)">
            <div class="p-4 md:p-5 space-y-3 md:space-y-4">
              <!-- Content preview: copy + visual side by side -->
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-3 md:gap-4">
                <!-- Copy content preview -->
                <div class="rounded-lg p-3 md:p-4 liquid-glass-inset">
                  <div class="flex items-center gap-2 mb-2 md:mb-3">
                    <div class="w-6 h-6 md:w-7 md:h-7 rounded-md bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center">
                      <AppIcon name="Pencil" size="sm" variant="white" />
                    </div>
                    <span class="text-xs font-semibold text-slate-800">{{ t('review.copyContent') }}</span>
                  </div>
                  <div class="rounded-md p-2.5 md:p-3 bg-white/60 border-l-2 border-rose-400">
                    <div v-if="reviewStore.getQueueCopyContent(wf.thread_id)?.selected_title" class="text-rose-500 font-bold text-sm mb-1">
                      {{ reviewStore.getQueueCopyContent(wf.thread_id)!.selected_title }}
                    </div>
                    <div v-if="reviewStore.getQueueCopyContent(wf.thread_id)?.body_text" class="text-slate-600 text-xs leading-relaxed whitespace-pre-wrap line-clamp-6">
                      {{ reviewStore.getQueueCopyContent(wf.thread_id)!.body_text }}
                    </div>
                    <div v-if="reviewStore.getQueueCopyContent(wf.thread_id)?.hashtags?.length" class="flex gap-1 flex-wrap mt-2">
                      <span v-for="tag in reviewStore.getQueueCopyContent(wf.thread_id)!.hashtags!.slice(0, 5)" :key="tag" class="px-1 py-0.5 rounded bg-rose-50 text-rose-500 text-[10px] font-medium">
                        {{ tag }}
                      </span>
                    </div>
                    <div v-if="!reviewStore.getQueueCopyContent(wf.thread_id)?.selected_title && !reviewStore.getQueueCopyContent(wf.thread_id)?.body_text" class="text-xs text-slate-400 italic">
                      {{ t('common.loadingState') }}
                    </div>
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
                  <div class="rounded-md p-2.5 md:p-3 bg-white/60 border-l-2 border-teal-400">
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
                      class="relative aspect-square rounded-md overflow-hidden border border-slate-200 bg-slate-50"
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
                  class="w-full bg-white rounded-md p-2.5 border border-slate-200 text-slate-700 text-xs resize-none focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 placeholder:text-slate-400 transition-all"
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
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all"
                    />
                    <input
                      :value="getMRJR(wf.thread_id)"
                      @input="setMRJR(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.rejectReason')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all"
                    />
                    <input
                      :value="getMTI(wf.thread_id)"
                      @input="setMTI(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.titleIssue')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all"
                    />
                    <input
                      :value="getMBI(wf.thread_id)"
                      @input="setMBI(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.bodyIssue')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all"
                    />
                    <input
                      :value="getMTGI(wf.thread_id)"
                      @input="setMTGI(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.tagsIssue')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all"
                    />
                    <input
                      :value="getMVI(wf.thread_id)"
                      @input="setMVI(wf.thread_id, ($event.target as HTMLInputElement).value)"
                      :placeholder="t('review.visualIssue')"
                      class="px-2.5 py-1.5 rounded-md border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 transition-all"
                    />
                  </div>
                </div>
              </div>

              <!-- Action buttons -->
              <div class="flex flex-wrap gap-2 pt-1">
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
                class="w-full px-2 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:border-rose-400 outline-none"
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
                  :class="['p-3 rounded-lg border text-left transition-all duration-200', publishMode === 'dry' ? 'border-teal-400 bg-teal-50 ring-1 ring-teal-300' : 'border-slate-200 bg-white hover:border-slate-300']"
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
                  :class="['p-3 rounded-lg border text-left transition-all duration-200', publishMode === 'live' ? 'border-rose-400 bg-rose-50 ring-1 ring-rose-300' : 'border-slate-200 bg-white hover:border-slate-300']"
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

            <div v-if="publishMode === 'live' && !canRealPublish" class="p-3 rounded-lg liquid-glass-amber liquid-glass-hover">
              <div class="flex items-start gap-2">
                <AppIcon name="AlertTriangle" size="sm" variant="peach" />
                <p class="text-xs text-amber-700">{{ t('review.publishConfirm.useBrowserOffWarning') }}</p>
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
