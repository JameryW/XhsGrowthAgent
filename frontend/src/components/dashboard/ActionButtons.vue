<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore, useReviewStore } from '@/stores'

const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()

// Check if workflow is waiting for review
const isReviewing = computed(() => workflowStore.currentPhase === 'reviewing')
const needsReview = computed(() => reviewStore.hasPendingReview)

// Operations
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
  <div class="flex flex-wrap gap-3">
    <!-- Prominent review button when workflow is in reviewing phase -->
    <NeonButton
      v-if="isReviewing"
      variant="cyan"
      size="lg"
      class="w-full sm:w-auto animate-pulse"
      @click="goToReview"
    >
      <span class="inline-flex items-center gap-2">
        <AppIcon name="CheckCircle" size="lg" variant="white" />
        <span class="font-bold">去审核内容</span>
        <span v-if="needsReview" class="text-xs opacity-70">待处理</span>
      </span>
    </NeonButton>

    <!-- Regular buttons when not reviewing -->
    <NeonButton v-if="!isReviewing" variant="pink" @click="pauseWorkflow" :loading="workflowStore.isLoading">
      <span class="inline-flex items-center gap-2">
        <AppIcon name="Pause" size="sm" variant="white" />
        <span>暂停工作流</span>
      </span>
    </NeonButton>

    <NeonButton variant="cyan" @click="workflowStore.refreshStatus()">
      <span class="inline-flex items-center gap-2">
        <AppIcon name="RefreshCw" size="sm" variant="white" />
        <span>刷新状态</span>
      </span>
    </NeonButton>

    <!-- Standard review button when not in reviewing phase -->
    <NeonButton v-if="!isReviewing" variant="purple" @click="goToReview">
      <span class="inline-flex items-center gap-2">
        <AppIcon name="CheckCircle" size="sm" variant="white" />
        <span>进入审核</span>
      </span>
    </NeonButton>
  </div>
</template>