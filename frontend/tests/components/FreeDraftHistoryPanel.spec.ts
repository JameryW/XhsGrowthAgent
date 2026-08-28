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

  it('shows the persisted engagement snapshot only on published drafts that have one', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [
        draft({
          draft_id: 'pub-snap',
          title: '已发布有快照',
          published: true,
          last_analytics: {
            post_id: 'p1',
            views: 900,
            likes: 30,
            collects: 10,
            comments: 5,
            shares: 2,
            engagement_rate: 5.22,
            fetched_at: '2026-08-24T08:00:00Z',
          },
        }),
        draft({ draft_id: 'unpub', title: '未发布草稿' }),
        draft({ draft_id: 'pub-no-snap', title: '已发布无快照', published: true }),
      ],
      count: 3,
    })

    const wrapper = await mountPanel()
    const badges = wrapper.findAll('[data-testid="free-draft-engagement"]')
    expect(badges).toHaveLength(1)
    expect(badges[0].text()).toContain('900')
    expect(badges[0].text()).toContain('30')
    expect(badges[0].text()).toContain('10')
    // captured-at context travels as the badge tooltip
    expect(badges[0].attributes('title')).toBeTruthy()
  })

  it('renders the views trend badge only when the server-computed trend exists', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [
        draft({
          draft_id: 'trend-up',
          title: '上涨笔记',
          published: true,
          last_analytics: {
            post_id: 'p1', views: 350, likes: 70, collects: 17, comments: 11, shares: 2,
            engagement_rate: 28.57, fetched_at: '2026-08-25T09:30:00Z',
          },
          engagement_trend: { views: 350, delta_views: 200, captured_at: '2026-08-25T09:30:00Z' },
        }),
        draft({
          draft_id: 'trend-down',
          title: '下滑笔记',
          published: true,
          last_analytics: {
            post_id: 'p2', views: 90, likes: 18, collects: 4, comments: 3, shares: 0,
            engagement_rate: 27.78, fetched_at: '2026-08-25T09:30:00Z',
          },
          engagement_trend: { views: 90, delta_views: -310, captured_at: '2026-08-25T09:30:00Z' },
        }),
        draft({
          draft_id: 'no-trend',
          title: '单点快照',
          published: true,
          last_analytics: {
            post_id: 'p3', views: 500, likes: 100, collects: 25, comments: 16, shares: 5,
            engagement_rate: 29.2, fetched_at: '2026-08-25T09:30:00Z',
          },
        }),
      ],
      count: 3,
    })

    const wrapper = await mountPanel()
    const trends = wrapper.findAll('[data-testid="free-draft-trend"]')
    expect(trends).toHaveLength(2)
    expect(trends[0].text()).toContain('+200')
    expect(trends[1].text()).toContain('-310')
  })

  it('renders the anchor badge only for drafts with creative-memory anchors', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [
        draft({
          draft_id: 'anchored',
          title: '有锚定',
          style_id: 'style_治愈',
          play_id: 'p_9',
          material_ids: ['m1'],
        }),
        draft({ draft_id: 'plain', title: '无锚定' }),
      ],
      count: 2,
    })

    const wrapper = await mountPanel()
    const badges = wrapper.findAll('[data-testid="free-draft-anchors"]')
    expect(badges).toHaveLength(1)
    expect(badges[0].text()).toContain('3')
    // tooltip lists the anchored ids
    expect(badges[0].attributes('title')).toContain('style_治愈')
    expect(badges[0].attributes('title')).toContain('p_9')
    expect(badges[0].attributes('title')).toContain('m1')
  })

  it('surfaces publish failures, contextual actions, and the account overview', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [
        draft({
          draft_id: 'failed',
          title: '待修复发布',
          last_publish: { status: 'failed', error_type: 'account_inactive', at: '2026-08-25T09:30:00Z' },
        }),
        draft({
          draft_id: 'revision',
          title: '待修订内容',
          last_evaluation: { overall_score: 62, decision: 'needs_revision' },
        }),
        draft({
          draft_id: 'ready',
          title: '待发布内容',
          last_evaluation: { overall_score: 91, decision: 'approved' },
        }),
        draft({ draft_id: 'published', title: '已发布内容', published: true }),
        draft({ draft_id: 'plain', title: '普通草稿' }),
      ],
      count: 5,
    })

    const wrapper = await mountPanel()
    const overviewText = wrapper.find('[data-testid="free-draft-overview"]').text()
    expect(overviewText).toMatch(/Shown|显示篇数/)
    expect(overviewText).toMatch(/Need attention|待处理篇数/)
    expect(wrapper.findAll('[data-testid="free-draft-publish-failure"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('account_inactive')
    expect(wrapper.text()).toMatch(/Open the draft to fix and retry|打开草稿修复后重试/)
    expect(wrapper.text()).toMatch(/Fix & retry|修复并重试/)
    expect(wrapper.text()).toMatch(/Review & revise|检查并修订/)
    expect(wrapper.text()).toMatch(/Review & publish|检查并发布/)
    expect(wrapper.text()).toMatch(/Open draft|打开草稿/)
    expect(wrapper.text()).toMatch(/Continue writing|继续写作/)

    const reviewAttentionButton = wrapper.find('[data-testid="free-draft-overview"] button')
    expect(reviewAttentionButton.exists()).toBe(true)
    await reviewAttentionButton.trigger('click')
    expect(wrapper.findAll('article')).toHaveLength(3)

    const failedFilter = wrapper.findAll('button').find(button => /Publish failed|发布失败/.test(button.text()))
    expect(failedFilter).toBeTruthy()
    await failedFilter!.trigger('click')
    expect(wrapper.findAll('article')).toHaveLength(1)
    expect(wrapper.find('article').text()).toContain('待修复发布')
  })

  it('starts a new free draft from the empty state', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({ account_id: 'acct-a', drafts: [], count: 0 })

    const wrapper = await mountPanel()
    expect(wrapper.find('[data-testid="free-drafts-empty"]').exists()).toBe(true)
    const newDraftButton = wrapper.findAll('button').find(button => /New draft|新建草稿/.test(button.text()))
    expect(newDraftButton).toBeTruthy()
    await newDraftButton!.trigger('click')
    expect(routerPush).toHaveBeenCalledWith({
      name: 'tui',
      query: { mode: 'free', account_id: 'acct-a' },
    })
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
