// frontend/src/stores/toast.ts

import { defineStore } from "pinia"
import { ref } from "vue"

export type ToastType = "info" | "success" | "warning" | "error"

export interface ToastMessage {
  id: string
  type: ToastType
  title: string
  message?: string
  duration?: number
  timestamp: Date
}

export const useToastStore = defineStore("toast", () => {
  const toasts = ref<ToastMessage[]>([])
  const maxToasts = 5

  /**
   * 添加toast消息
   */
  function addToast(
    type: ToastType,
    title: string,
    message?: string,
    duration = 5000
  ): void {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const toast: ToastMessage = {
      id,
      type,
      title,
      message,
      duration,
      timestamp: new Date(),
    }

    // 限制最大toast数量
    if (toasts.value.length >= maxToasts) {
      toasts.value.shift()
    }

    toasts.value.push(toast)

    // 自动移除
    if (duration > 0) {
      setTimeout(() => {
        removeToast(id)
      }, duration)
    }
  }

  /**
   * 移除toast消息
   */
  function removeToast(id: string): void {
    const index = toasts.value.findIndex((t) => t.id === id)
    if (index !== -1) {
      toasts.value.splice(index, 1)
    }
  }

  /**
   * 清除所有toast
   */
  function clearAll(): void {
    toasts.value = []
  }

  // 快捷方法
  const info = (title: string, message?: string) => addToast("info", title, message)
  const success = (title: string, message?: string) => addToast("success", title, message)
  const warning = (title: string, message?: string) => addToast("warning", title, message)
  const error = (title: string, message?: string) => addToast("error", title, message, 8000)

  return {
    toasts,
    addToast,
    removeToast,
    clearAll,
    info,
    success,
    warning,
    error,
  }
})