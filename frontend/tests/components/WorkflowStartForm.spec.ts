import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WorkflowStartForm from '@/components/WorkflowStartForm.vue'
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

function account(id: string, name: string, niche: string, isActive = false): Account {
  return {
    id,
    name,
    niche,
    is_active: isActive,
    created_at: '2026-07-13T00:00:00Z',
  }
}

describe('WorkflowStartForm account niche defaults', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountWithAccounts(accounts: Account[], active: Account | null, initialNiche?: string) {
    mockedListAccounts.mockResolvedValue(accounts)
    mockedGetActiveAccount.mockResolvedValue(active)
    const wrapper = mount(WorkflowStartForm, {
      props: { initialNiche },
    })
    await flushPromises()
    return wrapper
  }

  it('uses the active account bound niche by default', async () => {
    const active = account('beauty', '美妆账号', '美妆', true)
    const wrapper = await mountWithAccounts([active], active)

    expect((wrapper.vm as any).getConfig()).toMatchObject({
      accountId: 'beauty',
      niche: '美妆',
    })
    expect(wrapper.text()).toContain('已自动使用账号绑定赛道：美妆')
  })

  it('changes the default niche with the selected account until the user chooses manually', async () => {
    const beauty = account('beauty', '美妆账号', '美妆', true)
    const tech = account('tech', '数码账号', '数码')
    const wrapper = await mountWithAccounts([beauty, tech], beauty)

    await wrapper.find('select').setValue('tech')
    expect((wrapper.vm as any).getConfig().niche).toBe('数码')

    const foodButton = wrapper.findAll('button').find((button) => button.text().includes('美食'))
    expect(foodButton).toBeDefined()
    await foodButton!.trigger('click')
    await wrapper.find('select').setValue('beauty')

    expect((wrapper.vm as any).getConfig().niche).toBe('美食')
  })

  it('keeps an explicit route niche ahead of the bound account default', async () => {
    const active = account('beauty', '美妆账号', '美妆', true)
    const wrapper = await mountWithAccounts([active], active, '旅行')

    expect((wrapper.vm as any).getConfig().niche).toBe('旅行')
  })
})
