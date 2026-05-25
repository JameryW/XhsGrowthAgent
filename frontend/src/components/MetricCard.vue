<script setup lang="ts">
interface Props {
  icon: string
  title: string
  value: string | number
  subtitle?: string
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
})

const colors = {
  pink: { bg: 'from-neon-pink to-neon-peach', text: 'text-neon-pink', border: 'border-neon-pink/30' },
  cyan: { bg: 'from-neon-cyan to-emerald-600', text: 'text-neon-cyan', border: 'border-neon-cyan/30' },
  purple: { bg: 'from-neon-purple to-purple-700', text: 'text-neon-purple', border: 'border-neon-purple/30' },
  peach: { bg: 'from-neon-peach to-neon-gold', text: 'text-neon-peach', border: 'border-neon-peach/30' },
}
</script>

<template>
  <div :class="['glass rounded-xl p-4 border', colors[props.variant].border]">
    <div class="flex items-center gap-3 mb-3">
      <div :class="['w-9 h-9 rounded-lg bg-gradient-to-br flex items-center justify-center', colors[props.variant].bg]">
        <span class="text-lg">{{ props.icon }}</span>
      </div>
      <div class="mono text-xs text-white/50">{{ props.title }}</div>
    </div>
    <div :class="['mono text-3xl font-bold', colors[props.variant].text]">
      {{ props.value }}
    </div>
    <div v-if="props.subtitle" class="mono text-xs text-neon-cyan mt-2">
      {{ props.subtitle }}
    </div>
  </div>
</template>