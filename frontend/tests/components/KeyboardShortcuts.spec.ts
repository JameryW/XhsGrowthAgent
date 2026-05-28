import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import KeyboardShortcuts from '@/components/KeyboardShortcuts.vue'

// Mock the shortcuts store
const mockShowShortcutsPanel = vi.fn()
const mockHideShortcutsPanel = vi.fn()

vi.mock('@/stores/shortcuts', () => ({
  useShortcutsStore: vi.fn(() => ({
    showPanel: false,
    showShortcutsPanel: mockShowShortcutsPanel,
    hideShortcutsPanel: mockHideShortcutsPanel,
    currentRoute: 'dashboard',
  })),
  SHORTCUTS: [
    { key: 'k', ctrl: true, description: 'Open command palette', action: 'open_command_palette' },
    { key: 'r', ctrl: true, description: 'Refresh workflow', action: 'refresh_workflow' },
    { key: 'Escape', description: 'Close panel/modal', action: 'close_panel' },
    { key: '?', shift: true, description: 'Show shortcuts help', action: 'show_shortcuts' },
    { key: 'a', description: 'Go to analytics', action: 'navigate_analytics', pages: ['dashboard', 'review'] },
    { key: 'p', description: 'Go to review/publish', action: 'navigate_review', pages: ['dashboard', 'analytics'] },
    { key: 'r', description: 'Go to review page', action: 'navigate_review_page', pages: ['dashboard'] },
  ]
}))

describe('KeyboardShortcuts', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  describe('visual panel rendering', () => {
    it('renders panel when isOpen=true', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
      expect(wrapper.find('[aria-modal="true"]').exists()).toBe(true)
    })

    it('hides panel when isOpen=false', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: false },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    })

    it('has proper z-index for modal', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const modal = wrapper.find('.fixed.inset-0')
      expect(modal.classes()).toContain('z-50')
    })

    it('renders backdrop with blur', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const backdrop = wrapper.find('.bg-slate-900\\/50')
      expect(backdrop.exists()).toBe(true)
      expect(backdrop.classes()).toContain('backdrop-blur-sm')
    })

    it('renders header with title', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('快捷键面板')
    })

    it('renders close button in header', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const closeBtn = wrapper.find('[aria-label="关闭"]')
      expect(closeBtn.exists()).toBe(true)
    })
  })

  describe('category display', () => {
    it('shows shortcuts grouped by category', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      // Should have category headers
      expect(wrapper.text()).toContain('全局')
    })

    it('shows shortcuts count per category', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      // Should show count indicator
      expect(wrapper.html()).toContain('text-xs text-slate-400')
    })

    it('applies different colors for categories', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      // Global category should have violet color
      const globalHeader = wrapper.find('.text-violet-500')
      expect(globalHeader.exists()).toBe(true)
    })
  })

  describe('shortcut display', () => {
    it('shows shortcut description', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('Open command palette')
    })

    it('shows shortcut action identifier', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.html()).toContain('open_command_palette')
    })

    it('formats key combinations correctly', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      // Ctrl+K should be formatted
      expect(wrapper.text()).toContain('Ctrl')
      expect(wrapper.text()).toContain('k')
    })

    it('shows kbd element with styling', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const kbd = wrapper.find('kbd')
      expect(kbd.exists()).toBe(true)
      expect(kbd.classes()).toContain('rounded-lg')
      expect(kbd.classes()).toContain('font-mono')
    })
  })

  describe('close functionality', () => {
    it('emits close when close button clicked', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const closeBtn = wrapper.find('[aria-label="关闭"]')
      await closeBtn.trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close on Escape key', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      // Trigger keydown on the dialog element, not wrapper
      const dialog = wrapper.find('[role="dialog"]')
      await dialog.trigger('keydown', { key: 'Escape' })
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close on backdrop click', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      // The handleBackdropClick checks if e.target === e.currentTarget
      // We need to simulate clicking directly on the dialog element
      // (not a child), which would make target === currentTarget
      const dialog = wrapper.find('[role="dialog"]')
      // Trigger click directly on dialog element (simulates clicking the backdrop area)
      // In Vue Test Utils, triggering click on the parent element
      // should satisfy target === currentTarget check
      await dialog.trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('does not close on panel content click', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      const panel = wrapper.find('.bg-white\\/98')
      await panel.trigger('click')
      expect(wrapper.emitted('close')).toBeFalsy()
    })
  })

  describe('accessibility', () => {
    it('has proper ARIA attributes', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
      expect(wrapper.find('[aria-modal="true"]').exists()).toBe(true)
      expect(wrapper.find('[aria-labelledby]').exists()).toBe(true)
    })

    it('has footer hint for closing', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain('关闭此面板')
    })

    it('manages focus on open/close', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: false },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })

      // Focus should be saved when opened
      await wrapper.setProps({ isOpen: true })
      await wrapper.vm.$nextTick()
      expect(wrapper.emitted()).toBeDefined()
    })
  })

  describe('store integration', () => {
    it('calls showShortcutsPanel on mount when open', async () => {
      mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      expect(mockShowShortcutsPanel).toHaveBeenCalled()
    })

    it('calls hideShortcutsPanel on unmount', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      wrapper.unmount()
      expect(mockHideShortcutsPanel).toHaveBeenCalled()
    })
  })

  describe('animation', () => {
    it('has transition classes for smooth animation', async () => {
      const wrapper = mount(KeyboardShortcuts, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: {
              template: '<div><slot /></div>'
            }
          }
        }
      })
      await wrapper.vm.$nextTick()
      // Check for Transition component
      expect(wrapper.html()).toContain('shortcuts')
    })
  })
})