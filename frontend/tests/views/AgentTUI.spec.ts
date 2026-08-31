import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AgentTUI from '@/views/AgentTUI.vue'
import { getActiveAccount, listAccounts } from '@/api/accounts'
import client from '@/api/client'

const { FakeTerminal, FakeWebSocket, routeQuery } = vi.hoisted(() => {
  class HoistedFakeTerminal {
    static instances: HoistedFakeTerminal[] = []
    cols = 80
    lines: string[] = []
    onDataHandler: ((data: string) => void) | null = null
    onResizeHandler: ((event: { cols: number }) => void) | null = null

    constructor() {
      HoistedFakeTerminal.instances.push(this)
    }

    loadAddon() {}
    open() {}
    focus() {}
    dispose() {}
    buffer = { active: { viewportY: 0, baseY: 0 } }
    onScroll() { return { dispose: vi.fn() } }
    scrollToBottom() {}
    onData(handler: (data: string) => void) {
      this.onDataHandler = handler
      return { dispose: vi.fn() }
    }
    onResize(handler: (event: { cols: number }) => void) {
      this.onResizeHandler = handler
      return { dispose: vi.fn() }
    }
    attachCustomKeyEventHandler() {}
    writeln(line: string) { this.lines.push(line) }
    write(line: string) { this.lines.push(line) }
    clear() {}
    getSelection() { return '' }
    selectAll() {}

    type(text: string) {
      this.onDataHandler?.(text)
    }
  }

  class HoistedFakeWebSocket {
    static readonly CONNECTING = 0
    static readonly OPEN = 1
    static readonly CLOSED = 3
    static instances: HoistedFakeWebSocket[] = []
    readyState = HoistedFakeWebSocket.CONNECTING
    sent: string[] = []
    onopen: (() => void) | null = null
    onmessage: ((event: MessageEvent) => void) | null = null
    onclose: (() => void) | null = null
    onerror: (() => void) | null = null

    constructor(public readonly url: string) {
      HoistedFakeWebSocket.instances.push(this)
    }

    send(payload: string) {
      this.sent.push(payload)
    }

    open() {
      this.readyState = HoistedFakeWebSocket.OPEN
      this.onopen?.()
    }

    close() {
      this.readyState = HoistedFakeWebSocket.CLOSED
      this.onclose?.()
    }
  }

  return {
    FakeTerminal: HoistedFakeTerminal,
    FakeWebSocket: HoistedFakeWebSocket,
    routeQuery: { mode: 'free' } as Record<string, string>,
  }
})

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: routeQuery }),
}))

vi.mock('@/api/accounts', () => ({
  listAccounts: vi.fn().mockResolvedValue([]),
  getActiveAccount: vi.fn().mockResolvedValue(null),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
}))

vi.mock('@xterm/xterm', () => ({
  Terminal: FakeTerminal,
}))
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class { fit() {} },
}))
vi.mock('@xterm/addon-search', () => ({
  SearchAddon: class {
    clearDecorations() {}
    findNext() { return true }
    findPrevious() { return true }
  },
}))
vi.mock('@xterm/addon-web-links', () => ({
  WebLinksAddon: class {},
}))
vi.mock('@xterm/addon-webgl', () => ({
  WebglAddon: class {
    onContextLoss() {}
    dispose() {}
  },
}))
vi.mock('@/api/workflow', () => ({
  startWorkflow: vi.fn(),
  pauseWorkflow: vi.fn(),
  resumeWorkflow: vi.fn(),
  cancelWorkflow: vi.fn(),
  getWorkflowStatus: vi.fn(),
}))
vi.mock('@/api/review', () => ({ submitReview: vi.fn() }))
vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

