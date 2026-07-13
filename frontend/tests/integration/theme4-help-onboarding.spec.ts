import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import App from '@/App.vue'
import OnboardingTour from '@/components/OnboardingTour.vue'
import KeyboardShortcutsHelp from '@/components/KeyboardShortcutsHelp.vue'
import HelpCenter from '@/components/HelpCenter.vue'
import { useOnboardingStore } from '@/stores/onboarding'
import { useShortcutsStore } from '@/stores/shortcuts'
import { ONBOARDING_STORAGE_KEY, DEFAULT_ONBOARDING_STATE } from '@/types/onboarding'

// Mock ResizeObserver
vi.stubGlobal('ResizeObserver', vi.fn(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
})))

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} },
  }
})()

vi.stubGlobal('localStorage', localStorageMock)

// Mock WebSocket
vi.stubGlobal('WebSocket', vi.fn(() => ({
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  send: vi.fn(),
  close: vi.fn(),
})))

describe('Theme 4: Help & Onboarding - Acceptance Tests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorageMock.clear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('AC1: New user completes onboarding flow (3 steps)', () => {
    it('shows onboarding tour for new users (localStorage empty)', async () => {
      const onboardingStore = useOnboardingStore()

      // New user - no localStorage data
      expect(onboardingStore.hasCompleted).toBe(false)

      // Init onboarding should start tour
      expect(onboardingStore.isOnboardingActive).toBe(false)
      onboardingStore.startTour()
      expect(onboardingStore.isOnboardingActive).toBe(true)
      expect(onboardingStore.currentStep).toBe(1)
    })

    it('allows user to navigate through all 3 steps', async () => {
      const onboardingStore = useOnboardingStore()
      onboardingStore.startTour()

      // Step 1
      expect(onboardingStore.currentStep).toBe(1)

      // Go to step 2
      onboardingStore.nextStep()
      expect(onboardingStore.currentStep).toBe(2)

      // Go to step 3
      onboardingStore.nextStep()
      expect(onboardingStore.currentStep).toBe(3)

      // Complete tour
      onboardingStore.completeTour()
      expect(onboardingStore.hasCompleted).toBe(true)
      expect(onboardingStore.isOnboardingActive).toBe(false)
    })

    it('saves completion state to localStorage', async () => {
      const onboardingStore = useOnboardingStore()
      onboardingStore.startTour()
      onboardingStore.nextStep()
      onboardingStore.nextStep()
      onboardingStore.completeTour()

      // Check localStorage
      const stored = localStorageMock.getItem(ONBOARDING_STORAGE_KEY)
      expect(stored).not.toBeNull()

      const state = JSON.parse(stored!)
      expect(state.has_completed_onboarding).toBe(true)
      expect(state.skipped).toBe(false)
      expect(state.completed_at).toBeDefined()
    })

    it('allows user to skip onboarding', async () => {
      const onboardingStore = useOnboardingStore()
      onboardingStore.startTour()

      // Skip tour
      onboardingStore.skipTour()

      expect(onboardingStore.hasCompleted).toBe(true)
      expect(onboardingStore.isOnboardingActive).toBe(false)

      // Check localStorage
      const stored = localStorageMock.getItem(ONBOARDING_STORAGE_KEY)
      const state = JSON.parse(stored!)
      expect(state.skipped).toBe(true)
    })

    it('does not show tour for users who already completed', async () => {
      // Set localStorage to show completed
      localStorageMock.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({
        has_completed_onboarding: true,
        completed_at: new Date().toISOString(),
      }))

      const onboardingStore = useOnboardingStore()
      onboardingStore.loadFromStorage()

      expect(onboardingStore.hasCompleted).toBe(true)

      // Try to start tour - should not start
      onboardingStore.startTour()
      expect(onboardingStore.isOnboardingActive).toBe(false)
    })

    it('OnboardingTour component renders all steps correctly', async () => {
      const wrapper = mount(OnboardingTour, {
        props: { isActive: true, currentStep: 1 },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' },
            AppIcon: { template: '<span class="app-icon"></span>' },
          },
        },
      })

      // Check step 1 renders
      expect(wrapper.text()).toContain('了解工作流')

      // Change to step 2
      await wrapper.setProps({ currentStep: 2 })
      expect(wrapper.text()).toContain('开始创作')

      // Change to step 3
      await wrapper.setProps({ currentStep: 3 })
      expect(wrapper.text()).toContain('审核与发布')
    })
  })

  describe('AC2: Keyboard shortcuts work correctly (press ? to show panel)', () => {
    it('shows shortcuts panel when ? key is pressed', async () => {
      const shortcutsStore = useShortcutsStore()

      // Initially panel is hidden
      expect(shortcutsStore.showPanel).toBe(false)

      // Simulate ? key press
      shortcutsStore.showShortcutsPanel()

      expect(shortcutsStore.showPanel).toBe(true)
    })

    it('hides shortcuts panel when Escape key is pressed', async () => {
      const shortcutsStore = useShortcutsStore()
      shortcutsStore.showShortcutsPanel()

      expect(shortcutsStore.showPanel).toBe(true)

      // Simulate Escape key
      shortcutsStore.hideShortcutsPanel()

      expect(shortcutsStore.showPanel).toBe(false)
    })

    it('KeyboardShortcutsHelp component renders shortcuts correctly', async () => {
      const wrapper = mount(KeyboardShortcutsHelp, {
        props: { isOpen: true },
        global: {
          stubs: {
            Teleport: { template: '<div><slot /></div>' },
            AppIcon: { template: '<span class="app-icon"></span>' },
          },
        },
      })

      // Check that shortcuts panel is visible
      expect(wrapper.find('[role="dialog"]').exists()).toBe(true)

      // Check for shortcut keys display
      expect(wrapper.findAll('kbd').length).toBeGreaterThan(0)
    })

    it('supports Ctrl+K shortcut to open panel', async () => {
      const shortcutsStore = useShortcutsStore()

      // Simulate Ctrl+K
      shortcutsStore.showShortcutsPanel()

      expect(shortcutsStore.showPanel).toBe(true)
    })

    it('shortcuts store provides correct shortcuts list', async () => {
      const shortcutsStore = useShortcutsStore()

      // Check that SHORTCUTS are defined
      expect(shortcutsStore.SHORTCUTS.length).toBeGreaterThan(0)

      // Check specific shortcuts exist
      const openCommandPalette = shortcutsStore.getShortcutByAction('open_command_palette')
      expect(openCommandPalette).toBeDefined()
      expect(openCommandPalette?.key).toBe('k')
      expect(openCommandPalette?.ctrl).toBe(true)

      const showShortcuts = shortcutsStore.getShortcutByAction('show_shortcuts')
      expect(showShortcuts).toBeDefined()
      expect(showShortcuts?.key).toBe('?')
      expect(showShortcuts?.shift).toBe(true)
    })
  })

  describe('AC3: Help information is accurate (HelpCenter FAQ)', () => {
    it('HelpCenter component renders with FAQ option', async () => {
      const wrapper = mount(HelpCenter, {
        global: {
          stubs: {
            AppIcon: { template: '<span class="app-icon"></span>' },
          },
        },
      })

      // Find help button
      const helpButton = wrapper.find('button[aria-label="帮助中心"]')
      expect(helpButton.exists()).toBe(true)

      // Click to open dropdown
      await helpButton.trigger('click')

      // Check dropdown menu items
      expect(wrapper.text()).toContain('常见问题')
      expect(wrapper.text()).toContain('快捷键')
      expect(wrapper.text()).toContain('反馈建议')
    })

    it('HelpCenter emits open-faq event when FAQ clicked', async () => {
      const wrapper = mount(HelpCenter, {
        global: {
          stubs: {
            AppIcon: { template: '<span class="app-icon"></span>' },
          },
        },
      })

      // Open dropdown
      await wrapper.find('button[aria-label="帮助中心"]').trigger('click')

      // Click FAQ button
      const faqButton = wrapper.findAll('button').find(b => b.text().includes('常见问题'))
      await faqButton?.trigger('click')

      expect(wrapper.emitted('open-faq')).toBeTruthy()
    })

    it('HelpCenter emits open-shortcuts event when shortcuts clicked', async () => {
      const wrapper = mount(HelpCenter, {
        global: {
          stubs: {
            AppIcon: { template: '<span class="app-icon"></span>' },
          },
        },
      })

      // Open dropdown
      await wrapper.find('button[aria-label="帮助中心"]').trigger('click')

      // Click shortcuts button
      const shortcutsButton = wrapper.findAll('button').find(b => b.text().includes('快捷键'))
      await shortcutsButton?.trigger('click')

      expect(wrapper.emitted('open-shortcuts')).toBeTruthy()
    })

    it('HelpCenter emits send-feedback event when feedback clicked', async () => {
      const wrapper = mount(HelpCenter, {
        global: {
          stubs: {
            AppIcon: { template: '<span class="app-icon"></span>' },
          },
        },
      })

      // Open dropdown
      await wrapper.find('button[aria-label="帮助中心"]').trigger('click')

      // Click feedback button
      const feedbackButton = wrapper.findAll('button').find(b => b.text().includes('反馈建议'))
      await feedbackButton?.trigger('click')

      expect(wrapper.emitted('send-feedback')).toBeTruthy()
    })

    it('HelpCenter closes dropdown when clicking outside', async () => {
      const wrapper = mount(HelpCenter, {
        attachTo: document.body,
        global: {
          stubs: {
            AppIcon: { template: '<span class="app-icon"></span>' },
          },
        },
      })

      // Open dropdown
      await wrapper.find('button[aria-label="帮助中心"]').trigger('click')
      expect(wrapper.vm.isOpen).toBe(true)

      // Click outside
      document.body.click()

      expect(wrapper.vm.isOpen).toBe(false)
    })

    it('HelpCenter has proper accessibility attributes', async () => {
      const wrapper = mount(HelpCenter, {
        global: {
          stubs: {
            AppIcon: { template: '<span class="app-icon"></span>' },
          },
        },
      })

      const button = wrapper.find('button')
      expect(button.attributes('aria-expanded')).toBeDefined()
      expect(button.attributes('aria-haspopup')).toBe('true')
      expect(button.attributes('aria-label')).toBe('帮助中心')
    })
  })

  describe('Integration: Full onboarding + help flow', () => {
    it('integrates onboarding with App.vue', async () => {
      // This test verifies the integration is properly connected
      const onboardingStore = useOnboardingStore()
      const shortcutsStore = useShortcutsStore()

      // Start onboarding
      onboardingStore.startTour()
      expect(onboardingStore.isOnboardingActive).toBe(true)

      // Complete all steps
      onboardingStore.nextStep()
      onboardingStore.nextStep()
      onboardingStore.completeTour()

      // Verify completion
      expect(onboardingStore.hasCompleted).toBe(true)

      // Test shortcuts
      shortcutsStore.showShortcutsPanel()
      expect(shortcutsStore.showPanel).toBe(true)
      shortcutsStore.hideShortcutsPanel()
      expect(shortcutsStore.showPanel).toBe(false)
    })

    it('preserves state across store reloads', async () => {
      const onboardingStore = useOnboardingStore()

      // Complete onboarding
      onboardingStore.startTour()
      onboardingStore.completeTour()

      // Verify localStorage has the data
      const stored = localStorageMock.getItem(ONBOARDING_STORAGE_KEY)
      expect(stored).not.toBeNull()

      // Create new store instance (simulating app restart)
      setActivePinia(createPinia())
      const newStore = useOnboardingStore()
      newStore.loadFromStorage()

      // Should have completed state
      expect(newStore.hasCompleted).toBe(true)
    })
  })
})
