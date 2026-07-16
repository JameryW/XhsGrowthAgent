import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'xhs-theme-mode'

function readStoredMode(): ThemeMode {
  if (typeof window === 'undefined') return 'system'

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // Storage can be unavailable in private browsing or restricted iframes.
  }

  return 'system'
}

function prefersDark(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)').matches
    : false
}

export const useThemeStore = defineStore('theme', () => {
  const mode = ref<ThemeMode>(readStoredMode())
  const systemPrefersDark = ref(prefersDark())
  let mediaQuery: MediaQueryList | null = null
  let initialized = false

  const isDark = computed(() => mode.value === 'dark' || (mode.value === 'system' && systemPrefersDark.value))

  function applyTheme() {
    if (typeof document === 'undefined') return

    const root = document.documentElement
    root.classList.toggle('dark', isDark.value)
    root.dataset.theme = isDark.value ? 'dark' : 'light'
    root.style.colorScheme = isDark.value ? 'dark' : 'light'
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', isDark.value ? '#0b1120' : '#f43f5e')
  }

  const handleSystemThemeChange = (event: MediaQueryListEvent) => {
    systemPrefersDark.value = event.matches
    if (mode.value === 'system') applyTheme()
  }

  function init() {
    applyTheme()
    if (initialized || typeof window === 'undefined' || typeof window.matchMedia !== 'function') return

    initialized = true
    mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    systemPrefersDark.value = mediaQuery.matches
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handleSystemThemeChange)
    } else {
      mediaQuery.addListener(handleSystemThemeChange)
    }
    applyTheme()
  }

  function dispose() {
    if (!mediaQuery) return
    if (typeof mediaQuery.removeEventListener === 'function') {
      mediaQuery.removeEventListener('change', handleSystemThemeChange)
    } else {
      mediaQuery.removeListener(handleSystemThemeChange)
    }
    mediaQuery = null
    initialized = false
  }

  function setMode(nextMode: ThemeMode) {
    mode.value = nextMode
    try {
      window.localStorage.setItem(STORAGE_KEY, nextMode)
    } catch {
      // Keep the in-memory preference when persistent storage is unavailable.
    }
    applyTheme()
  }

  function toggle() {
    setMode(isDark.value ? 'light' : 'dark')
  }

  return { mode, systemPrefersDark, isDark, init, dispose, setMode, toggle }
})
