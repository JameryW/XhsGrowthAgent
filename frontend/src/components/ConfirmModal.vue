<script setup lang="ts">
import { ref, computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

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
  confirmLabel: '确认',
  cancelLabel: '取消',
  variant: 'warning',
  confirmAction: '',
})

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

const handleConfirm = () => emit('confirm')
const handleCancel = () => emit('cancel')

// Keyboard: Escape to cancel
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    handleCancel()
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
        @keydown="handleKeyDown"
      >
        <!-- Backdrop -->
        <div
          class="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
          @click="handleCancel"
          aria-hidden="true"
        />

        <!-- Modal -->
        <div class="relative w-full max-w-md p-6 rounded-2xl bg-white/98 shadow-xl border border-slate-200/50">
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
          <p class="text-slate-600 mb-4">{{ message }}</p>

          <!-- Action Preview -->
          <div v-if="confirmAction" class="mb-4 p-3 rounded-lg bg-slate-50 border border-slate-200">
            <p class="text-xs text-slate-500 uppercase tracking-wide mb-1">操作预览</p>
            <p class="text-sm text-slate-700">{{ confirmAction }}</p>
          </div>

          <!-- Buttons -->
          <div class="flex gap-3 justify-end">
            <button
              class="px-4 py-2.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100 transition-all"
              @click="handleCancel"
            >
              {{ cancelLabel }}
            </button>
            <button
              ref="confirmButtonRef"
              :class="[
                'px-4 py-2.5 rounded-lg border font-medium flex items-center gap-2 transition-all',
                confirmButtonClass
              ]"
              @click="handleConfirm"
            >
              <AppIcon name="Check" size="sm" variant="white" />
              {{ confirmLabel }}
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