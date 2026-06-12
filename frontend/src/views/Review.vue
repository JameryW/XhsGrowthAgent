<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import CelebrationEffect from '@/components/CelebrationEffect.vue'
import RipplePanel from '@/components/RipplePanel.vue'
import { ReviewSkeleton } from '@/components/skeletons'
import { useWorkflowStore, useReviewStore, useToastStore } from '@/stores'
import type { ContentStatus, CopyContent, VisualPlan } from '@/types'

const { t } = useI18n()
const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()
const toastStore = useToastStore()

// General feedback
const comments = ref('')
const selectedDecision = ref<ContentStatus | null>(null)
const isSubmitting = ref(false)
const error = ref<string | null>(null)

// Structured feedback fields
const titleIssue = ref('')
const bodyIssue = ref('')
const tagsIssue = ref('')
const visualIssue = ref('')
const timingIssue = ref('')

// Required reason for reject/revise
const rejectReason = ref('')
const revisionReason = ref('')

// Show structured feedback panel
const showStructuredFeedback = ref(false)

// Version history state
const showVersionHistory = ref(false)
const expandedVersion = ref<string | null>(null)

// Version diff comparison state
const compareMode = ref(false)
const selectedForCompare = ref<string[]>([])

function toggleCompareVersion(versionId: string) {
  const idx = selectedForCompare.value.indexOf(versionId)
  if (idx >= 0) {
    selectedForCompare.value.splice(idx, 1)
  } else if (selectedForCompare.value.length < 2) {
    selectedForCompare.value.push(versionId)
  } else {
    // Replace the first selected
    selectedForCompare.value.shift()
    selectedForCompare.value.push(versionId)
  }
}

const compareVersions = computed(() => {
  if (selectedForCompare.value.length !== 2) return null
  const versions = reviewStore.versionHistory
  const v1 = versions.find(v => v.version_id === selectedForCompare.value[0])
  const v2 = versions.find(v => v.version_id === selectedForCompare.value[1])
  if (!v1 || !v2) return null
  return { left: v1, right: v2 }
})

function diffField(left: string, right: string): boolean {
  return left !== right
}

// Celebration effect state
const showCelebration = ref(false)

// Watch for workflow completion
watch(
  () => workflowStore.currentPhase,
  (newPhase) => {
    if (newPhase === 'completed') {
      showCelebration.value = true
    }
  }
)

// Loading state
const isLoading = computed(() => reviewStore.isLoading && !reviewStore.pendingReview)

// Check if there's pending review content
const hasPendingReview = computed(() => reviewStore.hasPendingReview)
const isLoaded = computed(() => !reviewStore.isLoading)

// Workflow context for empty state
const currentPhase = computed(() => workflowStore.currentPhase)
const hasThread = computed(() => !!workflowStore.currentThreadId)
const isWorkflowRunning = computed(() => workflowStore.isRunning)

const phaseLabels: Record<string, string> = {
  idle: t('review.emptyState.phaseIdle'),
  scouting: t('review.emptyState.phaseScouting'),
  planning: t('review.emptyState.phasePlanning'),
  creating: t('review.emptyState.phaseCreating'),
  reviewing: t('review.emptyState.phaseReviewing'),
  publishing: t('review.emptyState.phasePublishing'),
  analyzing: t('review.emptyState.phaseAnalyzing'),
  engaging: t('review.emptyState.phaseEngaging'),
  completed: t('review.emptyState.phaseCompleted'),
  error: t('review.emptyState.phaseError'),
  cancelled: t('review.emptyState.phaseCancelled'),
}

const emptyStateHint = computed(() => {
  if (!hasThread.value) return { icon: 'Inbox', text: t('review.emptyState.noWorkflow'), color: 'slate' }
  const phase = currentPhase.value
  if (phase === 'completed') return { icon: 'CheckCircle', text: t('review.emptyState.workflowCompleted'), color: 'emerald' }
  if (phase === 'error') return { icon: 'AlertTriangle', text: t('review.emptyState.workflowError'), color: 'rose' }
  if (phase === 'cancelled') return { icon: 'XCircle', text: t('review.emptyState.workflowCancelled'), color: 'slate' }
  if (phase === 'reviewing') return { icon: 'Clock', text: t('review.emptyState.loadingReview'), color: 'amber' }
  if (isWorkflowRunning.value) return { icon: 'Loader', text: t('review.emptyState.stillRunning', { phase: phaseLabels[phase] || phase }), color: 'cyan' }
  return { icon: 'Inbox', text: t('review.emptyState.notReached'), color: 'slate' }
})

// Confirmation modal state
const showConfirmModal = ref(false)
const pendingDecision = ref<ContentStatus | null>(null)
const confirmModalTitle = ref('')
const confirmModalMessage = ref('')
const confirmModalAction = ref('')
const confirmModalVariant = ref<'danger' | 'warning' | 'info'>('warning')

// Publish confirmation state
const showPublishConfirm = ref(false)
const publishDryRun = ref(true)

