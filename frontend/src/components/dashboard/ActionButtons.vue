<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore, useReviewStore, useRealtimeStore, useAccountsStore } from '@/stores'
import { accountIdFromThreadId } from '@/utils/threadAccount'
import { accountQuery } from '@/utils/accountViewSession'

const { t } = useI18n()
const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()
const realtimeStore = useRealtimeStore()
const accountsStore = useAccountsStore()

// Check if workflow is active
const hasActiveWorkflow = computed(() => !!workflowStore.currentThreadId)
const isReviewing = computed(() => workflowStore.currentPhase === 'reviewing')
const isPaused = computed(() => workflowStore.currentPhase === 'paused')
const isStale = computed(() => workflowStore.isStale)
const isCancelled = computed(() => workflowStore.currentPhase === 'cancelled')
const needsReview = computed(() => reviewStore.hasPendingReview)
const canPause = computed(() => workflowStore.isRunning)
const canReview = computed(() => workflowStore.isAwaitingReview || isReviewing.value)
const waitingStatusText = computed(() => {
  if (workflowStore.isAwaitingDraft) return t('dashboard.actionButtons.awaitingDraft')
  if (workflowStore.isAwaitingChoice) return t('dashboard.actionButtons.awaitingChoice')
  if (workflowStore.isAwaitingReview) return t('dashboard.actionButtons.awaitingReview')
  if (workflowStore.isAwaitingBrief) return t('dashboard.actionButtons.awaitingBrief')
  if (workflowStore.isAwaitingRippleDecision) return t('dashboard.actionButtons.awaitingRipple')
  if (workflowStore.isAwaitingBloggerSelection) return t('dashboard.actionButtons.awaitingBlogger')
  return ''
})

// Phase-aware computed
const currentPhase = computed(() => workflowStore.currentPhase)
const hasRippleData = computed(() => workflowStore.hasRippleData)
const publishResult = computed(() => (workflowStore.workflowState as any)?.publish_result || {})
const hasPostUrl = computed(() => !!publishResult.value?.post_url)

// Status source indicator
const statusSource = computed(() => {
  if (realtimeStore.connectionStatus === 'connected') return 'realtime'
  if (workflowStore.workflowState) return 'polling'
  return 'snapshot'
})

const statusSourceLabel = computed(() => {
  switch (statusSource.value) {
    case 'realtime': return t('connection.connected')
    case 'polling': return t('connection.reconnecting')
    default: return t('connection.disconnected')
  }
})

const statusSourceIcon = computed(() => {
  switch (statusSource.value) {
    case 'realtime': return 'Wifi'
    case 'polling': return 'RefreshCw'
    default: return 'WifiOff'
  }
})

const statusSourceColor = computed(() => {
  switch (statusSource.value) {
    case 'realtime': return 'text-emerald-500'
    case 'polling': return 'text-amber-500'
    default: return 'text-slate-400'
  }
})

// Operations
const startNewWorkflow = () => {
  router.push('/start')
}

const pauseWorkflow = () => {
  workflowStore.pauseWorkflow()
}

const goToReview = () => {
  const threadId = workflowStore.currentThreadId
  if (!threadId) return
  reviewStore.fetchPendingReview(threadId)
  const owner =
    workflowStore.effectiveState?.account_id
    || accountIdFromThreadId(threadId)
  const q = accountQuery(owner, { omitIfEquals: accountsStore.activeAccountId })
  router.push({
    name: 'review',
    params: { threadId },
    query: q,
  })
}

const resumeWorkflow = () => {
  workflowStore.resumeWorkflow()
}

const openPostUrl = () => {
  if (publishResult.value?.post_url) {
    window.open(publishResult.value.post_url, '_blank', 'noopener,noreferrer')
  }
}
</script>

