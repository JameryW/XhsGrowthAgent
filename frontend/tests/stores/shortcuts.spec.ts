// frontend/tests/stores/shortcuts.spec.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useShortcutsStore, SHORTCUTS } from '@/stores/shortcuts'

describe('shortcuts store', () => {
  beforeEach(() => {
    // Create a fresh Pinia instance for each test
    setActivePinia(createPinia())
  })

  describe('initial state', () => {
    it('has correct default values', () => {
      const store = useShortcutsStore()

      expect(store.showPanel).toBe(false)
      expect(store.activeShortcuts).toEqual([])
      expect(store.chordMode).toBe(false)
      expect(store.chordPrefix).toBe(null)
      expect(store.currentRoute).toBe('dashboard')
    })

    it('exposes SHORTCUTS constant', () => {
      expect(SHORTCUTS).toBeDefined()
      expect(SHORTCUTS.length).toBeGreaterThan(0)
    })
  })

  describe('showShortcutsPanel', () => {
    it('sets showPanel to true', () => {
      const store = useShortcutsStore()

      store.showShortcutsPanel()

      expect(store.showPanel).toBe(true)
    })

    it('sets activeShortcuts to available shortcuts', () => {
      const store = useShortcutsStore()

      store.showShortcutsPanel()

      expect(store.activeShortcuts.length).toBeGreaterThan(0)
    })
  })

  describe('hideShortcutsPanel', () => {
    it('sets showPanel to false', () => {
      const store = useShortcutsStore()
      store.showShortcutsPanel()

      store.hideShortcutsPanel()

      expect(store.showPanel).toBe(false)
    })

    it('clears activeShortcuts', () => {
      const store = useShortcutsStore()
      store.showShortcutsPanel()

      store.hideShortcutsPanel()

      expect(store.activeShortcuts).toEqual([])
    })
  })

  describe('togglePanel', () => {
    it('shows panel when hidden', () => {
      const store = useShortcutsStore()
      store.showPanel = false

      store.togglePanel()

      expect(store.showPanel).toBe(true)
    })

    it('hides panel when shown', () => {
      const store = useShortcutsStore()
      store.showShortcutsPanel()

      store.togglePanel()

      expect(store.showPanel).toBe(false)
    })
  })

  describe('executeShortcut', () => {
    it('adds action to activeShortcuts', () => {
      const store = useShortcutsStore()

      store.executeShortcut('open_command_palette')

      expect(store.activeShortcuts).toContain('open_command_palette')
    })

    it('enters chord mode when starting chord', () => {
      const store = useShortcutsStore()

      store.executeShortcut('start_chord')

      expect(store.chordMode).toBe(true)
      expect(store.chordPrefix).toBe('g')
    })

    it('exits chord mode after completing navigation', () => {
      const store = useShortcutsStore()
      store.chordMode = true
      store.chordPrefix = 'g'

      store.executeShortcut('navigate_home')

      expect(store.chordMode).toBe(false)
      expect(store.chordPrefix).toBe(null)
    })

    it('exits chord mode after navigate_dashboard', () => {
      const store = useShortcutsStore()
      store.chordMode = true
      store.chordPrefix = 'g'

      store.executeShortcut('navigate_dashboard')

      expect(store.chordMode).toBe(false)
      expect(store.chordPrefix).toBe(null)
    })
  })

  describe('setCurrentRoute', () => {
    it('updates currentRoute', () => {
      const store = useShortcutsStore()

      store.setCurrentRoute('review')

      expect(store.currentRoute).toBe('review')
    })
  })

  describe('resetChordMode', () => {
    it('clears chord mode state', () => {
      const store = useShortcutsStore()
      store.chordMode = true
      store.chordPrefix = 'g'

      store.resetChordMode()

      expect(store.chordMode).toBe(false)
      expect(store.chordPrefix).toBe(null)
    })
  })

  describe('availableShortcuts computed', () => {
    it('returns shortcuts for current page', () => {
      const store = useShortcutsStore()
      store.setCurrentRoute('dashboard')

      const shortcuts = store.availableShortcuts

      // Should include global shortcuts
      expect(shortcuts.some(s => s.action === 'open_command_palette')).toBe(true)
      // Should include dashboard-specific shortcuts
      expect(shortcuts.some(s => s.action === 'navigate_review')).toBe(true)
    })

    it('filters shortcuts by page', () => {
      const store = useShortcutsStore()
      store.setCurrentRoute('analytics')

      const shortcuts = store.availableShortcuts

      // Should include analytics-specific shortcuts
      expect(shortcuts.some(s => s.action === 'navigate_review')).toBe(true)
      // Should NOT include dashboard-specific shortcuts
      expect(shortcuts.some(s => s.action === 'r' && s.pages?.includes('dashboard'))).toBe(false)
    })

    it('returns chord shortcuts when in chord mode', () => {
      const store = useShortcutsStore()
      store.chordMode = true
      store.chordPrefix = 'g'

      const shortcuts = store.availableShortcuts

      // Should only return chord shortcuts
      expect(shortcuts.every(s => s.pages?.includes('chord_g'))).toBe(true)
      expect(shortcuts.some(s => s.action === 'navigate_home')).toBe(true)
      expect(shortcuts.some(s => s.action === 'navigate_dashboard')).toBe(true)
    })

    it('returns global shortcuts on all pages', () => {
      const store = useShortcutsStore()
      store.setCurrentRoute('review')

      const shortcuts = store.availableShortcuts

      // Global shortcuts (no pages specified) should be available everywhere
      expect(shortcuts.some(s => !s.pages)).toBe(true)
    })
  })

  describe('getShortcutByAction', () => {
    it('returns shortcut for valid action', () => {
      const store = useShortcutsStore()

      const shortcut = store.getShortcutByAction('open_command_palette')

      expect(shortcut).toBeDefined()
      expect(shortcut?.action).toBe('open_command_palette')
      expect(shortcut?.key).toBe('k')
      expect(shortcut?.ctrl).toBe(true)
    })

    it('returns undefined for invalid action', () => {
      const store = useShortcutsStore()

      const shortcut = store.getShortcutByAction('invalid_action')

      expect(shortcut).toBeUndefined()
    })
  })

  describe('isShortcutAvailable', () => {
    it('returns true for available shortcut', () => {
      const store = useShortcutsStore()
      store.setCurrentRoute('dashboard')

      expect(store.isShortcutAvailable('open_command_palette')).toBe(true)
    })

    it('returns false for unavailable shortcut', () => {
      const store = useShortcutsStore()
      store.setCurrentRoute('analytics')

      // 'r' shortcut for review is only available on dashboard
      expect(store.isShortcutAvailable('r')).toBe(false)
    })

    it('returns true for global shortcuts on any page', () => {
      const store = useShortcutsStore()
      store.setCurrentRoute('review')

      expect(store.isShortcutAvailable('open_command_palette')).toBe(true)
    })
  })

  describe('SHORTCUTS configuration', () => {
    it('includes Ctrl+K shortcut', () => {
      const ctrlK = SHORTCUTS.find(s => s.key === 'k' && s.ctrl)
      expect(ctrlK).toBeDefined()
      expect(ctrlK?.description).toBe('Open command palette')
    })

    it('includes Ctrl+R shortcut', () => {
      const ctrlR = SHORTCUTS.find(s => s.key === 'r' && s.ctrl)
      expect(ctrlR).toBeDefined()
      expect(ctrlR?.description).toBe('Refresh workflow')
    })

    it('includes Escape shortcut', () => {
      const escape = SHORTCUTS.find(s => s.key === 'Escape')
      expect(escape).toBeDefined()
      expect(escape?.description).toBe('Close panel/modal')
    })

    it('includes Shift+? shortcut', () => {
      const help = SHORTCUTS.find(s => s.key === '?' && s.shift)
      expect(help).toBeDefined()
      expect(help?.description).toBe('Show shortcuts help')
    })

    it('includes navigation shortcuts', () => {
      const a = SHORTCUTS.find(s => s.key === 'a')
      expect(a).toBeDefined()
      expect(a?.action).toBe('navigate_analytics')

      const p = SHORTCUTS.find(s => s.key === 'p')
      expect(p).toBeDefined()
      expect(p?.action).toBe('navigate_review')
    })

    it('includes chord shortcuts (G + H/D)', () => {
      const g = SHORTCUTS.find(s => s.key === 'g')
      expect(g).toBeDefined()
      expect(g?.action).toBe('start_chord')

      const h = SHORTCUTS.find(s => s.key === 'h')
      expect(h).toBeDefined()
      expect(h?.pages?.includes('chord_g')).toBe(true)

      const d = SHORTCUTS.find(s => s.key === 'd')
      expect(d).toBeDefined()
      expect(d?.pages?.includes('chord_g')).toBe(true)
    })
  })
})