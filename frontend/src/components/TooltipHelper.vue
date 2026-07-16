<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'

interface Props {
  content: string
  position: 'top' | 'bottom' | 'left' | 'right'
}

const props = defineProps<Props>()

// Target element reference (passed via expose)
const targetEl = ref<HTMLElement | null>(null)

// Tooltip visibility
const isVisible = ref(false)

// Tooltip position coordinates
const tooltipPos = ref({ top: 0, left: 0 })

// Arrow position
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

// Arrow direction class
const arrowClass = computed(() => {
  switch (props.position) {
    case 'top':
      return 'border-l-transparent border-r-transparent border-b-white border-t-transparent'
    case 'bottom':
      return 'border-l-transparent border-r-transparent border-t-white border-b-transparent'
    case 'left':
      return 'border-t-transparent border-b-transparent border-r-white border-l-transparent'
    case 'right':
      return 'border-t-transparent border-b-transparent border-l-white border-r-transparent'
  }
})

// Update tooltip position
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

// Show tooltip
const show = () => {
  isVisible.value = true
  updatePosition()
}

// Hide tooltip
const hide = () => {
  isVisible.value = false
}

// Handle hover/focus events
const handleMouseEnter = () => show()
const handleMouseLeave = () => hide()
const handleFocus = () => show()
const handleBlur = () => hide()

// Attach listeners to target element
const attachListeners = (el: HTMLElement) => {
  targetEl.value = el
  el.addEventListener('mouseenter', handleMouseEnter)
  el.addEventListener('mouseleave', handleMouseLeave)
  el.addEventListener('focus', handleFocus)
  el.addEventListener('blur', handleBlur)
}

// Detach listeners
const detachListeners = () => {
  if (targetEl.value) {
    targetEl.value.removeEventListener('mouseenter', handleMouseEnter)
    targetEl.value.removeEventListener('mouseleave', handleMouseLeave)
    targetEl.value.removeEventListener('focus', handleFocus)
    targetEl.value.removeEventListener('blur', handleBlur)
  }
}

// Handle window resize
const handleResize = () => {
  if (isVisible.value) {
    updatePosition()
  }
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  detachListeners()
  window.removeEventListener('resize', handleResize)
})

// Expose attach method for parent to bind target
defineExpose({
  attach: attachListeners,
  detach: detachListeners,
  show,
  hide,
})
</script>

<template>
  <Teleport to="body">
    <Transition name="tooltip">
      <div
        v-if="isVisible"
        class="fixed z-40 px-3 py-2 rounded-lg bg-white shadow-lg border border-slate-200/50 text-sm text-slate-700 max-w-xs dark:bg-slate-900 dark:border-slate-600/60 dark:text-slate-200 dark:shadow-slate-950/40"
        :style="{
          top: `${tooltipPos.top}px`,
          left: `${tooltipPos.left}px`,
        }"
        role="tooltip"
        :aria-hidden="!isVisible"
      >
        {{ content }}
        <!-- Arrow -->
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