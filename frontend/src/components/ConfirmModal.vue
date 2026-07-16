<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'

const { t } = useI18n()

interface Props {
  isOpen: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'warning' | 'info'
  confirmAction?: string // Preview of what will happen
}

const props = withDefaults(defineProps<Props>(), {
  confirmLabel: '',
  cancelLabel: '',
  variant: 'warning',
  confirmAction: '',
})

const displayConfirmLabel = computed(() => props.confirmLabel || t('common.confirm'))
const displayCancelLabel = computed(() => props.cancelLabel || t('common.cancel'))

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

// Button styles based on variant
const confirmButtonClass = computed(() => {
  switch (props.variant) {
    case 'danger':
      return 'bg-gradient-to-r from-rose-500 to-rose-400 border-rose-200 text-white shadow-sm'
    case 'warning':
      return 'bg-gradient-to-r from-amber-500 to-amber-400 border-amber-200 text-white shadow-sm'
    default:
      return 'bg-gradient-to-r from-teal-500 to-teal-400 border-teal-200 text-white shadow-sm'
  }
})

const iconVariant = computed(() => {
  switch (props.variant) {
    case 'danger': return 'pink'
    case 'warning': return 'peach'
    default: return 'cyan'
  }
})

const iconName = computed(() => {
  switch (props.variant) {
    case 'danger': return 'AlertCircle'
    case 'warning': return 'AlertTriangle'
    default: return 'Info'
  }
})

// Focus trap - focus confirm button on open
const confirmButtonRef = ref<HTMLButtonElement | null>(null)
const cancelButtonRef = ref<HTMLButtonElement | null>(null)
const previousFocusElement = ref<HTMLElement | null>(null)

// Focus management: save previous focus, set focus to cancel button when opened, restore on close
watch(() => props.isOpen, async (isOpen) => {
  if (isOpen) {
    // Save the element that had focus before modal opened
    previousFocusElement.value = document.activeElement as HTMLElement
    // Wait for DOM update then focus the cancel button (safer default)
    await nextTick()
    cancelButtonRef.value?.focus()
  } else {
    // Restore focus to the previous element
    previousFocusElement.value?.focus()
  }
})

const handleConfirm = () => emit('confirm')
const handleCancel = () => emit('cancel')

// Keyboard: Escape to cancel, Tab to cycle focus within modal
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    handleCancel()
  } else if (e.key === 'Tab') {
    // Simple focus trap: cycle between cancel and confirm buttons
    const focusableElements = [cancelButtonRef.value, confirmButtonRef.value].filter(Boolean) as HTMLButtonElement[]
    if (focusableElements.length === 0) return

    const currentIndex = focusableElements.indexOf(document.activeElement as HTMLButtonElement)
    if (e.shiftKey) {
      // Shift+Tab: go backwards
      const prevIndex = currentIndex <= 0 ? focusableElements.length - 1 : currentIndex - 1
      focusableElements[prevIndex]?.focus()
      e.preventDefault()
    } else {
      // Tab: go forwards
      const nextIndex = currentIndex >= focusableElements.length - 1 ? 0 : currentIndex + 1
      focusableElements[nextIndex]?.focus()
      e.preventDefault()
    }
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-50 flex items-center justify-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        aria-describedby="modal-message"
        @keydown="handleKeyDown"
      >
        <!-- Backdrop -->
        <div
          class="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
          @click="handleCancel"
          aria-hidden="true"
        />

        <!-- Modal -->
        <div class="relative w-full max-w-md p-6 rounded-2xl liquid-glass-elevated">
          <!-- Icon -->
          <div class="flex items-center gap-4 mb-4">
            <div
              :class="[
                'w-12 h-12 rounded-xl flex items-center justify-center',
                variant === 'danger' ? 'bg-rose-100' : variant === 'warning' ? 'bg-amber-100' : 'bg-teal-100'
              ]"
            >
              <AppIcon :name="iconName" size="lg" :variant="iconVariant" />
            </div>
            <h2 id="modal-title" class="text-lg font-semibold text-slate-800">
              {{ title }}
            </h2>
          </div>

          <!-- Message -->
          <p id="modal-message" class="text-slate-600 mb-4">{{ message }}</p>

          <!-- Action Preview -->
          <div v-if="confirmAction" class="mb-4 p-3 rounded-lg liquid-glass-inset">
            <p class="text-xs text-slate-500 uppercase tracking-wide mb-1">{{ t('common.actionPreview') }}</p>
            <p class="text-sm text-slate-700">{{ confirmAction }}</p>
          </div>

          <!-- Buttons -->
          <div class="flex gap-3 justify-end">
            <button
              ref="cancelButtonRef"
              type="button"
              class="min-h-11 px-4 py-2.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100 transition-all dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
              @click="handleCancel"
            >
              {{ displayCancelLabel }}
            </button>
            <button
              ref="confirmButtonRef"
              type="button"
              :class="[
                'min-h-11 px-4 py-2.5 rounded-lg border font-medium flex items-center gap-2 transition-all',
                confirmButtonClass
              ]"
              @click="handleConfirm"
            >
              <AppIcon name="Check" size="sm" variant="white" />
              {{ displayConfirmLabel }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-enter-active {
  transition: all 0.3s ease-out;
}

.modal-leave-active {
  transition: all 0.2s ease-in;
}

.modal-enter-from {
  opacity: 0;
}

.modal-leave-to {
  opacity: 0;
}

.modal-enter-from > div:last-child {
  transform: scale(0.95) translateY(10px);
}

.modal-leave-to > div:last-child {
  transform: scale(0.95) translateY(-10px);
}
</style>
