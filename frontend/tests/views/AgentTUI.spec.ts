import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AgentTUI from '@/views/AgentTUI.vue'

const { FakeTerminal, FakeWebSocket } = vi.hoisted(() => {
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
  }
})

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { mode: 'free' } }),
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
})
