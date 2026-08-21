import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AgentTUI from '@/views/AgentTUI.vue'
import { getActiveAccount, listAccounts } from '@/api/accounts'

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
    delete routeQuery.topic
    vi.mocked(listAccounts).mockResolvedValue([])
    vi.mocked(getActiveAccount).mockResolvedValue(null)
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
})