onMounted(() => {
  if (workflowStore.currentThreadId) {
    reviewStore.fetchPendingReview(workflowStore.currentThreadId)
  }
})

const copyContent = computed<Partial<CopyContent>>(() => {
  const raw: any = reviewStore.copyContent || {}
  // Brief mode: shooting_plan contains the copy (title_candidates, body_copy, hashtags)
  if (!raw.selected_title && !raw.body_text) {
    const sp = (workflowStore.workflowState as any)?.shooting_plan || {}
    if (sp.title_candidates?.length || sp.body_copy) {
      return {
        selected_title: sp.title_candidates?.[0] || '',
        title_candidates: sp.title_candidates || [],
        body_text: sp.body_copy || '',
        hashtags: [...(sp.required_hashtags || []), ...(sp.optional_hashtags || [])],
      }
    }
  }
  return raw as Partial<CopyContent>
})
const visualPlan = computed<Partial<VisualPlan>>(() => reviewStore.visualPlan || {})

// Ripple data from workflow store
const ripplePrediction = computed(() => workflowStore.ripplePrediction)
const ripplePmf = computed(() => workflowStore.ripplePmf)
const rippleReason = computed(() => workflowStore.rippleReason)
const hasRipple = computed(() =>
  Object.keys(ripplePrediction.value).length > 0 ||
  Object.keys(ripplePmf.value).length > 0
)

