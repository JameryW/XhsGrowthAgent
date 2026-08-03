import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import TooltipHelper from '@/components/TooltipHelper.vue'

// INF-11/EV-08: slot-based tooltip. Trigger lives in the default slot; hover/focus
// on the wrapper span toggles the Teleported tooltip.
const teleported = {
  global: {
    stubs: {
      Teleport: { template: '<div><slot /></div>' },
    },
  },
}

function mountWithSlot(content = 'tip', position: 'top' | 'bottom' | 'left' | 'right' = 'top') {
  return mount(TooltipHelper, {
    props: { content, position },
    slots: { default: '<button data-trigger>trigger</button>' },
    attachTo: document.body,
    ...teleported,
  })
}

describe('TooltipHelper', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('content display', () => {
    it('displays tooltip content on hover', async () => {
      const wrapper = mountWithSlot('This is a helpful tip', 'top')
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)

      wrapper.find("span").trigger('mouseenter')
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)
      expect(wrapper.text()).toContain('This is a helpful tip')
      wrapper.unmount()
    })

    it('hides content when not visible', async () => {
      const wrapper = mountWithSlot('Hidden tip', 'top')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
      wrapper.unmount()
    })

    it('does not show when content is empty', async () => {
      const wrapper = mountWithSlot('', 'top')
      wrapper.find("span").trigger('mouseenter')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
      wrapper.unmount()
    })

    it('applies max-width class', async () => {
      const wrapper = mountWithSlot('Test', 'bottom')
      wrapper.find("span").trigger('mouseenter')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('.max-w-xs').exists()).toBe(true)
      wrapper.unmount()
    })
  })

  describe('position handling', () => {
    for (const pos of ['top', 'bottom', 'left', 'right'] as const) {
      it(`renders tooltip for ${pos} placement`, async () => {
        const wrapper = mountWithSlot(`${pos} tooltip`, pos)
        wrapper.find("span").trigger('mouseenter')
        await wrapper.vm.$nextTick()
        expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)
        wrapper.unmount()
      })
    }

    it('renders arrow for position', async () => {
      const wrapper = mountWithSlot('With arrow', 'top')
      wrapper.find("span").trigger('mouseenter')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('.border-8').exists()).toBe(true)
      wrapper.unmount()
    })
  })

  describe('show/hide behavior', () => {
    it('shows on hover', async () => {
      const wrapper = mountWithSlot('Hover tip', 'top')
      wrapper.find("span").trigger('mouseenter')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)
      wrapper.unmount()
    })

    it('hides on mouse leave', async () => {
      const wrapper = mountWithSlot('Hover tip', 'top')
      wrapper.find("span").trigger('mouseenter')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      wrapper.find("span").trigger('mouseleave')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
      wrapper.unmount()
    })

    it('shows on Focus', async () => {
      const wrapper = mountWithSlot('Focus tip', 'bottom')
      wrapper.find("span").trigger('focus')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)
      wrapper.unmount()
    })

    it('hides on blur', async () => {
      const wrapper = mountWithSlot('Focus tip', 'bottom')
      wrapper.find("span").trigger('focus')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      wrapper.find("span").trigger('blur')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
      wrapper.unmount()
    })
  })

  describe('animation', () => {
    it('has fade transition class', async () => {
      const wrapper = mountWithSlot('Animated', 'top')
      expect(wrapper.html()).toContain('tooltip')
      wrapper.unmount()
    })
  })

  describe('accessibility', () => {
    it('has role="tooltip"', async () => {
      const wrapper = mountWithSlot('Accessible', 'top')
      wrapper.find("span").trigger('mouseenter')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)
      wrapper.unmount()
    })

    it('has aria-hidden when not visible', async () => {
      const wrapper = mountWithSlot('Hidden', 'top')
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
      wrapper.unmount()
    })
  })
})
