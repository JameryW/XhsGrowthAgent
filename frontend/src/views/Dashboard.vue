<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import WorkflowHeader from '@/components/dashboard/WorkflowHeader.vue'
import WorkflowTimeline from '@/components/dashboard/WorkflowTimeline.vue'
import ContentCards from '@/components/dashboard/ContentCards.vue'
import OptimizationPanel from '@/components/dashboard/OptimizationPanel.vue'
import ActionButtons from '@/components/dashboard/ActionButtons.vue'
import { useWorkflowStore } from '@/stores'

const workflowStore = useWorkflowStore()
const showOptimization = computed(() => workflowStore.currentPhase === 'creating')

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
  <div class="space-y-6">
    <WorkflowHeader />
    <WorkflowTimeline />
    <ContentCards />
    <OptimizationPanel v-if="showOptimization" />
    <ActionButtons />
  </div>
</template>