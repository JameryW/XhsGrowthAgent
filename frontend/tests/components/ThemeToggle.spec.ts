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

  it('exposes a localized accessible label and switches the theme', async () => {
    const wrapper = mount(ThemeToggle)

    expect(wrapper.attributes('aria-label')).toBe('切换到暗黑模式')
    await wrapper.trigger('click')

    const store = useThemeStore()
    expect(store.mode).toBe('dark')
    expect(wrapper.attributes('aria-label')).toBe('切换到浅色模式')
    expect(wrapper.find('svg').exists()).toBe(true)
  })
})
