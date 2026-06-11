<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToastStore } from "@/stores/toast"
import type { ToastType } from "@/stores/toast"
import AppIcon from "@/components/AppIcon.vue"

const { t } = useI18n()

const toastStore = useToastStore()

const toastStyles: Record<ToastType, {
  borderClass: string
  bgClass: string
  iconVariant: 'pink' | 'cyan' | 'purple' | 'peach' | 'white'
  icon: string
}> = {
  info: {
    borderClass: "border-neon-cyan/20",
    bgClass: "bg-white",
    iconVariant: 'cyan',
    icon: "Info",
  },
  success: {
    borderClass: "border-neon-green/20",
    bgClass: "bg-white",
    iconVariant: 'cyan',
    icon: "CheckCircle",
  },
  warning: {
    borderClass: "border-neon-peach/20",
    bgClass: "bg-white",
    iconVariant: 'peach',
    icon: "AlertTriangle",
  },
  error: {
    borderClass: "border-neon-pink/20",
    bgClass: "bg-white",
    iconVariant: 'pink',
    icon: "XCircle",
  },
}

function closeToast(id: string) {
  toastStore.removeToast(id)
}

// Keyboard: Escape to dismiss latest toast
function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape' && toastStore.toasts.length > 0) {
    const latestToast = toastStore.toasts[toastStore.toasts.length - 1]
    closeToast(latestToast.id)
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="fixed top-12 right-4 z-50 flex flex-col gap-2 max-w-sm pointer-events-none" role="region" :aria-label="t('toast.notifications')">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toastStore.toasts"
        :key="toast.id"
        class="p-4 rounded-xl liquid-glass-elevated pointer-events-auto"
        :class="[toastStyles[toast.type].borderClass]"
        role="alert"
        :aria-live="toast.type === 'error' ? 'assertive' : 'polite'"
      >
        <div class="flex items-start gap-3">
          <!-- Icon -->
          <div class="w-8 h-8 rounded-lg flex items-center justify-center bg-slate-50">
            <AppIcon
              :name="toastStyles[toast.type].icon"
              size="md"
              :variant="toastStyles[toast.type].iconVariant"
              :aria-label="toast.type"
            />
          </div>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <h4 class="text-sm font-semibold text-slate-800 truncate">
              {{ toast.title }}
            </h4>
            <p v-if="toast.message" class="text-xs text-slate-500 mt-1 line-clamp-2 leading-relaxed">
              {{ toast.message }}
            </p>
          </div>

          <!-- Close button -->
          <button
            class="w-6 h-6 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all duration-150"
            @click="closeToast(toast.id)"
            :aria-label="t('common.close')"
          >
            <AppIcon name="X" size="sm" variant="cyan" />
          </button>
        </div>

        <!-- Progress bar for auto-dismiss -->
        <div class="mt-3 h-1 bg-slate-100 rounded-full overflow-hidden">
          <div
            class="h-full rounded-full animate-progress"
            :class="toast.type === 'error' ? 'bg-rose-400' : toast.type === 'warning' ? 'bg-amber-400' : toast.type === 'success' ? 'bg-teal-400' : 'bg-teal-500'"
          />
        </div>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active {
  transition: all 0.4s ease-out;
}

.toast-leave-active {
  transition: all 0.3s ease-in;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(20px) scale(0.95);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(20px) scale(0.95);
}

.toast-move {
  transition: transform 0.3s ease;
}

.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.animate-progress {
  animation: progress-shrink 5s linear forwards;
}

@keyframes progress-shrink {
  from { width: 100%; }
  to { width: 0%; }
}
</style>