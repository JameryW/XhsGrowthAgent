<!-- frontend/src/components/AnimatedCounter.vue -->
<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { useAnimation } from '@/composables/useAnimation'

/**
 * AnimatedCounter component
 * Smoothly animates a number value using requestAnimationFrame
 */

interface Props {
  /** The target value to animate to */
  value: number
  /** Animation duration in milliseconds */
  duration?: number
  /** Format function for display (e.g., for currency) */
  format?: (value: number) => string
}

const props = withDefaults(defineProps<Props>(), {
  duration: 500,
  format: (value: number) => value.toString()
})

const { animatedCounter, cancelAnimation, isAnimating } = useAnimation()
const displayValue = ref(props.value)

// Animate when value prop changes
watch(
  () => props.value,
  (newValue, oldValue) => {
    // Skip animation for initial value or if values are the same
    if (oldValue === undefined || newValue === oldValue) {
      displayValue.value = newValue
      return
    }

    // Cancel any existing animation
    cancelAnimation()

    // Start animation from current display value to new value
    animatedCounter(displayValue.value, newValue, props.duration, (current) => {
      displayValue.value = current
    })
  },
  { immediate: false }
)

// Cleanup on unmount
onUnmounted(() => {
  cancelAnimation()
})

// Expose for testing
defineExpose({
  displayValue,
  isAnimating
})
</script>

<template>
  <span class="animated-counter" :class="{ 'is-animating': isAnimating }">
    {{ props.format(displayValue) }}
  </span>
</template>

<style scoped>
.animated-counter {
  display: inline-block;
  font-variant-numeric: tabular-nums;
  transition: transform 0.1s ease-out;
}

.animated-counter.is-animating {
  transform: scale(1.02);
}
</style>