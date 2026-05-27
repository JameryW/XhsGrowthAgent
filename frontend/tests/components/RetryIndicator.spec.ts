// frontend/tests/components/RetryIndicator.spec.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import RetryIndicator from '@/components/RetryIndicator.vue'

describe('RetryIndicator', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('retry count display', () => {
    it('displays retry count correctly', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 3, nextRetryIn: 10 }
      })

      expect(wrapper.text()).toContain('第3次重试')
    })

    it('displays retry count for first retry', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 5 }
      })

      expect(wrapper.text()).toContain('第1次重试')
    })

    it('displays retry count for higher values', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 10, nextRetryIn: 30 }
      })

      expect(wrapper.text()).toContain('第10次重试')
    })
  })

  describe('timer countdown', () => {
    it('shows countdown time initially', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 15 }
      })

      expect(wrapper.text()).toContain('15秒')
    })

    it('formats seconds correctly for values under 60', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 45 }
      })

      expect(wrapper.text()).toContain('45秒')
    })

    it('formats minutes correctly for values over 60', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 90 }
      })

      expect(wrapper.text()).toContain('1分30秒')
    })

    it('formats exact minutes without seconds', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 120 }
      })

      expect(wrapper.text()).toContain('2分钟')
    })

    it('counts down after one second', async () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      expect(wrapper.text()).toContain('10秒')

      vi.advanceTimersByTime(1000)
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain('9秒')
    })

    it('counts down multiple seconds', async () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 30 }
      })

      expect(wrapper.text()).toContain('30秒')

      vi.advanceTimersByTime(5000)
      await wrapper.vm.$nextTick()

      expect(wrapper.text()).toContain('25秒')
    })
  })

  describe('progress bar', () => {
    it('shows progress bar element', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      expect(wrapper.find('.h-2.bg-amber-100').exists()).toBe(true)
    })

    it('progress bar starts at 0%', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      const progressBar = wrapper.find('.bg-gradient-to-r')
      expect(progressBar.attributes('style')).toContain('width: 0%')
    })

    it('progress bar advances after countdown', async () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      vi.advanceTimersByTime(5000) // 5 seconds passed = 50%
      await wrapper.vm.$nextTick()

      const progressBar = wrapper.find('.bg-gradient-to-r')
      expect(progressBar.attributes('style')).toContain('width: 50%')
    })

    it('progress bar reaches 100% when countdown ends', async () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 5 }
      })

      vi.advanceTimersByTime(5000) // 5 seconds passed = 100%
      await wrapper.vm.$nextTick()

      const progressBar = wrapper.find('.bg-gradient-to-r')
      expect(progressBar.attributes('style')).toContain('width: 100%')
    })
  })

  describe('cancel button', () => {
    it('has cancel button', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      expect(wrapper.find('button').exists()).toBe(true)
      expect(wrapper.text()).toContain('取消重试')
    })

    it('emits cancel event when clicked', async () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      await wrapper.find('button').trigger('click')

      expect(wrapper.emitted('cancel')).toBeTruthy()
      expect(wrapper.emitted('cancel').length).toBe(1)
    })
  })

  describe('structure and styling', () => {
    it('has amber color theme', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      expect(wrapper.find('.bg-amber-50\\/80').exists()).toBe(true)
      expect(wrapper.find('.border-amber-200\\/50').exists()).toBe(true)
    })

    it('has icon container', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      expect(wrapper.find('.w-8.h-8').exists()).toBe(true)
      expect(wrapper.find('.rounded-lg').exists()).toBe(true)
    })

    it('has proper accessibility attributes', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      expect(wrapper.find('[role="status"]').exists()).toBe(true)
      expect(wrapper.find('[aria-live="polite"]').exists()).toBe(true)
      expect(wrapper.find('[aria-label="重试状态"]').exists()).toBe(true)
    })
  })

  describe('timer cleanup', () => {
    it('clears timer on unmount', () => {
      const wrapper = mount(RetryIndicator, {
        props: { retryCount: 1, nextRetryIn: 10 }
      })

      // Should have started a timer
      expect(vi.getTimerCount()).toBe(1)

      wrapper.unmount()

      // Timer should be cleared
      vi.advanceTimersByTime(1000)
      // No timer should be running after unmount
      expect(vi.getTimerCount()).toBe(0)
    })
  })
})