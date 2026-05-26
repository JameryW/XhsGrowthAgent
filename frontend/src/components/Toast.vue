<script setup lang="ts">
import { useToastStore } from "@/stores/toast"
import type { ToastType } from "@/stores/toast"

const toastStore = useToastStore()

const toastClasses: Record<ToastType, string> = {
  info: "border-neon-blue bg-neon-blue/10",
  success: "border-neon-green bg-neon-green/10",
  warning: "border-neon-yellow bg-neon-yellow/10",
  error: "border-neon-red bg-neon-red/10",
}

const iconColors: Record<ToastType, string> = {
  info: "text-neon-blue",
  success: "text-neon-green",
  warning: "text-neon-yellow",
  error: "text-neon-red",
}

const icons: Record<ToastType, string> = {
  info: "ℹ",
  success: "✓",
  warning: "⚠",
  error: "✕",
}

function closeToast(id: string) {
  toastStore.removeToast(id)
}
</script>

<template>
  <div class="fixed top-4 right-4 z-50 flex flex-col gap-3 max-w-sm">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toastStore.toasts"
        :key="toast.id"
        class="p-4 rounded-lg border shadow-lg backdrop-blur-sm"
        :class="toastClasses[toast.type]"
      >
        <div class="flex items-start gap-3">
          <!-- Icon -->
          <span class="text-lg font-bold" :class="iconColors[toast.type]">
            {{ icons[toast.type] }}
          </span>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <h4 class="text-sm font-semibold text-white truncate">
              {{ toast.title }}
            </h4>
            <p v-if="toast.message" class="text-xs text-gray-400 mt-1 line-clamp-2">
              {{ toast.message }}
            </p>
          </div>

          <!-- Close button -->
          <button
            class="text-gray-500 hover:text-white transition-colors"
            @click="closeToast(toast.id)"
          >
            ✕
          </button>
        </div>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-enter-active {
  transition: all 0.3s ease-out;
}

.toast-leave-active {
  transition: all 0.2s ease-in;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
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
</style>