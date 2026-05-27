<script setup lang="ts">
import { computed } from 'vue'
import CircularProgress from '@/components/CircularProgress.vue'
import AppIcon from '@/components/AppIcon.vue'
import MiniProgress from '@/components/MiniProgress.vue'
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
</script>

<template>
  <div class="rounded-2xl p-6 relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm">
    <div class="flex items-center gap-5">
      <!-- Progress & Logo -->
      <div class="flex items-center gap-4">
        <CircularProgress :value="workflowProgress" variant="cyan" size="lg" show-value />
        <div class="w-16 h-16 rounded-xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 flex items-center justify-center shadow-sm">
          <AppIcon name="Rocket" size="xl" variant="white" aria-label="Workflow" />
        </div>
      </div>

      <!-- Info -->
      <div class="flex-1 space-y-2">
        <div class="flex items-center gap-3">
          <span class="px-2 py-1 rounded bg-teal-50 text-teal-600 text-xs uppercase tracking-wide font-medium">WORKFLOW</span>
          <span class="text-xs text-slate-400">{{ workflowStore.currentThreadId || '—' }}</span>
        </div>
        <div class="text-xl font-semibold text-slate-800">
          {{ workflowStore.currentPhase === 'idle' ? '等待启动' : `${workflowStore.currentPhase} 阶段` }}
        </div>
        <MiniProgress :value="workflowProgress" variant="cyan" class="max-w-xs" />
      </div>

      <!-- Status Badge -->
      <div :class="[
        'px-4 py-2.5 rounded-lg border font-medium flex items-center gap-2 transition-all duration-200',
        workflowStore.isRunning
          ? 'bg-gradient-to-r from-teal-500 to-teal-400 border-teal-200 text-white shadow-sm'
          : 'bg-slate-50 border-slate-200 text-slate-500'
      ]">
        <AppIcon :name="workflowStore.isRunning ? 'Circle' : 'Minus'" size="sm" :variant="workflowStore.isRunning ? 'white' : 'cyan'" :animate="workflowStore.isRunning" />
        <span>{{ workflowStore.isRunning ? 'RUNNING' : 'IDLE' }}</span>
      </div>
    </div>
  </div>
</template>