describe('AgentTUI free creation interaction contract', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    FakeTerminal.instances = []
    FakeWebSocket.instances = []
    sessionStorage.clear()
    routeQuery.mode = 'free'
    delete routeQuery.account_id
    delete routeQuery.draft_id
    delete routeQuery.action
    delete routeQuery.goal
    delete routeQuery.topic
    vi.mocked(listAccounts).mockResolvedValue([])
    vi.mocked(getActiveAccount).mockResolvedValue(null)
    vi.mocked(client.get).mockReset()
    vi.mocked(client.post).mockReset()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      disconnect() {}
    })
  })

  async function mountFreeTui() {
    const wrapper = mount(AgentTUI)
    await flushPromises()
    return { wrapper, terminal: FakeTerminal.instances[0], socket: FakeWebSocket.instances[0] }
  }

  it('dispatches /start from the default Agent mode as a new free session', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()
    socket.open()

    terminal.type('/start')
    terminal.type('\r')
    await flushPromises()

    expect(socket.sent).toContain(JSON.stringify({ type: 'new_session' }))
    expect(terminal.lines.join('\n')).toContain('已开启新会话')
    wrapper.unmount()
  })

  it('queues a creation message while connecting and flushes it after open', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()

    terminal.type('帮我写一篇旅行笔记')
    terminal.type('\r')
    await flushPromises()
    expect(socket.sent).toHaveLength(0)
    expect(terminal.lines.join('\n')).toContain('消息已暂存')
    expect(wrapper.find('.tui-queue-state').text()).toContain('待发送：1')

    socket.open()
    await flushPromises()

    expect(socket.sent).toContain(JSON.stringify({
      type: 'send_message',
      content: '帮我写一篇旅行笔记',
    }))
    expect(terminal.lines.join('\n')).toContain('已发送暂存消息')
    expect(wrapper.find('.tui-queue-state').exists()).toBe(false)
    wrapper.unmount()
  })

  it('starts a new session before messages typed after the reset request', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()

    terminal.type('旧会话里的消息')
    terminal.type('\r')
    terminal.type('/start')
    terminal.type('\r')
    terminal.type('新会话里的消息')
    terminal.type('\r')
    await flushPromises()

    socket.open()
    await flushPromises()

    expect(socket.sent).toEqual([
      JSON.stringify({ type: 'new_session' }),
      JSON.stringify({ type: 'send_message', content: '新会话里的消息' }),
    ])
    expect(terminal.lines.join('\n')).toContain('新会话请求已暂存')
    expect(terminal.lines.join('\n')).toContain('已开启新会话')
    wrapper.unmount()
  })

  it('offers a visible stop action for an active Agent turn', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()
    socket.open()

    terminal.type('帮我写一篇笔记')
    terminal.type('\r')
    await flushPromises()
    expect(wrapper.find('.tui-quick-btn-stop').exists()).toBe(true)

    await wrapper.find('.tui-quick-btn-stop').trigger('click')
    await flushPromises()

    expect(socket.sent).toContain(JSON.stringify({ type: 'abort' }))
    expect(wrapper.find('.tui-running-indicator').exists()).toBe(false)
    expect(terminal.lines.join('\n')).toContain('已请求停止生成')
    wrapper.unmount()
  })

  it('uses the same abort path for Ctrl+C', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()
    socket.open()

    terminal.type('帮我写一篇笔记')
    terminal.type('\r')
    await flushPromises()
    terminal.type('\x03')
    await flushPromises()

    expect(socket.sent).toContain(JSON.stringify({ type: 'abort' }))
    expect(wrapper.find('.tui-running-indicator').exists()).toBe(false)
    wrapper.unmount()
  })

  it('makes the prompt available again when an active turn is interrupted', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()
    socket.open()

    terminal.type('帮我写一篇笔记')
    terminal.type('\r')
    await flushPromises()
    expect(wrapper.find('.tui-running-indicator').exists()).toBe(true)

    socket.close()
    await flushPromises()

    expect(wrapper.find('.tui-running-indicator').exists()).toBe(false)
    expect(terminal.lines.join('\n')).toContain('本轮输出可能未完成')
    wrapper.unmount()
  })

  it('prefills a free-creation example without sending it', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()

    await wrapper.find('.tui-prompt-btn').trigger('click')
    await flushPromises()

    expect(socket.sent).toHaveLength(0)
    expect(terminal.lines.join('\n')).toContain('写一篇小红书笔记')
    wrapper.unmount()
  })

  it('prefills the native mobile input without sending it', async () => {
    const previousWidth = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 375 })
    const { wrapper, socket } = await mountFreeTui()

    await wrapper.find('.tui-prompt-btn').trigger('click')
    await flushPromises()

    expect((wrapper.find('.tui-mobile-input').element as HTMLInputElement).value).toBe('写一篇小红书笔记')
    expect(socket.sent).toHaveLength(0)
    wrapper.unmount()
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: previousWidth })
  })

  it('carries a Start Creating goal into the editable prompt without sending it', async () => {
    routeQuery.topic = '写一篇京都三天亲子旅行笔记'
    const { wrapper, terminal, socket } = await mountFreeTui()

    expect(terminal.lines.join('\n')).toContain('写一篇京都三天亲子旅行笔记')
    expect(socket.sent).toHaveLength(0)
    expect(wrapper.find('.tui-mobile-input').exists()).toBe(false)
    wrapper.unmount()
  })

  it('uses the selected route account for the free workspace context', async () => {
    routeQuery.account_id = 'selected-account'
    vi.mocked(listAccounts).mockResolvedValue([{
      id: 'selected-account',
      name: 'Selected creator',
      niche: 'travel',
      is_active: false,
      created_at: '2026-08-21T00:00:00Z',
    }])
    vi.mocked(getActiveAccount).mockResolvedValue(null)

    const { wrapper } = await mountFreeTui()

    expect(wrapper.find('.tui-account-context').text()).toContain('Selected creator')
    wrapper.unmount()
  })

  it('renders exactly one prompt and one closing rule for a turn with empty message pairs', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()
    socket.open()
    await flushPromises()

    // omp emits empty message pairs (no text blocks) around the real text
    // turn — replay the captured sequence from the live bridge.
    const send = (obj: Record<string, unknown>) =>
      socket.onmessage?.({ data: JSON.stringify(obj) } as MessageEvent)
    const promptCount = () => terminal.lines.filter((l) => l.includes('❯')).length
    const baseline = promptCount()

    terminal.type('hello')
    terminal.type('\r')
    await flushPromises()

    send({ type: 'status', status: 'running' })
    send({ type: 'agent_message', text: '', done: false })
    send({ type: 'agent_message', text: '', done: true })
    send({ type: 'agent_message', text: '', done: false })
    send({ type: 'agent_message', text: '', done: true })
    send({ type: 'agent_message', text: '', done: false })
    send({ type: 'agent_message', text: 'Hello', done: false })
    send({ type: 'agent_message', text: '', done: true })
    send({ type: 'status', status: 'idle' })
    send({ type: 'session_end' })
    await flushPromises()

    // done + idle + session_end collapse into exactly one new prompt
    expect(promptCount() - baseline).toBe(1)
    // only the text turn gets a ◆ ─── closing rule; empty pairs leave nothing
    expect(terminal.lines.filter((l) => l.includes('◆') && l.includes('─'))).toHaveLength(1)
    // typed desktop input stays on its own line (one write chunk from the
    // fake terminal type()) — a second entry would be the removed echo
    expect(terminal.lines.filter((l) => l.includes('hello'))).toHaveLength(1)
    wrapper.unmount()
  })

  it('echoes quick-action commands once since no typed line exists', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()
    socket.open()
    await flushPromises()

    await wrapper.find('.tui-quick-btn:not(.tui-quick-btn-stop)').trigger('click')
    await flushPromises()

    expect(terminal.lines.some((l) => l.includes('❯') && l.includes('/start'))).toBe(true)
    wrapper.unmount()
  })

  it('keeps publishing and manual-copy controls visible in the free command grid', async () => {
    const { wrapper, terminal } = await mountFreeTui()
    const output = terminal.lines.join('\n')

    expect(output).toContain('/publish <id> [confirm]')
    expect(output).toContain('/copy <id>')
    wrapper.unmount()
  })

  it('replies pong to an application-level ping', async () => {
    const { wrapper, socket } = await mountFreeTui()
    socket.open()
    await flushPromises()

    socket.onmessage?.({ data: JSON.stringify({ type: 'ping' }) } as MessageEvent)
    await flushPromises()

    expect(socket.sent).toContain(JSON.stringify({ type: 'pong' }))
    wrapper.unmount()
  })

  it('resumes the same session with a replay cursor after a drop', async () => {
    const { wrapper, socket } = await mountFreeTui()
    socket.open()
    await flushPromises()
    const send = (obj: Record<string, unknown>) =>
      socket.onmessage?.({ data: JSON.stringify(obj) } as MessageEvent)

    send({ type: 'status', status: 'connected', session_id: 'omp_abc', resumed: true })
    send({ type: 'status', status: 'running', session_id: 'omp_abc', seq: 7 })
    await flushPromises()

    // First connect carries no cursor
    expect(FakeWebSocket.instances[0].url).not.toContain('session_id')

    vi.useFakeTimers()
    socket.close()
    await vi.advanceTimersByTimeAsync(3100)

    expect(FakeWebSocket.instances).toHaveLength(2)
    const reconnectUrl = FakeWebSocket.instances[1].url
    expect(reconnectUrl).toContain('mode=free')
    expect(reconnectUrl).toContain('session_id=omp_abc')
    expect(reconnectUrl).toContain('last_seq=7')
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('resets the replay cursor when the backend cannot resume the session', async () => {
    const { wrapper, socket } = await mountFreeTui()
    socket.open()
    await flushPromises()
    const send = (obj: Record<string, unknown>) =>
      socket.onmessage?.({ data: JSON.stringify(obj) } as MessageEvent)

    send({ type: 'status', status: 'connected', session_id: 'omp_abc', resumed: true })
    send({ type: 'status', status: 'running', session_id: 'omp_abc', seq: 7 })
    // Server restarted: same session_id, but a fresh subprocess (no replay)
    send({ type: 'status', status: 'connected', session_id: 'omp_abc', resumed: false })
    await flushPromises()

    vi.useFakeTimers()
    socket.close()
    await vi.advanceTimersByTimeAsync(3100)

    const reconnectUrl = FakeWebSocket.instances[1].url
    expect(reconnectUrl).toContain('session_id=omp_abc')
    expect(reconnectUrl).not.toContain('last_seq')
    wrapper.unmount()
    vi.useRealTimers()
  })

  it('keeps the turn alive across provider retry and compaction statuses', async () => {
    const { wrapper, terminal, socket } = await mountFreeTui()
    socket.open()
    await flushPromises()
    const send = (obj: Record<string, unknown>) =>
      socket.onmessage?.({ data: JSON.stringify(obj) } as MessageEvent)

    terminal.type('帮我写一篇笔记')
    terminal.type('\r')
    await flushPromises()
    expect(wrapper.find('.tui-running-indicator').exists()).toBe(true)

    send({ type: 'status', status: 'running' })
    send({ type: 'status', status: 'retrying' })
    await flushPromises()
    expect(wrapper.find('.tui-running-indicator').exists()).toBe(true)

    send({ type: 'status', status: 'compacting' })
    send({ type: 'status', status: 'running' })
    await flushPromises()
    expect(wrapper.find('.tui-running-indicator').exists()).toBe(true)

    send({ type: 'status', status: 'idle' })
    send({ type: 'session_end' })
    await flushPromises()
    expect(wrapper.find('.tui-running-indicator').exists()).toBe(false)
    wrapper.unmount()
  })

  // ── /publish + /copy ─────────────────────────────────────────────────
  function stubOwnedAccount() {
    routeQuery.account_id = 'acct-1'
    vi.mocked(listAccounts).mockResolvedValue([{
      id: 'acct-1',
      name: 'Owned creator',
      niche: 'travel',
      is_active: false,
      created_at: '2026-08-21T00:00:00Z',
    }])
  }

  function stubDraft(draft: Record<string, unknown>) {
    vi.mocked(client.get).mockResolvedValue({ draft_id: 'd1', draft } as never)
  }

  it('opens an existing free draft from the route deep link', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    stubDraft({
      title: '深链打开的草稿',
      body: '草稿正文',
      hashtags: ['#自由创作'],
    })

    const { wrapper, terminal } = await mountFreeTui()

    expect(client.get).toHaveBeenCalledWith('/free/draft/d1?account_id=acct-1')
    expect(terminal.lines.join('\n')).toContain('深链打开的草稿')
    wrapper.unmount()
  })

  it('opens a publish preview after a publish action deep link without posting', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    routeQuery.action = 'publish'
    stubDraft({
      title: '深链待发布',
      last_evaluation: { overall_score: 88, decision: 'approved' },
    })

    const { wrapper, terminal } = await mountFreeTui()

    expect(client.get).toHaveBeenCalledTimes(2)
    expect(client.get).toHaveBeenNthCalledWith(1, '/free/draft/d1?account_id=acct-1')
    expect(client.get).toHaveBeenNthCalledWith(2, '/free/draft/d1?account_id=acct-1')
    expect(client.post).not.toHaveBeenCalled()
    const out = terminal.lines.join('\n')
    expect(out).toContain('深链待发布')
    expect(out).toContain('发布预览')
    expect(out).toContain('/publish d1 confirm')
    wrapper.unmount()
  })

  it('runs analytics after a real-post deep link while preserving the account', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    routeQuery.action = 'analytics'
    vi.mocked(client.get)
      .mockResolvedValueOnce({
        draft_id: 'd1',
        draft: { title: '深链真实帖子', published: true, post_id: 'post_9' },
      } as never)
      .mockResolvedValueOnce({
        draft_id: 'd1',
        post_id: 'post_9',
        analytics: { views: 1200, likes: 88, collects: 21, engagement_rate: 5.2 },
      } as never)

    const { wrapper, terminal } = await mountFreeTui()

    expect(client.get).toHaveBeenNthCalledWith(1, '/free/draft/d1?account_id=acct-1')
    expect(client.get).toHaveBeenNthCalledWith(2, '/free/analytics/d1?account_id=acct-1')
    expect(client.post).not.toHaveBeenCalled()
    const out = terminal.lines.join('\n')
    expect(out).toContain('深链真实帖子')
    expect(out).toContain('草稿数据分析')
    expect(out).toContain('1200')
    wrapper.unmount()
  })

  it('does not run analytics when a valid analytics action targets a mock post', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    routeQuery.action = 'analytics'
    stubDraft({ title: '模拟发布草稿', published: true, post_id: 'mock_dry_run' })

    const { wrapper, terminal } = await mountFreeTui()

    expect(client.get).toHaveBeenCalledTimes(1)
    expect(client.get).toHaveBeenCalledWith('/free/draft/d1?account_id=acct-1')
    expect(client.post).not.toHaveBeenCalled()
    const out = terminal.lines.join('\n')
    expect(out).toContain('模拟发布草稿')
    expect(out).toContain('模拟发布')
    expect(out).not.toContain('/analytics d1')
    wrapper.unmount()
  })

  it('treats unknown and unsafe deep-link actions as ordinary draft links', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    routeQuery.action = 'delete'
    stubDraft({ title: '未知动作草稿', published: true, post_id: 'mock_dry_run' })

    const { wrapper, terminal } = await mountFreeTui()

    expect(client.get).toHaveBeenCalledTimes(1)
    expect(client.post).not.toHaveBeenCalled()
    expect(terminal.lines.join('\n')).toContain('未知动作草稿')
    expect(terminal.lines.join('\n')).toContain('模拟发布')
    wrapper.unmount()
  })

  it('prefers the explicit goal query over the legacy topic query', async () => {
    routeQuery.goal = '为新手整理一份护肤入门清单'
    routeQuery.topic = '旧链接里的主题'
    const { wrapper, terminal, socket } = await mountFreeTui()

    expect(terminal.lines.join('\n')).toContain('为新手整理一份护肤入门清单')
    expect(terminal.lines.join('\n')).not.toContain('旧链接里的主题')
    expect(socket.sent).toHaveLength(0)
    wrapper.unmount()
  })

  it('previews a publish without confirm and never posts', async () => {
    stubOwnedAccount()
    stubDraft({
      title: '京都亲子三日',
      body: '正文',
      hashtags: ['#旅行'],
      last_evaluation: { overall_score: 88, decision: 'approved' },
    })
    const { wrapper, terminal } = await mountFreeTui()

    terminal.type('/publish d1')
    terminal.type('\r')
    await flushPromises()

    expect(client.post).not.toHaveBeenCalled()
    const out = terminal.lines.join('\n')
    expect(out).toContain('发布预览')
    expect(out).toContain('京都亲子三日')
    expect(out).toContain('/publish d1 confirm')
    wrapper.unmount()
  })

  it('refuses to publish on a degraded evaluation', async () => {
    stubOwnedAccount()
    stubDraft({
      title: '降级草稿',
      last_evaluation: { degraded: true, decision: 'approved', overall_score: 100 },
    })
    const { wrapper, terminal } = await mountFreeTui()

    terminal.type('/publish d1 confirm')
    terminal.type('\r')
    await flushPromises()

    expect(client.post).not.toHaveBeenCalled()
    expect(terminal.lines.join('\n')).toContain('降级')
    wrapper.unmount()
  })

  it('refuses to re-publish a draft that already has a real post', async () => {
    stubOwnedAccount()
    stubDraft({
      title: '已发布草稿',
      published: true,
      post_id: 'post_9',
      post_url: 'https://xhs.link/9',
    })
    const { wrapper, terminal } = await mountFreeTui()

    terminal.type('/publish d1 confirm')
    terminal.type('\r')
    await flushPromises()

    expect(client.post).not.toHaveBeenCalled()
    const out = terminal.lines.join('\n')
    expect(out).toContain('已发布')
    expect(out).toContain('/analytics d1')
    wrapper.unmount()
  })

  it('publishes through the free endpoint once confirmed', async () => {
    stubOwnedAccount()
    stubDraft({
      title: '确认发布草稿',
      last_evaluation: { overall_score: 82, decision: 'approved' },
    })
    vi.mocked(client.post).mockResolvedValue({
      draft_id: 'd1',
      publish_result: {
        status: 'published',
        post_id: 'post_11',
        post_url: 'https://xhs.link/11',
      },
    } as never)
    const { wrapper, terminal } = await mountFreeTui()

    terminal.type('/publish d1 confirm')
    terminal.type('\r')
    await flushPromises()

    expect(client.post).toHaveBeenCalledWith('/free/publish', {
      account_id: 'acct-1',
      draft_id: 'd1',
    })
    const out = terminal.lines.join('\n')
    expect(out).toContain('已发布：确认发布草稿')
    expect(out).toContain('https://xhs.link/11')
    wrapper.unmount()
  })

  it('renders a publish failure with its recorded cause', async () => {
    stubOwnedAccount()
    stubDraft({ title: '失败草稿' })
    vi.mocked(client.post).mockResolvedValue({
      draft_id: 'd1',
      publish_result: {
        status: 'auth_expired',
        error: 'login required',
        error_type: 'AuthExpired',
      },
    } as never)
    const { wrapper, terminal } = await mountFreeTui()

    terminal.type('/publish d1 confirm')
    terminal.type('\r')
    await flushPromises()

    const out = terminal.lines.join('\n')
    expect(out).toContain('发布失败')
    expect(out).toContain('auth_expired')
    expect(out).toContain('/draft d1')
    wrapper.unmount()
  })

  // ── post-publish feedback loop: persisted engagement snapshot ─────────
  it('notes the saved snapshot after a successful /analytics fetch', async () => {
    stubOwnedAccount()
    vi.mocked(client.get).mockResolvedValue({
      draft_id: 'd1',
      post_id: 'post_9',
      analytics: {
        views: 1200,
        likes: 88,
        collects: 21,
        comments: 9,
        shares: 3,
        engagement_rate: 5.2,
        fetched_at: '2026-08-24 10:00:00',
      },
    } as never)
    const { wrapper, terminal } = await mountFreeTui()

    terminal.type('/analytics d1')
    terminal.type('\r')
    await flushPromises()

    const out = terminal.lines.join('\n')
    expect(out).toContain('1200')
    expect(out).toContain('快照已保存到草稿')
    wrapper.unmount()
  })

  it('shows the persisted engagement snapshot inside the draft detail card', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    stubDraft({
      title: '有表现的草稿',
      published: true,
      post_id: 'post_9',
      post_url: 'https://xhs.link/9',
      last_analytics: {
        post_id: 'post_9',
        views: 1500,
        likes: 320,
        collects: 80,
        comments: 45,
        shares: 12,
        engagement_rate: 30.47,
        fetched_at: '2026-08-24T09:30:00+00:00',
      },
    })
    const { wrapper, terminal } = await mountFreeTui()

    const out = terminal.lines.join('\n')
    expect(out).toContain('最近表现')
    expect(out).toContain('1500')
    expect(out).toContain('320')
    expect(out).toContain('80')
    wrapper.unmount()
  })

  it('omits the engagement line when the draft has no snapshot yet', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    stubDraft({ title: '无快照草稿', published: true, post_id: 'post_8' })
    const { wrapper, terminal } = await mountFreeTui()

    expect(terminal.lines.join('\n')).not.toContain('最近表现')
    wrapper.unmount()
  })

  // ── snapshot trend series: views movement between captures ────────────
  it('shows the views trend inside the detail card once two snapshots exist', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    stubDraft({
      title: '有走势的草稿',
      published: true,
      post_id: 'post_9',
      last_analytics: {
        post_id: 'post_9',
        views: 350,
        likes: 70,
        collects: 17,
        comments: 11,
        shares: 2,
        engagement_rate: 28.57,
        fetched_at: '2026-08-25T09:30:00+00:00',
      },
      analytics_snapshots: [
        { views: 150 },
        { views: 350 },
      ],
    })
    const { wrapper, terminal } = await mountFreeTui()

    const out = terminal.lines.join('\n')
    expect(out).toContain('走势')
    expect(out).toContain('+200')
    expect(out).not.toContain('-0 浏览')
    wrapper.unmount()
  })

  it('shows a negative trend with the minus sign and no trend line below two snapshots', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    stubDraft({
      title: '下滑草稿',
      published: true,
      post_id: 'post_9',
      last_analytics: {
        post_id: 'post_9',
        views: 90,
        likes: 18,
        collects: 4,
        comments: 3,
        shares: 0,
        engagement_rate: 27.78,
        fetched_at: '2026-08-25T09:30:00+00:00',
      },
      analytics_snapshots: [{ views: 400 }, { views: 90 }],
    })
    const { wrapper, terminal } = await mountFreeTui()

    const out = terminal.lines.join('\n')
    expect(out).toContain('-310')
    wrapper.unmount()
  })

  it('omits the trend line when fewer than two snapshots exist', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    stubDraft({
      title: '单点快照草稿',
      published: true,
      post_id: 'post_9',
      last_analytics: {
        post_id: 'post_9',
        views: 500,
        likes: 100,
        collects: 25,
        comments: 16,
        shares: 5,
        engagement_rate: 29.2,
        fetched_at: '2026-08-25T09:30:00+00:00',
      },
      analytics_snapshots: [{ views: 500 }],
    })
    const { wrapper, terminal } = await mountFreeTui()

    expect(terminal.lines.join('\n')).toContain('最近表现')
    expect(terminal.lines.join('\n')).not.toContain('走势')
    wrapper.unmount()
  })

  // ── creative-memory anchors display ───────────────────────────────────
  it('shows the anchors line with style, play and material count', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    stubDraft({
      title: '锚定草稿',
      style_id: 'style_治愈',
      play_id: 'p_9',
      material_ids: ['m1', 'm2'],
    })
    const { wrapper, terminal } = await mountFreeTui()

    const out = terminal.lines.join('\n')
    expect(out).toContain('锚定')
    expect(out).toContain('风格 style_治愈')
    expect(out).toContain('打法 p_9')
    expect(out).toContain('素材 ×2')
    wrapper.unmount()
  })

  it('omits the anchors line when the draft has no anchors', async () => {
    stubOwnedAccount()
    routeQuery.draft_id = 'd1'
    stubDraft({ title: '普通草稿' })
    const { wrapper, terminal } = await mountFreeTui()

    expect(terminal.lines.join('\n')).not.toContain('锚定：')
    wrapper.unmount()
  })

  it('copies title, body and hashtags to the clipboard', async () => {
    stubOwnedAccount()
    stubDraft({
      title: '复制草稿',
      body: '第一行\n第二行',
      hashtags: ['#旅行', '#亲子'],
    })
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const { wrapper, terminal } = await mountFreeTui()

    terminal.type('/copy d1')
    terminal.type('\r')
    await flushPromises()

    expect(writeText).toHaveBeenCalledWith('复制草稿\n\n第一行\n第二行\n\n#旅行 #亲子')
    expect(terminal.lines.join('\n')).toContain('已复制到剪贴板')
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('falls back to a manual-selection hint when the clipboard fails', async () => {
    stubOwnedAccount()
    stubDraft({ title: '剪贴板失败', body: '正文' })
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const { wrapper, terminal } = await mountFreeTui()

    terminal.type('/copy d1')
    terminal.type('\r')
    await flushPromises()

    const out = terminal.lines.join('\n')
    expect(out).toContain('剪贴板不可用')
    expect(out).toContain('/draft d1')
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('rejects free-only commands outside free mode', async () => {
    routeQuery.mode = 'trend'
    const { wrapper, terminal } = await mountFreeTui()

    terminal.type('/publish d1 confirm')
    terminal.type('\r')
    await flushPromises()

    expect(client.get).not.toHaveBeenCalled()
    expect(client.post).not.toHaveBeenCalled()
    expect(terminal.lines.join('\n')).toContain('自由创作模式与工作流完全隔离')
    wrapper.unmount()
  })
})
