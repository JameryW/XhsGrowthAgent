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

  it('persists explicit mode changes and cycles light → dark → system without a reload', () => {
    const store = useThemeStore()
    store.init()

    store.setMode('dark')
    expect(localStorage.getItem('xhs-theme-mode')).toBe('dark')
    expect(store.isDark).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    store.toggle()
    expect(store.mode).toBe('system')
    expect(store.isDark).toBe(false)
    expect(document.documentElement.classList.contains('dark')).toBe(false)

    store.toggle()
    expect(store.mode).toBe('light')

    store.toggle()
    expect(store.mode).toBe('dark')
    expect(store.isDark).toBe(true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('guards the first painted frames so a theme change does not animate every surface', () => {
    const callbacks: Array<(time: number) => void> = []
    const originalRequestAnimationFrame = window.requestAnimationFrame
    const originalCancelAnimationFrame = window.cancelAnimationFrame
    const requestAnimationFrame = vi.fn((callback: (time: number) => void) => {
      callbacks.push(callback)
      return callbacks.length
    })

    Object.defineProperty(window, 'requestAnimationFrame', {
      configurable: true,
      value: requestAnimationFrame,
    })
    Object.defineProperty(window, 'cancelAnimationFrame', {
      configurable: true,
      value: vi.fn(),
    })

    try {
      const store = useThemeStore()
      store.setMode('dark')

      expect(document.documentElement.classList.contains('theme-switching')).toBe(true)
      expect(requestAnimationFrame).toHaveBeenCalledTimes(1)

      callbacks.shift()?.(0)
      expect(document.documentElement.classList.contains('theme-switching')).toBe(true)
      expect(requestAnimationFrame).toHaveBeenCalledTimes(2)

      callbacks.shift()?.(0)
      expect(document.documentElement.classList.contains('theme-switching')).toBe(false)
    } finally {
      Object.defineProperty(window, 'requestAnimationFrame', {
        configurable: true,
        value: originalRequestAnimationFrame,
      })
      Object.defineProperty(window, 'cancelAnimationFrame', {
        configurable: true,
        value: originalCancelAnimationFrame,
      })
    }
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
