import { describe, expect, it, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useThemeStore } from '@/stores/theme'

describe('ThemeToggle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    document.documentElement.className = ''
  })

  it('exposes a localized accessible label and cycles light → dark → system', async () => {
    const wrapper = mount(ThemeToggle)
    const store = useThemeStore()

    // Default mode is system.
    expect(store.mode).toBe('system')
    expect(wrapper.attributes('aria-label')).toBe('跟随系统')

    await wrapper.trigger('click')
    expect(store.mode).toBe('light')
    expect(wrapper.attributes('aria-label')).toBe('浅色模式')

    await wrapper.trigger('click')
    expect(store.mode).toBe('dark')
    expect(wrapper.attributes('aria-label')).toBe('暗黑模式')

    await wrapper.trigger('click')
    expect(store.mode).toBe('system')
    expect(wrapper.attributes('aria-label')).toBe('跟随系统')
    expect(wrapper.find('svg').exists()).toBe(true)
  })
})
