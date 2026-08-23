import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FreeDraftHistoryPanel from '@/components/history/FreeDraftHistoryPanel.vue'
import type { FreeDraftSummary } from '@/api/free'

const routerPush = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/api/free', () => ({
  listFreeDrafts: vi.fn(),
  deleteFreeDraft: vi.fn(),
}))

const draft = (overrides: Partial<FreeDraftSummary> = {}): FreeDraftSummary => ({
  draft_id: 'draft-1',
  title: '京都亲子三日',
  hashtags: ['#旅行'],
  created_at: '2026-08-21T08:00:00Z',
  updated_at: '2026-08-22T08:00:00Z',
  published: false,
  last_evaluation: null,
  ...overrides,
})

async function mountPanel(accountId: string | null = 'acct-a') {
  const wrapper = mount(FreeDraftHistoryPanel, {
    props: { accountId },
    global: {
      stubs: {
        AppIcon: true,
        NeonButton: {
          props: ['loading', 'variant', 'size'],
          template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
        },
        ConfirmModal: {
          props: ['isOpen'],
          template: '<div v-if="isOpen" data-testid="confirm-modal"><button type="button" data-testid="confirm-delete" @click="$emit(\'confirm\')">confirm</button><button type="button" @click="$emit(\'cancel\')">cancel</button></div>',
        },
      },
    },
  })
  await flushPromises()
  return wrapper
}

describe('FreeDraftHistoryPanel', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    routerPush.mockReset()
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockReset()
    vi.mocked(api.deleteFreeDraft).mockReset()
  })

  it('does not request drafts without an account and scopes a loaded list', async () => {
    const api = await import('@/api/free')
    const wrapper = await mountPanel(null)
    expect(api.listFreeDrafts).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="free-drafts-no-account"]').exists()).toBe(true)

    vi.mocked(api.listFreeDrafts).mockResolvedValue({ account_id: 'acct-a', drafts: [draft()], count: 1 })
    await wrapper.setProps({ accountId: 'acct-a' })
    await flushPromises()
    expect(api.listFreeDrafts).toHaveBeenCalledWith('acct-a', { status: 'all' }, expect.objectContaining({ suppressToast: true }))
    expect(wrapper.text()).toContain('京都亲子三日')
  })

  it('filters by title and draft state without dropping account-scoped rows', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [
        draft(),
        draft({ draft_id: 'draft-2', title: '已发布攻略', published: true, last_evaluation: { overall_score: 86, decision: 'approved' } }),
      ],
      count: 2,
    })
    const wrapper = await mountPanel()

    await wrapper.find('input[type="search"]').setValue('已发布')
    expect(wrapper.text()).toContain('已发布攻略')
    expect(wrapper.text()).not.toContain('京都亲子三日')

    await wrapper.findAll('button').find(button => button.text().includes('Published'))?.trigger('click')
    expect(wrapper.findAll('article')).toHaveLength(1)
    expect(api.listFreeDrafts).toHaveBeenCalledWith('acct-a', { status: 'all' }, expect.anything())
  })

  it('does not present degraded evaluation scores or decisions as valid', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [draft({
        last_evaluation: { overall_score: 72, decision: 'approved', degraded: true },
      })],
      count: 1,
    })

    const wrapper = await mountPanel()
    const card = wrapper.find('article')
    expect(card.text()).toContain('评估不可用')
    expect(card.text()).not.toContain('72')
    expect(card.text()).not.toContain('通过')
  })

  it('renders a retry state, opens Continue deep links, and guards deletion', async () => {
    const api = await import('@/api/free')
    let attempts = 0
    vi.mocked(api.listFreeDrafts).mockImplementation(async () => {
      attempts += 1
      if (attempts === 1) throw new Error('offline')
      return { account_id: 'acct-a', drafts: [draft()], count: 1 }
    })
    vi.mocked(api.deleteFreeDraft).mockResolvedValue({ draft_id: 'draft-1', deleted: true })
    const wrapper = await mountPanel()

    expect(wrapper.find('[data-testid="free-drafts-error"]').exists()).toBe(true)
    await wrapper.find('[data-testid="free-drafts-error"] button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('京都亲子三日')

    const continueButton = wrapper.find('article button')
    expect(continueButton.text()).not.toBe('')
    await continueButton.trigger('click')
    expect(routerPush).toHaveBeenCalledWith({
      name: 'tui',
      query: { mode: 'free', account_id: 'acct-a', draft_id: 'draft-1' },
    })

    const deleteButton = wrapper.find('article button[aria-label]')
    await deleteButton.trigger('click')
    expect(wrapper.find('[data-testid="confirm-modal"]').exists()).toBe(true)
    expect(api.deleteFreeDraft).not.toHaveBeenCalled()
    await wrapper.find('[data-testid="confirm-delete"]').trigger('click')
    await flushPromises()
    expect(api.deleteFreeDraft).toHaveBeenCalledWith('acct-a', 'draft-1', { suppressToast: true })
    expect(wrapper.find('article').exists()).toBe(false)
  })

  it('ignores a late response from a previous account', async () => {
    const api = await import('@/api/free')
    let resolveA!: (value: unknown) => void
    const responseA = new Promise(resolve => { resolveA = resolve })
    vi.mocked(api.listFreeDrafts)
      .mockReturnValueOnce(responseA as ReturnType<typeof api.listFreeDrafts>)
      .mockResolvedValueOnce({ account_id: 'acct-b', drafts: [draft({ draft_id: 'draft-b', title: 'B draft' })], count: 1 })

    const wrapper = await mountPanel('acct-a')
    await wrapper.setProps({ accountId: 'acct-b' })
    await flushPromises()
    resolveA({ account_id: 'acct-a', drafts: [draft({ title: 'Stale A draft' })], count: 1 })
    await flushPromises()

    expect(wrapper.text()).toContain('B draft')
    expect(wrapper.text()).not.toContain('Stale A draft')
  })

  it('ignores a late delete result after switching accounts', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValueOnce({
      account_id: 'acct-a',
      drafts: [draft()],
      count: 1,
    }).mockResolvedValueOnce({
      account_id: 'acct-b',
      drafts: [draft({ draft_id: 'draft-b', title: 'B draft' })],
      count: 1,
    })
    let resolveDelete!: (value: { draft_id: string; deleted: boolean }) => void
    vi.mocked(api.deleteFreeDraft).mockReturnValueOnce(new Promise(resolve => { resolveDelete = resolve }))

    const wrapper = await mountPanel('acct-a')
    await wrapper.find('article button[aria-label]').trigger('click')
    await wrapper.find('[data-testid="confirm-delete"]').trigger('click')
    await wrapper.setProps({ accountId: 'acct-b' })
    await flushPromises()

    resolveDelete({ draft_id: 'draft-1', deleted: true })
    await flushPromises()

    expect(wrapper.text()).toContain('B draft')
    expect(wrapper.text()).not.toContain('京都亲子三日')
  })
})
