// @vitest-environment node
// frontend/tests/stores/error.spec.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useErrorStore, ERROR_TYPE_COLORS } from '@/stores/error'
import type { ErrorType } from '@/types/error'

describe('error store', () => {
  beforeEach(() => {
    // Create a fresh Pinia instance for each test
    setActivePinia(createPinia())
  })

  describe('setError and clearError', () => {
    it('sets error state correctly', () => {
      const store = useErrorStore()

      store.setError('api', 'Network request failed')

      expect(store.hasError).toBe(true)
      expect(store.errorType).toBe('api')
      expect(store.errorMessage).toBe('Network request failed')
      expect(store.errorState?.retryCount).toBe(0)
      expect(store.errorState?.isRecovering).toBe(false)
    })

    it('clears error state correctly', () => {
      const store = useErrorStore()

      store.setError('timeout', 'Request timed out')
      expect(store.hasError).toBe(true)

      store.clearError()

      expect(store.hasError).toBe(false)
      expect(store.errorType).toBe(null)
      expect(store.errorMessage).toBe('')
      expect(store.errorState).toBe(null)
    })

    it('clears retry count when clearing error', () => {
      const store = useErrorStore()

      store.setError('api', 'Error')
      store.incrementRetry()
      store.incrementRetry()
      expect(store.retryCount).toBe(2)

      store.clearError()

      expect(store.retryCount).toBe(0)
    })
  })

  describe('incrementRetry', () => {
    it('increments retry count', () => {
      const store = useErrorStore()

      store.setError('api', 'Error')
      const count1 = store.incrementRetry()
      const count2 = store.incrementRetry()
      const count3 = store.incrementRetry()

      expect(count1).toBe(1)
      expect(count2).toBe(2)
      expect(count3).toBe(3)
      expect(store.retryCount).toBe(3)
    })

    it('updates error state retry count', () => {
      const store = useErrorStore()

      store.setError('api', 'Error')
      store.incrementRetry()

      expect(store.errorState?.retryCount).toBe(1)
    })

    it('increments retry count even without error state', () => {
      const store = useErrorStore()

      // No error set
      expect(store.hasError).toBe(false)

      const count = store.incrementRetry()

      expect(count).toBe(1)
      expect(store.retryCount).toBe(1)
    })
  })

  describe('setRecovering', () => {
    it('sets recovering state to true', () => {
      const store = useErrorStore()

      store.setError('api', 'Error')
      store.setRecovering(true)

      expect(store.errorState?.isRecovering).toBe(true)
    })

    it('sets recovering state to false', () => {
      const store = useErrorStore()

      store.setError('api', 'Error')
      store.setRecovering(true)
      store.setRecovering(false)

      expect(store.errorState?.isRecovering).toBe(false)
    })

    it('does nothing when no error state', () => {
      const store = useErrorStore()

      // No error set
      store.setRecovering(true)

      expect(store.errorState).toBe(null)
    })
  })

  describe('getters', () => {
    it('hasError returns true when error is set', () => {
      const store = useErrorStore()

      expect(store.hasError).toBe(false)
      store.setError('api', 'Error')
      expect(store.hasError).toBe(true)
    })

    it('errorType returns correct type', () => {
      const store = useErrorStore()

      expect(store.errorType).toBe(null)
      store.setError('timeout', 'Timeout')
      expect(store.errorType).toBe('timeout')
    })

    it('errorMessage returns correct message', () => {
      const store = useErrorStore()

      expect(store.errorMessage).toBe('')
      store.setError('unknown', 'Unknown error occurred')
      expect(store.errorMessage).toBe('Unknown error occurred')
    })
  })

  describe('ERROR_TYPE_COLORS mapping', () => {
    it('maps api to rose color', () => {
      expect(ERROR_TYPE_COLORS.api).toBe('#f43f5e')
    })

    it('maps timeout to amber color', () => {
      expect(ERROR_TYPE_COLORS.timeout).toBe('#f59e0b')
    })

    it('maps unknown to violet color', () => {
      expect(ERROR_TYPE_COLORS.unknown).toBe('#8b5cf6')
    })

    it('maps retry_success to green color', () => {
      expect(ERROR_TYPE_COLORS.retry_success).toBe('#22c55e')
    })

    it('covers all error types', () => {
      const types: ErrorType[] = ['api', 'timeout', 'unknown', 'retry_success']

      types.forEach(type => {
        expect(ERROR_TYPE_COLORS[type]).toBeDefined()
        expect(ERROR_TYPE_COLORS[type]).toMatch(/^#[0-9a-f]{6}$/i)
      })
    })
  })

  describe('timestamp', () => {
    it('sets timestamp when creating error', () => {
      const store = useErrorStore()

      const beforeTime = new Date().toISOString()
      store.setError('api', 'Error')
      const afterTime = new Date().toISOString()

      expect(store.errorState?.timestamp).toBeDefined()
      // Timestamp should be between before and after
      expect(store.errorState?.timestamp >= beforeTime).toBe(true)
      expect(store.errorState?.timestamp <= afterTime).toBe(true)
    })
  })
})