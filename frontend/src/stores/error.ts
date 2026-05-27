// frontend/src/stores/error.ts

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ErrorState, ErrorType } from '@/types/error'

/**
 * Color mapping for error types
 * Used for visual feedback in UI components
 */
export const ERROR_TYPE_COLORS: Record<ErrorType, string> = {
  api: '#f43f5e',        // rose-500
  timeout: '#f59e0b',    // amber-500
  unknown: '#8b5cf6',    // violet-500
  retry_success: '#22c55e' // green-500
}

/**
 * Default error state (no error)
 */
const DEFAULT_ERROR_STATE: ErrorState | null = null

export const useErrorStore = defineStore('error', () => {
  // State
  const errorState = ref<ErrorState | null>(DEFAULT_ERROR_STATE)
  const retryCount = ref(0)

  // Getters
  const hasError = computed(() => errorState.value !== null)
  const errorType = computed(() => errorState.value?.type ?? null)
  const errorMessage = computed(() => errorState.value?.message ?? '')

  // Actions
  /**
   * Set an error with type and message
   * @param type - Error type (api, timeout, unknown, retry_success)
   * @param message - Error message to display
   */
  function setError(type: ErrorType, message: string): void {
    errorState.value = {
      type,
      message,
      retryCount: retryCount.value,
      isRecovering: false,
      timestamp: new Date().toISOString()
    }
  }

  /**
   * Clear the current error state
   */
  function clearError(): void {
    errorState.value = null
    retryCount.value = 0
  }

  /**
   * Increment the retry counter
   * @returns New retry count
   */
  function incrementRetry(): number {
    retryCount.value += 1
    if (errorState.value) {
      errorState.value.retryCount = retryCount.value
    }
    return retryCount.value
  }

  /**
   * Set the recovering state
   * @param isRecovering - Whether the system is currently recovering
   */
  function setRecovering(isRecovering: boolean): void {
    if (errorState.value) {
      errorState.value.isRecovering = isRecovering
    }
  }

  return {
    // State
    errorState,
    retryCount,
    // Getters
    hasError,
    errorType,
    errorMessage,
    // Actions
    setError,
    clearError,
    incrementRetry,
    setRecovering
  }
})