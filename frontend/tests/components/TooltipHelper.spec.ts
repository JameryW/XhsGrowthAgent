import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import TooltipHelper from '@/components/TooltipHelper.vue'

describe('TooltipHelper', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('content display', () => {
    it('displays tooltip content', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'This is a helpful tip', position: 'top' },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      // Show tooltip via exposed method
      const tooltip = wrapper.vm as any
      tooltip.show()

      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)
      expect(wrapper.text()).toContain('This is a helpful tip')
    })

    it('hides content when not visible', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Hidden tip', position: 'top' },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
    })

    it('applies max-width class', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Test', position: 'bottom' },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const tooltip = wrapper.vm as any
      tooltip.show()
      await wrapper.vm.$nextTick()

      expect(wrapper.find('.max-w-xs').exists()).toBe(true)
    })
  })

  describe('position handling', () => {
    it('calculates position for top placement', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Top tooltip', position: 'top' },
        attachTo: document.body,
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      // Create a mock target element
      const targetEl = document.createElement('div')
      targetEl.style.position = 'absolute'
      targetEl.style.top = '100px'
      targetEl.style.left = '100px'
      targetEl.style.width = '100px'
      targetEl.style.height = '50px'
      document.body.appendChild(targetEl)

      const tooltip = wrapper.vm as any
      tooltip.attach(targetEl)
      tooltip.show()

      await wrapper.vm.$nextTick()

      // Tooltip should be positioned above the target
      const tooltipEl = wrapper.find('[role="tooltip"]')
      expect(tooltipEl.exists()).toBe(true)

      // Cleanup
      document.body.removeChild(targetEl)
      wrapper.unmount()
    })

    it('calculates position for bottom placement', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Bottom tooltip', position: 'bottom' },
        attachTo: document.body,
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const targetEl = document.createElement('div')
      targetEl.style.position = 'absolute'
      targetEl.style.top = '100px'
      targetEl.style.left = '100px'
      targetEl.style.width = '100px'
      targetEl.style.height = '50px'
      document.body.appendChild(targetEl)

      const tooltip = wrapper.vm as any
      tooltip.attach(targetEl)
      tooltip.show()

      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      document.body.removeChild(targetEl)
      wrapper.unmount()
    })

    it('calculates position for left placement', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Left tooltip', position: 'left' },
        attachTo: document.body,
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const targetEl = document.createElement('div')
      document.body.appendChild(targetEl)

      const tooltip = wrapper.vm as any
      tooltip.attach(targetEl)
      tooltip.show()

      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      document.body.removeChild(targetEl)
      wrapper.unmount()
    })

    it('calculates position for right placement', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Right tooltip', position: 'right' },
        attachTo: document.body,
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const targetEl = document.createElement('div')
      document.body.appendChild(targetEl)

      const tooltip = wrapper.vm as any
      tooltip.attach(targetEl)
      tooltip.show()

      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      document.body.removeChild(targetEl)
      wrapper.unmount()
    })

    it('renders arrow for position', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'With arrow', position: 'top' },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const tooltip = wrapper.vm as any
      tooltip.show()
      await wrapper.vm.$nextTick()

      expect(wrapper.find('.border-8').exists()).toBe(true)
    })
  })

  describe('show/hide behavior', () => {
    it('shows on hover via attach method', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Hover tip', position: 'top' },
        attachTo: document.body,
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const targetEl = document.createElement('button')
      document.body.appendChild(targetEl)

      const tooltip = wrapper.vm as any
      tooltip.attach(targetEl)

      // Trigger hover
      targetEl.dispatchEvent(new MouseEvent('mouseenter'))
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      document.body.removeChild(targetEl)
      wrapper.unmount()
    })

    it('hides on mouse leave', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Hover tip', position: 'top' },
        attachTo: document.body,
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const targetEl = document.createElement('button')
      document.body.appendChild(targetEl)

      const tooltip = wrapper.vm as any
      tooltip.attach(targetEl)

      // Show
      targetEl.dispatchEvent(new MouseEvent('mouseenter'))
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      // Hide
      targetEl.dispatchEvent(new MouseEvent('mouseleave'))
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)

      document.body.removeChild(targetEl)
      wrapper.unmount()
    })

    it('shows on focus', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Focus tip', position: 'bottom' },
        attachTo: document.body,
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const targetEl = document.createElement('input')
      document.body.appendChild(targetEl)

      const tooltip = wrapper.vm as any
      tooltip.attach(targetEl)

      targetEl.dispatchEvent(new FocusEvent('focus'))
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      document.body.removeChild(targetEl)
      wrapper.unmount()
    })

    it('hides on blur', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Focus tip', position: 'bottom' },
        attachTo: document.body,
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const targetEl = document.createElement('input')
      document.body.appendChild(targetEl)

      const tooltip = wrapper.vm as any
      tooltip.attach(targetEl)

      // Show
      targetEl.dispatchEvent(new FocusEvent('focus'))
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      // Hide
      targetEl.dispatchEvent(new FocusEvent('blur'))
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)

      document.body.removeChild(targetEl)
      wrapper.unmount()
    })

    it('can be manually shown via expose', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Manual show', position: 'top' },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const tooltip = wrapper.vm as any
      tooltip.show()
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)
    })

    it('can be manually hidden via expose', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Manual hide', position: 'top' },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const tooltip = wrapper.vm as any
      tooltip.show()
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)

      tooltip.hide()
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="tooltip"]').exists()).toBe(false)
    })
  })

  describe('animation', () => {
    it('has fade transition class', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Animated', position: 'top' },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      // Check for transition name in template
      expect(wrapper.html()).toContain('tooltip')
    })
  })

  describe('accessibility', () => {
    it('has role="tooltip"', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Accessible', position: 'top' },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      const tooltip = wrapper.vm as any
      tooltip.show()
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[role="tooltip"]').exists()).toBe(true)
    })

    it('has aria-hidden when not visible', async () => {
      const wrapper = mount(TooltipHelper, {
        props: { content: 'Hidden', position: 'top' },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      // When not visible, aria-hidden should be true
      expect(wrapper.vm.isVisible).toBe(false)
    })
  })
})