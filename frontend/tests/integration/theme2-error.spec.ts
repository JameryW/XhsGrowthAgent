import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import ErrorCard from '@/components/ErrorCard.vue'
import ErrorBoundary from '@/components/ErrorBoundary.vue'
import OfflineRecovery from '@/components/OfflineRecovery.vue'
import RetryIndicator from '@/components/RetryIndicator.vue'
import { useRetry, retryWithBackoff, calculateDelay, DEFAULT_CONFIG } from '@/composables/useRetry'
import { useErrorStore } from '@/stores/error'
import type { ErrorType } from '@/types/error'

// Helper component that throws an error during render
const ErrorThrowingComponent = defineComponent({
  name: 'ErrorThrowingComponent',
  render() {
    throw new Error('Test error from child component')
  }
})

/**
 * Theme 2 Acceptance Tests
 *
 * AC1: All API errors have clear message and actionable recovery button (ErrorCard works)
 * AC2: Retry mechanism works correctly (exponential backoff, max 3 retries)
 * AC3: Offline state handled correctly (warning shown, auto recovery)
 */
describe('Theme 2 Acceptance Tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('AC1: All API errors have clear message and actionable recovery', () => {
    it('ErrorCard renders with correct type, message, and retry button', () => {
      const wrapper = mount(ErrorCard, {
        props: {
          type: 'api' as ErrorType,
          message: 'Network request failed'
        }
      })

      // Verify error message is displayed
      expect(wrapper.text()).toContain('Network request failed')

      // Verify title for api type
      expect(wrapper.text()).toContain('API 错误')

      // Verify retry button exists
      const buttons = wrapper.findAllComponents({ name: 'NeonButton' })
      expect(buttons.length).toBe(2) // retry + dismiss

      // Verify color theme for api errors
      expect(wrapper.find('.bg-rose-50\\/80').exists()).toBe(true)
    })

    it('ErrorCard shows retry button for all error types except retry_success', () => {
      const errorTypes: ErrorType[] = ['api', 'timeout', 'unknown']

      errorTypes.forEach(type => {
        const wrapper = mount(ErrorCard, {
          props: { type, message: 'Error occurred' }
        })

        // Should have retry button
        const buttons = wrapper.findAllComponents({ name: 'NeonButton' })
        expect(buttons.length).toBe(2)
        expect(wrapper.text()).toContain('重试')
      })
    })

    it('ErrorCard displays correct title and color for each error type', () => {
      const typeTests: Array<{ type: ErrorType; title: string; bgClass: string }> = [
        { type: 'api', title: 'API 错误', bgClass: 'bg-rose-50/80' },
        { type: 'timeout', title: '请求超时', bgClass: 'bg-amber-50/80' },
        { type: 'unknown', title: '未知错误', bgClass: 'bg-violet-50/80' },
        { type: 'retry_success', title: '重试成功', bgClass: 'bg-green-50/80' }
      ]

      typeTests.forEach(({ type, title, bgClass }) => {
        const wrapper = mount(ErrorCard, {
          props: { type, message: 'Test message' }
        })

        expect(wrapper.text()).toContain(title)
        expect(wrapper.find(`.${bgClass.replace('/', '\\/')}`).exists()).toBe(true)
      })
    })

    it('ErrorCard emits retry event when retry button is clicked', async () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error' }
      })

      const buttons = wrapper.findAllComponents({ name: 'NeonButton' })
      const retryButton = buttons[0]
      await retryButton.trigger('click')

      expect(wrapper.emitted('retry')).toBeTruthy()
      expect(wrapper.emitted('retry').length).toBe(1)
    })

    it('ErrorCard emits dismiss event when dismiss button is clicked', async () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error' }
      })

      const buttons = wrapper.findAllComponents({ name: 'NeonButton' })
      const dismissButton = buttons[1]
      await dismissButton.trigger('click')

      expect(wrapper.emitted('dismiss')).toBeTruthy()
      expect(wrapper.emitted('dismiss').length).toBe(1)
    })

    it('ErrorBoundary catches errors and shows fallback UI', async () => {
      const wrapper = mount(ErrorBoundary, {
        global: {
          config: {
            errorHandler: () => {} // Silence Vue's global error handler
          }
        },
        slots: {
          default: () => h(ErrorThrowingComponent)
        }
      })

      await flushPromises()

      // Should show error UI
      expect(wrapper.find('.bg-rose-50\\/80').exists()).toBe(true)
      expect(wrapper.text()).toContain('组件错误')
      expect(wrapper.text()).toContain('Test error from child component')
    })

    it('ErrorBoundary has refresh button for recovery', async () => {
      const wrapper = mount(ErrorBoundary, {
        global: {
          config: {
            errorHandler: () => {} // Silence Vue's global error handler
          }
        },
        slots: {
          default: () => h(ErrorThrowingComponent)
        }
      })

      await flushPromises()

      // Check refresh button exists
      const buttons = wrapper.findAllComponents({ name: 'NeonButton' })
      expect(buttons.length).toBeGreaterThan(0)
      expect(wrapper.text()).toContain('刷新')

      // Click refresh should emit event
      const button = buttons[0]
      await button.trigger('click')
      expect(wrapper.emitted('refresh')).toBeTruthy()
    })

    it('ErrorCard has clear error message display', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Network request failed' }
      })

      // Error message is clearly displayed
      expect(wrapper.text()).toContain('Network request failed')
      expect(wrapper.text()).toContain('API 错误')

      // Has rounded card structure for clear visual separation
      expect(wrapper.find('.rounded-2xl').exists()).toBe(true)
      expect(wrapper.find('.p-6').exists()).toBe(true)
    })

    it('ErrorCard displays retry count for transparency', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error', retryCount: 3 }
      })

      // Shows retry count for user awareness
      expect(wrapper.text()).toContain('已重试 3 次')
      expect(wrapper.text()).toContain('重试 (3)')
    })
  })

  describe('AC2: Retry mechanism works correctly', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('useRetry calculates exponential backoff delays correctly', () => {
      const { calculateDelay } = useRetry()

      // First retry: 1000ms (baseDelay)
      expect(calculateDelay(0)).toBe(1000)

      // Second retry: 2000ms (2x baseDelay)
      expect(calculateDelay(1)).toBe(2000)

      // Third retry: 4000ms (4x baseDelay)
      expect(calculateDelay(2)).toBe(4000)

      // Fourth retry: capped at maxDelay (4000ms)
      expect(calculateDelay(3)).toBe(4000)
    })

    it('useRetry respects max retries limit (default 3)', async () => {
      const fn = vi.fn().mockImplementation(() => Promise.reject(new Error('always fails')))

      // Catch rejection to prevent unhandled rejection warning
      const promise = retryWithBackoff(fn).catch(e => e)
      await vi.runAllTimersAsync()
      const result = await promise

      expect(result).toBeInstanceOf(Error)
      expect(result.message).toBe('always fails')

      // Should be called 4 times: 1 initial + 3 retries
      expect(fn).toHaveBeenCalledTimes(4)
    })

    it('useRetry succeeds after retries', async () => {
      const fn = vi.fn()
        .mockRejectedValueOnce(new Error('fail 1'))
        .mockRejectedValueOnce(new Error('fail 2'))
        .mockResolvedValueOnce('success')

      const promise = retryWithBackoff(fn)
      await vi.runAllTimersAsync()
      const result = await promise

      expect(result).toBe('success')
      expect(fn).toHaveBeenCalledTimes(3)
    })

    it('RetryIndicator displays retry count and countdown', async () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 2, nextRetryIn: 10 }
      })

      // Shows retry count
      expect(wrapper.text()).toContain('第2次重试')

      // Shows countdown
      expect(wrapper.text()).toContain('10秒')

      // Progress bar exists
      expect(wrapper.find('.h-2.bg-amber-100').exists()).toBe(true)
    })

    it('RetryIndicator countdown decrements over time', async () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 30 }
      })

      expect(wrapper.text()).toContain('30秒')

      vi.advanceTimersByTime(5000)
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain('25秒')
    })

    it('RetryIndicator emits cancel event when cancel button clicked', async () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      await wrapper.find('button').trigger('click')

      expect(wrapper.emitted('cancel')).toBeTruthy()
    })

    it('ErrorStore tracks retry count correctly', () => {
      const store = useErrorStore()

      store.setError('api', 'Error')

      const count1 = store.incrementRetry()
      const count2 = store.incrementRetry()
      const count3 = store.incrementRetry()

      expect(count1).toBe(1)
      expect(count2).toBe(2)
      expect(count3).toBe(3)
      expect(store.errorState?.retryCount).toBe(3)
    })

    it('ErrorStore clears retry count when error is cleared', () => {
      const store = useErrorStore()

      store.setError('api', 'Error')
      store.incrementRetry()
      store.incrementRetry()
      expect(store.retryCount).toBe(2)

      store.clearError()

      expect(store.retryCount).toBe(0)
      expect(store.hasError).toBe(false)
    })

    it('DEFAULT_CONFIG has correct retry limits', () => {
      expect(DEFAULT_CONFIG.maxRetries).toBe(3)
      expect(DEFAULT_CONFIG.baseDelay).toBe(1000)
      expect(DEFAULT_CONFIG.maxDelay).toBe(4000)
    })
  })

  describe('AC3: Offline state handled correctly', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
      vi.restoreAllMocks()
    })

    it('OfflineRecovery shows warning when offline', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      expect(wrapper.find('.fixed.top-0').exists()).toBe(true)
      expect(wrapper.text()).toContain('网络连接已断开')
      expect(wrapper.text()).toContain('请检查网络设置')
    })

    it('OfflineRecovery hides warning when online', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: true }
      })

      expect(wrapper.find('.fixed.top-0').exists()).toBe(false)
    })

    it('OfflineRecovery emits events on online/offline state changes', async () => {
      const wrapper = mount(OfflineRecovery)

      // Dispatch offline event
      window.dispatchEvent(new Event('offline'))
      await flushPromises()

      expect(wrapper.emitted('offline')).toBeTruthy()

      // Dispatch online event
      window.dispatchEvent(new Event('online'))
      await flushPromises()

      expect(wrapper.emitted('online')).toBeTruthy()
    })

    it('OfflineRecovery auto-recovers when connection restored', async () => {
      const wrapper = mount(OfflineRecovery)

      // Go offline
      window.dispatchEvent(new Event('offline'))
      await flushPromises()

      expect(wrapper.emitted('offline')).toBeTruthy()

      // Go back online
      window.dispatchEvent(new Event('online'))
      await flushPromises()

      expect(wrapper.emitted('online')).toBeTruthy()
      expect(wrapper.emitted('online').length).toBe(1)
    })

    it('OfflineRecovery toggles warning when prop changes', async () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: true }
      })

      // Initially online - no warning
      expect(wrapper.find('.fixed.top-0').exists()).toBe(false)

      // Change to offline
      await wrapper.setProps({ isOnline: false })
      await flushPromises()

      // Should show warning
      expect(wrapper.find('.fixed.top-0').exists()).toBe(true)

      // Change back to online
      await wrapper.setProps({ isOnline: true })
      await flushPromises()

      // Warning should be hidden
      expect(wrapper.find('.fixed.top-0').exists()).toBe(false)
    })

    it('OfflineRecovery has amber color theme for warning', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      expect(wrapper.find('.from-amber-500').exists()).toBe(true)
      expect(wrapper.find('.to-amber-400').exists()).toBe(true)
    })

    it('OfflineRecovery has proper accessibility attributes', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      expect(wrapper.find('[role="status"]').exists()).toBe(true)
      expect(wrapper.find('[aria-live="assertive"]').exists()).toBe(true)
      expect(wrapper.find('[aria-label="网络离线警告"]').exists()).toBe(true)
    })

    it('OfflineRecovery removes event listeners on unmount', () => {
      const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener')

      const wrapper = mount(OfflineRecovery)
      wrapper.unmount()

      expect(removeEventListenerSpy).toHaveBeenCalledWith('online', expect.any(Function))
      expect(removeEventListenerSpy).toHaveBeenCalledWith('offline', expect.any(Function))
    })
  })
})
