import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AccountScopeBar from '@/components/AccountScopeBar.vue'

const chips = [
  {
    id: 'acct-a',
    name: 'Workspace Acc',
    total: 0,
    isViewing: true,
    isWorkspace: true,
  },
  {
    id: 'acct-b',
    name: 'Other Acc',
    total: 3,
    isViewing: false,
    isWorkspace: false,
  },
]

describe('AccountScopeBar', () => {
  it('renders chips with totals and workspace badge', () => {
    const wrapper = mount(AccountScopeBar, {
      props: {
        chips,
        label: 'View account',
        workspaceBadgeLabel: 'Workspace',
        tone: 'violet',
      },
    })
    expect(wrapper.text()).toContain('View account')
    expect(wrapper.text()).toContain('Workspace Acc')
    expect(wrapper.text()).toContain('Other Acc')
    expect(wrapper.text()).toContain('Workspace')
    expect(wrapper.text()).toContain('3')
  })

  it('emits select and prefetch', async () => {
    const wrapper = mount(AccountScopeBar, {
      props: {
        chips,
        label: 'View account',
        workspaceBadgeLabel: 'Workspace',
      },
    })
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBe(2)
    await buttons[1].trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual(['acct-b'])
    await buttons[1].trigger('mouseenter')
    expect(wrapper.emitted('prefetch')?.[0]).toEqual(['acct-b'])
  })

  it('hides when fewer than two chips', () => {
    const wrapper = mount(AccountScopeBar, {
      props: {
        chips: [chips[0]],
        label: 'View account',
        workspaceBadgeLabel: 'Workspace',
      },
    })
    expect(wrapper.find('[role="group"]').exists()).toBe(false)
  })

  it('selects with Enter key and announces viewing changes', async () => {
    const scrollIntoView = vi.fn()
    // jsdom lacks scrollIntoView — stub so the active-chip scroll path is covered.
    Element.prototype.scrollIntoView = scrollIntoView

    const wrapper = mount(AccountScopeBar, {
      props: {
        chips,
        label: 'View account',
        workspaceBadgeLabel: 'Workspace',
        announceTemplate: 'Viewing account {name}',
      },
      attachTo: document.body,
    })
    const other = wrapper.findAll('button')[1]
    await other.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')?.[0]).toEqual(['acct-b'])

    await wrapper.setProps({
      chips: [
        { ...chips[0], isViewing: false },
        { ...chips[1], isViewing: true },
      ],
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[aria-live="polite"]').text()).toContain('Other Acc')
    expect(scrollIntoView).toHaveBeenCalled()
    wrapper.unmount()
  })
})

describe('AccountViewNotice', () => {
  it('renders auto and viewOnly variants', async () => {
    const { default: AccountViewNotice } = await import('@/components/AccountViewNotice.vue')
    const auto = mount(AccountViewNotice, {
      props: { variant: 'auto', message: 'auto msg' },
      slots: { actions: '<button>ok</button>' },
    })
    expect(auto.text()).toContain('auto msg')
    expect(auto.find('[data-testid="account-view-notice-auto"]').exists()).toBe(true)

    const viewOnly = mount(AccountViewNotice, {
      props: { variant: 'viewOnly', message: 'view only' },
    })
    expect(viewOnly.find('[data-testid="account-view-notice-view-only"]').exists()).toBe(true)
  })
})
