<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import WorkflowTabBar from '@/components/dashboard/WorkflowTabBar.vue'
import WorkflowHeader from '@/components/dashboard/WorkflowHeader.vue'
import WorkflowTimeline from '@/components/dashboard/WorkflowTimeline.vue'
import ContentCards from '@/components/dashboard/ContentCards.vue'
import OptimizationPanel from '@/components/dashboard/OptimizationPanel.vue'
import ActionButtons from '@/components/dashboard/ActionButtons.vue'
import BloggerSelectionPanel from '@/components/dashboard/BloggerSelectionPanel.vue'
import BriefFileUpload from '@/components/BriefFileUpload.vue'
import CelebrationModal from '@/components/CelebrationModal.vue'
import { DashboardSkeleton } from '@/components/skeletons'
import ErrorState from '@/components/ErrorState.vue'
import ErrorCard from '@/components/ErrorCard.vue'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore, useToastStore, useErrorStore } from '@/stores'
import { useRealtimeStore } from '@/stores/realtime'

const { t } = useI18n()
const router = useRouter()
const workflowStore = useWorkflowStore()
const toastStore = useToastStore()
const errorStore = useErrorStore()

// Auto-enter replay mode from URL query
const route = router.currentRoute
if (route.value.query.replay === 'true' && workflowStore.activeThreadId) {
  workflowStore.enterReplayMode()
}

const showOptimization = computed(() =>
  workflowStore.currentPhase === 'creating' ||
  workflowStore.isAwaitingDraft ||
  workflowStore.isAwaitingChoice
)
const showBloggerSelection = computed(() =>
  workflowStore.isAwaitingBloggerSelection
)
const showBriefUpload = computed(() =>
  !workflowStore.isReplayMode &&
  (workflowStore.isAwaitingBrief ||
  (workflowStore.currentPhase === 'briefing' && !workflowStore.briefUploadedText))
)
const showBriefContent = computed(() => {
  const bc = workflowStore.workflowState?.brief_content
  return bc && Object.keys(bc).length > 0 && (bc.brand_name || bc.raw_text)
})
const isLoading = computed(() => workflowStore.isLoading && !workflowStore.workflowState)
const hasError = computed(() => workflowStore.error !== null)

const nextAction = computed(() => {
  if (workflowStore.isAwaitingReview) {
    return {
      icon: 'CheckCircle',
      title: t('dashboard.nextAction.reviewTitle'),
      description: t('dashboard.nextAction.reviewDesc'),
      label: t('dashboard.nextAction.reviewCta'),
      path: workflowStore.activeThreadId ? `/review/${workflowStore.activeThreadId}` : '/review',
    }
  }
  if (workflowStore.isAwaitingBrief || workflowStore.isAwaitingDraft || workflowStore.isAwaitingChoice) {
    return {
      icon: 'Pencil',
      title: t('dashboard.nextAction.continueTitle'),
      description: t('dashboard.nextAction.continueDesc'),
      label: t('dashboard.nextAction.continueCta'),
      path: '/dashboard',
    }
  }
  if (!workflowStore.activeThreadId && workflowStore.currentPhase === 'idle') {
    return {
      icon: 'Rocket',
      title: t('dashboard.nextAction.startTitle'),
      description: t('dashboard.nextAction.startDesc'),
      label: t('dashboard.nextAction.startCta'),
      path: '/start',
    }
  }
  return null
})

// Celebration state
const showCelebration = ref(false)
const hasShownCelebration = ref(false)

// Watch for workflow completion
watch(
  () => workflowStore.currentPhase,
  (newPhase, oldPhase) => {
    if (newPhase === 'completed' && oldPhase !== 'completed' && !hasShownCelebration.value) {
      showCelebration.value = true
      hasShownCelebration.value = true
      toastStore.success(t('dashboard.completed'), t('dashboard.completedMessage'))
    }
  }
)

const handleCloseCelebration = () => {
  showCelebration.value = false
}

// ErrorCard handlers
const handleErrorRetry = () => {
  errorStore.clearError()
  if (workflowStore.activeThreadId) {
    void workflowStore.refreshStatus()
  } else {
    router.push('/start')
  }
}

