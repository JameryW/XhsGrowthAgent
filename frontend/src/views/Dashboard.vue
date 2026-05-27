<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, watch } from 'vue'
import WorkflowHeader from '@/components/dashboard/WorkflowHeader.vue'
import WorkflowTimeline from '@/components/dashboard/WorkflowTimeline.vue'
import ContentCards from '@/components/dashboard/ContentCards.vue'
import OptimizationPanel from '@/components/dashboard/OptimizationPanel.vue'
import ActionButtons from '@/components/dashboard/ActionButtons.vue'
import CelebrationModal from '@/components/CelebrationModal.vue'
import { DashboardSkeleton } from '@/components/skeletons'
import ErrorState from '@/components/ErrorState.vue'
import { useWorkflowStore, useToastStore } from '@/stores'

const workflowStore = useWorkflowStore()
const toastStore = useToastStore()

const showOptimization = computed(() => workflowStore.currentPhase === 'creating')
const isLoading = computed(() => workflowStore.isLoading && !workflowStore.workflowState)
const hasError = computed(() => workflowStore.error !== null)

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
      toastStore.success('工作流完成', '内容已成功发布到小红书')
    }
  }
)

const handleCloseCelebration = () => {
  showCelebration.value = false
}

onMounted(() => {
  if (workflowStore.currentThreadId) {
    workflowStore.refreshStatus()
    workflowStore.startPolling(5000)
  }
})

onUnmounted(() => {
  workflowStore.stopPolling()
})
</script>

<template>
  <DashboardSkeleton v-if="isLoading" />
  <div v-else class="space-y-6">
    <ErrorState v-if="hasError" />
    <WorkflowHeader />
    <WorkflowTimeline />
    <ContentCards />
    <OptimizationPanel v-if="showOptimization" />
    <ActionButtons />
  </div>

  <!-- Celebration Modal -->
  <CelebrationModal
    :show="showCelebration"
    @close="handleCloseCelebration"
  />
</template>