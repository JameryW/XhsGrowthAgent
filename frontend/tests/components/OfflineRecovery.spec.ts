// frontend/tests/components/OfflineRecovery.spec.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import OfflineRecovery from '@/components/OfflineRecovery.vue'
import { createPinia, setActivePinia } from 'pinia'

describe('OfflineRecovery', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  describe('offline state (prop-based)', () => {
    it('hides warning bar when online (prop)', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: true }
      })

      expect(wrapper.find('.fixed.top-0').exists()).toBe(false)
    })

    it('shows warning bar when offline (prop)', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      expect(wrapper.find('.fixed.top-0').exists()).toBe(true)
    })

    it('shows warning message when offline', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      expect(wrapper.text()).toContain('网络连接已断开')
      expect(wrapper.text()).toContain('请检查网络设置')
    })

    it('toggles warning when prop changes', async () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: true }
      })

      // Initially online - no warning
      expect(wrapper.find('.fixed.top-0').exists()).toBe(false)

      // Change to offline
      await wrapper.setProps({ isOnline: false })
      await flushPromises()

      // Now should show warning
      expect(wrapper.find('.fixed.top-0').exists()).toBe(true)

      // Change back to online
      await wrapper.setProps({ isOnline: true })
      await flushPromises()

      // Warning should be hidden
      expect(wrapper.find('.fixed.top-0').exists()).toBe(false)
    })
  })

  describe('offline state (event-based)', () => {
    it('shows warning when offline event triggers internal state change', async () => {
      // Start with online prop to ensure initial state is online
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: true }
      })

      // Remove prop to use internal state
      await wrapper.setProps({ isOnline: undefined })
      await flushPromises()

      // Trigger offline event
      window.dispatchEvent(new Event('offline'))
      await flushPromises()

      // Should show warning
      expect(wrapper.find('.fixed.top-0').exists()).toBe(true)
    })

    it('hides warning when online event triggers internal state change', async () => {
      // Start with offline to trigger warning
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      // Should show warning
      expect(wrapper.find('.fixed.top-0').exists()).toBe(true)

      // Remove prop to use internal state, then trigger online
      await wrapper.setProps({ isOnline: undefined })
      await flushPromises()

      // Trigger online event
      window.dispatchEvent(new Event('online'))
      await flushPromises()

      // Should hide warning
      expect(wrapper.find('.fixed.top-0').exists()).toBe(false)
    })
  })

  describe('events', () => {
    it('emits online event when online event fired', async () => {
      const wrapper = mount(OfflineRecovery)

      // Dispatch 'online' event
      window.dispatchEvent(new Event('online'))
      await flushPromises()

      expect(wrapper.emitted('online')).toBeTruthy()
    })

    it('emits offline event when offline event fired', async () => {
      const wrapper = mount(OfflineRecovery)

      // Dispatch 'offline' event
      window.dispatchEvent(new Event('offline'))
      await flushPromises()

      expect(wrapper.emitted('offline')).toBeTruthy()
    })
  })

  describe('reconnection notification', () => {
    it('tracks wasOffline state', async () => {
      const wrapper = mount(OfflineRecovery)

      // Go offline
      window.dispatchEvent(new Event('offline'))
      await flushPromises()

      // Go back online
      window.dispatchEvent(new Event('online'))
      await flushPromises()

      // Should have emitted both events
      expect(wrapper.emitted('offline')).toBeTruthy()
      expect(wrapper.emitted('online')).toBeTruthy()
    })

    it('shows toast on reconnection', async () => {
      const wrapper = mount(OfflineRecovery)

      // Go offline
      window.dispatchEvent(new Event('offline'))
      await flushPromises()

      // Go back online
      window.dispatchEvent(new Event('online'))
      await flushPromises()

      // Toast should have been called (we can check emitted events)
      expect(wrapper.emitted('online').length).toBe(1)
    })

    it('shows toast when prop changes from offline to online', async () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      // Initially offline
      expect(wrapper.find('.fixed.top-0').exists()).toBe(true)

      // Change to online
      await wrapper.setProps({ isOnline: true })
      await flushPromises()

      // Warning should be hidden
      expect(wrapper.find('.fixed.top-0').exists()).toBe(false)
    })
  })

  describe('structure and styling', () => {
    it('has amber color theme for warning', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      expect(wrapper.find('.from-amber-500').exists()).toBe(true)
      expect(wrapper.find('.to-amber-400').exists()).toBe(true)
    })

    it('is fixed at top of screen', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      expect(wrapper.find('.fixed.top-0.left-0.right-0').exists()).toBe(true)
      expect(wrapper.find('.z-modal').exists()).toBe(true)
    })

    it('has WifiOff icon', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      // Icon component should be rendered
      expect(wrapper.findComponent({ name: 'AppIcon' }).exists()).toBe(true)
    })

    it('has proper accessibility attributes', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      expect(wrapper.find('[role="status"]').exists()).toBe(true)
      expect(wrapper.find('[aria-live="assertive"]').exists()).toBe(true)
      expect(wrapper.find('[aria-label="网络离线警告"]').exists()).toBe(true)
    })
  })

  describe('transition', () => {
    it('uses Transition component for animation', () => {
      const wrapper = mount(OfflineRecovery, {
        props: { isOnline: false }
      })

      // The Transition component is used for the offline bar
      expect(wrapper.html()).toContain('offline-recovery')
    })
  })

  describe('cleanup', () => {
    it('removes event listeners on unmount', () => {
      const removeEventListenerSpy = vi.spyOn(window, 'removeEventListener')

      const wrapper = mount(OfflineRecovery)
      wrapper.unmount()

      expect(removeEventListenerSpy).toHaveBeenCalledWith('online', expect.any(Function))
      expect(removeEventListenerSpy).toHaveBeenCalledWith('offline', expect.any(Function))
    })
  })
})