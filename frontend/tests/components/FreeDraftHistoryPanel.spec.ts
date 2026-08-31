import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FreeDraftDetailDrawer from '@/components/history/FreeDraftDetailDrawer.vue'
import FreeDraftHistoryPanel from '@/components/history/FreeDraftHistoryPanel.vue'
import type { FreeDraftDetailResponse, FreeDraftRecord, FreeDraftSummary } from '@/api/free'

const routerPush = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/api/free', () => ({
  listFreeDrafts: vi.fn(),
  getFreeDraft: vi.fn(),
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
        Teleport: { template: '<div><slot /></div>' },
        AppIcon: true,
        NeonButton: {
          props: ['loading', 'variant', 'size'],
          emits: ['click'],
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
    vi.mocked(api.getFreeDraft).mockReset()
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

  it('maps safe next-step actions while keeping ordinary draft links unchanged', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [
        draft({
          draft_id: 'approved',
          title: '待发布',
          last_evaluation: { overall_score: 91, decision: 'approved' },
        }),
        draft({
          draft_id: 'failed',
          title: '发布失败',
          last_publish: { status: 'failed' },
        }),
        draft({
          draft_id: 'real-post',
          title: '真实帖子',
          published: true,
        }),
        draft({
          draft_id: 'mock-post',
          title: '模拟帖子',
          published: true,
        }),
        draft({
          draft_id: 'snapshot-post',
          title: '旧响应真实帖子',
          published: true,
          last_analytics: { post_id: 'note_from_snapshot' },
        }),
        draft({
          draft_id: 'status-post',
          title: '旧响应已发布',
          published: true,
          last_publish: { status: 'published' },
        }),
        draft({
          draft_id: 'mock-status',
          title: '旧响应模拟发布',
          published: true,
          last_publish: { status: 'mock_published' },
        }),
        draft({
          draft_id: 'revision',
          title: '待修订',
          last_evaluation: { overall_score: 62, decision: 'needs_revision' },
        }),
        draft({ draft_id: 'plain', title: '普通草稿' }),
      ],
      count: 9,
    })
    vi.mocked(api.getFreeDraft).mockImplementation(async (_accountId, draftId) => ({
      draft_id: draftId,
      draft: draftId === 'real-post'
        ? { ...draft({ draft_id: draftId, published: true }), post_id: 'note_123' }
        : draftId === 'mock-post'
          ? { ...draft({ draft_id: draftId, published: true }), post_id: 'mock_dry_run' }
          : { ...draft({ draft_id: draftId, published: true }), post_id: '' },
    }))

    const wrapper = await mountPanel()
    const expectedActions = [
      { draftId: 'approved', action: 'publish' },
      { draftId: 'failed', action: 'publish' },
      { draftId: 'real-post', action: 'analytics' },
      { draftId: 'mock-post' },
      { draftId: 'snapshot-post', action: 'analytics' },
      { draftId: 'status-post' },
      { draftId: 'mock-status' },
      { draftId: 'revision' },
      { draftId: 'plain' },
    ]

    for (const expected of expectedActions) {
      routerPush.mockClear()
      const article = wrapper.findAll('article').find(item => item.attributes('aria-labelledby') === `free-draft-${expected.draftId}`)
      expect(article).toBeTruthy()
      await article!.findAll('button')[0].trigger('click')
      await flushPromises()
      expect(routerPush).toHaveBeenCalledWith({
        name: 'tui',
        query: {
          mode: 'free',
          account_id: 'acct-a',
          draft_id: expected.draftId,
          ...(expected.action ? { action: expected.action } : {}),
        },
      })
    }
    expect(api.getFreeDraft).toHaveBeenCalledWith('acct-a', 'real-post', { suppressToast: true })
    expect(api.getFreeDraft).toHaveBeenCalledWith('acct-a', 'mock-post', { suppressToast: true })
    expect(api.getFreeDraft).toHaveBeenCalledWith('acct-a', 'status-post', { suppressToast: true })
    expect(api.getFreeDraft).not.toHaveBeenCalledWith('acct-a', 'mock-status', expect.anything())
  })

  it('previews in place and reuses the loaded detail for the safe TUI next step', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [draft({
        draft_id: 'real-post',
        title: '真实帖子草稿',
        published: true,
      })],
      count: 1,
    })
    vi.mocked(api.getFreeDraft).mockResolvedValue({
      draft_id: 'real-post',
      draft: {
        ...draft({ draft_id: 'real-post', title: '真实帖子草稿', published: true }),
        account_id: 'acct-a',
        body: '完整正文',
        post_id: 'note_real_9',
      },
    })

    const wrapper = await mountPanel()
    await wrapper.find('input[type="search"]').setValue('真实')
    const previewButton = wrapper.findAll('article button').find(button => /Preview|预览/.test(button.text()))
    expect(previewButton).toBeTruthy()
    await previewButton!.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="free-draft-detail-drawer"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="free-draft-detail-content"]').text()).toContain('完整正文')
    expect((wrapper.find('input[type="search"]').element as HTMLInputElement).value).toBe('真实')
    expect(routerPush).not.toHaveBeenCalled()
    expect(api.getFreeDraft).toHaveBeenCalledTimes(1)
    expect(api.getFreeDraft).toHaveBeenCalledWith('acct-a', 'real-post', expect.objectContaining({
      signal: expect.any(AbortSignal),
      suppressToast: true,
    }))

    const footerButtons = wrapper.findAll('[data-testid="free-draft-detail-drawer"] footer button')
    expect(footerButtons[footerButtons.length - 1].text()).toMatch(/Open draft|打开草稿/)
    await footerButtons[footerButtons.length - 1].trigger('click')
    await flushPromises()
    expect(api.getFreeDraft).toHaveBeenCalledTimes(1)
    expect(routerPush).toHaveBeenCalledWith({
      name: 'tui',
      query: {
        mode: 'free',
        account_id: 'acct-a',
        draft_id: 'real-post',
        action: 'analytics',
      },
    })
  })

  it('reviews only the filtered queue, drops stale detail, and continues the current draft safely', async () => {
    const api = await import('@/api/free')
    const matchA = draft({ draft_id: 'match-a', title: '匹配 A' })
    const matchB = draft({ draft_id: 'match-b', title: '匹配 B', published: true })
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [draft({ draft_id: 'hidden', title: '筛选外草稿' }), matchA, matchB],
      count: 3,
    })
    let resolveA!: (response: FreeDraftDetailResponse) => void
    const detailA = new Promise<FreeDraftDetailResponse>(resolve => { resolveA = resolve })
    vi.mocked(api.getFreeDraft).mockImplementation(async (_accountId, draftId) => {
      if (draftId === 'match-a') return detailA
      return {
        draft_id: 'match-b',
        draft: {
          ...matchB,
          account_id: 'acct-a',
          body: '当前 B 正文',
          post_id: 'note_current_b',
        },
      }
    })

    const wrapper = await mountPanel()
    await wrapper.find('input[type="search"]').setValue('匹配')
    expect(wrapper.findAll('article')).toHaveLength(2)
    const firstPreview = wrapper.findAll('article')[0].findAll('button').find(button => /Preview|预览/.test(button.text()))
    await firstPreview!.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="free-draft-queue-position"]').text()).toMatch(/第 1 条，共 2 条|Draft 1 of 2/)
    expect((wrapper.find('[data-testid="free-draft-queue-previous"]').element as HTMLButtonElement).disabled).toBe(true)
    const firstSignal = vi.mocked(api.getFreeDraft).mock.calls[0][2]?.signal
    await wrapper.find('[data-testid="free-draft-queue-next"]').trigger('click')
    await flushPromises()

    expect(firstSignal?.aborted).toBe(true)
    expect(wrapper.find('[data-testid="free-draft-queue-position"]').text()).toMatch(/第 2 条，共 2 条|Draft 2 of 2/)
    expect(wrapper.find('[data-testid="free-draft-detail-content"]').text()).toContain('当前 B 正文')
    expect((wrapper.find('[data-testid="free-draft-queue-next"]').element as HTMLButtonElement).disabled).toBe(true)
    expect((wrapper.find('input[type="search"]').element as HTMLInputElement).value).toBe('匹配')
    expect(routerPush).not.toHaveBeenCalled()

    await wrapper.find('[data-testid="free-draft-queue-previous"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-queue-position"]').text()).toMatch(/第 1 条，共 2 条|Draft 1 of 2/)
    await wrapper.find('[data-testid="free-draft-queue-next"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-queue-position"]').text()).toMatch(/第 2 条，共 2 条|Draft 2 of 2/)
    expect(wrapper.find('[data-testid="free-draft-detail-content"]').text()).toContain('当前 B 正文')

    resolveA({
      draft_id: 'match-a',
      draft: { ...matchA, account_id: 'acct-a', body: '迟到 A 正文' },
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('迟到 A 正文')

    const drawer = wrapper.findComponent(FreeDraftDetailDrawer)
    drawer.vm.$emit('continue', {
      ...matchA,
      account_id: 'acct-a',
      body: '过期 A 详情',
    } satisfies FreeDraftRecord)
    await flushPromises()
    expect(routerPush).not.toHaveBeenCalled()

    const footerButtons = wrapper.findAll('[data-testid="free-draft-detail-drawer"] footer button')
    expect(footerButtons[footerButtons.length - 1].text()).toMatch(/Open draft|打开草稿/)
    await footerButtons[footerButtons.length - 1].trigger('click')
    await flushPromises()
    expect(api.getFreeDraft).toHaveBeenCalledTimes(4)
    expect(api.deleteFreeDraft).not.toHaveBeenCalled()
    expect(routerPush).toHaveBeenCalledWith({
      name: 'tui',
      query: {
        mode: 'free',
        account_id: 'acct-a',
        draft_id: 'match-b',
        action: 'analytics',
      },
    })
  })

  it('closes the queue when a filter removes the current draft', async () => {
    const api = await import('@/api/free')
    const draftA = draft({ draft_id: 'only-a', title: 'Only A' })
    const draftB = draft({ draft_id: 'only-b', title: 'Only B' })
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [draftA, draftB],
      count: 2,
    })
    vi.mocked(api.getFreeDraft).mockResolvedValue({
      draft_id: 'only-b',
      draft: { ...draftB, account_id: 'acct-a', body: 'B body' },
    })

    const wrapper = await mountPanel()
    const secondPreview = wrapper.findAll('article')[1].findAll('button').find(button => /Preview|预览/.test(button.text()))
    await secondPreview!.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-detail-drawer"]').exists()).toBe(true)

    await wrapper.find('input[type="search"]').setValue('Only A')
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-detail-drawer"]').exists()).toBe(false)
    expect(routerPush).not.toHaveBeenCalled()
    expect(api.deleteFreeDraft).not.toHaveBeenCalled()
  })

  it('re-derives queue position after refresh and closes when refresh removes the target', async () => {
    const api = await import('@/api/free')
    const draftA = draft({ draft_id: 'queue-a', title: 'Queue A' })
    const draftB = draft({ draft_id: 'queue-b', title: 'Queue B' })
    const draftC = draft({ draft_id: 'queue-c', title: 'Queue C' })
    vi.mocked(api.listFreeDrafts)
      .mockResolvedValueOnce({ account_id: 'acct-a', drafts: [draftA, draftB, draftC], count: 3 })
      .mockResolvedValueOnce({ account_id: 'acct-a', drafts: [draftB, draftA, draftC], count: 3 })
      .mockResolvedValueOnce({ account_id: 'acct-a', drafts: [draftA, draftC], count: 2 })
    vi.mocked(api.getFreeDraft).mockResolvedValue({
      draft_id: 'queue-b',
      draft: { ...draftB, account_id: 'acct-a', body: 'Queue B body' },
    })

    const wrapper = await mountPanel()
    const secondPreview = wrapper.findAll('article')[1].findAll('button').find(button => /Preview|预览/.test(button.text()))
    await secondPreview!.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-queue-position"]').text()).toMatch(/第 2 条，共 3 条|Draft 2 of 3/)

    await (wrapper.vm as unknown as { refresh: () => Promise<void> }).refresh()
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-detail-drawer"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="free-draft-queue-position"]').text()).toMatch(/第 1 条，共 3 条|Draft 1 of 3/)
    expect(api.getFreeDraft).toHaveBeenCalledTimes(1)

    await (wrapper.vm as unknown as { refresh: () => Promise<void> }).refresh()
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-detail-drawer"]').exists()).toBe(false)
    expect(routerPush).not.toHaveBeenCalled()
    expect(api.deleteFreeDraft).not.toHaveBeenCalled()
  })

  it('closes and aborts the open detail when the account changes', async () => {
    const api = await import('@/api/free')
    const draftA = draft({ draft_id: 'account-a-draft', title: 'Account A draft' })
    vi.mocked(api.listFreeDrafts)
      .mockResolvedValueOnce({ account_id: 'acct-a', drafts: [draftA], count: 1 })
      .mockResolvedValueOnce({
        account_id: 'acct-b',
        drafts: [draft({ draft_id: 'account-b-draft', title: 'Account B draft' })],
        count: 1,
      })
    vi.mocked(api.getFreeDraft).mockReturnValue(new Promise(() => {}))

    const wrapper = await mountPanel('acct-a')
    const preview = wrapper.find('article').findAll('button').find(button => /Preview|预览/.test(button.text()))
    await preview!.trigger('click')
    await flushPromises()
    const signal = vi.mocked(api.getFreeDraft).mock.calls[0][2]?.signal

    await wrapper.setProps({ accountId: 'acct-b' })
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    expect(wrapper.find('[data-testid="free-draft-detail-drawer"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Account B draft')
    expect(routerPush).not.toHaveBeenCalled()
    expect(api.deleteFreeDraft).not.toHaveBeenCalled()
  })

  it('opens the publish preview deep link from loaded detail without another read', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [draft({
        draft_id: 'approved-preview',
        title: '通过待发布',
        last_evaluation: { overall_score: 92, decision: 'approved' },
      })],
      count: 1,
    })
    vi.mocked(api.getFreeDraft).mockResolvedValue({
      draft_id: 'approved-preview',
      draft: {
        ...draft({
          draft_id: 'approved-preview',
          title: '通过待发布',
          last_evaluation: { overall_score: 92, decision: 'approved' },
        }),
        account_id: 'acct-a',
        body: '完整待发布正文',
      },
    })

    const wrapper = await mountPanel()
    const previewButton = wrapper.findAll('article button').find(button => /Preview|预览/.test(button.text()))
    await previewButton!.trigger('click')
    await flushPromises()
    const footerButtons = wrapper.findAll('[data-testid="free-draft-detail-drawer"] footer button')
    await footerButtons[footerButtons.length - 1].trigger('click')
    await flushPromises()

    expect(api.getFreeDraft).toHaveBeenCalledTimes(1)
    expect(routerPush).toHaveBeenCalledWith({
      name: 'tui',
      query: {
        mode: 'free',
        account_id: 'acct-a',
        draft_id: 'approved-preview',
        action: 'publish',
      },
    })
  })

  it('trusts the loaded current post id over a stale analytics snapshot', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.listFreeDrafts).mockResolvedValue({
      account_id: 'acct-a',
      drafts: [draft({ draft_id: 'mock-current', title: '当前试运行草稿', published: true })],
      count: 1,
    })
    vi.mocked(api.getFreeDraft).mockResolvedValue({
      draft_id: 'mock-current',
      draft: {
        ...draft({ draft_id: 'mock-current', title: '当前试运行草稿', published: true }),
        account_id: 'acct-a',
        post_id: 'mock_current',
        last_analytics: { post_id: 'note_stale_real' },
      },
    })

    const wrapper = await mountPanel()
    const previewButton = wrapper.findAll('article button').find(button => /Preview|预览/.test(button.text()))
    await previewButton!.trigger('click')
    await flushPromises()
    const footerButtons = wrapper.findAll('[data-testid="free-draft-detail-drawer"] footer button')
    await footerButtons[footerButtons.length - 1].trigger('click')
    await flushPromises()

    expect(api.getFreeDraft).toHaveBeenCalledTimes(1)
    expect(routerPush).toHaveBeenCalledWith({
      name: 'tui',
      query: {
        mode: 'free',
        account_id: 'acct-a',
        draft_id: 'mock-current',
      },
    })
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
