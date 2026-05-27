<script setup lang="ts">
import ContentCard from '@/components/ContentCard.vue'
import { useWorkflowStore } from '@/stores'

const workflowStore = useWorkflowStore()

// Memoized phase order for consistent status lookup
const phaseOrder = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'completed'] as const

const getNodeStatus = (phase: string) => {
  const currentPhase = workflowStore.currentPhase
  const currentIndex = phaseOrder.indexOf(currentPhase as any)
  const nodeIndex = phaseOrder.indexOf(phase as any)

  if (nodeIndex < currentIndex) return 'completed'
  if (nodeIndex === currentIndex) return 'running'
  return 'pending'
}
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
    <ContentCard
      v-if="Object.keys(workflowStore.trendData).length > 0"
      title="趋势发现"
      icon="Search"
      :content="workflowStore.trendData"
      variant="pink"
      :completed="getNodeStatus('scouting') === 'completed'"
    />
    <ContentCard
      v-if="Object.keys(workflowStore.contentPlan).length > 0"
      title="策略规划"
      icon="ClipboardList"
      :content="workflowStore.contentPlan"
      variant="cyan"
      :completed="getNodeStatus('planning') === 'completed'"
    />
    <ContentCard
      v-if="Object.keys(workflowStore.copyContent).length > 0"
      title="文案创作"
      icon="Pencil"
      :content="workflowStore.copyContent"
      variant="purple"
      :completed="true"
    />
  </div>
</template>