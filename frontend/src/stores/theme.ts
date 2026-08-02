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
  let themeSwitchFrame: number | null = null

  const isDark = computed(() => mode.value === 'dark' || (mode.value === 'system' && systemPrefersDark.value))

  function releaseThemeSwitchGuard() {
    if (typeof document !== 'undefined') {
      document.documentElement.classList.remove('theme-switching')
    }
    themeSwitchFrame = null
  }

  function startThemeSwitchGuard() {
    if (typeof document === 'undefined') return

    const root = document.documentElement
    root.classList.add('theme-switching')

    if (typeof window === 'undefined') {
      releaseThemeSwitchGuard()
      return
    }

    if (typeof window.requestAnimationFrame !== 'function') {
      window.setTimeout(releaseThemeSwitchGuard, 32)
      return
    }

    if (themeSwitchFrame !== null && typeof window.cancelAnimationFrame === 'function') {
      window.cancelAnimationFrame(themeSwitchFrame)
    }

    // Keep the guard through one painted frame so the new palette is applied
    // immediately, without animating every card's color/border transition.
    themeSwitchFrame = window.requestAnimationFrame(() => {
      themeSwitchFrame = window.requestAnimationFrame(releaseThemeSwitchGuard)
    })
  }

  function applyTheme(withSwitchGuard = false) {
    if (typeof document === 'undefined') return

    if (withSwitchGuard) startThemeSwitchGuard()

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
    if (
      themeSwitchFrame !== null
      && typeof window !== 'undefined'
      && typeof window.cancelAnimationFrame === 'function'
    ) {
      window.cancelAnimationFrame(themeSwitchFrame)
    }
    releaseThemeSwitchGuard()

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
    applyTheme(true)
  }

  const MODE_CYCLE: Record<ThemeMode, ThemeMode> = {
    light: 'dark',
    dark: 'system',
    system: 'light',
  }

  function toggle() {
    setMode(MODE_CYCLE[mode.value])
  }

  return { mode, systemPrefersDark, isDark, init, dispose, setMode, toggle }
})
