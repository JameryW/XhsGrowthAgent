<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'

interface Step {
  name: string
  status: 'completed' | 'active' | 'pending'
}

interface Props {
  steps: Step[]
  layout?: 'horizontal' | 'vertical'
}

withDefaults(defineProps<Props>(), {
  layout: 'vertical'
})

const getStepIconClass = (status: string) => {
  switch (status) {
    case 'completed': return 'bg-teal-500 text-white'
    case 'active': return 'bg-rose-500 text-white pulse-animation'
    default: return 'bg-slate-200 text-slate-400'
  }
}
</script>

<template>
  <div class="step-indicator-wrapper flex gap-3" :class="layout">
    <div v-for="(step, i) in steps" :key="i" class="step-item flex items-center gap-3">
      <div class="w-8 h-8 rounded-full flex items-center justify-center" :class="getStepIconClass(step.status)">
        <AppIcon v-if="step.status==='completed'" name="Check" size="sm" />
        <AppIcon v-else-if="step.status==='active'" name="Loader" size="sm" animate />
        <span v-else>{{ i+1 }}</span>
      </div>
      <div class="text-sm" :class="step.status==='active' ? 'text-slate-800' : 'text-slate-500'">
        {{ step.name }}
      </div>
      <div v-if="layout==='vertical' && i<steps.length-1" class="ml-4 w-0.5 h-6 bg-slate-200" />
    </div>
  </div>
</template>