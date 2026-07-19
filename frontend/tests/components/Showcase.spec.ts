import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Showcase from '@/views/Showcase.vue'

const routerMock = vi.hoisted(() => ({
  replace: vi.fn(() => Promise.resolve()),
  push: vi.fn(() => Promise.resolve()),
}))
const routeMock = vi.hoisted(() => ({ query: {} as Record<string, string> }))
const listPublicCasesMock = vi.hoisted(() => vi.fn())
const getPublicCaseMock = vi.hoisted(() => vi.fn())
const authState = vi.hoisted(() => ({ isAuthenticated: false, isInitialized: true }))

vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => routeMock,
}))
vi.mock('@/api/publicShowcase', () => ({
  listPublicCases: listPublicCasesMock,
  getPublicCase: getPublicCaseMock,
}))
vi.mock('@/stores', () => ({
  useAuthStore: () => ({ get isAuthenticated() { return authState.isAuthenticated }, get isInitialized() { return authState.isInitialized }, initialize: vi.fn() }),
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ get isAuthenticated() { return authState.isAuthenticated }, get isInitialized() { return authState.isInitialized }, initialize: vi.fn() }),
}))

function publicCase(public_id: string, title: string, featured = false) {
  return {
    public_id,
    title,
    summary: `${title} summary`,
    status: 'completed' as const,
    phase: 'completed',
    workflow_mode: 'trend' as const,
    created_at: '2026-07-16T10:00:00Z',
    updated_at: '2026-07-16T10:00:00Z',
    featured,
    replay_available: true,
    result_preview: { title, topic: '测试主题' },
  }
}

function mountShowcase() {
  return mount(Showcase, {
    global: {
      stubs: {
        AppIcon: { template: '<span />' },
        PublicReplayResult: { template: '<div class="public-result-stub" />' },
        ThemeToggle: { template: '<button aria-label="theme" />' },
      },
    },
  })
}

describe('Showcase public UX contract', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    routeMock.query = {}
    authState.isAuthenticated = false
    authState.isInitialized = true
    const featured = publicCase('case-featured', '真实案例标题', true)
    const other = publicCase('case-other', '第二个案例')
    listPublicCasesMock.mockResolvedValue({
      cases: [featured, other],
      total: 2,
      limit: 100,
      offset: 0,
      featured_public_id: featured.public_id,
    })
    getPublicCaseMock.mockImplementation(async (publicId: string) => ({
      ...(publicId === featured.public_id ? featured : other),
      result: { title: publicId === featured.public_id ? featured.title : other.title, topic: '测试主题' },
    }))
  })

  afterEach(() => sessionStorage.clear())

  it('renders one featured case and keeps public replay navigation', async () => {
    const wrapper = mountShowcase()
    await flushPromises()

    expect(wrapper.find('#featured-heading').text()).toContain('真实案例标题')
    expect(wrapper.findAll('.case-card')).toHaveLength(1)
    expect(wrapper.findAll('button').some(button => button.text().includes('登录'))).toBe(false)
    await wrapper.find('.case-card a').trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'replay', params: { publicId: 'case-other' }, query: { from: '/' } })
  })

  it('normalizes URL filters and keeps them synchronized', async () => {
    routeMock.query = { status: 'invalid', mode: 'brief', sort: 'title' }
    const wrapper = mountShowcase()
    await flushPromises()

    expect(routerMock.replace).toHaveBeenCalledWith({ query: { mode: 'brief', sort: 'title' } })
    // SH-04: status is a chip row now (not a select); click the "completed" chip.
    const statusButtons = wrapper.findAll('[aria-pressed]')
    const completedChip = statusButtons.find(btn => btn.text().includes('已完成')) || statusButtons[1]
    await completedChip.trigger('click')
    expect(routerMock.replace).toHaveBeenLastCalledWith({ query: { status: 'completed', mode: 'brief', sort: 'title' } })
  })

  it('hydrates public session cache before the refresh resolves', async () => {
    let resolveRefresh!: (value: unknown) => void
    listPublicCasesMock.mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve }))
    const cached = publicCase('cached-case', '缓存案例', true)
    sessionStorage.setItem('showcase:public-cases:v2', JSON.stringify({ version: 2, savedAt: Date.now(), cases: [cached] }))
    getPublicCaseMock.mockResolvedValue({ ...cached, result: { title: cached.title, topic: '缓存主题' } })

    const wrapper = mountShowcase()
    await flushPromises()
    expect(wrapper.find('#featured-heading').text()).toContain('缓存案例')
    expect(listPublicCasesMock).toHaveBeenCalledTimes(1)

    resolveRefresh({ cases: [cached], total: 1, limit: 100, offset: 0, featured_public_id: cached.public_id })
    await flushPromises()
    wrapper.unmount()
  })

  it('loads public cases in pages and appends the next page', async () => {
    const firstPage = [publicCase('case-featured', '真实案例标题', true), publicCase('case-other', '第二个案例')]
    const nextPage = [publicCase('case-next', '下一页案例')]
    listPublicCasesMock
      .mockResolvedValueOnce({ cases: firstPage, total: 3, limit: 20, offset: 0, featured_public_id: 'case-featured' })
      .mockResolvedValueOnce({ cases: nextPage, total: 3, limit: 20, offset: 2, featured_public_id: 'case-featured' })

    const wrapper = mountShowcase()
    await flushPromises()
    const loadMore = wrapper.findAll('button').find(button => button.text().includes('加载更多'))
    expect(loadMore?.exists()).toBe(true)

    await loadMore?.trigger('click')
    await flushPromises()

    expect(listPublicCasesMock).toHaveBeenLastCalledWith(
      { limit: 20, offset: 2, sort: 'recent' },
      expect.objectContaining({ suppressToast: true, signal: expect.any(AbortSignal) }),
    )
    expect(wrapper.findAll('.case-card')).toHaveLength(2)
    expect(wrapper.text()).toContain('下一页案例')
    wrapper.unmount()
  })

  it('sets localized public page metadata', async () => {
    const wrapper = mountShowcase()
    await flushPromises()

    expect(document.title).toContain('真实案例')
    expect(document.head.querySelector('meta[property="og:title"]')?.getAttribute('content')).toContain('真实案例')
    wrapper.unmount()
  })

  it('redirects unauthenticated start-creating CTA to /start with source attribution', async () => {
    const wrapper = mountShowcase()
    await flushPromises()

    const startButtons = wrapper.findAll('button').filter(button => button.text().includes('开始创作'))
    expect(startButtons.length).toBeGreaterThan(0)
    await startButtons[0].trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/start?source=showcase' } })
    wrapper.unmount()
  })

  it('sends authenticated start-creating CTA to /start with source attribution', async () => {
    authState.isAuthenticated = true
    const wrapper = mountShowcase()
    await flushPromises()

    const startButtons = wrapper.findAll('button').filter(button => button.text().includes('开始创作'))
    expect(startButtons.length).toBeGreaterThan(0)
    await startButtons[0].trigger('click')
    expect(routerMock.push).toHaveBeenCalledWith({ name: 'home', query: { source: 'showcase' } })
    wrapper.unmount()
  })
})
