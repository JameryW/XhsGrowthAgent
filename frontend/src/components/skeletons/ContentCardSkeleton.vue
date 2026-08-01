<script setup lang="ts">
interface Props {
  variant?: 'pink' | 'cyan' | 'purple' | 'peach'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
})

const shimmerColors = {
  pink: 'from-neon-pink/20 via-neon-pink/10 to-neon-pink/20',
  cyan: 'from-neon-cyan/20 via-neon-cyan/10 to-neon-cyan/20',
  purple: 'from-neon-purple/20 via-neon-purple/10 to-neon-purple/20',
  peach: 'from-neon-peach/20 via-neon-peach/10 to-neon-peach/20',
}

// Static purge-safe border classes (template interpolation never renders).
const borderColors = {
  pink: 'border-neon-pink/30',
  cyan: 'border-neon-cyan/30',
  purple: 'border-neon-purple/30',
  peach: 'border-neon-peach/30',
}
</script>

<template>
  <div class="gradient-border rounded-xl p-4 shimmer animate-pulse-glow" :class="borderColors[props.variant]">
    <!-- Animated background -->
    <div class="absolute inset-0 grid-pattern opacity-10 -z-10" />

    <!-- Icon + Title skeleton -->
    <div class="flex items-center gap-3 mb-4">
      <div class="w-10 h-10 rounded-lg bg-gradient-to-r animate-pulse morph-blob" :class="shimmerColors[props.variant]" />
      <div class="flex-1">
        <div class="h-4 w-20 rounded bg-gradient-to-r animate-pulse mb-2" :class="shimmerColors[props.variant]" />
        <div class="h-3 w-32 rounded bg-gradient-to-r animate-pulse" :class="shimmerColors[props.variant]" />
      </div>
    </div>
    <!-- Content skeleton -->
    <div class="bg-light-bgAlt rounded-lg p-3 border-l-2 border-gray-200">
      <div class="space-y-2">
        <div class="h-3 w-full rounded bg-gradient-to-r animate-pulse" :class="shimmerColors[props.variant]" />
        <div class="h-3 w-3/4 rounded bg-gradient-to-r animate-pulse" :class="shimmerColors[props.variant]" />
        <div class="h-3 w-1/2 rounded bg-gradient-to-r animate-pulse" :class="shimmerColors[props.variant]" />
      </div>
    </div>
  </div>
</template>