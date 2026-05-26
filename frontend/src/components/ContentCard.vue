<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

interface Props {
  title: string
  content: Record<string, any>
  icon: string // lucide icon name
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
  completed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
  completed: false,
})

// Check if content has data
const hasContent = computed(() => Object.keys(props.content).length > 0)

const styles = {
  pink: {
    border: 'border-neon-pink/10',
    iconBg: 'from-neon-pink via-neon-pinkLight to-neon-peach',
    glow: 'shadow-neon-pink-sm',
    accent: 'border-neon-pink',
    textLight: 'text-neon-pinkLight',
    text: 'text-neon-pink',
  },
  cyan: {
    border: 'border-neon-cyan/10',
    iconBg: 'from-neon-cyan via-neon-cyanLight to-neon-green',
    glow: 'shadow-neon-cyan-sm',
    accent: 'border-neon-cyan',
    textLight: 'text-neon-cyan',
    text: 'text-neon-cyan',
  },
  purple: {
    border: 'border-neon-purple/10',
    iconBg: 'from-neon-purple via-neon-purpleLight to-neon-blue',
    glow: 'shadow-neon-purple-sm',
    accent: 'border-neon-purple',
    textLight: 'text-neon-purple',
    text: 'text-neon-purple',
  },
  peach: {
    border: 'border-neon-peach/10',
    iconBg: 'from-neon-peach via-neon-peachLight to-neon-yellow',
    glow: 'shadow-neon-peach',
    accent: 'border-neon-peach',
    textLight: 'text-neon-peach',
    text: 'text-neon-peach',
  },
}
</script>

<template>
  <div :class="['rounded-xl p-5 relative overflow-hidden bg-white/98 backdrop-blur-sm border transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5', styles[props.variant].border]">
    <!-- Header -->
    <div class="flex items-center gap-3 mb-4">
      <div :class="['w-11 h-11 rounded-xl bg-gradient-to-br flex items-center justify-center shadow-sm', styles[props.variant].iconBg]">
        <AppIcon :name="props.icon" size="md" variant="white" :aria-label="props.title" />
      </div>
      <div class="flex-1">
        <div class="text-slate-800 font-semibold text-sm">{{ props.title }}</div>
        <div class="text-xs text-slate-400 uppercase tracking-wide">Module Output</div>
      </div>
      <div v-if="props.completed" :class="['px-2.5 py-1 rounded-lg flex items-center gap-1.5 bg-teal-50 border border-teal-100']">
        <AppIcon name="Check" size="sm" variant="cyan" aria-label="Completed" />
        <span class="text-xs text-teal-600 font-medium">完成</span>
      </div>
    </div>

    <!-- Content -->
    <div v-if="hasContent" :class="['bg-slate-50 rounded-lg p-4 border-l-2', styles[props.variant].accent]">
      <div class="text-xs text-slate-600 space-y-2">
        <div v-for="(value, key) in props.content" :key="key" class="flex items-start gap-2">
          <span :class="styles[props.variant].text">▸</span>
          <span class="text-slate-400">{{ key }}:</span>
          <span :class="styles[props.variant].textLight">{{ value }}</span>
        </div>
      </div>
    </div>

    <!-- Loading state -->
    <div v-else class="bg-slate-50 rounded-lg p-4 border-l-2 border-slate-200">
      <div class="h-4 w-full rounded bg-slate-200 animate-pulse" />
    </div>
  </div>
</template>