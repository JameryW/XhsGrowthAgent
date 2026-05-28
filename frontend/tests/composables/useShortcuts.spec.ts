// frontend/tests/composables/useShortcuts.spec.ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useShortcuts, SHORTCUTS_MAP, buildShortcutKey, parseKeyEvent } from '@/composables/useShortcuts'
import { useShortcutsStore } from '@/stores/shortcuts'

// Mock window.addEventListener/removeEventListener
const originalAddEventListener = window.addEventListener
const originalRemoveEventListener = window.removeEventListener

describe('useShortcuts', () => {
  beforeEach(() => {
    // Create a fresh Pinia instance for each test
    setActivePinia(createPinia())
    // Mock window event listeners
    vi.spyOn(window, 'addEventListener')
    vi.spyOn(window, 'removeEventListener')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('SHORTCUTS_MAP constant', () => {
    it('has Ctrl+K shortcut', () => {
      expect(SHORTCUTS_MAP['Ctrl+k']).toBeDefined()
      expect(SHORTCUTS_MAP['Ctrl+k'].action).toBe('open_command_palette')
    })

    it('has Ctrl+R shortcut', () => {
      expect(SHORTCUTS_MAP['Ctrl+r']).toBeDefined()
      expect(SHORTCUTS_MAP['Ctrl+r'].action).toBe('refresh_workflow')
    })

    it('has Escape shortcut', () => {
      expect(SHORTCUTS_MAP['Escape']).toBeDefined()
      expect(SHORTCUTS_MAP['Escape'].action).toBe('close_panel')
    })

    it('has Shift+? shortcut', () => {
      expect(SHORTCUTS_MAP['Shift+?']).toBeDefined()
      expect(SHORTCUTS_MAP['Shift+?'].action).toBe('show_shortcuts')
    })

    it('includes all shortcuts from SHORTCUTS', () => {
      const shortcutsCount = Object.keys(SHORTCUTS_MAP).length
      expect(shortcutsCount).toBeGreaterThan(0)
    })
  })

  describe('buildShortcutKey', () => {
    it('builds key for Ctrl+K', () => {
      const key = buildShortcutKey({ key: 'k', ctrl: true, description: '', action: '' })
      expect(key).toBe('Ctrl+k')
    })

    it('builds key for Shift+?', () => {
      const key = buildShortcutKey({ key: '?', shift: true, description: '', action: '' })
      expect(key).toBe('Shift+?')
    })

    it('builds key for plain key', () => {
      const key = buildShortcutKey({ key: 'a', description: '', action: '' })
      expect(key).toBe('a')
    })

    it('builds key for Ctrl+Shift+key', () => {
      const key = buildShortcutKey({ key: 'x', ctrl: true, shift: true, description: '', action: '' })
      expect(key).toBe('Ctrl+Shift+x')
    })
  })

  describe('parseKeyEvent', () => {
    it('parses Ctrl+K event', () => {
      const event = new KeyboardEvent('keydown', { key: 'k', ctrlKey: true })
      const key = parseKeyEvent(event)
      expect(key).toBe('Ctrl+k')
    })

    it('parses Shift+? event', () => {
      const event = new KeyboardEvent('keydown', { key: '?', shiftKey: true })
      const key = parseKeyEvent(event)
      expect(key).toBe('Shift+?')
    })

    it('parses Escape event', () => {
      const event = new KeyboardEvent('keydown', { key: 'Escape' })
      const key = parseKeyEvent(event)
      expect(key).toBe('Escape')
    })

    it('treats metaKey as Ctrl', () => {
      const event = new KeyboardEvent('keydown', { key: 'k', metaKey: true })
      const key = parseKeyEvent(event)
      expect(key).toBe('Ctrl+k')
    })
  })

  describe('setupKeyboardListeners', () => {
    it('adds keydown listener', () => {
      const shortcuts = useShortcuts()

      shortcuts.setupKeyboardListeners()

      expect(window.addEventListener).toHaveBeenCalledWith('keydown', shortcuts.handleKeyPress)
    })

    it('does not add listener twice', () => {
      const shortcuts = useShortcuts()

      shortcuts.setupKeyboardListeners()
      shortcuts.setupKeyboardListeners()

      expect(window.addEventListener).toHaveBeenCalledTimes(1)
    })

    it('sets listenersActive to true', () => {
      const shortcuts = useShortcuts()

      shortcuts.setupKeyboardListeners()

      expect(shortcuts.listenersActive.value).toBe(true)
    })
  })

  describe('removeKeyboardListeners', () => {
    it('removes keydown listener', () => {
      const shortcuts = useShortcuts()
      shortcuts.setupKeyboardListeners()

      shortcuts.removeKeyboardListeners()

      expect(window.removeEventListener).toHaveBeenCalledWith('keydown', shortcuts.handleKeyPress)
    })

    it('does not remove listener if not active', () => {
      const shortcuts = useShortcuts()
      // Don't setup listeners

      shortcuts.removeKeyboardListeners()

      expect(window.removeEventListener).not.toHaveBeenCalled()
    })

    it('sets listenersActive to false', () => {
      const shortcuts = useShortcuts()
      shortcuts.setupKeyboardListeners()

      shortcuts.removeKeyboardListeners()

      expect(shortcuts.listenersActive.value).toBe(false)
    })
  })

  describe('handleKeyPress', () => {
    it('updates lastKeyPressed', () => {
      const shortcuts = useShortcuts()
      const event = new KeyboardEvent('keydown', { key: 'k', ctrlKey: true })

      shortcuts.handleKeyPress(event)

      expect(shortcuts.lastKeyPressed.value).toBe('Ctrl+k')
    })

    it('executes matching shortcut', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()
      const event = new KeyboardEvent('keydown', { key: 'k', ctrlKey: true })

      shortcuts.handleKeyPress(event)

      expect(store.activeShortcuts).toContain('open_command_palette')
    })

    it('prevents default for shortcuts', () => {
      const shortcuts = useShortcuts()
      const event = new KeyboardEvent('keydown', { key: 'k', ctrlKey: true })
      const preventDefaultSpy = vi.spyOn(event, 'preventDefault')

      shortcuts.handleKeyPress(event)

      expect(preventDefaultSpy).toHaveBeenCalled()
    })

    it('does not execute shortcut not valid for page', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()
      store.setCurrentRoute('analytics')

      // 'a' shortcut is for dashboard and review, not analytics
      const event = new KeyboardEvent('keydown', { key: 'a' })

      shortcuts.handleKeyPress(event)

      // Should not add navigate_analytics because it's not valid for analytics page
      expect(store.activeShortcuts).not.toContain('navigate_analytics')
    })

    it('executes Escape to close panel', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()
      store.showShortcutsPanel()

      const event = new KeyboardEvent('keydown', { key: 'Escape' })
      shortcuts.handleKeyPress(event)

      expect(store.showPanel).toBe(false)
    })

    it('executes chord mode for G key', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()
      store.setCurrentRoute('dashboard')

      const event = new KeyboardEvent('keydown', { key: 'g' })
      shortcuts.handleKeyPress(event)

      expect(store.chordMode).toBe(true)
      expect(store.chordPrefix).toBe('g')
    })
  })

  describe('activeShortcutsForPage computed', () => {
    it('returns shortcuts for current page', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()
      store.setCurrentRoute('dashboard')

      const active = shortcuts.activeShortcutsForPage.value

      // Should include global shortcuts
      expect(active.some(s => s.action === 'open_command_palette')).toBe(true)
    })

    it('filters shortcuts by page', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()
      store.setCurrentRoute('analytics')

      const active = shortcuts.activeShortcutsForPage.value

      // Should include analytics-specific shortcuts
      expect(active.some(s => s.action === 'navigate_review')).toBe(true)
    })
  })

  describe('getShortcutByKey', () => {
    it('returns shortcut for valid key', () => {
      const shortcuts = useShortcuts()

      const shortcut = shortcuts.getShortcutByKey('Ctrl+k')

      expect(shortcut?.action).toBe('open_command_palette')
    })

    it('returns undefined for invalid key', () => {
      const shortcuts = useShortcuts()

      const shortcut = shortcuts.getShortcutByKey('Ctrl+z')

      expect(shortcut).toBeUndefined()
    })
  })

  describe('getShortcutsForPage', () => {
    it('returns shortcuts for dashboard', () => {
      const shortcuts = useShortcuts()

      const pageShortcuts = shortcuts.getShortcutsForPage('dashboard')

      expect(pageShortcuts.some(s => s.action === 'navigate_review')).toBe(true)
      expect(pageShortcuts.some(s => s.action === 'open_command_palette')).toBe(true)
    })

    it('returns shortcuts for review page', () => {
      const shortcuts = useShortcuts()

      const pageShortcuts = shortcuts.getShortcutsForPage('review')

      expect(pageShortcuts.some(s => s.action === 'navigate_analytics')).toBe(true)
    })

    it('returns global shortcuts for any page', () => {
      const shortcuts = useShortcuts()

      const pageShortcuts = shortcuts.getShortcutsForPage('unknown')

      // Global shortcuts should be available
      expect(pageShortcuts.some(s => !s.pages)).toBe(true)
    })
  })

  describe('isShortcut', () => {
    it('returns true for valid shortcut', () => {
      const shortcuts = useShortcuts()

      expect(shortcuts.isShortcut('Ctrl+k')).toBe(true)
    })

    it('returns false for invalid shortcut', () => {
      const shortcuts = useShortcuts()

      expect(shortcuts.isShortcut('Ctrl+z')).toBe(false)
    })
  })

  describe('handleShortcutAction', () => {
    it('opens panel for open_command_palette', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()

      shortcuts.handleShortcutAction('open_command_palette')

      expect(store.showPanel).toBe(true)
    })

    it('closes panel for close_panel', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()
      store.showShortcutsPanel()

      shortcuts.handleShortcutAction('close_panel')

      expect(store.showPanel).toBe(false)
      expect(store.chordMode).toBe(false)
    })

    it('toggles panel for show_shortcuts', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()
      store.showPanel = false

      shortcuts.handleShortcutAction('show_shortcuts')

      expect(store.showPanel).toBe(true)
    })

    it('resets chord mode for navigation actions', () => {
      const shortcuts = useShortcuts()
      const store = useShortcutsStore()
      store.chordMode = true
      store.chordPrefix = 'g'

      shortcuts.handleShortcutAction('navigate_home')

      expect(store.chordMode).toBe(false)
      expect(store.chordPrefix).toBe(null)
    })
  })
})