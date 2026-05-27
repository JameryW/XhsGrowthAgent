<script setup lang="ts">
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore, useReviewStore } from '@/stores'

const router = useRouter()
const workflowStore = useWorkflowStore()
const reviewStore = useReviewStore()

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
    <NeonButton variant="pink" @click="pauseWorkflow" :loading="workflowStore.isLoading">
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
    <NeonButton variant="purple" @click="goToReview">
      <span class="inline-flex items-center gap-2">
        <AppIcon name="CheckCircle" size="sm" variant="white" />
        <span>进入审核</span>
      </span>
    </NeonButton>
  </div>
</template>