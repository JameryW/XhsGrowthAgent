<script setup lang="ts">
import { computed } from 'vue'
import WorkflowNode from '@/components/WorkflowNode.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore } from '@/stores'

const workflowStore = useWorkflowStore()

// Memoized phase order for performance
const phaseOrder = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'completed'] as const

// Progress calculation based on current phase
const workflowProgress = computed(() => {
  const currentPhase = workflowStore.currentPhase
  const currentIndex = phaseOrder.indexOf(currentPhase as any)
  if (currentIndex === -1) return 0
  return Math.round((currentIndex / (phaseOrder.length - 1)) * 100)
})

// Workflow nodes configuration
const workflowNodes = computed(() => [
  { icon: 'Search', label: '趋势发现', phase: 'scouting' },
  { icon: 'ClipboardList', label: '策略规划', phase: 'planning' },
  { icon: 'Pencil', label: '文案创作', phase: 'creating' },
  { icon: 'Palette', label: '视觉设计', phase: 'creating' },
  { icon: 'Clock', label: '审核', phase: 'reviewing' },
  { icon: 'Upload', label: '发布', phase: 'publishing' },
])

// Use memoized phaseOrder for consistent lookup
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
  <div class="bg-white/98 backdrop-blur-sm rounded-2xl p-6 border border-slate-200/50 shadow-sm">
    <div class="flex items-center gap-2 mb-5">
      <AppIcon name="GitBranch" size="md" variant="cyan" />
      <span class="text-xs text-slate-500 uppercase tracking-wide font-medium">Workflow Pipeline</span>
    </div>

    <!-- Progress line -->
    <div class="relative py-4">
      <div class="absolute top-1/2 left-0 right-0 h-1 bg-slate-100 rounded-full" />
      <div
        class="absolute top-1/2 left-0 h-1 bg-gradient-to-r from-rose-400 to-teal-400 rounded-full transition-all duration-500"
        :style="{ width: `${workflowProgress}%` }"
      />
    </div>

    <!-- Nodes -->
    <div class="flex justify-between items-center relative px-4">
      <WorkflowNode
        v-for="node in workflowNodes"
        :key="node.phase"
        :icon="node.icon"
        :label="node.label"
        :status="getNodeStatus(node.phase)"
      />
    </div>
  </div>
</template>