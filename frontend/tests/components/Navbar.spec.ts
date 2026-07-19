import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import Navbar from '@/components/Navbar.vue'
import { getActiveAccount, listAccounts } from '@/api/accounts'

const { routerPush } = vi.hoisted(() => ({ routerPush: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/dashboard/demo-thread', name: 'dashboard' }),
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/api/accounts', () => ({
  listAccounts: vi.fn(),
  getActiveAccount: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
}))

const mockedListAccounts = vi.mocked(listAccounts)
const mockedGetActiveAccount = vi.mocked(getActiveAccount)

describe('Navbar workspace navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    routerPush.mockClear()
    mockedListAccounts.mockResolvedValue([
      {
        id: 'beauty',
        name: '美妆账号',
        niche: '美妆',
        is_active: true,
        created_at: '2026-07-15T00:00:00Z',
      },
    ])
    mockedGetActiveAccount.mockResolvedValue({
      id: 'beauty',
      name: '美妆账号',
      niche: '美妆',
      is_active: true,
      created_at: '2026-07-15T00:00:00Z',
    })
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    })
  })

  it('renders grouped navigation, workspace status and active account context', async () => {
    const wrapper = mount(Navbar)
    await flushPromises()

    expect(wrapper.text()).toContain('工作区')
    expect(wrapper.text()).toContain('洞察与历史')
    expect(wrapper.text()).toContain('查看工作流进度与下一步')
    expect(wrapper.text()).toContain('美妆账号')
    expect(wrapper.find('button[aria-current="page"]').text()).toContain('工作流仪表盘')
    expect(wrapper.find('button[aria-label="账户"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-current="page"] svg').classes()).toContain('text-neon-pink')
  })

  it('keeps account management and start actions as real navigation targets', async () => {
    const wrapper = mount(Navbar)

    await wrapper.find('button[aria-label="开始创作"]').trigger('click')
    expect(routerPush).toHaveBeenCalledWith('/start')

    await wrapper.find('button[aria-label="账户"]').trigger('click')
    expect(routerPush).toHaveBeenCalledWith('/settings?tab=xhs-accounts')
  })
})
