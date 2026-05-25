<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  variant?: 'pink' | 'cyan' | 'purple' | 'peach' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  loading?: boolean
  ariaLabel?: string
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
  size: 'md',
  disabled: false,
  loading: false,
  ariaLabel: '',
})

const emit = defineEmits<{
  click: []
}>()

const variantClasses = computed(() => {
  const variants = {
    pink: 'bg-gradient-to-br from-neon-pink to-neon-peach border-neon-pink shadow-neon-pink hover:shadow-[0_0_30px_rgba(254,44,85,0.7)]',
    cyan: 'bg-gradient-to-br from-neon-cyan to-emerald-600 border-neon-cyan shadow-neon-cyan hover:shadow-[0_0_30px_rgba(78,205,196,0.7)]',
    purple: 'bg-gradient-to-br from-neon-purple to-purple-700 border-neon-purple shadow-neon-purple hover:shadow-[0_0_30px_rgba(102,126,234,0.7)]',
    peach: 'bg-gradient-to-br from-neon-peach to-neon-gold border-neon-peach shadow-neon-peach hover:shadow-[0_0_30px_rgba(255,228,225,0.7)]',
    ghost: 'bg-transparent border-white/20 hover:bg-white/10',
  }
  return variants[props.variant]
})

const sizeClasses = computed(() => {
  const sizes = {
    sm: 'px-4 py-2 text-sm',
    md: 'px-6 py-3 text-base',
    lg: 'px-8 py-4 text-lg',
  }
  return sizes[props.size]
})

const handleClick = () => {
  if (!props.disabled && !props.loading) {
    emit('click')
  }
}
</script>

<template>
  <button
    @click="handleClick"
    :disabled="disabled || loading"
    :aria-label="ariaLabel || undefined"
    :aria-busy="loading"
    :class="[
      'relative rounded-lg border-2 font-bold text-white transition-all duration-200',
      'disabled:opacity-50 disabled:cursor-not-allowed',
      'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50',
      variantClasses,
      sizeClasses,
    ]"
  >
    <span v-if="loading" class="animate-pulse">⏳</span>
    <slot v-else />
  </button>
</template>