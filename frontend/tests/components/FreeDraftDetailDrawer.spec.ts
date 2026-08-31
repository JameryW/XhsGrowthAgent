import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FreeDraftDetailDrawer from '@/components/history/FreeDraftDetailDrawer.vue'
import type { FreeDraftDetailResponse, FreeDraftRecord } from '@/api/free'

vi.mock('@/api/free', () => ({
  getFreeDraft: vi.fn(),
}))

const mountedWrappers: Array<ReturnType<typeof mount>> = []

const completeDetail = (overrides: Partial<FreeDraftRecord> = {}): FreeDraftRecord => ({
  draft_id: 'draft-a',
  account_id: 'acct-a',
  title: '完整草稿标题',
  body: '第一段正文\n第二段正文',
  hashtags: ['#旅行', '#亲子'],
  created_at: '2026-08-20T08:00:00Z',
  updated_at: '2026-08-21T08:00:00Z',
  image_paths: ['cover.png', 'detail.png'],
  niche: '亲子旅行',
  content_angle: '三天实用路线',
  target_audience: '第一次带孩子去京都的家庭',
  published: true,
  post_id: 'note_real_1',
  post_url: 'https://www.xiaohongshu.com/explore/note_real_1',
  last_evaluation: {
    overall_score: 91,
    decision: 'approved',
    summary: '结构清晰，可以发布。',
    revision_hints: ['补充交通时间'],
    degraded: false,
  },
  style_id: 'style_warm',
  play_id: 'play_route',
  material_ids: ['material_1', 'material_2'],
  last_publish: {
    status: 'published',
    at: '2026-08-22T08:00:00Z',
  },
  last_analytics: {
    post_id: 'note_real_1',
    views: 350,
    likes: 70,
    collects: 17,
    comments: 11,
    shares: 2,
    fetched_at: '2026-08-23T08:00:00Z',
  },
  analytics_snapshots: [
    { post_id: 'note_real_1', views: 150, fetched_at: '2026-08-22T08:00:00Z' },
    { post_id: 'note_real_1', views: 350, fetched_at: '2026-08-23T08:00:00Z' },
  ],
  ...overrides,
})

function responseFor(detail: FreeDraftRecord): FreeDraftDetailResponse {
  return { draft_id: detail.draft_id, draft: detail }
}

