import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import CreatorQualityWorkspace from '@/components/evaluation/CreatorQualityWorkspace.vue'
import type { Account } from '@/api/accounts'
import { getActiveAccount, listAccounts } from '@/api/accounts'

vi.mock('@/api/accounts', () => ({
  listAccounts: vi.fn(),
  getActiveAccount: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
}))

const mockedListAccounts = vi.mocked(listAccounts)
const mockedGetActiveAccount = vi.mocked(getActiveAccount)

function account(id: string, name: string, isActive = false): Account {
  return {
    id,
    name,
    is_active: isActive,
    created_at: '2026-07-13T00:00:00Z',
  }
}

describe('CreatorQualityWorkspace', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('defaults to the active account and exposes the historical-quality layout', async () => {
    const active = account('active', '已导入真实昵称', true)
    const other = account('other', '备用账号')
    mockedListAccounts.mockResolvedValue([other, active])
    mockedGetActiveAccount.mockResolvedValue(active)

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: { template: '<div />' } },
        { path: '/settings', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    await router.isReady()

    const wrapper = mount(CreatorQualityWorkspace, {
      global: {
        plugins: [router],
        stubs: {
          CreatorQualityPanel: {
            props: ['accountId', 'accountName'],
            template: '<div data-testid="quality-panel">{{ accountId }} / {{ accountName }}</div>',
          },
          CreatorNoteQualityPanel: {
            props: ['accountId', 'accountName'],
            template: '<div data-testid="note-quality-panel">{{ accountId }} / {{ accountName }}</div>',
          },
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('select').element.value).toBe('active')
    expect(wrapper.get('[data-testid="quality-panel"]').text()).toContain('已导入真实昵称')
    expect(wrapper.text()).toContain('历史笔记创作质量')
  })
})