const handleErrorDismiss = () => {
  errorStore.clearError()
}

async function handleBriefConfirm(_text: string) {
  // Upload already updated state; resume workflow to proceed with brief_analyzer
  await workflowStore.resumeWorkflow()
  toastStore.success(t('brief.uploadSuccess'), t('brief.confirmed'))
}

async function handleBriefSkip() {
  // Resume with skip decision — brief_gate will mark clarification as resolved
  await workflowStore.resumeWorkflow({ action: 'skip' })
  toastStore.success(t('brief.skipped'))
}

function handleBriefClear() {
  workflowStore.clearBriefUpload()
}

onMounted(async () => {
  const threadId = route.value.params.threadId
  if (typeof threadId === 'string' && threadId && threadId !== workflowStore.activeThreadId) {
    workflowStore.setThreadId(threadId)
  }
  const realtimeStore = useRealtimeStore()
  realtimeStore.connect()
  // Refresh all tabs first — this also cleans up stale IDs from localStorage
  if (workflowStore.openTabIds.length > 0) {
    await workflowStore.refreshAllTabs()
  }
  // Subscribe WebSocket for valid open tabs only (after cleanup)
  const validIds = workflowStore.openTabIds
  if (validIds.length > 0) {
    for (const id of validIds) {
      realtimeStore.subscribeWorkflow(id)
    }
    workflowStore.startPolling(workflowStore.currentPhase === 'planning' ? 3000 : 5000)
  } else if (workflowStore.activeThreadId && workflowStore.workflowStates.has(workflowStore.activeThreadId)) {
    // Only subscribe if the active thread has valid state
    realtimeStore.subscribeWorkflow(workflowStore.activeThreadId)
    workflowStore.refreshStatus()
    workflowStore.startPolling(workflowStore.currentPhase === 'planning' ? 3000 : 5000)
  }
})

onUnmounted(() => {
  workflowStore.stopPolling()
})
</script>

