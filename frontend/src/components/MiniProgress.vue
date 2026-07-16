<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

interface Props {
  value: number // 0-100
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
  showLabel?: boolean
  animated?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'cyan',
  showLabel: false,
  animated: true,
})

// Refined color scheme matching tailwind config
const colorMap = {
  pink: { from: '#F43F5E', to: '#FB7185' },
  cyan: { from: '#14B8A6', to: '#5EEAD4' },
  purple: { from: '#8B5CF6', to: '#A78BFA' },
  peach: { from: '#F59E0B', to: '#FBBF24' },
}

const colors = computed(() => colorMap[props.variant])
const percentage = computed(() => Math.min(100, Math.max(0, props.value)))
</script>

<template>
  <div class="w-full" aria-live="polite" :aria-label="t('miniProgress.progress', { percent: percentage })">
    <div class="h-1.5 bg-slate-100 rounded-full overflow-hidden relative dark:bg-slate-800">
      <!-- Progress bar -->
      <div
        :class="['h-full rounded-full relative overflow-hidden transition-all', animated ? 'duration-500 ease-out' : '',]"
        :style="{
          width: `${percentage}%`,
          background: `linear-gradient(90deg, ${colors.from}, ${colors.to})`,
        }"
      >
        <!-- Subtle glow -->
        <div
          class="absolute inset-0 opacity-20"
          :style="{
            background: `linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent)`,
          }"
        />
      </div>
    </div>

    <div v-if="showLabel" class="text-xs text-slate-500 mt-1 flex justify-between font-medium">
      <span>{{ t('miniProgress.label') }}</span>
      <span :class="`text-${props.variant === 'pink' ? 'rose' : props.variant === 'cyan' ? 'teal' : props.variant === 'purple' ? 'violet' : 'amber'}-600`">{{ percentage }}%</span>
    </div>
  </div>
</template>