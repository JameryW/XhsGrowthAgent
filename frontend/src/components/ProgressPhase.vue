<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLoading } from '@/composables/useLoading'
import AnimatedCounter from '@/components/AnimatedCounter.vue'
import type { WorkflowPhase } from '@/types'

const { t } = useI18n()

interface Props {
  percent: number
  currentPhase?: WorkflowPhase
}

const props = withDefaults(defineProps<Props>(), {
  currentPhase: 'idle'
})

const { phaseToColor } = useLoading()

const phaseLabels: Record<string, string> = {
  idle: t('dashboard.phase.idle'),
  scouting: t('dashboard.phase.scouting'),
  planning: t('dashboard.phase.planning'),
  creating: t('dashboard.phase.creating'),
  reviewing: t('dashboard.phase.reviewing'),
  publishing: t('dashboard.phase.publishing'),
  analyzing: t('dashboard.phase.analyzing'),
  engaging: t('dashboard.phase.engaging'),
  completed: t('dashboard.phase.completed'),
  error: t('dashboard.phase.error'),
  cancelled: t('dashboard.phase.cancelled'),
}

const progressColor = computed(() => {
  return phaseToColor(props.currentPhase)
})

const progressWidth = computed(() => {
  return `${props.percent}%`
})

const phaseDisplay = computed(() => phaseLabels[props.currentPhase] || props.currentPhase)
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
        {{ phaseDisplay }}
      </span>
      <span class="text-xs text-slate-600 font-semibold">
        <AnimatedCounter :value="percent" :duration="300" :format="(v: number) => `${v}%`" />
      </span>
    </div>
  </div>
</template>

<style scoped>
.progress-phase-wrapper {
  width: 100%;
}
</style>