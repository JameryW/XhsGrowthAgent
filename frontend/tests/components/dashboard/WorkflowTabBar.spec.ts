import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorkflowTabBar from '@/components/dashboard/WorkflowTabBar.vue'
import i18n, { loadLocaleMessages } from '@/locales'

const tab = {
  threadId: 'thread-1',
  label: '今日选题',
  status: 'running' as const,
  phase: 'creating' as const,
  progress: 40,
}

function mountTabBar(overrides: Record<string, unknown> = {}) {
  return mount(WorkflowTabBar, {
    props: {
      tabs: [tab],
      activeThreadId: tab.threadId,
      hasOverflow: false,
      overflowTabs: [],
      ...overrides,
    },
    global: {
      plugins: [i18n],
      stubs: {
        AppIcon: { template: '<span />' },
        Teleport: { template: '<div><slot /></div>' },
      },
    },
  })
}

describe('WorkflowTabBar', () => {
  const originalLocale = i18n.global.locale.value

  beforeEach(() => {
    i18n.global.locale.value = 'zh-CN'
  })

  afterEach(() => {
    i18n.global.locale.value = originalLocale
  })

  it('keeps close and rename controls discoverable at touch size', async () => {
    const wrapper = mountTabBar()

    const close = wrapper.find('.tab-close')
    const rename = wrapper.find('.tab-rename')
    expect(close.classes()).toContain('min-h-11')
    expect(close.classes()).toContain('min-w-[44px]')
    expect(rename.classes()).toContain('min-h-11')
    expect(rename.classes()).toContain('min-w-[44px]')
    expect(rename.attributes('aria-label')).toBe(i18n.global.t('dashboard.tabBar.rename'))

    await rename.trigger('click')
    const input = wrapper.find('.tab-edit-input')
    expect(input.exists()).toBe(true)
    expect(input.attributes('aria-label')).toBe(i18n.global.t('dashboard.tabBar.renameEditing'))

    await input.setValue('新的工作流')
    await input.trigger('keydown.enter')
    expect(wrapper.emitted('rename')).toEqual([['thread-1', '新的工作流']])
  })

  it('offers the same rename entry from the overflow menu', async () => {
    const overflowTab = { ...tab, threadId: 'thread-2', label: '另一个工作流' }
    const wrapper = mountTabBar({
      hasOverflow: true,
      overflowTabs: [overflowTab],
    })

    await wrapper.find('.tab-overflow-trigger').trigger('click')
    const rename = wrapper.find('.overflow-dropdown .tab-rename')
    expect(rename.exists()).toBe(true)
    await rename.trigger('click')

    const input = wrapper.find('.overflow-dropdown .tab-edit-input')
    await input.setValue('重命名后的工作流')
    await input.trigger('keydown.enter')
    expect(wrapper.emitted('rename')).toEqual([['thread-2', '重命名后的工作流']])
  })

  it('uses the English labels for the touch rename entry', async () => {
    await loadLocaleMessages('en')
    i18n.global.locale.value = 'en'
    const wrapper = mountTabBar()

    expect(wrapper.find('.tab-rename').attributes('aria-label')).toBe('Rename workflow tab')
    expect(wrapper.find('[role="tablist"]').attributes('aria-label')).toBe('Workflow tabs')
  })
})
