// frontend/src/stores/shortcuts.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

/**
 * Shortcut definition
 */
export interface ShortcutDefinition {
  key: string
  ctrl?: boolean
  shift?: boolean
  alt?: boolean
  description: string
  action: string // Action identifier
  pages?: string[] // Pages where this shortcut is active (empty = all pages)
}

/**
 * Shortcuts configuration
 */
export const SHORTCUTS: ShortcutDefinition[] = [
  // Global shortcuts
  { key: 'k', ctrl: true, description: 'Open command palette', action: 'open_command_palette' },
  { key: 'r', ctrl: true, description: 'Refresh workflow', action: 'refresh_workflow' },
  { key: 'Escape', description: 'Close panel/modal', action: 'close_panel' },
  { key: '?', shift: true, description: 'Show shortcuts help', action: 'show_shortcuts' },

  // Navigation shortcuts
  { key: 'a', description: 'Go to analytics', action: 'navigate_analytics', pages: ['dashboard', 'review'] },
  { key: 'p', description: 'Go to review/publish', action: 'navigate_review', pages: ['dashboard', 'analytics'] },
  { key: 'r', description: 'Go to review page', action: 'navigate_review', pages: ['dashboard'] },

  // Chord shortcuts (G + key)
  { key: 'g', description: 'Start chord navigation', action: 'start_chord' },
  { key: 'h', description: 'Go to home (after G)', action: 'navigate_home', pages: ['chord_g'] },
  { key: 'd', description: 'Go to dashboard (after G)', action: 'navigate_dashboard', pages: ['chord_g'] },
]

/**
 * Shortcuts store for managing keyboard shortcuts and panel state
 */
export const useShortcutsStore = defineStore('shortcuts', () => {
  // State
  const showPanel = ref(false)
  const activeShortcuts = ref<string[]>([])
  const chordMode = ref(false)
  const chordPrefix = ref<string | null>(null)
  const currentRoute = ref<string>('dashboard')

  // Computed
  const availableShortcuts = computed(() => {
    if (chordMode.value) {
      // In chord mode, only show shortcuts for the current chord
      return SHORTCUTS.filter(s => s.pages?.includes(`chord_${chordPrefix.value}`))
    }
    // Show shortcuts for current page or global shortcuts (no pages specified)
    return SHORTCUTS.filter(s => !s.pages || s.pages.includes(currentRoute.value))
  })

  // Actions
  /**
   * Show the shortcuts panel
   */
  function showShortcutsPanel(): void {
    showPanel.value = true
    activeShortcuts.value = availableShortcuts.value.map(s => s.action)
  }

  /**
   * Hide the shortcuts panel
   */
  function hideShortcutsPanel(): void {
    showPanel.value = false
    activeShortcuts.value = []
  }

  /**
   * Toggle the shortcuts panel
   */
  function togglePanel(): void {
    if (showPanel.value) {
      hideShortcutsPanel()
    } else {
      showShortcutsPanel()
    }
  }

  /**
   * Execute a shortcut action
   */
  function executeShortcut(action: string): void {
    // This will be connected to actual actions via the composable
    activeShortcuts.value = [...activeShortcuts.value, action]

    // Handle chord mode
    if (action === 'start_chord') {
      chordMode.value = true
      chordPrefix.value = 'g'
    } else if (chordMode.value && ['navigate_home', 'navigate_dashboard'].includes(action)) {
      // Complete chord navigation
      chordMode.value = false
      chordPrefix.value = null
    }
  }

  /**
   * Set the current route
   */
  function setCurrentRoute(route: string): void {
    currentRoute.value = route
  }

  /**
   * Reset chord mode
   */
  function resetChordMode(): void {
    chordMode.value = false
    chordPrefix.value = null
  }

  /**
   * Get shortcut by action
   */
  function getShortcutByAction(action: string): ShortcutDefinition | undefined {
    return SHORTCUTS.find(s => s.action === action)
  }

  /**
   * Check if a shortcut is available on current page
   */
  function isShortcutAvailable(action: string): boolean {
    return availableShortcuts.value.some(s => s.action === action)
  }

  return {
    // State
    showPanel,
    activeShortcuts,
    chordMode,
    chordPrefix,
    currentRoute,
    // Computed
    availableShortcuts,
    // Actions
    showShortcutsPanel,
    hideShortcutsPanel,
    togglePanel,
    executeShortcut,
    setCurrentRoute,
    resetChordMode,
    getShortcutByAction,
    isShortcutAvailable,
    // Constants
    SHORTCUTS,
  }
})