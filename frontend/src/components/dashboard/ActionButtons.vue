<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import NeonButton from '@/components/NeonButton.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore, useReviewStore } from '@/stores'

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
  <div class="flex flex-wrap gap-3" role="group" aria-label="工作流操作按钮">
    <!-- Start new workflow when no active workflow -->
    <NeonButton
      v-if="!hasActiveWorkflow"
      variant="pink"
      size="lg"
      class="w-full sm:w-auto"
      title="启动新的内容增长工作流"
      aria-label="启动新工作流"
      :loading="isStarting"
      @click="startNewWorkflow"
    >
      <span class="inline-flex items-center gap-2">
        <AppIcon name="Rocket" size="lg" variant="white" />
        <span class="font-bold">启动新工作流</span>
      </span>
    </NeonButton>

    <!-- Prominent review button when workflow is in reviewing phase -->
    <NeonButton
      v-if="isReviewing"
      variant="cyan"
      size="lg"
      class="w-full sm:w-auto animate-pulse"
      title="前往审核页面查看并决定内容"
      aria-label="去审核内容 - 内容已准备好等待审核"
      @click="goToReview"
    >
      <span class="inline-flex items-center gap-2">
        <AppIcon name="CheckCircle" size="lg" variant="white" />
        <span class="font-bold">去审核内容</span>
        <span v-if="needsReview" class="text-xs opacity-70">待处理</span>
      </span>
    </NeonButton>

    <!-- Regular buttons when not reviewing -->
    <NeonButton
      v-if="!isReviewing"
      variant="pink"
      title="暂停当前工作流执行"
      aria-label="暂停工作流"
      @click="pauseWorkflow"
      :loading="workflowStore.isLoading"
    >
      <span class="inline-flex items-center gap-2">
        <AppIcon name="Pause" size="sm" variant="white" />
        <span>暂停工作流</span>
      </span>
    </NeonButton>

    <NeonButton
      variant="cyan"
      title="刷新获取最新工作流状态"
      aria-label="刷新状态"
      @click="workflowStore.refreshStatus()"
    >
      <span class="inline-flex items-center gap-2">
        <AppIcon name="RefreshCw" size="sm" variant="white" />
        <span>刷新状态</span>
      </span>
    </NeonButton>

    <!-- Standard review button when not in reviewing phase -->
    <NeonButton
      v-if="!isReviewing"
      variant="purple"
      title="前往审核页面查看内容"
      aria-label="进入审核页面"
      @click="goToReview"
    >
      <span class="inline-flex items-center gap-2">
        <AppIcon name="CheckCircle" size="sm" variant="white" />
        <span>进入审核</span>
      </span>
    </NeonButton>
  </div>
</template>