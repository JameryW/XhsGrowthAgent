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

// Static neon-token classes (purge-safe) — bar gradient reuses the same
// neon palette as tailwind.config; label keeps the slate-family text tones.
const colorMap = {
  pink: { bar: 'from-neon-pink to-neon-pinkLight', label: 'text-rose-600' },
  cyan: { bar: 'from-neon-cyan to-neon-cyanLight', label: 'text-teal-600' },
  purple: { bar: 'from-neon-purple to-neon-purpleLight', label: 'text-violet-600' },
  peach: { bar: 'from-neon-peach to-neon-peachLight', label: 'text-amber-600' },
}

const colors = computed(() => colorMap[props.variant])
const percentage = computed(() => Math.min(100, Math.max(0, props.value)))
</script>

<template>
  <div class="w-full" aria-live="polite" :aria-label="t('miniProgress.progress', { percent: percentage })">
    <div class="h-1.5 bg-slate-100 rounded-full overflow-hidden relative dark:bg-slate-800 dark-explicit">
      <!-- Progress bar -->
      <div
        :class="['h-full rounded-full relative overflow-hidden transition-all bg-gradient-to-r', colors.bar, animated ? 'duration-500 ease-out' : '',]"
        :style="{ width: `${percentage}%` }"
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
      <span :class="colors.label">{{ percentage }}%</span>
    </div>
  </div>
</template>