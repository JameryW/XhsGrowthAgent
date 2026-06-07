// frontend/src/composables/useShortcuts.ts
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useShortcutsStore, SHORTCUTS } from '@/stores/shortcuts'
import type { ShortcutDefinition } from '@/stores/shortcuts'

/**
 * Shortcuts map for quick lookup by key combination
 */
export const SHORTCUTS_MAP: Record<string, ShortcutDefinition> = {}

// Build shortcuts map
SHORTCUTS.forEach(shortcut => {
  const key = buildShortcutKey(shortcut)
  SHORTCUTS_MAP[key] = shortcut
})

/**
 * Build a unique key string for a shortcut
 * Exported for testing and external use
 */
export function buildShortcutKey(shortcut: ShortcutDefinition): string {
  const parts: string[] = []
  if (shortcut.ctrl) parts.push('Ctrl')
  if (shortcut.shift) parts.push('Shift')
  if (shortcut.alt) parts.push('Alt')
  parts.push(shortcut.key)
  return parts.join('+')
}

/**
 * Parse a keyboard event into a shortcut key string
 * Exported for testing and external use
 */
export function parseKeyEvent(event: KeyboardEvent): string {
  const parts: string[] = []
  if (event.ctrlKey || event.metaKey) parts.push('Ctrl')
  if (event.shiftKey) parts.push('Shift')
  if (event.altKey) parts.push('Alt')
  parts.push(event.key)
  return parts.join('+')
}

/**
 * Check if a shortcut is valid for the current page
 */
function isShortcutValidForPage(shortcut: ShortcutDefinition, currentRoute: string): boolean {
  // Global shortcuts (no pages specified) are valid everywhere
  if (!shortcut.pages) return true

  // Check if shortcut's pages include current route
  return shortcut.pages.includes(currentRoute)
}

/**
 * Composable for keyboard shortcuts functionality
 */
export function useShortcuts() {
  const store = useShortcutsStore()
  const listenersActive = ref(false)
  const lastKeyPressed = ref<string | null>(null)

  // Computed
  const activeShortcutsForPage = computed(() => {
    return SHORTCUTS.filter(s => isShortcutValidForPage(s, store.currentRoute))
  })

  /**
   * Handle keyboard press event
   */
  function handleKeyPress(event: KeyboardEvent): void {
    // Skip shortcuts when typing in input/textarea/contenteditable
    const target = event.target as HTMLElement
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
      return
    }

    const keyString = parseKeyEvent(event)
    lastKeyPressed.value = keyString

    // Look up shortcut
    const shortcut = SHORTCUTS_MAP[keyString]

    if (!shortcut) {
      // No matching shortcut
      return
    }

    // Check if shortcut is valid for current page
    if (!isShortcutValidForPage(shortcut, store.currentRoute)) {
      return
    }

    // Prevent default browser behavior for shortcuts
    event.preventDefault()

    // Execute the shortcut action
    store.executeShortcut(shortcut.action)

    // Trigger action handler
    handleShortcutAction(shortcut.action)
  }

  /**
   * Handle shortcut action (navigation, commands, etc.)
   */
  function handleShortcutAction(action: string): void {
    switch (action) {
      case 'open_command_palette':
        store.showShortcutsPanel()
        break
      case 'close_panel':
        store.hideShortcutsPanel()
        store.resetChordMode()
        break
      case 'show_shortcuts':
        store.togglePanel()
        break
      case 'refresh_workflow':
        // This would call workflow store's refreshStatus
        // Will be connected when integrated
        break
      case 'navigate_analytics':
        // Navigation would be handled by router
        // Will be connected when integrated
        break
      case 'navigate_review':
        // Navigation would be handled by router
        break
      case 'navigate_home':
        // Navigation would be handled by router
        store.resetChordMode()
        break
      case 'navigate_dashboard':
        // Navigation would be handled by router
        store.resetChordMode()
        break
      case 'start_chord':
        // Already handled by store.executeShortcut
        break
    }
  }

  /**
   * Setup keyboard listeners
   */
  function setupKeyboardListeners(): void {
    if (listenersActive.value) return

    window.addEventListener('keydown', handleKeyPress)
    listenersActive.value = true
  }

  /**
   * Remove keyboard listeners
   */
  function removeKeyboardListeners(): void {
    if (!listenersActive.value) return

    window.removeEventListener('keydown', handleKeyPress)
    listenersActive.value = false
  }

  /**
   * Get shortcut by key combination
   */
  function getShortcutByKey(key: string): ShortcutDefinition | undefined {
    return SHORTCUTS_MAP[key]
  }

  /**
   * Get all shortcuts for a page
   */
  function getShortcutsForPage(page: string): ShortcutDefinition[] {
    return SHORTCUTS.filter(s => isShortcutValidForPage(s, page))
  }

  /**
   * Check if a key combination matches a shortcut
   */
  function isShortcut(key: string): boolean {
    return SHORTCUTS_MAP[key] !== undefined
  }

  // Auto-setup listeners on mount, cleanup on unmount
  onMounted(() => {
    setupKeyboardListeners()
  })

  onUnmounted(() => {
    removeKeyboardListeners()
  })

  return {
    // State
    listenersActive,
    lastKeyPressed,
    // Computed
    activeShortcutsForPage,
    // Actions
    setupKeyboardListeners,
    removeKeyboardListeners,
    handleKeyPress,
    handleShortcutAction,
    getShortcutByKey,
    getShortcutsForPage,
    isShortcut,
    // Constants
    SHORTCUTS_MAP,
    // Helpers
    buildShortcutKey,
    parseKeyEvent,
  }
}