<script setup lang="ts">
import { computed } from 'vue'
import * as LucideIcons from '@lucide/vue'
import { cn } from '@/utils/cn'

interface Props {
  name: string // lucide icon name (e.g., 'Home', 'CheckCircle')
  size?: 'sm' | 'md' | 'lg' | 'xl'
  variant?: 'pink' | 'cyan' | 'purple' | 'peach' | 'white'
  animate?: boolean
  ariaLabel?: string
}

const props = withDefaults(defineProps<Props>(), {
  size: 'md',
  variant: 'white',
  animate: false,
  ariaLabel: '',
})

// Icon sizes in pixels
const sizeMap = {
  sm: 16,
  md: 20,
  lg: 24,
  xl: 32,
}

// Neon color classes
const colorClasses = {
  pink: 'text-neon-pink',
  cyan: 'text-neon-cyan',
  purple: 'text-neon-purple',
  peach: 'text-neon-peach',
  white: 'text-white',
}

const iconSize = computed(() => sizeMap[props.size])
const colorClass = computed(() => colorClasses[props.variant])

// Get the icon component dynamically
const IconComponent = computed(() => {
  const iconName = props.name
  // @lucide/vue exports icons as PascalCase components
  return (LucideIcons as Record<string, any>)[iconName] || LucideIcons.HelpCircle
})

const iconClasses = computed(() =>
  cn(
    colorClass.value,
    props.animate && 'animate-spin-slow'
  )
)
</script>

<template>
  <component
    :is="IconComponent"
    :size="iconSize"
    :class="iconClasses"
    :aria-label="ariaLabel || undefined"
    role="img"
  />
</template>