function mountDrawer(props: Partial<{
  accountId: string | null
  draftId: string | null
  isOpen: boolean
  nextStepLabel: string
}> = {}, stubTeleport = true) {
  const wrapper = mount(FreeDraftDetailDrawer, {
    attachTo: document.body,
    props: {
      accountId: 'acct-a',
      draftId: 'draft-a',
      isOpen: true,
      nextStepLabel: '打开草稿',
      ...props,
    },
    global: {
      stubs: {
        ...(stubTeleport ? { Teleport: { template: '<div><slot /></div>' } } : {}),
        AppIcon: true,
        NeonButton: {
          props: ['disabled', 'loading', 'variant', 'size'],
          emits: ['click'],
          template: '<button type="button" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('FreeDraftDetailDrawer', () => {
  beforeEach(async () => {
    const api = await import('@/api/free')
    vi.mocked(api.getFreeDraft).mockReset()
  })

  afterEach(() => {
    for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount()
    document.body.innerHTML = ''
  })

  it('renders the complete account-scoped record and emits the loaded detail', async () => {
    const api = await import('@/api/free')
    const detail = completeDetail()
    vi.mocked(api.getFreeDraft).mockResolvedValue(responseFor(detail))

    const wrapper = mountDrawer()
    await flushPromises()

    expect(api.getFreeDraft).toHaveBeenCalledWith('acct-a', 'draft-a', expect.objectContaining({
      signal: expect.any(AbortSignal),
      suppressToast: true,
    }))
    const text = wrapper.text()
    expect(text).toContain('完整草稿标题')
    expect(text).toContain('第一段正文')
    expect(text).toContain('亲子旅行')
    expect(text).toContain('三天实用路线')
    expect(text).toContain('第一次带孩子去京都的家庭')
    expect(text).toContain('91')
    expect(text).toContain('结构清晰，可以发布。')
    expect(text).toContain('补充交通时间')
    expect(text).toContain('style_warm')
    expect(text).toContain('play_route')
    expect(text).toContain('material_2')
    expect(text).toContain('350')
    expect(wrapper.find('[data-testid="free-draft-detail-trend"]').text()).toContain('+200')
    expect(wrapper.find('a[target="_blank"]').attributes('href')).toBe('https://www.xiaohongshu.com/explore/note_real_1')

    const footerButtons = wrapper.findAll('footer button')
    await footerButtons[footerButtons.length - 1].trigger('click')
    expect(wrapper.emitted('continue')?.[0]).toEqual([detail])
  })

  it('keeps the stable drawer shell and disabled next step while loading', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.getFreeDraft).mockReturnValue(new Promise(() => {}))

    const wrapper = mountDrawer()
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="free-draft-detail-loading"]').exists()).toBe(true)
    expect(wrapper.find('header').exists()).toBe(true)
    expect(wrapper.find('footer').exists()).toBe(true)
    expect(wrapper.findAll('footer button').at(-1)?.attributes('disabled')).toBeDefined()
  })

  it('shows a local error and retries without closing or navigating', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.getFreeDraft)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(responseFor(completeDetail()))

    const wrapper = mountDrawer()
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-detail-error"]').text()).toContain('offline')

    await wrapper.find('[data-testid="free-draft-detail-error"] button').trigger('click')
    await flushPromises()
    expect(api.getFreeDraft).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="free-draft-detail-content"]').exists()).toBe(true)
    expect(wrapper.emitted('close')).toBeUndefined()
    expect(wrapper.emitted('continue')).toBeUndefined()
  })

  it('renders explicit unavailable states for empty, mismatched, and missing data', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.getFreeDraft).mockResolvedValueOnce({
      draft_id: 'draft-a',
      draft: {} as FreeDraftRecord,
    })

    const wrapper = mountDrawer()
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-detail-unavailable"]').exists()).toBe(true)

    vi.mocked(api.getFreeDraft).mockResolvedValueOnce({
      draft_id: 'draft-b',
      draft: completeDetail({ draft_id: 'another-draft' }),
    })
    await wrapper.setProps({ draftId: 'draft-b' })
    await flushPromises()
    expect(wrapper.find('[data-testid="free-draft-detail-unavailable"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('完整草稿标题')

    vi.mocked(api.getFreeDraft).mockResolvedValueOnce(responseFor(completeDetail({
      draft_id: 'draft-c',
      body: '',
      image_paths: undefined,
      niche: '',
      content_angle: '',
      target_audience: '',
      last_evaluation: null,
      style_id: '',
      play_id: '',
      material_ids: [],
      last_publish: null,
      published: undefined,
      post_id: '',
      post_url: '',
      last_analytics: null,
      analytics_snapshots: [],
    })))
    await wrapper.setProps({ draftId: 'draft-c' })
    await flushPromises()

    expect(wrapper.text()).toContain('该草稿暂无正文')
    expect(wrapper.text()).toContain('尚未记录评估结果')
    expect(wrapper.text()).toContain('尚未记录创作记忆锚点')
    expect(wrapper.text()).toContain('尚未采集表现快照')
    expect(wrapper.find('[data-testid="free-draft-detail-publish"]').text()).toContain('暂无')
    expect(wrapper.find('[data-testid="free-draft-detail-publish"]').text()).not.toContain('未发布')
    expect(wrapper.find('[data-testid="free-draft-detail-analytics"] dl').exists()).toBe(false)
  })

  it('surfaces degraded evaluation and publish failure facts without trusting a fallback verdict', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.getFreeDraft).mockResolvedValue(responseFor(completeDetail({
      published: false,
      post_id: 'mock_dry_run',
      post_url: 'https://www.xiaohongshu.com/explore/mock',
      last_evaluation: {
        overall_score: 100,
        decision: 'approved',
        degraded: true,
        summary: '评估服务暂时不可用',
        revision_hints: ['稍后重新评估'],
      },
      last_publish: {
        status: 'failed',
        error_type: 'account_inactive',
        error: 'browser session missing',
      },
    })))

    const wrapper = mountDrawer()
    await flushPromises()
    const evaluation = wrapper.find('[data-testid="free-draft-detail-evaluation"]')
    expect(evaluation.text()).toContain('评估不可用')
    expect(evaluation.text()).toContain('评估服务暂时不可用')
    expect(evaluation.text()).toContain('稍后重新评估')
    expect(evaluation.text()).not.toContain('100')
    expect(evaluation.text()).not.toContain('通过')
    expect(wrapper.find('[data-testid="free-draft-detail-publish"]').text()).toContain('account_inactive')
    expect(wrapper.find('[data-testid="free-draft-detail-publish"]').text()).toContain('browser session missing')
    expect(wrapper.find('a[target="_blank"]').exists()).toBe(false)
  })

  it('aborts a previous draft read and ignores its late response', async () => {
    const api = await import('@/api/free')
    let resolveA!: (response: FreeDraftDetailResponse) => void
    const responseA = new Promise<FreeDraftDetailResponse>(resolve => { resolveA = resolve })
    const detailB = completeDetail({ draft_id: 'draft-b', title: 'Current B draft' })
    vi.mocked(api.getFreeDraft)
      .mockReturnValueOnce(responseA)
      .mockResolvedValueOnce(responseFor(detailB))

    const wrapper = mountDrawer()
    await flushPromises()
    const firstSignal = vi.mocked(api.getFreeDraft).mock.calls[0][2]?.signal
    await wrapper.setProps({ draftId: 'draft-b' })
    await flushPromises()
    expect(firstSignal?.aborted).toBe(true)
    expect(wrapper.text()).toContain('Current B draft')

    resolveA(responseFor(completeDetail({ title: 'Stale A draft' })))
    await flushPromises()
    expect(wrapper.text()).toContain('Current B draft')
    expect(wrapper.text()).not.toContain('Stale A draft')
  })

  it('closes on an account switch and prevents the old account response from repainting', async () => {
    const api = await import('@/api/free')
    let resolveA!: (response: FreeDraftDetailResponse) => void
    vi.mocked(api.getFreeDraft).mockReturnValueOnce(new Promise(resolve => { resolveA = resolve }))

    const wrapper = mountDrawer()
    await flushPromises()
    const firstSignal = vi.mocked(api.getFreeDraft).mock.calls[0][2]?.signal
    await wrapper.setProps({ accountId: 'acct-b' })
    await flushPromises()

    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(firstSignal?.aborted).toBe(true)
    expect(api.getFreeDraft).toHaveBeenCalledTimes(1)
    resolveA(responseFor(completeDetail({ title: 'Stale account draft' })))
    await flushPromises()
    expect(wrapper.text()).not.toContain('Stale account draft')
  })

  it('closes by Esc and backdrop, traps focus, and restores the trigger after close', async () => {
    const api = await import('@/api/free')
    vi.mocked(api.getFreeDraft).mockResolvedValue(responseFor(completeDetail()))
    const wrapper = mountDrawer({ isOpen: false }, false)
    const trigger = document.createElement('button')
    document.body.insertBefore(trigger, document.body.firstChild)
    trigger.focus()
    await wrapper.setProps({ isOpen: true })
    await flushPromises()
    const closeButton = document.querySelector<HTMLButtonElement>('[data-testid="free-draft-detail-drawer"] button[aria-label]')
    const dialog = document.querySelector<HTMLElement>('[data-testid="free-draft-detail-drawer"]')
    const backdrop = document.querySelector<HTMLElement>('[data-testid="free-draft-detail-backdrop"]')
    expect(closeButton).not.toBeNull()
    expect(dialog).not.toBeNull()
    expect(backdrop).not.toBeNull()
    await vi.waitFor(() => {
      expect(document.activeElement).toBe(closeButton)
    })

    const footerButtons = Array.from(document.querySelectorAll<HTMLButtonElement>('[data-testid="free-draft-detail-drawer"] footer button'))
    const lastButton = footerButtons[footerButtons.length - 1]
    closeButton!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }))
    expect(document.activeElement).toBe(lastButton)
    lastButton.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    expect(document.activeElement).toBe(closeButton)

    closeButton!.click()
    await flushPromises()
    expect(wrapper.emitted('close')).toHaveLength(1)

    dialog!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(wrapper.emitted('close')).toHaveLength(2)
    backdrop!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(wrapper.emitted('close')).toHaveLength(3)

    await wrapper.setProps({ isOpen: false })
    await flushPromises()
    expect(document.activeElement).toBe(trigger)
  })
})
