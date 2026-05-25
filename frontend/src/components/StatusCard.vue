<script setup lang="ts">
interface Props {
  title: string
  value: string | number
  subtitle?: string
  icon?: string
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
})

const variantClasses = {
  pink: 'border-neon-pink/30 shadow-[0_0_30px_rgba(254,44,85,0.2)]',
  cyan: 'border-neon-cyan/30 shadow-[0_0_30px_rgba(78,205,196,0.2)]',
  purple: 'border-neon-purple/30 shadow-[0_0_30px_rgba(102,126,234,0.2)]',
  peach: 'border-neon-peach/30 shadow-[0_0_30px_rgba(255,228,225,0.2)]',
}

const iconBgClasses = {
  pink: 'from-neon-pink to-neon-peach',
  cyan: 'from-neon-cyan to-emerald-600',
  purple: 'from-neon-purple to-purple-700',
  peach: 'from-neon-peach to-neon-gold',
}

const valueColorClasses = {
  pink: 'text-neon-pink',
  cyan: 'text-neon-cyan',
  purple: 'text-neon-purple',
  peach: 'text-neon-peach',
}
</script>

<template>
  <div :class="['glass rounded-xl p-4', variantClasses[props.variant]]">
    <div class="flex items-center gap-3 mb-3">
      <div
        v-if="props.icon"
        :class="[
          'w-9 h-9 rounded-lg bg-gradient-to-br flex items-center justify-center text-lg',
          iconBgClasses[props.variant]
        ]"
      >
        {{ props.icon }}
      </div>
      <div class="mono text-xs text-white/50">{{ props.title }}</div>
    </div>
    <div :class="['mono text-3xl font-bold', valueColorClasses[props.variant]]">
      {{ props.value }}
    </div>
    <div v-if="props.subtitle" class="mono text-xs text-neon-cyan mt-2">
      {{ props.subtitle }}
    </div>
  </div>
</template>