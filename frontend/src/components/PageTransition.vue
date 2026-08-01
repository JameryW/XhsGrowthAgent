<!-- frontend/src/components/PageTransition.vue -->
<script setup lang="ts">
/**
 * PageTransition component
 * Vue transition wrapper with fade + slide animation
 * Route components are lazy loaded, so keep them inside Suspense. The
 * transition intentionally does not use out-in: Vue Router resolves lazy
 * route components asynchronously and out-in can remove the old page before
 * the new component has a renderable vnode, leaving a blank RouterView.
 */
import { useI18n } from 'vue-i18n'

interface Props {
  /** Transition duration in milliseconds */
  duration?: number
}

const props = withDefaults(defineProps<Props>(), {
  duration: 200
})

const { t } = useI18n()

// Compute transition style based on duration
const transitionStyle = {
  '--transition-duration': `${props.duration}ms`
}
</script>

<template>
  <RouterView v-slot="{ Component, route }">
    <Transition
      name="fade-slide"
      :style="transitionStyle"
    >
      <Suspense timeout="0">
        <component :is="Component" :key="route.fullPath" />
        <template #fallback>
          <div class="page-transition-loading" role="status" aria-busy="true" :aria-label="t('common.loadingPage')">
            <span class="h-8 w-8 rounded-full border-2 border-slate-200 border-t-teal-500 animate-spin dark:border-slate-700 dark:border-t-teal-400" aria-hidden="true" />
          </div>
        </template>
      </Suspense>
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
  /* No out-in mode (see script note), so the leaving page overlaps the
     entering one: pull it out of flow to avoid stacking/scroll jumps. */
  position: absolute;
  inset: 0;
  width: 100%;
}

.page-transition-loading {
  display: flex;
  min-height: 12rem;
  align-items: center;
  justify-content: center;
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