<template>
  <div class="space-y-2 md:space-y-3" role="group" :aria-label="t('dashboard.actionButtons.ariaLabel')">
    <!-- Status source indicator -->
    <div class="flex items-center justify-between px-1">
      <div class="flex items-center gap-2">
        <AppIcon
          :name="statusSourceIcon"
          size="sm"
          :class="statusSourceColor"
        />
        <span class="text-xs text-slate-500">{{ statusSourceLabel }}</span>
      </div>
      <span v-if="hasActiveWorkflow" class="text-xs text-slate-400">
        {{ workflowStore.currentThreadId?.slice(0, 12) }}...
      </span>
    </div>

    <div
      v-if="waitingStatusText"
      class="flex items-center gap-2 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-200"
      role="status"
      aria-live="polite"
    >
      <AppIcon name="Clock" size="sm" variant="cyan" aria-hidden="true" />
      <span>{{ waitingStatusText }}</span>
    </div>

    <!-- Action buttons -->
    <div class="flex flex-wrap gap-3">
      <!-- Start new workflow when no active workflow -->
      <NeonButton
        v-if="!hasActiveWorkflow"
        variant="pink"
        size="lg"
        class="w-full sm:w-auto"
        :title="t('dashboard.actionButtons.startNewDesc')"
        :aria-label="t('dashboard.actionButtons.startNew')"
        @click="startNewWorkflow"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="Rocket" size="lg" variant="white" />
          <span class="font-bold">{{ t('dashboard.actionButtons.startNew') }}</span>
        </span>
      </NeonButton>

      <!-- Prominent review button when workflow is in reviewing phase -->
      <NeonButton
        v-if="canReview"
        variant="cyan"
        size="lg"
        class="w-full sm:w-auto animate-pulse"
        :title="t('dashboard.actionButtons.goReviewPendingDesc')"
        :aria-label="t('dashboard.actionButtons.goReviewPending')"
        @click="goToReview"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="CheckCircle" size="lg" variant="white" />
          <span class="font-bold">{{ t('dashboard.actionButtons.goReview') }}</span>
          <span v-if="needsReview" class="text-xs opacity-70">{{ t('dashboard.timeline.pending') }}</span>
        </span>
      </NeonButton>

      <!-- Draft edit button when awaiting draft confirmation -->
      <NeonButton
        v-if="workflowStore.isAwaitingDraft"
        variant="pink"
        size="lg"
        class="w-full sm:w-auto animate-pulse"
        :aria-label="t('dashboard.actionButtons.editDraft')"
        @click="router.push('/dashboard')"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="Pencil" size="lg" variant="white" />
          <span class="font-bold">{{ t('dashboard.actionButtons.editDraft') }}</span>
        </span>
      </NeonButton>

      <!-- Resume button when paused -->
      <NeonButton
        v-if="isPaused"
        variant="cyan"
        size="lg"
        class="w-full sm:w-auto"
        :title="t('dashboard.actionButtons.resumeDesc')"
        :aria-label="t('dashboard.actionButtons.resume')"
        :loading="workflowStore.isLoading"
        @click="resumeWorkflow"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="Play" size="lg" variant="white" />
          <span class="font-bold">{{ t('dashboard.actionButtons.resume') }}</span>
        </span>
      </NeonButton>

      <!-- Resume button when stale -->
      <NeonButton
        v-if="isStale"
        variant="peach"
        size="lg"
        class="w-full sm:w-auto"
        :title="t('workflow.staleHint')"
        :aria-label="t('dashboard.actionButtons.resume')"
        :loading="workflowStore.isLoading"
        @click="resumeWorkflow"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="Play" size="lg" variant="white" />
          <span class="font-bold">{{ t('dashboard.actionButtons.resume') }}</span>
        </span>
      </NeonButton>

      <!-- Start new workflow when cancelled -->
      <NeonButton
        v-if="isCancelled"
        variant="pink"
        size="lg"
        class="w-full sm:w-auto"
        :title="t('dashboard.actionButtons.startNewDesc')"
        :aria-label="t('dashboard.actionButtons.startNew')"
        @click="startNewWorkflow"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="Rocket" size="lg" variant="white" />
          <span class="font-bold">{{ t('dashboard.actionButtons.startNew') }}</span>
        </span>
      </NeonButton>

      <!-- Regular buttons when not reviewing, paused, or cancelled -->
      <NeonButton
        v-if="canPause"
        variant="pink"
        size="sm"
        :title="t('dashboard.actionButtons.pauseDesc')"
        :aria-label="t('dashboard.actionButtons.pause')"
        @click="pauseWorkflow"
        :loading="workflowStore.isLoading"
      >
        <span class="inline-flex items-center gap-1.5">
          <AppIcon name="Pause" size="sm" variant="white" />
          <span>{{ t('dashboard.actionButtons.pause') }}</span>
        </span>
      </NeonButton>

      <NeonButton
        variant="cyan"
        size="sm"
        :title="t('dashboard.actionButtons.refreshDesc')"
        :aria-label="t('dashboard.actionButtons.refresh')"
        @click="workflowStore.refreshStatus()"
      >
        <span class="inline-flex items-center gap-1.5">
          <AppIcon name="RefreshCw" size="sm" variant="white" />
          <span>{{ t('dashboard.actionButtons.refresh') }}</span>
        </span>
      </NeonButton>

      <!-- Context-aware: View post after publishing -->
      <NeonButton
        v-if="hasPostUrl && (currentPhase === 'publishing' || currentPhase === 'analyzing' || currentPhase === 'completed')"
        variant="cyan"
        size="sm"
        :title="t('dashboard.publishResult.viewPost')"
        @click="openPostUrl"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="ExternalLink" size="sm" variant="white" />
          <span>{{ t('dashboard.publishResult.viewPost') }}</span>
        </span>
      </NeonButton>

      <!-- Context-aware: Ripple data available indicator -->
      <div
        v-if="hasRippleData && (currentPhase === 'planning' || currentPhase === 'analyzing')"
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-50 border border-violet-100 text-violet-600 text-xs dark:bg-violet-950/40 dark:border-violet-500/30 dark:text-violet-200"
      >
        <AppIcon name="Zap" size="sm" variant="purple" />
        <span>{{ t('dashboard.ripple.title') }}</span>
      </div>
    </div>
  </div>
</template>
