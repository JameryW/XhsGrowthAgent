import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import XhsAccountsPanel from '@/components/settings/XhsAccountsPanel.vue'
import { useAccountsStore } from '@/stores/accounts'
import { syncAllCreatorStats } from '@/api/analytics'
import type { Account } from '@/api/accounts'

const toastMock = {
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}

vi.mock('@/stores/toast', () => ({ useToastStore: () => toastMock }))

vi.mock('@/api/accounts', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/accounts')>()
  return {
    ...actual,
    getAccountLoginStatus: vi.fn().mockRejectedValue(new Error('offline')),
  }
})

vi.mock('@/api/analytics', () => ({
  syncAllCreatorStats: vi.fn(),
}))

const mockedSyncAll = vi.mocked(syncAllCreatorStats)

function account(partial: Partial<Account> = {}): Account {
  return {
    id: 'acc-1',
    name: '测试账号',
    is_active: true,
    created_at: '2026-07-13T00:00:00Z',
    ...partial,
  }
}

function mountPanel() {
  return mount(XhsAccountsPanel, {
    global: {
      stubs: {
        AppIcon: true,
        NeonButton: {
          props: ['loading', 'disabled'],
          template: '<button :disabled="disabled"><slot /></button>',
        },
        CreatorStatsPanel: true,
        QrLoginModal: true,
        ConfirmModal: true,
      },
    },
  })
}

function syncNowButton(wrapper: ReturnType<typeof mountPanel>) {
  return wrapper.findAll('button').find(b => b.text().includes('立即同步'))
}

describe('XhsAccountsPanel 手动同步入口', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    const store = useAccountsStore()
    vi.spyOn(store, 'fetchAccounts').mockResolvedValue(undefined)
  })

  it('点击"立即同步"调用 sync-all 并在成功后提示', async () => {
    const store = useAccountsStore()
    store.accounts = [account()]
    mockedSyncAll.mockResolvedValue({
      ok: true,
      status: 'completed',
      active_accounts: 1,
      succeeded: 1,
      failed: 0,
      results: [],
    })

    const wrapper = mountPanel()
    await flushPromises()

    const button = syncNowButton(wrapper)
    expect(button).toBeTruthy()
    expect(button!.attributes('disabled')).toBeUndefined()
    await button!.trigger('click')
    await flushPromises()

    expect(mockedSyncAll).toHaveBeenCalledWith({ period: '30d', analyze: true })
    expect(toastMock.success).toHaveBeenCalledOnce()
    expect(toastMock.error).not.toHaveBeenCalled()
  })

  it('冷却期内提示稍后再试，不当作失败', async () => {
    const store = useAccountsStore()
    store.accounts = [account()]
    mockedSyncAll.mockResolvedValue({
      ok: false,
      status: 'cooldown',
      active_accounts: 0,
      succeeded: 0,
      failed: 0,
      results: [],
      retry_after_seconds: 1700,
    })

    const wrapper = mountPanel()
    await flushPromises()
    await syncNowButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(toastMock.warning).toHaveBeenCalledOnce()
    expect(toastMock.success).not.toHaveBeenCalled()
    expect(toastMock.error).not.toHaveBeenCalled()
  })

  it('已有任务进行中时给出提示', async () => {
    const store = useAccountsStore()
    store.accounts = [account()]
    mockedSyncAll.mockResolvedValue({
      ok: false,
      status: 'already_running',
      active_accounts: 0,
      succeeded: 0,
      failed: 0,
      results: [],
    })

    const wrapper = mountPanel()
    await flushPromises()
    await syncNowButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(toastMock.warning).toHaveBeenCalledOnce()
    expect(toastMock.error).not.toHaveBeenCalled()
  })

  it('没有激活账号时按钮禁用', async () => {
    const store = useAccountsStore()
    store.accounts = [account({ is_active: false })]

    const wrapper = mountPanel()
    await flushPromises()

    expect(syncNowButton(wrapper)!.attributes('disabled')).toBeDefined()
    expect(mockedSyncAll).not.toHaveBeenCalled()
  })
})
