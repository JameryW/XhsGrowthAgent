<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'

// INF-11/EV-08: accessible floating tooltip. Wrap any inline trigger in the
// default slot; hover/focus toggles a Teleported, positioned tooltip.
interface Props {
  content: string
  position?: 'top' | 'bottom' | 'left' | 'right'
}

const props = withDefaults(defineProps<Props>(), {
  position: 'top',
})

const targetEl = ref<HTMLElement | null>(null)
const isVisible = ref(false)
const tooltipPos = ref({ top: 0, left: 0 })

const arrowPos = computed(() => {
  switch (props.position) {
    case 'top':
      return { bottom: '-6px', left: '50%', transform: 'translateX(-50%)' }
    case 'bottom':
      return { top: '-6px', left: '50%', transform: 'translateX(-50%)' }
    case 'left':
      return { right: '-6px', top: '50%', transform: 'translateY(-50%)' }
    case 'right':
      return { left: '-6px', top: '50%', transform: 'translateY(-50%)' }
  }
})

const arrowClass = computed(() => {
  switch (props.position) {
    case 'top':
      return 'border-l-transparent border-r-transparent border-b-white border-t-transparent dark:border-b-slate-900'
    case 'bottom':
      return 'border-l-transparent border-r-transparent border-t-white border-b-transparent dark:border-t-slate-900'
    case 'left':
      return 'border-t-transparent border-b-transparent border-r-white border-l-transparent dark:border-r-slate-900'
    case 'right':
      return 'border-t-transparent border-b-transparent border-l-white border-r-transparent dark:border-l-slate-900'
  }
})

const updatePosition = async () => {
  if (!targetEl.value || !isVisible.value) return

  await nextTick()
  const rect = targetEl.value.getBoundingClientRect()
  const tooltipWidth = 200
  const tooltipHeight = 40
  const padding = 8

  switch (props.position) {
    case 'top':
      tooltipPos.value = {
        top: rect.top - tooltipHeight - padding - 6,
        left: rect.left + rect.width / 2 - tooltipWidth / 2,
      }
      break
    case 'bottom':
      tooltipPos.value = {
        top: rect.bottom + padding + 6,
        left: rect.left + rect.width / 2 - tooltipWidth / 2,
      }
      break
    case 'left':
      tooltipPos.value = {
        top: rect.top + rect.height / 2 - tooltipHeight / 2,
        left: rect.left - tooltipWidth - padding - 6,
      }
      break
    case 'right':
      tooltipPos.value = {
        top: rect.top + rect.height / 2 - tooltipHeight / 2,
        left: rect.right + padding + 6,
      }
      break
  }
}

const show = () => {
  if (!props.content) return
  isVisible.value = true
  updatePosition()
}

const hide = () => {
  isVisible.value = false
}

const handleResize = () => {
  if (isVisible.value) {
    updatePosition()
  }
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <span
    ref="targetEl"
    class="inline-flex"
    @mouseenter="show"
    @mouseleave="hide"
    @focus="show"
    @blur="hide"
  >
    <slot />
  </span>
  <Teleport to="body">
    <Transition name="tooltip">
      <div
        v-if="isVisible"
        class="dark-explicit fixed z-dropdown px-3 py-2 rounded-lg bg-white shadow-lg border border-slate-200/50 text-sm text-slate-700 max-w-xs dark:bg-slate-900 dark:border-slate-600/60 dark:text-slate-200 dark:shadow-slate-950/40"
        :style="{
          top: `${tooltipPos.top}px`,
          left: `${tooltipPos.left}px`,
        }"
        role="tooltip"
        :aria-hidden="!isVisible"
      >
        {{ content }}
        <span
          class="absolute w-0 h-0 border-8"
          :style="arrowPos"
          :class="arrowClass"
        />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.tooltip-enter-active {
  transition: opacity 0.2s ease-out, transform 0.2s ease-out;
}

.tooltip-leave-active {
  transition: opacity 0.2s ease-in, transform 0.2s ease-in;
}

.tooltip-enter-from {
  opacity: 0;
  transform: scale(0.95);
}

.tooltip-leave-to {
  opacity: 0;
  transform: scale(0.95);
}
</style>
