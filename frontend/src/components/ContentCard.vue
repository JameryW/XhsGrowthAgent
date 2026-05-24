<script setup lang="ts">
interface Props {
  title: string
  content: Record<string, any>
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
  completed?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
  completed: false,
})

const borderGlowClasses = {
  pink: 'border-neon-pink/30',
  cyan: 'border-neon-cyan/30',
  purple: 'border-neon-purple/30',
  peach: 'border-neon-pink/30',
}

const iconBgClasses = {
  pink: 'from-neon-pink to-neon-peach',
  cyan: 'from-neon-cyan to-emerald-600',
  purple: 'from-neon-purple to-purple-700',
  peach: 'from-neon-peach to-neon-gold',
}
</script>

<template>
  <div :class="['glass rounded-xl p-4 border', borderGlowClasses[props.variant]]">
    <div class="flex items-center gap-3 mb-4">
      <div :class="['w-10 h-10 rounded-lg bg-gradient-to-br flex items-center justify-center', iconBgClasses[props.variant]]">
        <span class="text-lg">{{ props.title.split(' ')[0] }}</span>
      </div>
      <div class="flex-1">
        <div class="text-white font-bold text-sm">{{ props.title.split(' ').slice(1).join(' ') }}</div>
        <div class="mono text-xs text-white/50">MODULE_OUTPUT</div>
      </div>
      <div v-if="props.completed" class="text-neon-cyan mono text-xs">
        ✓ 完成
      </div>
    </div>

    <div class="bg-black/50 rounded-lg p-3 border-l-2 border-neon-cyan">
      <div class="mono text-xs text-white/70 space-y-1">
        <div v-for="(value, key) in props.content" :key="key">
          <span class="text-neon-pink">►</span>
          <span class="text-white/50">{{ key }}:</span>
          <span class="text-neon-cyan">{{ value }}</span>
        </div>
      </div>
    </div>
  </div>
</template>