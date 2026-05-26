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
</script>

<template>
  <div class="gradient-border rounded-xl p-4 shimmer animate-pulse-glow" :class="`border-neon-${props.variant}/30`">
    <!-- Animated background -->
    <div class="absolute inset-0 grid-pattern opacity-10 -z-10" />

    <!-- Icon + Title skeleton -->
    <div class="flex items-center gap-3 mb-3">
      <div class="w-9 h-9 rounded-lg bg-gradient-to-r animate-pulse morph-blob" :class="shimmerColors[props.variant]" />
      <div class="h-4 w-24 rounded bg-gradient-to-r animate-pulse" :class="shimmerColors[props.variant]" />
    </div>
    <!-- Value skeleton -->
    <div class="h-8 w-16 rounded bg-gradient-to-r animate-pulse" :class="shimmerColors[props.variant]" />
    <!-- Subtitle skeleton -->
    <div class="h-3 w-20 rounded bg-gradient-to-r animate-pulse mt-2" :class="shimmerColors[props.variant]" />
  </div>
</template>