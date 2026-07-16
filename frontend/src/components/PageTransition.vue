<!-- frontend/src/components/PageTransition.vue -->
<script setup lang="ts">
/**
 * PageTransition component
 * Vue transition wrapper with fade + slide animation
 * Uses mode="out-in" for smooth page transitions
 */

interface Props {
  /** Transition duration in milliseconds */
  duration?: number
}

const props = withDefaults(defineProps<Props>(), {
  duration: 200
})

// Compute transition style based on duration
const transitionStyle = {
  '--transition-duration': `${props.duration}ms`
}
</script>

<template>
  <RouterView v-slot="{ Component, route }">
    <Transition
      name="fade-slide"
      mode="out-in"
      :style="transitionStyle"
    >
      <component :is="Component" :key="route.path" />
    </Transition>
  </RouterView>
</template>

<style scoped>
/* Fade slide transition styles */
.fade-slide-enter-active {
  animation: fade-slide-in var(--transition-duration, 200ms) ease-out;
}

.fade-slide-leave-active {
  animation: fade-slide-out var(--transition-duration, 200ms) ease-out;
}

@keyframes fade-slide-in {
  from {
    opacity: 0;
    transform: translateX(20px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes fade-slide-out {
  from {
    opacity: 1;
    transform: translateX(0);
  }
  to {
    opacity: 0;
    transform: translateX(-20px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .fade-slide-enter-active,
  .fade-slide-leave-active {
    animation: none;
  }
}
</style>