<template>
  <div class="dashboard-container">
    <!-- Workflow Tab Bar (sticky) -->
    <div class="pb-1">
      <WorkflowTabBar
        v-if="workflowStore.openTabIds.length > 0"
        :tabs="workflowStore.visibleTabs"
        :active-thread-id="workflowStore.activeThreadId"
        :has-overflow="workflowStore.hasOverflow"
        :overflow-tabs="workflowStore.overflowTabs"
        @switch="workflowStore.switchTab($event)"
        @close="workflowStore.closeTab($event)"
        @rename="(id, label) => workflowStore.renameTab(id, label)"
      />
    </div>

    <DashboardSkeleton v-if="isLoading" />
    <div v-else class="space-y-3 md:space-y-5">
      <ErrorState v-if="hasError" />

      <!-- ErrorCard for API errors -->
      <ErrorCard
        v-if="errorStore.hasError && errorStore.errorType"
        :type="errorStore.errorType"
        :message="errorStore.errorMessage"
        :retry-count="errorStore.retryCount"
        @retry="handleErrorRetry"
        @dismiss="handleErrorDismiss"
      />

      <!-- One prominent next step prevents users from scanning the full timeline. -->
      <div v-if="nextAction" class="flex items-center gap-3 rounded-xl border border-cyan-200/70 bg-gradient-to-r from-cyan-50/90 to-white p-3 md:p-4">
        <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-cyan-100">
          <AppIcon :name="nextAction.icon" size="md" variant="cyan" aria-hidden="true" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-semibold text-slate-700">{{ nextAction.title }}</div>
          <p class="mt-0.5 text-xs text-slate-500">{{ nextAction.description }}</p>
        </div>
        <NeonButton variant="cyan" size="sm" @click="router.push(nextAction.path)">
          {{ nextAction.label }}
        </NeonButton>
      </div>

      <!-- Stale Workflow Recovery -->
      <div v-if="workflowStore.isStale" class="rounded-xl p-3 md:p-4 liquid-glass-amber liquid-glass-hover">
        <div class="flex items-start gap-2 md:gap-3">
          <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-amber-100 flex items-center justify-center flex-shrink-0">
            <AppIcon name="AlertTriangle" size="md" variant="peach" />
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-amber-700 font-semibold text-sm mb-1">{{ t('workflow.staleDetected') }}</div>
            <p class="text-amber-600 text-xs md:text-sm mb-2">{{ t('workflow.staleHint') }}</p>
            <button
              @click="workflowStore.resumeWorkflow()"
              class="btn-sm bg-amber-100 text-amber-600 hover:bg-amber-200 text-xs"
            >
              {{ t('dashboard.actionButtons.resume') }}
            </button>
          </div>
        </div>
      </div>

      <!-- Publish Error Recovery -->
      <div v-if="workflowStore.publishError" class="liquid-glass-rose rounded-xl p-3 md:p-4">
        <div class="flex items-start gap-2 md:gap-3">
          <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-rose-100 flex items-center justify-center flex-shrink-0">
            <AppIcon name="AlertTriangle" size="md" variant="pink" />
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-rose-700 font-semibold text-sm mb-1">{{ t('dashboard.publishFailed') }}</div>
            <p class="text-rose-600 text-xs md:text-sm mb-2">{{ workflowStore.publishError.message }}</p>
            <div v-if="workflowStore.publishError.recovery" class="space-y-2">
              <p class="text-xs text-rose-500">{{ workflowStore.publishError.recovery.hint }}</p>
              <div class="flex flex-wrap items-center gap-2">
                <button
                  v-if="workflowStore.publishError.recovery.action === 'retry'"
                  @click="workflowStore.retryPublish()"
                  class="btn-sm bg-rose-100 text-rose-600 hover:bg-rose-200 text-xs"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <button
                  v-if="workflowStore.publishError.recovery.action === 'revise_content'"
                  @click="router.push('/review')"
                  class="btn-sm bg-amber-100 text-amber-600 hover:bg-amber-200 text-xs"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <button
                  v-if="workflowStore.publishError.recovery.action === 'reconfigure'"
                  @click="router.push('/start')"
                  class="btn-sm bg-violet-100 text-violet-600 hover:bg-violet-200 text-xs"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <button
                  v-if="workflowStore.publishError.recovery.action === 'retry_later'"
                  @click="workflowStore.resumeWorkflow()"
                  class="btn-sm bg-amber-100 text-amber-600 hover:bg-amber-200 text-xs"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
                <button
                  v-if="workflowStore.publishError.recovery.action === 'provide_images'"
                  @click="router.push('/review')"
                  class="btn-sm bg-teal-100 text-teal-600 hover:bg-teal-200 text-xs"
                >
                  {{ workflowStore.publishError.recovery.action_label }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <WorkflowHeader />

      <!-- Replay mode banner -->
      <div v-if="workflowStore.isReplayMode" class="rounded-xl p-3 md:p-4 liquid-glass-violet liquid-glass-hover">
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2 md:gap-3 min-w-0">
            <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-violet-100 flex items-center justify-center flex-shrink-0">
              <AppIcon name="History" size="md" variant="purple" />
            </div>
            <div class="min-w-0">
              <div class="text-violet-700 font-semibold text-sm">{{ t('workflow.replayMode') }}</div>
              <p class="text-violet-500 text-xs truncate">{{ t('workflow.replayModeDesc') }}</p>
            </div>
          </div>
          <NeonButton variant="ghost" size="sm" @click="workflowStore.exitReplayMode()">
            {{ t('workflow.exitReplay') }}
          </NeonButton>
        </div>
      </div>

      <!-- Brief Content Summary (shown after brief is parsed) -->
      <div v-if="showBriefContent && !showBriefUpload" class="rounded-xl p-3 md:p-4 liquid-glass">
        <div class="flex items-center gap-2 mb-3">
          <AppIcon name="FileText" size="sm" variant="pink" />
          <span class="text-sm font-semibold text-slate-700">{{ t('brief.contentTitle') }}</span>
          <span v-if="workflowStore.workflowState?.brief_content?.confidence != null" class="text-[10px] px-1.5 py-0.5 rounded-full"
            :class="(workflowStore.workflowState?.brief_content?.confidence ?? 0) >= 0.6 ? 'bg-teal-50 text-teal-600' : 'bg-amber-50 text-amber-600'">
            {{ Math.round((workflowStore.workflowState?.brief_content?.confidence ?? 0) * 100) }}%
          </span>
        </div>
        <div class="space-y-2">
          <div v-if="workflowStore.workflowState?.brief_content?.brand_name" class="flex items-start gap-2">
            <span class="text-xs text-slate-400 min-w-[60px]">{{ t('brief.brand') }}</span>
            <span class="text-sm text-slate-700 font-medium">{{ workflowStore.workflowState.brief_content.brand_name }}</span>
          </div>
          <div v-if="workflowStore.workflowState?.brief_content?.product_name" class="flex items-start gap-2">
            <span class="text-xs text-slate-400 min-w-[60px]">{{ t('brief.product') }}</span>
            <span class="text-sm text-slate-700 font-medium">{{ workflowStore.workflowState.brief_content.product_name }}</span>
          </div>
          <div v-if="workflowStore.workflowState?.brief_content?.content_direction" class="flex items-start gap-2">
            <span class="text-xs text-slate-400 min-w-[60px]">{{ t('brief.direction') }}</span>
            <span class="text-sm text-slate-700">{{ workflowStore.workflowState.brief_content.content_direction }}</span>
          </div>
          <div v-if="workflowStore.workflowState?.brief_content?.selling_points?.length" class="flex items-start gap-2">
            <span class="text-xs text-slate-400 min-w-[60px]">{{ t('brief.sellingPoints') }}</span>
            <div class="flex flex-wrap gap-1">
              <span v-for="sp in workflowStore.workflowState.brief_content.selling_points" :key="sp" class="text-[11px] px-1.5 py-0.5 rounded bg-pink-50 text-pink-600">{{ sp }}</span>
            </div>
          </div>
          <div v-if="workflowStore.workflowState?.brief_content?.required_hashtags?.length" class="flex items-start gap-2">
            <span class="text-xs text-slate-400 min-w-[60px]">{{ t('brief.hashtags') }}</span>
            <div class="flex flex-wrap gap-1">
              <span v-for="tag in workflowStore.workflowState.brief_content.required_hashtags" :key="tag" class="text-[11px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
            </div>
          </div>
          <details v-if="workflowStore.workflowState?.brief_content?.raw_text" class="mt-2">
            <summary class="text-xs text-slate-400 cursor-pointer hover:text-slate-600">{{ t('brief.viewRaw') }}</summary>
            <pre class="mt-1.5 p-2.5 rounded-lg bg-slate-50 text-xs text-slate-600 whitespace-pre-wrap max-h-40 overflow-y-auto">{{ workflowStore.workflowState.brief_content.raw_text }}</pre>
          </details>
        </div>
      </div>

      <!-- Brief PDF Upload (shown when awaiting brief input) -->
      <div v-if="showBriefUpload" class="rounded-xl p-3 md:p-4 bg-gradient-to-br from-neon-pink/5 to-neon-peach/5 border border-neon-pink/20">
        <BriefFileUpload
          :is-uploading="workflowStore.isBriefUploading"
          :uploaded-text="workflowStore.briefUploadedText"
          :source-type="workflowStore.briefSourceType"
          :thread-id="workflowStore.currentThreadId || ''"
          @upload="(file: File) => workflowStore.uploadBriefPdf(workflowStore.currentThreadId!, file)"
          @confirm="handleBriefConfirm"
          @clear="handleBriefClear"
        />
        <!-- Skip button when brief_gate interrupted (has clarification questions) -->
        <div v-if="workflowStore.isAwaitingBrief && workflowStore.workflowState?.brief_content?.raw_text" class="flex justify-end mt-3">
          <NeonButton variant="ghost" size="sm" @click="handleBriefSkip">
            <span class="text-xs">{{ t('brief.skipClarification') }}</span>
          </NeonButton>
        </div>
      </div>

      <WorkflowTimeline />
      <ContentCards />
      <BloggerSelectionPanel v-if="showBloggerSelection" />
      <OptimizationPanel v-if="showOptimization" />
      <ActionButtons />
    </div>

    <!-- Celebration Modal -->
    <CelebrationModal
      :show="showCelebration"
      @close="handleCloseCelebration"
    />
  </div>
</template>
