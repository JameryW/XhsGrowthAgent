<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore, useReviewStore, useRealtimeStore } from '@/stores'

const { t } = useI18n()
const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()
const realtimeStore = useRealtimeStore()

// Check if workflow is active
const hasActiveWorkflow = computed(() => !!workflowStore.currentThreadId)
const isReviewing = computed(() => workflowStore.currentPhase === 'reviewing')
const needsReview = computed(() => reviewStore.hasPendingReview)
const isStarting = ref(false)

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
const startNewWorkflow = async () => {
  isStarting.value = true
  try {
    await workflowStore.startWorkflow('default', 'scouting')
  } finally {
    isStarting.value = false
  }
}

const pauseWorkflow = () => {
  workflowStore.pauseWorkflow()
}

const goToReview = () => {
  if (workflowStore.currentThreadId) {
    reviewStore.fetchPendingReview(workflowStore.currentThreadId)
    router.push('/review')
  }
}
</script>

<template>
  <div class="space-y-3" role="group" :aria-label="t('dashboard.actionButtons.ariaLabel')">
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
        :loading="isStarting"
        @click="startNewWorkflow"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="Rocket" size="lg" variant="white" />
          <span class="font-bold">{{ t('dashboard.actionButtons.startNew') }}</span>
        </span>
      </NeonButton>

      <!-- Prominent review button when workflow is in reviewing phase -->
      <NeonButton
        v-if="isReviewing"
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

      <!-- Regular buttons when not reviewing -->
      <NeonButton
        v-if="!isReviewing"
        variant="pink"
        :title="t('dashboard.actionButtons.pauseDesc')"
        :aria-label="t('dashboard.actionButtons.pause')"
        @click="pauseWorkflow"
        :loading="workflowStore.isLoading"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="Pause" size="sm" variant="white" />
          <span>{{ t('dashboard.actionButtons.pause') }}</span>
        </span>
      </NeonButton>

      <NeonButton
        variant="cyan"
        :title="t('dashboard.actionButtons.refreshDesc')"
        :aria-label="t('dashboard.actionButtons.refresh')"
        @click="workflowStore.refreshStatus()"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="RefreshCw" size="sm" variant="white" />
          <span>{{ t('dashboard.actionButtons.refresh') }}</span>
        </span>
      </NeonButton>

      <!-- Standard review button when not in reviewing phase -->
      <NeonButton
        v-if="!isReviewing"
        variant="purple"
        :title="t('dashboard.actionButtons.goReviewDesc')"
        :aria-label="t('dashboard.actionButtons.goReview')"
        @click="goToReview"
      >
        <span class="inline-flex items-center gap-2">
          <AppIcon name="CheckCircle" size="sm" variant="white" />
          <span>{{ t('dashboard.actionButtons.goReview') }}</span>
        </span>
      </NeonButton>
    </div>
  </div>
</template>