// Build structured feedback comment
function buildFeedback(decision: ContentStatus): string {
  const parts: string[] = []
  if (comments.value) parts.push(comments.value)

  if (decision === 'needs_revision' || decision === 'rejected') {
    const structured: string[] = []
    if (titleIssue.value) structured.push(`${t('review.titlePrefix')}: ${titleIssue.value}`)
    if (bodyIssue.value) structured.push(`${t('review.bodyPrefix')}: ${bodyIssue.value}`)
    if (tagsIssue.value) structured.push(`${t('review.tagsPrefix')}: ${tagsIssue.value}`)
    if (visualIssue.value) structured.push(`${t('review.visualPrefix')}: ${visualIssue.value}`)
    if (timingIssue.value) structured.push(`${t('review.timingPrefix')}: ${timingIssue.value}`)
    if (structured.length) parts.push(`${t('review.structuredPrefix')} ${structured.join('; ')}`)
  }

  if (decision === 'rejected' && rejectReason.value) {
    parts.push(`${t('review.rejectPrefix')} ${rejectReason.value}`)
  }
  if (decision === 'needs_revision' && revisionReason.value) {
    parts.push(`${t('review.revisionPrefix')} ${revisionReason.value}`)
  }

  return parts.join('\n')
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

function copyVersion(version: { title: string; body: string; hashtags: string[] }) {
  const text = [version.title, '', version.body, '', ...version.hashtags.map(t => `#${t}`)].join('\n')
  navigator.clipboard.writeText(text).then(() => {
    toastStore.success(t('review.versionHistory.copied'), t('review.versionHistory.copiedDesc'))
  })
}

// Validate before submit
function validateDecision(decision: ContentStatus): string | null {
  if (decision === 'rejected' && !rejectReason.value.trim()) {
    return t('review.rejectReason')
  }
  if (decision === 'needs_revision' && !revisionReason.value.trim()) {
    return t('review.revisionReason')
  }
  return null
}

// Request confirmation before action
const requestDecision = (decision: ContentStatus) => {
  // Validate required fields
  const validationError = validateDecision(decision)
  if (validationError) {
    error.value = validationError
    toastStore.warning(t('review.submitFailedTitle'), validationError)
    return
  }

  error.value = null
  pendingDecision.value = decision

  if (decision === 'rejected') {
    confirmModalTitle.value = t('review.confirmReject.title')
    confirmModalMessage.value = t('review.confirmReject.message')
    confirmModalAction.value = t('review.confirmReject.action')
    confirmModalVariant.value = 'danger'
    showConfirmModal.value = true
  } else if (decision === 'approved') {
    // Show publish confirmation with dry-run toggle
    showPublishConfirm.value = true
  } else {
    // needs_revision - no confirmation needed
    executeDecision(decision)
  }
}

// Execute decision after confirmation
const executeDecision = async (decision: ContentStatus) => {
  selectedDecision.value = decision
  error.value = null
  isSubmitting.value = true
  showConfirmModal.value = false
  showPublishConfirm.value = false

  try {
    const feedback = buildFeedback(decision)
    // Pass publish options for approved decisions
    const publishOpts = decision === 'approved'
      ? { dry_run: publishDryRun.value }
      : undefined
    const result = await reviewStore.submitDecision(decision, feedback, undefined, publishOpts)

    // Use backend next_phase to show accurate outcome
    const nextPhase = result?.next_phase || decision
    if (decision === 'approved') {
      if (result?.publish_skipped) {
        toastStore.warning(
          t('review.decisionApproved'),
          `${t('review.publishSkipped')}: ${result?.skip_reason || t('review.publishSkippedReason')}`
        )
      } else {
        const mode = publishDryRun.value ? t('review.dryRunMode') : t('review.liveMode')
        toastStore.success(
          t('review.decisionApproved'),
          `${t('review.decisionLabel')}: ${decision} · ${mode} → ${nextPhase}`
        )
      }
    } else if (decision === 'rejected') {
      toastStore.warning(
        t('review.decisionRejected'),
        `${t('review.decisionLabel')}: ${decision} → ${nextPhase}`
      )
    } else {
      toastStore.info(
        t('review.decisionRevision'),
        `${t('review.decisionLabel')}: ${decision} → ${nextPhase}`
      )
    }

    router.push('/dashboard')
  } catch (e: any) {
    error.value = e.message || t('review.submitFailed')
    toastStore.error(t('review.submitFailedTitle'), e.message)
  } finally {
    isSubmitting.value = false
    pendingDecision.value = null
  }
}

const confirmPublish = () => {
  showPublishConfirm.value = false
  executeDecision('approved')
}

const handleConfirm = () => {
  if (pendingDecision.value) {
    executeDecision(pendingDecision.value)
  }
}

const handleCancelConfirm = () => {
  showConfirmModal.value = false
  pendingDecision.value = null
  toastStore.info(t('review.cancelSuccess'), t('review.cancelMessage'))
}
</script>

<template>
  <ReviewSkeleton v-if="isLoading" />

  <!-- Empty State -->
  <div v-else-if="isLoaded && !hasPendingReview" class="flex items-center justify-center min-h-[60vh]">
    <div class="rounded-xl md:rounded-2xl p-6 md:p-10 max-w-md w-full liquid-glass text-center">
      <div class="w-12 h-12 md:w-16 md:h-16 rounded-xl md:rounded-2xl flex items-center justify-center mx-auto mb-3 md:mb-5" :class="{
        'bg-slate-100': emptyStateHint.color === 'slate',
        'bg-emerald-50': emptyStateHint.color === 'emerald',
        'bg-rose-50': emptyStateHint.color === 'rose',
        'bg-amber-50': emptyStateHint.color === 'amber',
        'bg-cyan-50': emptyStateHint.color === 'cyan',
      }">
        <AppIcon :name="emptyStateHint.icon" size="xl" :variant="(emptyStateHint.color === 'slate' ? 'cyan' : emptyStateHint.color) as any" />
      </div>
      <h2 class="text-lg md:text-xl font-semibold text-slate-700 mb-1.5 md:mb-2">{{ t('review.emptyState.title') }}</h2>
      <p class="text-xs md:text-sm text-slate-500 mb-3 md:mb-4">{{ emptyStateHint.text }}</p>

      <!-- Workflow phase indicator -->
      <div v-if="hasThread" class="inline-flex items-center gap-1.5 md:gap-2 px-2 md:px-3 py-1 md:py-1.5 rounded-full bg-slate-50 border border-slate-100 mb-3 md:mb-5">
        <span class="w-2 h-2 rounded-full" :class="{
          'bg-slate-400': currentPhase === 'idle' || currentPhase === 'cancelled',
          'bg-teal-500 animate-pulse': isWorkflowRunning,
          'bg-emerald-500': currentPhase === 'completed',
          'bg-rose-500': currentPhase === 'error',
          'bg-amber-500': currentPhase === 'reviewing',
        }" />
        <span class="text-[10px] md:text-xs text-slate-600">{{ t('review.emptyState.currentPhase') }}: {{ phaseLabels[currentPhase] || currentPhase }}</span>
      </div>

      <div class="space-y-1.5 md:space-y-2 text-left mb-4 md:mb-6">
        <div class="flex items-center gap-1.5 md:gap-2 text-xs md:text-sm text-slate-500">
          <AppIcon name="Circle" size="sm" variant="cyan" />
          <span>{{ t('review.emptyState.reason1') }}</span>
        </div>
        <div class="flex items-center gap-1.5 md:gap-2 text-xs md:text-sm text-slate-500">
          <AppIcon name="Circle" size="sm" variant="cyan" />
          <span>{{ t('review.emptyState.reason2') }}</span>
        </div>
        <div v-if="!hasThread" class="flex items-center gap-1.5 md:gap-2 text-xs md:text-sm text-slate-500">
          <AppIcon name="Circle" size="sm" variant="cyan" />
          <span>{{ t('review.emptyState.reason3') }}</span>
        </div>
      </div>
      <div class="flex gap-2 md:gap-3 justify-center">
        <NeonButton variant="pink" size="sm" class="md:size-md" @click="router.push('/dashboard')">
          {{ t('review.emptyState.goDashboard') }}
        </NeonButton>
        <NeonButton variant="ghost" size="sm" class="md:size-md" @click="router.push('/start')">
          {{ t('review.emptyState.goHome') }}
        </NeonButton>
      </div>
    </div>
  </div>

  <!-- Review Content -->
  <div v-else class="relative space-y-3 md:space-y-5">
    <!-- 审核状态栏 -->
    <div class="card">
      <div class="flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-5">
        <div class="w-10 h-10 md:w-14 md:h-14 rounded-lg md:rounded-xl bg-gradient-to-br from-amber-400 to-rose-400 flex items-center justify-center shadow-sm flex-shrink-0">
          <AppIcon name="Clock" size="md" variant="white" class="md:hidden" :aria-label="t('review.title')" />
          <AppIcon name="Clock" size="xl" variant="white" class="hidden md:block" :aria-label="t('review.title')" />
        </div>
        <div class="flex-1">
          <div class="flex items-center gap-1.5 md:gap-2 mb-1">
            <span class="px-1.5 md:px-2 py-0.5 md:py-1 rounded bg-amber-50 text-amber-600 text-[10px] md:text-xs uppercase tracking-wide font-medium">{{ t('review.pendingApproval') }}</span>
          </div>
          <div class="text-lg md:text-xl font-semibold text-slate-800">{{ t('review.title') }} · {{ t('review.subtitle') }}</div>
          <div class="text-[10px] md:text-xs text-slate-400 mt-1">
            <span v-if="workflowStore.workflowState?.label" class="font-medium text-slate-600">{{ workflowStore.workflowState.label }}</span>
            <span v-if="workflowStore.workflowState?.label && workflowStore.currentThreadId" class="mx-1">·</span>
            <span class="font-mono">{{ (workflowStore.currentThreadId || '—').slice(-8) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Ripple 传播预测摘要 -->
    <RipplePanel
      v-if="hasRipple"
      :prediction="ripplePrediction"
      :pmf="ripplePmf"
      :ripple-reason="rippleReason"
      variant="planning"
    />

    <!-- 内容预览 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-3 md:gap-4 review-content">
      <!-- 文案预览 -->
      <div class="rounded-xl p-3 md:p-5 liquid-glass liquid-glass-hover transition-all duration-200">
        <div class="flex items-center gap-2 md:gap-3 mb-3 md:mb-4">
          <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg md:rounded-xl bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
            <AppIcon name="Pencil" size="sm" variant="white" class="md:hidden" :aria-label="t('review.copyContent')" />
            <AppIcon name="Pencil" size="md" variant="white" class="hidden md:block" :aria-label="t('review.copyContent')" />
          </div>
          <div class="flex-1">
            <div class="text-slate-800 font-semibold text-xs md:text-sm">{{ t('review.copyContent') }}</div>
            <div class="text-[10px] md:text-xs text-slate-400 uppercase tracking-wide">{{ t('review.copyContentEn') }}</div>
          </div>
        </div>

        <div class="liquid-glass-inset rounded-lg p-3 md:p-4 border-l-2 border-rose-400">
          <div v-if="copyContent.selected_title" class="text-rose-500 font-bold text-base md:text-lg mb-1.5 md:mb-2">
            {{ copyContent.selected_title }}
          </div>
          <div v-if="copyContent.body_text" class="text-slate-600 text-xs md:text-sm mb-2 md:mb-3 leading-relaxed whitespace-pre-wrap">
            {{ copyContent.body_text }}
          </div>
          <div v-if="copyContent.hashtags?.length" class="flex gap-1.5 md:gap-2 flex-wrap">
            <span v-for="tag in copyContent.hashtags" :key="tag" class="px-1.5 md:px-2 py-0.5 md:py-1 rounded bg-rose-50 border border-rose-100 text-rose-500 text-[10px] md:text-xs font-medium">
              {{ tag }}
            </span>
          </div>
          <div v-if="!copyContent.selected_title && !copyContent.body_text" class="space-y-2">
            <div class="h-4 w-3/4 rounded bg-slate-200 animate-pulse" />
            <div class="h-3 w-full rounded bg-slate-200 animate-pulse" />
          </div>
        </div>
      </div>

      <!-- 视觉方案预览 -->
      <div class="rounded-xl p-3 md:p-5 liquid-glass liquid-glass-hover transition-all duration-200">
        <div class="flex items-center gap-2 md:gap-3 mb-3 md:mb-4">
          <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg md:rounded-xl bg-gradient-to-br from-teal-400 to-teal-500 flex items-center justify-center shadow-sm">
            <AppIcon name="Palette" size="sm" variant="white" class="md:hidden" :aria-label="t('review.visualPlan')" />
            <AppIcon name="Palette" size="md" variant="white" class="hidden md:block" :aria-label="t('review.visualPlan')" />
          </div>
          <div class="flex-1">
            <div class="text-slate-800 font-semibold text-xs md:text-sm">{{ t('review.visualPlan') }}</div>
            <div class="text-[10px] md:text-xs text-slate-400 uppercase tracking-wide">{{ t('review.visualPlanEn') }}</div>
          </div>
        </div>

        <div class="bg-slate-50 rounded-lg p-3 md:p-4 border-l-2 border-teal-400">
          <div v-if="visualPlan.layout_style" class="text-teal-500 font-bold text-sm md:text-base mb-1.5 md:mb-2">
            {{ visualPlan.layout_style }}
          </div>
          <div v-if="visualPlan.cover_prompt" class="text-slate-600 text-xs md:text-sm mb-2 md:mb-3 leading-relaxed">
            {{ visualPlan.cover_prompt }}
          </div>
          <div v-if="visualPlan.color_palette?.length" class="flex gap-1.5 md:gap-2 mt-1.5 md:mt-2">
            <div v-for="color in visualPlan.color_palette" :key="color" class="w-5 h-5 md:w-6 md:h-6 rounded-md md:rounded-lg border border-slate-200 hover:scale-110 transition-transform cursor-pointer" :style="{ background: color }" :title="color" />
          </div>
          <div v-if="!visualPlan.layout_style && !visualPlan.cover_prompt" class="space-y-2">
            <div class="h-4 w-1/2 rounded bg-slate-200 animate-pulse" />
            <div class="h-3 w-full rounded bg-slate-200 animate-pulse" />
          </div>
        </div>
      </div>
    </div>

    <!-- 版本历史对比 -->
    <div v-if="reviewStore.versionHistory.length > 0" class="card">
      <div class="flex items-center gap-2 md:gap-3 mb-3 md:mb-4">
        <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-gradient-to-br from-indigo-400 to-indigo-500 flex items-center justify-center shadow-sm">
          <AppIcon name="GitBranch" size="sm" variant="white" class="md:hidden" :aria-label="t('review.versionHistory.title')" />
          <AppIcon name="GitBranch" size="md" variant="white" class="hidden md:block" :aria-label="t('review.versionHistory.title')" />
        </div>
        <div class="flex-1">
          <div class="text-indigo-500 font-semibold text-xs md:text-sm">{{ t('review.versionHistory.title') }}</div>
          <div class="text-[10px] md:text-xs text-slate-400">{{ reviewStore.versionHistory.length }} {{ t('review.versionHistory.count') }}</div>
        </div>
        <div class="flex items-center gap-1.5 md:gap-2">
          <button
            v-if="reviewStore.versionHistory.length >= 2"
            @click="compareMode = !compareMode; selectedForCompare = []"
            :class="[
              'text-xs px-2.5 py-1 rounded-lg border transition-colors font-medium',
              compareMode ? 'bg-indigo-50 border-indigo-200 text-indigo-600' : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50'
            ]"
          >
            {{ compareMode ? t('review.versionHistory.exitCompare') : t('review.versionHistory.compare') }}
          </button>
          <button
            @click="showVersionHistory = !showVersionHistory"
            class="text-xs text-indigo-500 hover:text-indigo-600 transition-colors"
          >
            {{ showVersionHistory ? t('review.versionHistory.collapse') : t('review.versionHistory.expand') }}
          </button>
        </div>
      </div>

      <!-- Compare mode hint -->
      <div v-if="compareMode && showVersionHistory" class="mb-3 p-2.5 rounded-lg bg-indigo-50 border border-indigo-100 text-xs text-indigo-600">
        {{ t('review.versionHistory.selectTwo') }}
        <span v-if="selectedForCompare.length > 0" class="ml-1 font-medium">({{ selectedForCompare.length }}/2)</span>
      </div>

      <div v-if="showVersionHistory" class="space-y-3">
        <div
          v-for="(version, idx) in reviewStore.versionHistory"
          :key="version.version_id"
          :class="[
            'rounded-lg border overflow-hidden transition-colors',
            selectedForCompare.includes(version.version_id) ? 'border-indigo-300 bg-indigo-50/30' : 'border-slate-200'
          ]"
        >
          <!-- Version header -->
          <button
            class="w-full flex items-center justify-between p-3 hover:bg-slate-50 transition-colors"
            @click="compareMode ? toggleCompareVersion(version.version_id) : (expandedVersion = expandedVersion === version.version_id ? null : version.version_id)"
          >
            <div class="flex items-center gap-1.5 md:gap-2">
              <!-- Compare checkbox -->
              <span
                v-if="compareMode"
                :class="[
                  'w-5 h-5 rounded border-2 flex items-center justify-center transition-colors',
                  selectedForCompare.includes(version.version_id)
                    ? 'bg-indigo-500 border-indigo-500'
                    : 'bg-white border-slate-300'
                ]"
              >
                <AppIcon v-if="selectedForCompare.includes(version.version_id)" name="Check" size="sm" variant="white" />
              </span>
              <span class="w-6 h-6 rounded-full bg-indigo-100 text-indigo-600 text-xs font-medium flex items-center justify-center">
                {{ reviewStore.versionHistory.length - idx }}
              </span>
              <span class="text-sm font-medium text-slate-700">{{ version.changes_summary || t('review.versionLabel', { n: reviewStore.versionHistory.length - idx }) }}</span>
              <span v-if="version.title" class="text-xs text-slate-400 truncate max-w-[200px]">— {{ version.title }}</span>
            </div>
            <div class="flex items-center gap-1.5 md:gap-2">
              <span class="text-xs text-slate-400">{{ formatDate(version.created_at || '') }}</span>
              <AppIcon :name="expandedVersion === version.version_id ? 'ChevronUp' : 'ChevronDown'" size="sm" variant="cyan" />
            </div>
          </button>

          <!-- Version detail -->
          <div v-if="expandedVersion === version.version_id" class="border-t border-slate-100 p-4 bg-slate-50/50">
            <div v-if="version.title" class="mb-2">
              <span class="text-xs font-medium text-slate-500 uppercase tracking-wide">{{ t('review.versionHistory.copy') }}</span>
              <p class="text-rose-500 font-bold text-sm mt-1">{{ version.title }}</p>
            </div>
            <div v-if="version.body" class="mb-2">
              <p class="text-slate-600 text-xs leading-relaxed whitespace-pre-wrap">{{ version.body }}</p>
            </div>
            <div v-if="version.hashtags?.length" class="flex gap-1.5 flex-wrap mb-2">
              <span v-for="tag in version.hashtags" :key="tag" class="px-1.5 py-0.5 rounded bg-indigo-50 border border-indigo-100 text-indigo-500 text-xs">
                {{ tag }}
              </span>
            </div>
            <div class="flex gap-2 mt-3">
              <button
                @click.stop="copyVersion(version)"
                class="text-xs text-indigo-500 hover:text-indigo-600 flex items-center gap-1 transition-colors"
              >
                <AppIcon name="Copy" size="sm" variant="cyan" />
                {{ t('review.versionHistory.copyVersion') }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Diff comparison view -->
      <div v-if="compareVersions && showVersionHistory" class="mt-4 pt-4 border-t border-slate-200">
        <div class="flex items-center gap-2 mb-3">
          <AppIcon name="Columns" size="sm" variant="cyan" />
          <span class="text-xs text-slate-600 uppercase tracking-wide font-medium">{{ t('review.versionHistory.comparison') }}</span>
        </div>

        <div class="grid grid-cols-2 gap-4">
          <!-- Left version -->
          <div class="rounded-lg border border-slate-200 p-3">
            <div class="flex items-center gap-2 mb-2">
              <span class="text-xs px-2 py-0.5 rounded bg-slate-100 text-slate-600 font-medium">
                {{ t('review.versionHistory.before') }}
              </span>
              <span class="text-xs text-slate-400">{{ formatDate(compareVersions.left.created_at || '') }}</span>
            </div>
            <div v-if="compareVersions.left.title" class="mb-2">
              <span class="text-xs text-slate-400">{{ t('review.versionHistory.titleLabel') }}</span>
              <p :class="['text-sm font-medium mt-0.5', diffField(compareVersions.left.title, compareVersions.right.title) ? 'bg-rose-50 text-rose-700 px-1.5 py-0.5 rounded' : 'text-slate-700']">
                {{ compareVersions.left.title }}
              </p>
            </div>
            <div v-if="compareVersions.left.body" class="mb-2">
              <span class="text-xs text-slate-400">{{ t('review.versionHistory.bodyLabel') }}</span>
              <p :class="['text-xs leading-relaxed whitespace-pre-wrap mt-0.5', diffField(compareVersions.left.body, compareVersions.right.body) ? 'bg-rose-50 text-rose-700 px-1.5 py-0.5 rounded' : 'text-slate-600']">
                {{ compareVersions.left.body }}
              </p>
            </div>
            <div v-if="compareVersions.left.hashtags?.length" class="flex gap-1 flex-wrap">
              <span v-for="tag in compareVersions.left.hashtags" :key="tag"
                :class="['px-1.5 py-0.5 rounded text-xs', JSON.stringify(compareVersions.left.hashtags) !== JSON.stringify(compareVersions.right.hashtags) ? 'bg-rose-50 border border-rose-200 text-rose-600' : 'bg-slate-100 text-slate-500']">
                #{{ tag }}
              </span>
            </div>
          </div>

          <!-- Right version -->
          <div class="rounded-lg border border-indigo-200 p-3 bg-indigo-50/30">
            <div class="flex items-center gap-2 mb-2">
              <span class="text-xs px-2 py-0.5 rounded bg-indigo-100 text-indigo-600 font-medium">
                {{ t('review.versionHistory.after') }}
              </span>
              <span class="text-xs text-slate-400">{{ formatDate(compareVersions.right.created_at || '') }}</span>
            </div>
            <div v-if="compareVersions.right.title" class="mb-2">
              <span class="text-xs text-slate-400">{{ t('review.versionHistory.titleLabel') }}</span>
              <p :class="['text-sm font-medium mt-0.5', diffField(compareVersions.left.title, compareVersions.right.title) ? 'bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded' : 'text-slate-700']">
                {{ compareVersions.right.title }}
              </p>
            </div>
            <div v-if="compareVersions.right.body" class="mb-2">
              <span class="text-xs text-slate-400">{{ t('review.versionHistory.bodyLabel') }}</span>
              <p :class="['text-xs leading-relaxed whitespace-pre-wrap mt-0.5', diffField(compareVersions.left.body, compareVersions.right.body) ? 'bg-emerald-50 text-emerald-700 px-1.5 py-0.5 rounded' : 'text-slate-600']">
                {{ compareVersions.right.body }}
              </p>
            </div>
            <div v-if="compareVersions.right.hashtags?.length" class="flex gap-1 flex-wrap">
              <span v-for="tag in compareVersions.right.hashtags" :key="tag"
                :class="['px-1.5 py-0.5 rounded text-xs', JSON.stringify(compareVersions.left.hashtags) !== JSON.stringify(compareVersions.right.hashtags) ? 'bg-emerald-50 border border-emerald-200 text-emerald-600' : 'bg-slate-100 text-slate-500']">
                #{{ tag }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 操作按钮区 -->
    <div class="card">
      <div class="flex items-center gap-2 md:gap-3 mb-3 md:mb-4">
        <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-gradient-to-br from-rose-400 to-amber-400 flex items-center justify-center shadow-sm">
          <AppIcon name="GitBranch" size="sm" variant="white" class="md:hidden" :aria-label="t('review.actions')" />
          <AppIcon name="GitBranch" size="md" variant="white" class="hidden md:block" :aria-label="t('review.actions')" />
        </div>
        <div>
          <div class="text-rose-500 font-semibold text-xs md:text-sm">{{ t('review.actions') }}</div>
          <div class="text-[10px] md:text-xs text-slate-400">{{ t('review.selectAction') }}</div>
        </div>
      </div>

      <!-- Error display -->
      <div v-if="error" class="mb-3 md:mb-4 p-2 md:p-3 rounded-lg liquid-glass-rose text-rose-500 text-xs md:text-sm flex items-center gap-1.5 md:gap-2">
        <div class="w-5 h-5 md:w-6 md:h-6 rounded bg-rose-100 flex items-center justify-center">
          <AppIcon name="AlertTriangle" size="sm" variant="pink" animate />
        </div>
        <span>{{ error }}</span>
      </div>

      <div class="flex flex-wrap gap-3 mb-3 md:mb-4">
        <NeonButton variant="cyan" size="md" @click="requestDecision('approved')" :loading="isSubmitting" :disabled="isSubmitting">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="CheckCircle" size="md" variant="white" />
            <span class="font-semibold">{{ t('review.approve') }}</span>
          </span>
        </NeonButton>

        <NeonButton variant="purple" size="md" @click="showStructuredFeedback = true; requestDecision('needs_revision')" :loading="isSubmitting" :disabled="isSubmitting">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="Edit3" size="md" variant="white" />
            <span class="font-semibold">{{ t('review.revise') }}</span>
          </span>
        </NeonButton>

        <NeonButton variant="ghost" size="md" class="border border-rose-200 !text-rose-500 hover:bg-rose-50" @click="showStructuredFeedback = true; requestDecision('rejected')" :disabled="isSubmitting">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="XCircle" size="md" variant="pink" />
            <span class="font-semibold">{{ t('review.reject') }}</span>
          </span>
        </NeonButton>
      </div>

      <!-- General feedback -->
      <div class="liquid-glass-inset rounded-lg p-3 md:p-4 mb-3 md:mb-4">
        <div class="flex items-center gap-1.5 md:gap-2 mb-1.5 md:mb-2">
          <AppIcon name="MessageSquare" size="sm" variant="purple" />
          <span class="text-[10px] md:text-xs text-violet-600 uppercase tracking-wide font-medium">{{ t('review.feedbackLabel') }}</span>
        </div>
        <textarea
          v-model="comments"
          :aria-label="t('review.feedbackAriaLabel')"
          class="w-full bg-white rounded-lg p-3 border border-slate-200 text-slate-700 text-sm resize-none focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 placeholder:text-slate-400 transition-all duration-200"
          rows="3"
          :placeholder="t('review.feedbackPlaceholder')"
        />
      </div>

      <!-- Structured Feedback (for revise/reject) -->
      <div class="liquid-glass-inset rounded-lg p-3 md:p-4">
        <button
          class="flex items-center justify-between w-full mb-2 md:mb-3"
          @click="showStructuredFeedback = !showStructuredFeedback"
        >
          <div class="flex items-center gap-1.5 md:gap-2">
            <AppIcon name="List" size="sm" variant="cyan" />
            <span class="text-[10px] md:text-xs text-slate-600 uppercase tracking-wide font-medium">{{ t('review.structuredFeedback') }}</span>
          </div>
          <AppIcon :name="showStructuredFeedback ? 'ChevronUp' : 'ChevronDown'" size="sm" variant="cyan" />
        </button>

        <div v-if="showStructuredFeedback" class="space-y-2 md:space-y-3">
          <!-- Revision reason (required for revise) -->
          <div>
            <label class="block text-[10px] md:text-xs font-medium text-slate-600 mb-1">{{ t('review.revisionReason') }}</label>
            <input
              v-model="revisionReason"
              type="text"
              class="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm text-slate-700 focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all"
              :placeholder="t('review.revisionReasonPlaceholder')"
            />
          </div>

          <!-- Reject reason (required for reject) -->
          <div>
            <label class="block text-[10px] md:text-xs font-medium text-slate-600 mb-1">{{ t('review.rejectReason') }}</label>
            <input
              v-model="rejectReason"
              type="text"
              class="w-full px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm text-slate-700 focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all"
              :placeholder="t('review.rejectReasonPlaceholder')"
            />
          </div>

          <div class="border-t border-slate-200 pt-2 md:pt-3">
            <p class="text-[10px] md:text-xs text-slate-400 mb-1.5 md:mb-2">{{ t('review.structuredFeedbackLabel') }}</p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <input v-model="titleIssue" :placeholder="t('review.titleIssue')" class="px-3 py-2 rounded-lg border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all" />
              <input v-model="bodyIssue" :placeholder="t('review.bodyIssue')" class="px-3 py-2 rounded-lg border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all" />
              <input v-model="tagsIssue" :placeholder="t('review.tagsIssue')" class="px-3 py-2 rounded-lg border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all" />
              <input v-model="visualIssue" :placeholder="t('review.visualIssue')" class="px-3 py-2 rounded-lg border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all" />
              <input v-model="timingIssue" :placeholder="t('review.timingIssue')" class="px-3 py-2 rounded-lg border border-slate-200 bg-white text-xs text-slate-700 focus:outline-none focus:border-violet-300 focus:ring-1 focus:ring-violet-200 transition-all sm:col-span-2" />
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
                  <AppIcon name="CheckCircle" size="sm" variant="white" class="md:hidden" />
                  <AppIcon name="CheckCircle" size="md" variant="white" class="hidden md:block" />
                </div>
                <div>
                  <h3 class="text-base md:text-lg font-semibold text-slate-800">{{ t('review.publishConfirm.title') }}</h3>
                  <p class="text-xs text-slate-400">{{ t('review.publishConfirm.subtitle') }}</p>
                </div>
              </div>
            </div>

            <div class="p-4 md:p-5 space-y-3 md:space-y-4">
              <!-- Target info -->
              <div class="flex items-center justify-between py-2">
                <span class="text-xs md:text-sm text-slate-500">{{ t('review.publishConfirm.target') }}</span>
                <div class="flex items-center gap-1.5">
                  <span v-if="workflowStore.workflowState?.label" class="text-xs md:text-sm font-medium text-slate-700 truncate">{{ workflowStore.workflowState.label }}</span>
                  <span class="text-xs font-mono text-slate-400">{{ (workflowStore.currentThreadId || '').slice(-8) }}</span>
                </div>
              </div>

              <!-- Dry Run toggle -->
              <div class="flex items-center justify-between py-2 px-3 rounded-lg liquid-glass-inset">
                <div class="flex items-center gap-1.5 md:gap-2">
                  <AppIcon name="FlaskConical" size="sm" variant="cyan" />
                  <div>
                    <span class="text-xs md:text-sm text-slate-700">{{ t('review.publishConfirm.dryRun') }}</span>
                    <p class="text-xs text-slate-400">{{ t('review.publishConfirm.dryRunHelp') }}</p>
                  </div>
                </div>
                <button
                  @click="publishDryRun = !publishDryRun"
                  :class="[
                    'relative w-11 h-6 rounded-full transition-colors duration-200',
                    publishDryRun ? 'bg-teal-500' : 'bg-slate-300'
                  ]"
                  role="switch"
                  :aria-checked="publishDryRun"
                >
                  <span
                    :class="[
                      'absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform duration-200',
                      publishDryRun ? 'translate-x-5' : 'translate-x-0'
                    ]"
                  />
                </button>
              </div>

              <!-- Live warning -->
      <div v-if="!publishDryRun" class="p-3 rounded-lg liquid-glass-amber liquid-glass-hover">
                <div class="flex items-start gap-2">
                  <AppIcon name="AlertTriangle" size="sm" variant="peach" />
                  <p class="text-xs text-amber-700">{{ t('review.publishConfirm.liveWarning') }}</p>
                </div>
              </div>
            </div>

            <div class="p-4 md:p-5 border-t border-slate-100 flex gap-2 md:gap-3">
              <NeonButton variant="ghost" class="flex-1" @click="showPublishConfirm = false" :disabled="isSubmitting">
                {{ t('common.cancel') }}
              </NeonButton>
              <NeonButton variant="pink" class="flex-1" @click="confirmPublish" :loading="isSubmitting">
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

    <!-- Celebration Effect for workflow completion -->
    <div class="relative">
      <CelebrationEffect
        :is-active="showCelebration"
        type="confetti"
        :duration="3000"
      />
    </div>
  </div>
</template>
