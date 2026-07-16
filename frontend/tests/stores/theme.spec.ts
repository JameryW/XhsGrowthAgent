import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useThemeStore } from '@/stores/theme'

type MediaQueryStub = {
  matches: boolean
  listener?: (event: MediaQueryListEvent) => void
}

let mediaQuery: MediaQueryStub

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.documentElement.className = ''
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.style.colorScheme = ''
  mediaQuery = { matches: false }
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: vi.fn(() => ({
      get matches() { return mediaQuery.matches },
      media: '(prefers-color-scheme: dark)',
      addEventListener: (_event: string, listener: (event: MediaQueryListEvent) => void) => { mediaQuery.listener = listener },
      removeEventListener: vi.fn(),
      addListener: (_listener: (event: MediaQueryListEvent) => void) => undefined,
      removeListener: vi.fn(),
    })),
  })
})

afterEach(() => {
  document.documentElement.className = ''
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.style.colorScheme = ''
})

describe('useThemeStore', () => {
  it('follows the system preference by default and applies root metadata', () => {
    mediaQuery.matches = true
    const store = useThemeStore()

    expect(store.mode).toBe('system')
    store.init()

    expect(store.isDark).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(document.documentElement.style.colorScheme).toBe('dark')
  })

  it('persists explicit mode changes and toggles without a reload', () => {
    const store = useThemeStore()
    store.init()

    store.setMode('dark')
    expect(localStorage.getItem('xhs-theme-mode')).toBe('dark')
    expect(store.isDark).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    store.toggle()
    expect(store.mode).toBe('light')
    expect(store.isDark).toBe(false)
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('responds to system theme changes while in system mode', () => {
    const store = useThemeStore()
    store.init()

    expect(store.isDark).toBe(false)
    mediaQuery.matches = true
    mediaQuery.listener?.({ matches: true } as MediaQueryListEvent)

    expect(store.isDark).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})
