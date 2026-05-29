<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore, useReviewStore } from '@/stores'

const { t } = useI18n()
const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()

// Check if workflow is active
const hasActiveWorkflow = computed(() => !!workflowStore.currentThreadId)
const isReviewing = computed(() => workflowStore.currentPhase === 'reviewing')
const needsReview = computed(() => reviewStore.hasPendingReview)
const isStarting = ref(false)

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
  <div class="flex flex-wrap gap-3" role="group" :aria-label="t('dashboard.actionButtons.ariaLabel')">
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
</template>