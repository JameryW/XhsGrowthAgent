<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  value: number // 0-100
  variant?: 'pink' | 'cyan' | 'purple'
  size?: 'sm' | 'md' | 'lg'
  showValue?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'cyan',
  size: 'md',
  showValue: true,
})

// Refined color scheme matching tailwind config
const colorMap = {
  pink: { primary: '#F43F5E', light: '#FB7185' },
  cyan: { primary: '#14B8A6', light: '#5EEAD4' },
  purple: { primary: '#8B5CF6', light: '#A78BFA' },
}

const sizes = {
  sm: { width: 48, stroke: 4 },
  md: { width: 64, stroke: 5 },
  lg: { width: 80, stroke: 6 },
}

const colors = computed(() => colorMap[props.variant])
const sizeConfig = computed(() => sizes[props.size])
const percentage = computed(() => Math.min(100, Math.max(0, props.value)))

// Calculate stroke dasharray for circular progress
const radius = computed(() => (sizeConfig.value.width - sizeConfig.value.stroke) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const offset = computed(() => circumference.value - (percentage.value / 100) * circumference.value)
</script>

<template>
  <div class="relative inline-flex items-center justify-center" aria-live="polite" :aria-label="`${Math.round(percentage)}%`">
    <svg
      :width="sizeConfig.width"
      :height="sizeConfig.width"
      class="transform -rotate-90"
      aria-hidden="true"
    >
      <!-- Background circle -->
      <circle
        :cx="sizeConfig.width / 2"
        :cy="sizeConfig.width / 2"
        :r="radius"
        :stroke-width="sizeConfig.stroke"
        fill="transparent"
        stroke="rgba(0,0,0,0.08)"
      />

      <!-- Progress circle (main) -->
      <circle
        v-if="percentage > 0"
        :cx="sizeConfig.width / 2"
        :cy="sizeConfig.width / 2"
        :r="radius"
        :stroke-width="sizeConfig.stroke"
        fill="transparent"
        :stroke="colors.primary"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="offset"
        stroke-linecap="round"
        class="transition-all duration-500 ease-out"
      />
    </svg>

    <!-- Value display -->
    <div v-if="showValue" class="absolute flex flex-col items-center">
      <span class="text-sm text-slate-800 font-bold tabular-nums">
        {{ Math.round(percentage) }}
      </span>
      <span class="text-xs text-slate-400">%</span>
    </div>
  </div>
</template>