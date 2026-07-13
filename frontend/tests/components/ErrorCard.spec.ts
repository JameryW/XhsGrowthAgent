// frontend/tests/components/ErrorCard.spec.ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ErrorCard from '@/components/ErrorCard.vue'
import type { ErrorType } from '@/types/error'

describe('ErrorCard', () => {
  describe('colors per type', () => {
    it('uses rose color for api error type', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Network request failed' }
      })

      expect(wrapper.find('.bg-rose-50\\/80').exists()).toBe(true)
      expect(wrapper.find('.border-rose-200\\/50').exists()).toBe(true)
      expect(wrapper.find('.bg-rose-100').exists()).toBe(true)
    })

    it('uses amber color for timeout error type', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'timeout', message: 'Request timed out' }
      })

      expect(wrapper.find('.bg-amber-50\\/80').exists()).toBe(true)
      expect(wrapper.find('.border-amber-200\\/50').exists()).toBe(true)
      expect(wrapper.find('.bg-amber-100').exists()).toBe(true)
    })

    it('uses violet color for unknown error type', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'unknown', message: 'Something went wrong' }
      })

      expect(wrapper.find('.bg-violet-50\\/80').exists()).toBe(true)
      expect(wrapper.find('.border-violet-200\\/50').exists()).toBe(true)
      expect(wrapper.find('.bg-violet-100').exists()).toBe(true)
    })

    it('uses green color for retry_success error type', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'retry_success', message: 'Operation recovered' }
      })

      expect(wrapper.find('.bg-green-50\\/80').exists()).toBe(true)
      expect(wrapper.find('.border-green-200\\/50').exists()).toBe(true)
      expect(wrapper.find('.bg-green-100').exists()).toBe(true)
    })
  })

  describe('message displays', () => {
    it('displays the error message', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Network request failed' }
      })

      expect(wrapper.text()).toContain('Network request failed')
    })

    it('displays correct title for api type', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error' }
      })

      expect(wrapper.text()).toContain('API 错误')
    })

    it('displays correct title for timeout type', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'timeout', message: 'Error' }
      })

      expect(wrapper.text()).toContain('请求超时')
    })

    it('displays correct title for unknown type', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'unknown', message: 'Error' }
      })

      expect(wrapper.text()).toContain('未知错误')
    })

    it('displays correct title for retry_success type', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'retry_success', message: 'Success' }
      })

      expect(wrapper.text()).toContain('重试成功')
    })

    it('displays retry count when provided', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error', retryCount: 3 }
      })

      expect(wrapper.text()).toContain('已重试 3 次')
    })

    it('displays retry count in button', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error', retryCount: 2 }
      })

      expect(wrapper.text()).toContain('重试 (2)')
    })
  })

  describe('buttons work', () => {
    it('emits retry event when retry button clicked', async () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error' }
      })

      // Find retry button by looking for RefreshCw icon
      const buttons = wrapper.findAllComponents({ name: 'NeonButton' })
      const retryButton = buttons[0]
      await retryButton.trigger('click')

      expect(wrapper.emitted('retry')).toBeTruthy()
      expect(wrapper.emitted('retry').length).toBe(1)
    })

    it('emits dismiss event when dismiss button clicked', async () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error' }
      })

      // Find dismiss button by looking for X icon
      const buttons = wrapper.findAllComponents({ name: 'NeonButton' })
      const dismissButton = buttons[1]
      await dismissButton.trigger('click')

      expect(wrapper.emitted('dismiss')).toBeTruthy()
      expect(wrapper.emitted('dismiss').length).toBe(1)
    })

    it('hides retry button for retry_success type', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'retry_success', message: 'Success' }
      })

      // Should only have one button (dismiss)
      const buttons = wrapper.findAllComponents({ name: 'NeonButton' })
      expect(buttons.length).toBe(1)

      // Check that the title is "重试成功" not just "重试"
      expect(wrapper.find('h3').text()).toBe('重试成功')
    })

    it('shows retry button for non-success types', () => {
      const types: ErrorType[] = ['api', 'timeout', 'unknown']

      types.forEach(type => {
        const wrapper = mount(ErrorCard, {
          props: { type, message: 'Error' }
        })

        const buttons = wrapper.findAllComponents({ name: 'NeonButton' })
        expect(buttons.length).toBe(2)
        expect(wrapper.text()).toContain('重试')
      })
    })
  })

  describe('structure', () => {
    it('has proper rounded card structure', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error' }
      })

      expect(wrapper.find('.rounded-2xl').exists()).toBe(true)
      expect(wrapper.find('.p-6').exists()).toBe(true)
    })

    it('has icon container', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error' }
      })

      expect(wrapper.find('.w-12.h-12').exists()).toBe(true)
      expect(wrapper.find('.rounded-xl').exists()).toBe(true)
    })

    it('has action buttons container', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error' }
      })

      expect(wrapper.find('.flex.flex-col.gap-2').exists()).toBe(true)
    })
  })

  describe('retry count display', () => {
    it('shows retry count when greater than 0', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error', retryCount: 1 }
      })

      expect(wrapper.text()).toContain('已重试 1 次')
    })

    it('hides retry count when 0', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error', retryCount: 0 }
      })

      expect(wrapper.text()).not.toContain('已重试')
    })

    it('hides retry count when undefined', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error' }
      })

      expect(wrapper.text()).not.toContain('已重试')
    })

    it('shows retry count in button when provided', () => {
      const wrapper = mount(ErrorCard, {
        props: { type: 'api', message: 'Error', retryCount: 5 }
      })

      expect(wrapper.text()).toContain('重试 (5)')
    })
  })
})
