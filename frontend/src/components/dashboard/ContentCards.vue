<script setup lang="ts">
import ContentCard from '@/components/ContentCard.vue'
import AppIcon from '@/components/AppIcon.vue'
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

// Check if workflow is idle (not started)
const isIdle = () => workflowStore.currentPhase === 'idle'

// Check if all cards are empty
const allEmpty = () =>
  Object.keys(workflowStore.trendData).length === 0 &&
  Object.keys(workflowStore.contentPlan).length === 0 &&
  Object.keys(workflowStore.copyContent).length === 0
</script>

<template>
  <!-- Empty state when workflow hasn't started -->
  <div v-if="isIdle()" class="text-center py-12">
    <div class="w-16 h-16 mx-auto rounded-full bg-slate-100 flex items-center justify-center mb-4">
      <AppIcon name="Rocket" size="lg" variant="cyan" />
    </div>
    <p class="text-slate-500 text-lg mb-2">工作流尚未启动</p>
    <p class="text-slate-400 text-sm">前往首页开始新的增长流程</p>
  </div>

  <!-- Empty state when started but no data yet -->
  <div v-else-if="allEmpty() && !isIdle()" class="grid grid-cols-1 lg:grid-cols-3 gap-4">
    <div class="rounded-xl p-6 bg-white/98 border border-slate-200/50 text-center">
      <AppIcon name="Search" size="md" variant="pink" class="mb-3" />
      <p class="text-slate-400 text-sm">趋势数据正在收集...</p>
    </div>
    <div class="rounded-xl p-6 bg-white/98 border border-slate-200/50 text-center">
      <AppIcon name="ClipboardList" size="md" variant="cyan" class="mb-3" />
      <p class="text-slate-400 text-sm">策略规划即将开始...</p>
    </div>
    <div class="rounded-xl p-6 bg-white/98 border border-slate-200/50 text-center">
      <AppIcon name="Pencil" size="md" variant="purple" class="mb-3" />
      <p class="text-slate-400 text-sm">文案创作待处理...</p>
    </div>
  </div>

  <!-- Cards with data -->
  <div v-else class="grid grid-cols-1 lg:grid-cols-3 gap-4">
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