<script setup lang="ts">
import { computed } from 'vue'
import { useLoading } from '@/composables/useLoading'
import type { WorkflowPhase } from '@/types'

interface Props {
  percent: number
  currentPhase?: WorkflowPhase
}

const props = withDefaults(defineProps<Props>(), {
  currentPhase: 'idle'
})

const { phaseToColor } = useLoading()

const progressColor = computed(() => {
  return phaseToColor(props.currentPhase)
})

const progressWidth = computed(() => {
  return `${props.percent}%`
})
</script>

<template>
  <div class="progress-phase-wrapper">
    <div class="progress-bar-container bg-slate-200 rounded-full h-2 overflow-hidden">
      <div
        class="progress-bar-fill h-full transition-all duration-500 ease-out"
        :style="{ width: progressWidth, background: progressColor }"
        role="progressbar"
        :aria-valuenow="percent"
        aria-valuemin="0"
        aria-valuemax="100"
      />
    </div>

    <div class="flex justify-between items-center mt-2">
      <span class="text-xs text-slate-500 font-medium uppercase tracking-wide">
        {{ currentPhase }}
      </span>
      <span class="text-xs text-slate-600 font-semibold">
        {{ percent }}%
      </span>
    </div>
  </div>
</template>

<style scoped>
.progress-phase-wrapper {
  width: 100%;
}
</style>