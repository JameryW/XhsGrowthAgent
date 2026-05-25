<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  icon: string
  label: string
  status: 'completed' | 'running' | 'pending'
}

const props = defineProps<Props>()

// Pre-defined status styles
const statusClasses = {
  completed: 'bg-gradient-to-br from-neon-pink to-neon-peach border-2 border-white shadow-neon-pink',
  running: 'bg-gradient-to-br from-neon-peach to-neon-gold border-2 border-neon-pink animate-pulse-glow shadow-neon-pink',
  pending: 'bg-white/20 border border-white/30 opacity-50',
}

// Memoize label color class
const labelClass = computed(() => {
  switch (props.status) {
    case 'running': return 'text-neon-pink font-bold'
    case 'completed': return 'text-white'
    default: return 'text-white/40'
  }
})
</script>

<template>
  <div class="text-center">
    <div
      :class="[
        'w-20 h-20 hexagon flex items-center justify-center mx-auto',
        statusClasses[props.status]
      ]"
    >
      <span class="text-2xl">{{ props.icon }}</span>
    </div>
    <div :class="['mt-2 mono text-xs', labelClass]">
      {{ props.label }}
    </div>
    <div
      v-if="props.status === 'completed'"
      class="mono text-xs text-neon-cyan mt-1"
    >
      ✓ 完成
    </div>
    <div
      v-else-if="props.status === 'running'"
      class="mono text-xs text-neon-peach mt-1 animate-blink"
    >
      ⏳ 进行中
    </div>
  </div>
</template>