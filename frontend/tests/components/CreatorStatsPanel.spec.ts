import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CreatorStatsPanel from '@/components/settings/CreatorStatsPanel.vue'
import { useAccountsStore } from '@/stores/accounts'
import type { Account } from '@/api/accounts'
import { getCreatorStats, getCreatorSuggestions } from '@/api/analytics'

vi.mock('@/api/accounts', () => ({
  KNOWN_NICHES: [],
  resolveAccountNiche: vi.fn(),
}))

vi.mock('@/api/analytics', () => ({
  syncCreatorStats: vi.fn(),
  getCreatorStats: vi.fn(),
  getCreatorSuggestions: vi.fn(),
}))

const mockedGetCreatorStats = vi.mocked(getCreatorStats)
const mockedGetCreatorSuggestions = vi.mocked(getCreatorSuggestions)

function account(name: string): Account {
  return {
    id: 'account-1',
    name,
    is_active: true,
    created_at: '2026-07-13T00:00:00Z',
  }
}

describe('CreatorStatsPanel imported display name sync', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockedGetCreatorStats.mockResolvedValue({
      account: { creator_name: '真实导入昵称' },
      notes: [],
      total: 0,
    } as any)
    mockedGetCreatorSuggestions.mockResolvedValue({ suggestions: [] } as any)
  })

  it('updates the shared account label from the imported creator profile', async () => {
    const accountsStore = useAccountsStore()
    accountsStore.accounts = [account('旧账号名称')]
    accountsStore.activeAccount = accountsStore.accounts[0]

    mount(CreatorStatsPanel, {
      props: { accountId: 'account-1', accountName: '旧账号名称' },
      global: {
        stubs: {
          AppIcon: true,
          NeonButton: { template: '<button><slot /></button>' },
        },
      },
    })
    await flushPromises()

    expect(accountsStore.accounts[0].name).toBe('真实导入昵称')
    expect(accountsStore.activeAccount?.name).toBe('真实导入昵称')
  })

  it('renders imported audience distributions and per-note source coverage', async () => {
    mockedGetCreatorStats.mockResolvedValue({
      account: {
        creator_name: '真实导入昵称',
        audience_sources: [{ title: '首页推荐', value: 80 }],
        audience_view_periods: [{ start_point: '20:00', end_point: '21:00', count: 12 }],
        audience_profile: [{ title: '女性', value: 0.7 }],
      },
      notes: [{ note_id: 'n1', title: '测试笔记', views: 10, likes: 2, comments: 1, engagement_rate: 0.3, view_sources: [{ title: '搜索' }] }],
      total: 1,
      audience_analysis: {
        source_distribution: [{ title: '首页推荐', value: 80 }],
        peak_view_periods: [{ start_point: '20:00', end_point: '21:00', count: 12 }],
        audience_profile: [{ title: '女性', value: 0.7 }],
        coverage: { sources: true, periods: true, profile: true, notes_with_view_sources: 1 },
        insights: ['主要观看来源：首页推荐（80）'],
      },
    } as any)
    const wrapper = mount(CreatorStatsPanel, {
      props: { accountId: 'account-1' },
      global: {
        stubs: {
          AppIcon: true,
          NeonButton: { template: '<button><slot /></button>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('首页推荐')
    expect(wrapper.text()).toContain('20:00')
    expect(wrapper.text()).toContain('女性')
    expect(wrapper.text()).toContain('主要观看来源：首页推荐（80）')
  })
})
