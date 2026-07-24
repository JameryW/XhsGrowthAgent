<script setup lang="ts">
/**
 * AgentTUI — xterm.js-powered terminal page for XhsGrowthAgent.
 *
 * Two modes:
 * 1. Agent mode (default): WebSocket to omp bridge for AI agent conversation
 * 2. Command mode (fallback): direct API calls for workflow operations
 *
 * v6 upgrade: import from '@xterm/xterm', no canvas addon (removed in v6).
 * CJK: IME composition tracking, wcwidth-aware cursor, CJK font stack.
 * UX: search, shortcuts, copy/paste, right-click menu, WebGL renderer.
 * Mobile: native input bar, visualViewport, responsive layout.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { SearchAddon } from '@xterm/addon-search'
import { WebglAddon } from '@xterm/addon-webgl'
import '@xterm/xterm/css/xterm.css'
import { useAccountsStore, useWorkflowStore } from '@/stores'
import {
  startWorkflow,
  pauseWorkflow,
  resumeWorkflow,
  cancelWorkflow,
  getWorkflowStatus,
} from '@/api/workflow'
import { submitReview } from '@/api/review'
import client from '@/api/client'
import { markdownToAnsi, ANSI } from '@/utils/markdownToAnsi'
import {
  getStringWidth,
  padEndDisplay,
  truncateDisplay,
  wrapDisplay,
  cardWidth,
  writeBoxTitle,
  boxLine,
  boxBottom,
  hr,
  kvLine,
  badge,
  writeEmptyState,
  writeError,
} from '@/utils/ansiCards'

const { t } = useI18n()
const route = useRoute()
const workflowStore = useWorkflowStore()
const accountsStore = useAccountsStore()

// Keep the free-mode boundary close to the route so every input surface can
// make the same decision. Free mode is intentionally thread-less.
const isFreeCreationEntry = computed(() => route.query.mode === 'free')
const freeCreationTopic = computed(() => (
  typeof route.query.topic === 'string' ? route.query.topic : ''
))

/** Resolve the selected XHS account, not the console user's UUID. */
async function getCurrentAccountId(): Promise<string> {
  if (!accountsStore.activeAccountId) {
    await accountsStore.fetchAccounts()
  }
  return accountsStore.activeAccountId || 'default'
}

// ── Mobile detection ──────────────────────────────────────────────────
const isMobile = computed(() =>
  'ontouchstart' in window || navigator.maxTouchPoints > 0 || window.innerWidth < 768,
)

// ── xterm.js setup ──────────────────────────────────────────────────────
const termRef = ref<HTMLDivElement | null>(null)
let term: Terminal | null = null
let fitAddon: FitAddon | null = null
let searchAddon: SearchAddon | null = null

// ── State ───────────────────────────────────────────────────────────────
const activeThreadId = ref<string | null>(null)
const isProcessing = ref(false)
// Distinguish an in-flight Agent turn from local free-mode commands such as
// /suggest and /drafts. The stop control is driven by this narrower state.
const agentTurnProcessing = ref(false)
const currentInput = ref('')
const cursorPos = ref(0)
const commandHistory = ref<string[]>([])
const historyIndex = ref(-1)

type TuiMode = 'agent' | 'command'
const mode = ref<TuiMode>('command')

// ── IME composition tracking ──────────────────────────────────────────
let isComposing = false

// ── Search state ──────────────────────────────────────────────────────
const searchVisible = ref(false)
const searchQuery = ref('')
const searchCaseSensitive = ref(false)
const searchRegex = ref(false)
const searchResultInfo = ref('')

// ── Context menu state ────────────────────────────────────────────────
const contextMenuVisible = ref(false)
const contextMenuPos = ref({ x: 0, y: 0 })
const contextMenuHasSelection = ref(false)

// ── Mobile input state ────────────────────────────────────────────────
const mobileInput = ref('')

// ── Agent mode: WebSocket ───────────────────────────────────────────────
// Base WS URL — mode query param appended in connectAgentWs based on
// isFreeCreationEntry so free mode sessions register the free tool subset.
const WS_BASE_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/agent/ws`
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
const MAX_RECONNECT_ATTEMPTS = 3
const wsConnected = ref(false)
const wsConnecting = ref(false)
const wsStatus = ref<'idle' | 'running' | 'streaming'>('idle')
const MAX_PENDING_AGENT_MESSAGES = 5
// Messages typed while the free-mode socket is connecting are kept only for
// this component instance. They must never leak into another account/session.
const pendingAgentMessages: string[] = []
const pendingAgentMessageCount = ref(0)
// A new-session request is kept separately so it can invalidate older queued
// messages and be sent before messages typed after the reset request.
let pendingFreeNewSession = false
// Whether the ◆ AI turn marker has been emitted for the in-flight reply.
// Reset when the turn closes (done / error / session_end / disconnect).
let aiTurnMarkerShown = false

// ── Terminal column tracking (for adaptive markdown width) ────────────
let termCols = 80

// ── Terminal helpers ────────────────────────────────────────────────────

function writeLine(text: string) {
  term?.writeln(text)
}

function write(text: string) {
  term?.write(text)
}

function writeLineColored(text: string, color: string) {
  writeLine(`${color}${text}${ANSI.RESET}`)
}

/** Pad a label string to a fixed display width (accounting for CJK width) for aligned terminal output */
function padLabel(label: string, width: number): string {
  const w = getStringWidth(label)
  return w >= width ? label : label + ' '.repeat(width - w)
}

function writePrompt() {
  const prompt = isProcessing.value
    ? `${ANSI.DIM}⏳${ANSI.RESET} `
    : mode.value === 'agent' && wsConnected.value
      ? `${ANSI.BRIGHT_GREEN}❯${ANSI.RESET} `
      : `${ANSI.BRIGHT_CYAN}❯${ANSI.RESET} `
  write(prompt)
}

/** Clear current input line and rewrite — uses display width for cursor positioning */
function refreshInputLine() {
  if (!term) return
  term.write('\r\x1b[2K')
  writePrompt()
  if (currentInput.value) {
    term.write(currentInput.value)
    // Position cursor: move left by the width of text after cursor
    const afterCursor = currentInput.value.slice(cursorPos.value)
    const afterWidth = getStringWidth(afterCursor)
    if (afterWidth > 0) term.write(`\x1b[${afterWidth}D`)
  }
}

// ── Command history ─────────────────────────────────────────────────────

const MAX_HISTORY = 100

function pushHistory(cmd: string) {
  if (!cmd.trim()) return
  if (commandHistory.value[commandHistory.value.length - 1] !== cmd) {
    commandHistory.value.push(cmd)
    if (commandHistory.value.length > MAX_HISTORY) commandHistory.value.shift()
  }
  historyIndex.value = -1
}

function historyUp() {
  if (commandHistory.value.length === 0) return
  if (historyIndex.value < commandHistory.value.length - 1) {
    historyIndex.value++
    currentInput.value = commandHistory.value[commandHistory.value.length - 1 - historyIndex.value]
    cursorPos.value = currentInput.value.length
    refreshInputLine()
  }
}

function historyDown() {
  if (historyIndex.value > 0) {
    historyIndex.value--
    currentInput.value = commandHistory.value[commandHistory.value.length - 1 - historyIndex.value]
  } else if (historyIndex.value === 0) {
    historyIndex.value = -1
    currentInput.value = ''
  } else {
    return
  }
  cursorPos.value = currentInput.value.length
  refreshInputLine()
}

// ── Tab completion ──────────────────────────────────────────────────────

const SLASH_COMMANDS = [
  '/start', '/status', '/pause', '/resume', '/cancel',
  '/approve', '/reject', '/mode', '/help', '/clear', '/new', '/abort', '/drafts', '/draft', '/delete', '/analytics', '/edit', '/evaluate', '/suggest',
]

function tabComplete() {
  const input = currentInput.value
  if (!input.startsWith('/')) return

  const matches = SLASH_COMMANDS.filter(c => c.startsWith(input))
  if (matches.length === 1) {
    currentInput.value = matches[0] + ' '
    cursorPos.value = currentInput.value.length
    refreshInputLine()
  } else if (matches.length > 1) {
    writeLine('')
    writeLineColored(matches.join('  '), ANSI.DIM)
    writePrompt()
    term?.write(currentInput.value)
  }
}

// ── Input handling (CJK-aware) ──────────────────────────────────────────

function handleTermData(data: string) {
  if (!term) return

  // During IME composition, ignore intermediate data
  if (isComposing) return

  const code = data.charCodeAt(0)

  if (data === '\r') {
    // Enter
    const cmd = currentInput.value
    writeLine('')
    currentInput.value = ''
    cursorPos.value = 0
    historyIndex.value = -1
    if (cmd.trim()) {
      pushHistory(cmd.trim())
      processCommand(cmd)
    } else {
      writePrompt()
    }
  } else if (data === '\x7f' || data === '\b') {
    // Backspace — delete one codepoint before cursor
    if (cursorPos.value > 0) {
      // For CJK: one backspace deletes one codepoint (which may be width 2)
      const before = currentInput.value.slice(0, cursorPos.value - 1)
      const after = currentInput.value.slice(cursorPos.value)
      currentInput.value = before + after
      cursorPos.value--
      refreshInputLine()
    }
  } else if (data === '\t') {
    tabComplete()
  } else if (data === '\x03') {
    // Ctrl+C
    if (mode.value === 'agent' && agentTurnProcessing.value) {
      requestAgentAbort(false)
    }
    writeLineColored('^C', ANSI.YELLOW)
    currentInput.value = ''
    cursorPos.value = 0
    writePrompt()
  } else if (data === '\x1b[A') {
    historyUp()
  } else if (data === '\x1b[B') {
    historyDown()
  } else if (data === '\x1b[C') {
    // Right arrow — move by one codepoint
    if (cursorPos.value < currentInput.value.length) {
      cursorPos.value++
      refreshInputLine()
    }
  } else if (data === '\x1b[D') {
    // Left arrow
    if (cursorPos.value > 0) {
      cursorPos.value--
      refreshInputLine()
    }
  } else if (data === '\x1b[3~') {
    // Delete (forward)
    if (cursorPos.value < currentInput.value.length) {
      const before = currentInput.value.slice(0, cursorPos.value)
      const after = currentInput.value.slice(cursorPos.value + 1)
      currentInput.value = before + after
      refreshInputLine()
    }
  } else if (data === '\x1b[H') {
    // Home
    cursorPos.value = 0
    refreshInputLine()
  } else if (data === '\x1b[F') {
    // End
    cursorPos.value = currentInput.value.length
    refreshInputLine()
  } else if (code >= 32) {
    // Printable character — including CJK, emoji, etc.
    // data may be multi-character (IME composition result)
    const before = currentInput.value.slice(0, cursorPos.value)
    const after = currentInput.value.slice(cursorPos.value)
    currentInput.value = before + data + after
    cursorPos.value += [...data].length // advance by grapheme count
    if (after) {
      term.write(data + after)
      const afterWidth = getStringWidth(after)
      if (afterWidth > 0) term.write(`\x1b[${afterWidth}D`)
    } else {
      term.write(data)
    }
  }
}

// ── Keyboard shortcuts (via attachCustomKeyEventHandler) ──────────────

function setupKeyEventHandler() {
  if (!term) return
  term.attachCustomKeyEventHandler((ev: KeyboardEvent) => {
    if (ev.type !== 'keydown') return true

    // Ctrl+Shift+F: toggle search
    if (ev.ctrlKey && ev.shiftKey && ev.key === 'F') {
      toggleSearch()
      return false
    }
    // Ctrl+L: clear screen
    if (ev.ctrlKey && !ev.shiftKey && ev.key === 'l') {
      term?.clear()
      writePrompt()
      return false
    }
    // Ctrl+U: clear input line
    if (ev.ctrlKey && ev.key === 'u') {
      currentInput.value = ''
      cursorPos.value = 0
      refreshInputLine()
      return false
    }
    // Ctrl+W: delete word backward
    if (ev.ctrlKey && ev.key === 'w') {
      if (cursorPos.value > 0) {
        const before = currentInput.value.slice(0, cursorPos.value)
        const after = currentInput.value.slice(cursorPos.value)
        const trimmed = before.replace(/\S+\s*$/, '')
        currentInput.value = trimmed + after
        cursorPos.value = trimmed.length
        refreshInputLine()
      }
      return false
    }
    // Ctrl+A: cursor to start
    if (ev.ctrlKey && ev.key === 'a' && !ev.shiftKey) {
      cursorPos.value = 0
      refreshInputLine()
      return false
    }
    // Ctrl+E: cursor to end
    if (ev.ctrlKey && ev.key === 'e') {
      cursorPos.value = currentInput.value.length
      refreshInputLine()
      return false
    }
    // Ctrl+K: kill to end of line
    if (ev.ctrlKey && ev.key === 'k') {
      currentInput.value = currentInput.value.slice(0, cursorPos.value)
      refreshInputLine()
      return false
    }
    // Ctrl+Shift+C: copy selection
    if (ev.ctrlKey && ev.shiftKey && ev.key === 'C') {
      copySelection()
      return false
    }
    // Ctrl+Shift+V: paste
    if (ev.ctrlKey && ev.shiftKey && ev.key === 'V') {
      pasteFromClipboard()
      return false
    }
    // Escape: close search / context menu
    if (ev.key === 'Escape') {
      if (searchVisible.value) { closeSearch(); return false }
      if (contextMenuVisible.value) { closeContextMenu(); return false }
    }
    return true
  })
}

// ── Search ─────────────────────────────────────────────────────────────

function toggleSearch() {
  searchVisible.value = !searchVisible.value
  if (!searchVisible.value) {
    searchAddon?.clearDecorations()
    searchResultInfo.value = ''
  }
}

function closeSearch() {
  searchVisible.value = false
  searchAddon?.clearDecorations()
  searchResultInfo.value = ''
  term?.focus()
}

function doSearch(direction: 'next' | 'prev') {
  if (!searchAddon || !searchQuery.value) return
  const opts = {
    caseSensitive: searchCaseSensitive.value,
    regex: searchRegex.value,
    decorations: {
      matchBackground: '#33467c',
      matchBorder: '#7aa2f7',
      matchOverviewRuler: '#7aa2f7',
      activeMatchBackground: '#bb9af7',
      activeMatchBorder: '#c0caf5',
      activeMatchColorOverviewRuler: '#bb9af7',
    },
  }
  const found = direction === 'next'
    ? searchAddon.findNext(searchQuery.value, opts)
    : searchAddon.findPrevious(searchQuery.value, opts)
  // ponytail: searchAddon doesn't expose result count directly in v6; show found/not-found
  searchResultInfo.value = found ? '' : ' (not found)'
}

function onSearchInput() {
  if (!searchAddon || !searchQuery.value) {
    searchAddon?.clearDecorations()
    searchResultInfo.value = ''
    return
  }
  doSearch('next')
}

// ── Clipboard ──────────────────────────────────────────────────────────

async function copySelection() {
  const sel = term?.getSelection()
  if (!sel) return
  try {
    await navigator.clipboard.writeText(sel)
  } catch { /* clipboard API may fail in non-HTTPS */ }
}

async function pasteFromClipboard() {
  try {
    const text = await navigator.clipboard.readText()
    if (text) injectInput(text)
  } catch { /* clipboard API may fail */ }
}

/** Inject text into the terminal input buffer (for paste, mobile input, etc.) */
function injectInput(text: string) {
  if (!term) return
  // Strip carriage returns; keep newlines as Enter
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')
  for (let i = 0; i < lines.length; i++) {
    if (i > 0) {
      // Simulate Enter
      const cmd = currentInput.value
      writeLine('')
      currentInput.value = ''
      cursorPos.value = 0
      if (cmd.trim()) {
        pushHistory(cmd.trim())
        processCommand(cmd)
      } else {
        writePrompt()
      }
    }
    if (lines[i]) {
      // Inject as if typed
      handleTermData(lines[i])
    }
  }
}

// ── Context menu ───────────────────────────────────────────────────────

function handleContextMenu(ev: MouseEvent) {
  ev.preventDefault()
  contextMenuPos.value = { x: ev.clientX, y: ev.clientY }
  contextMenuHasSelection.value = !!term?.getSelection()
  contextMenuVisible.value = true
}

function closeContextMenu() {
  contextMenuVisible.value = false
}

function menuCopy() {
  copySelection()
  closeContextMenu()
}

function menuPaste() {
  pasteFromClipboard()
  closeContextMenu()
}

function menuSelectAll() {
  term?.selectAll()
  closeContextMenu()
}

function menuSearch() {
  closeContextMenu()
  searchVisible.value = true
}

function menuClear() {
  term?.clear()
  writePrompt()
  closeContextMenu()
}

// ── Mobile input ───────────────────────────────────────────────────────

function submitMobileInput() {
  const text = mobileInput.value
  if (!text.trim()) return
  injectInput(text)
  mobileInput.value = ''
}

function runQuickAction(command: string) {
  if (isProcessing.value) return
  void processCommand(command)
}

/** Put a natural-language example into the active input surface without
 * sending it. The user can edit the example before committing a request that
 * may create or update a draft. */
function prefillFreePrompt(prompt: string) {
  if (isProcessing.value) return
  if (isMobile.value) {
    mobileInput.value = prompt
    return
  }
  currentInput.value = prompt
  cursorPos.value = prompt.length
  historyIndex.value = -1
  refreshInputLine()
  term?.focus()
}

// ── WebSocket ───────────────────────────────────────────────────────────

function connectAgentWs() {
  // A manual retry can happen while an automatic retry is already opening a
  // socket. Reusing that attempt avoids duplicate agent sessions and mixed
  // event streams.
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  wsConnecting.value = true

  // Free mode appends ?mode=free so the backend registers only the free-mode
  // tool subset (no thread-bound workflow tools visible to the LLM).
  const wsUrl = isFreeCreationEntry.value
    ? `${WS_BASE_URL}?mode=free`
    : WS_BASE_URL
  let socket: WebSocket
  try {
    socket = new WebSocket(wsUrl)
  } catch {
    wsConnecting.value = false
    writeLineColored(
      isFreeCreationEntry.value ? t('tui.freeAgentUnavailable') : t('tui.agentUnavailable'),
      ANSI.YELLOW,
    )
    return
  }
  ws = socket

  socket.onopen = () => {
    if (ws !== socket) return
    wsConnected.value = true
    wsConnecting.value = false
    reconnectAttempts = 0
    mode.value = 'agent'
    writeLineColored(t('tui.agentConnected'), ANSI.BRIGHT_GREEN)
    const { queuedCount, startedNewSession } = flushPendingAgentMessages()
    if (startedNewSession) {
      writeLineColored(t('tui.freeNewSession'), ANSI.BRIGHT_GREEN)
    }
    if (queuedCount > 0) {
      isProcessing.value = true
      writeLineColored(t('tui.freeQueuedMessagesSent', { count: queuedCount }), ANSI.DIM)
    } else {
      writePrompt()
    }
  }

  socket.onmessage = (ev: MessageEvent) => {
    if (ws !== socket) return
    try {
      const event = JSON.parse(ev.data)
      handleAgentEvent(event)
    } catch { /* ignore malformed */ }
  }

  socket.onclose = () => {
    if (ws !== socket) return
    wsConnected.value = false
    wsConnecting.value = false
    aiTurnMarkerShown = false
    if (isFreeCreationEntry.value && isProcessing.value) {
      // A disconnected stream cannot be resumed by this TUI instance. Make
      // the prompt usable again instead of leaving it in a permanent busy
      // state after a successful reconnect.
      isProcessing.value = false
      writeLineColored(t('tui.agentTurnInterrupted'), ANSI.YELLOW)
    }
    agentTurnProcessing.value = false
    if (mode.value === 'agent') {
      mode.value = 'command'
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++
        wsConnecting.value = true
        writeLineColored(t('tui.agentDisconnected', { cur: reconnectAttempts, max: MAX_RECONNECT_ATTEMPTS }), ANSI.YELLOW)
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null
          connectAgentWs()
        }, 3000)
      } else {
        writeLineColored(t('tui.agentDisconnectedMax'), ANSI.RED)
        isProcessing.value = false
        writePrompt()
      }
    }
  }

  socket.onerror = () => { /* onclose will fire */ }
}

function disconnectAgentWs() {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = null
  wsConnecting.value = false
  const socket = ws
  ws = null
  socket?.close()
  wsConnected.value = false
  agentTurnProcessing.value = false
}

function sendAgentMessage(msg: Record<string, unknown>): boolean {
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify(msg))
      return true
    } catch {
      return false
    }
  }
  return false
}

function queueFreeAgentMessage(text: string) {
  if (pendingAgentMessages.length >= MAX_PENDING_AGENT_MESSAGES) {
    pendingAgentMessages.shift()
    writeLineColored(t('tui.freeMessageQueueFull'), ANSI.YELLOW)
  }
  pendingAgentMessages.push(text)
  pendingAgentMessageCount.value = pendingAgentMessages.length
  writeLineColored(t('tui.freeMessageQueued'), ANSI.YELLOW)
}

function clearPendingAgentMessages() {
  pendingAgentMessages.length = 0
  pendingAgentMessageCount.value = 0
}

function flushPendingAgentMessages(): { queuedCount: number; startedNewSession: boolean } {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    return { queuedCount: 0, startedNewSession: false }
  }

  let startedNewSession = false
  if (pendingFreeNewSession) {
    if (!sendAgentMessage({ type: 'new_session' })) {
      return { queuedCount: 0, startedNewSession: false }
    }
    pendingFreeNewSession = false
    agentTurnProcessing.value = false
    startedNewSession = true
  }

  let queuedCount = 0
  while (pendingAgentMessages.length > 0) {
    const content = pendingAgentMessages[0]
    if (!sendAgentMessage({ type: 'send_message', content })) break
    pendingAgentMessages.shift()
    pendingAgentMessageCount.value = pendingAgentMessages.length
    queuedCount++
  }
  if (queuedCount > 0) agentTurnProcessing.value = true
  return { queuedCount, startedNewSession }
}

function sendFreeNewSession() {
  // Any messages waiting before /start belong to the old context and must
  // never cross the session boundary.
  clearPendingAgentMessages()
  pendingFreeNewSession = true
  agentTurnProcessing.value = false
  if (sendAgentMessage({ type: 'new_session' })) {
    pendingFreeNewSession = false
    writeLineColored(t('tui.freeNewSession'), ANSI.BRIGHT_GREEN)
  } else {
    writeLineColored(t('tui.freeNewSessionQueued'), ANSI.YELLOW)
  }
}

function requestAgentAbort(writeTerminalPrompt = true) {
  const sent = sendAgentMessage({ type: 'abort' })
  agentTurnProcessing.value = false
  isProcessing.value = false
  writeLineColored(
    sent ? t('tui.agentAbortRequested') : (isFreeCreationEntry.value ? t('tui.freeAgentUnavailable') : t('tui.agentUnavailable')),
    ANSI.YELLOW,
  )
  if (writeTerminalPrompt) writePrompt()
}

function retryFreeAgentConnection() {
  if (!isFreeCreationEntry.value || wsConnected.value || wsConnecting.value) return
  reconnectAttempts = 0
  mode.value = 'agent'
  writeLineColored(t('tui.agentRetrying'), ANSI.YELLOW)
  connectAgentWs()
}

function handleAgentEvent(event: Record<string, unknown>) {
  const type = event.type as string

  if (type === 'ready') {
    writeLineColored(t('tui.agentReady'), ANSI.BRIGHT_GREEN)
    wsStatus.value = 'idle'
    writePrompt()
  } else if (type === 'agent_message') {
    const text = event.text as string
    const done = event.done as boolean
    if (!done && text) {
      if (!aiTurnMarkerShown) {
        // Turn marker makes consecutive AI replies distinguishable in scrollback
        writeLine(`${ANSI.BRIGHT_MAGENTA}◆${ANSI.RESET} ${ANSI.DIM}AI${ANSI.RESET}`)
        aiTurnMarkerShown = true
      }
      const ansi = markdownToAnsi(text, termCols)
      write(ansi)
    }
    if (done) {
      // Accent endpoint + dim rule closes the AI reply block, separates it from the next prompt
      aiTurnMarkerShown = false
      writeLine('')
      writeLine(`${ANSI.BRIGHT_MAGENTA}◆${ANSI.RESET} ${ANSI.DIM}${'─'.repeat(Math.max(8, Math.min(termCols - 4, 38)))}${ANSI.RESET}`)
      agentTurnProcessing.value = false
      isProcessing.value = false
      writePrompt()
    }
  } else if (type === 'tool_call') {
    const toolName = event.tool_name as string
    const args = event.args as Record<string, unknown>
    const argsStr = formatArgs(args)
    writeLine(`${ANSI.BRIGHT_YELLOW}▸${ANSI.RESET} ${ANSI.BRIGHT_CYAN}${toolName}${ANSI.RESET}${ANSI.DIM}(${argsStr})${ANSI.RESET}`)
  } else if (type === 'tool_result') {
    const toolName = event.tool_name as string
    const isError = event.is_error as boolean
    const lines = formatResultLines(event.result, isError)
    const mark = isError ? `${ANSI.RED}✗${ANSI.RESET}` : `${ANSI.BRIGHT_GREEN}✓${ANSI.RESET}`
    // ponytail: ↳ indent signals result is subordinate to the preceding ▸ call;
    // multi-line structured results (free_evaluate 6-dim, free_guide steps) render
    // across lines indented under the ↳, instead of being flattened+truncated.
    const header = `  ${ANSI.DIM}↳${ANSI.RESET} ${mark} ${ANSI.DIM}${toolName}${ANSI.RESET}`
    writeLine(`${header} ${lines[0]}`)
    // Tree connectors tie continuation lines to the call; the last line uses ╰
    const rest = lines.slice(1)
    for (let i = 0; i < rest.length; i++) {
      const branch = i === rest.length - 1 ? '╰' : '│'
      writeLine(`  ${ANSI.DIM}${branch}${ANSI.RESET} ${rest[i]}`)
    }
  } else if (type === 'status') {
    const status = event.status as string
    wsStatus.value = status as 'idle' | 'running' | 'streaming'
    if (status === 'running') {
      agentTurnProcessing.value = true
      isProcessing.value = true
    } else if (status === 'idle') {
      agentTurnProcessing.value = false
      isProcessing.value = false
      writePrompt()
    }
  } else if (type === 'session_end') {
    aiTurnMarkerShown = false
    agentTurnProcessing.value = false
    isProcessing.value = false
    writePrompt()
  } else if (type === 'error') {
    // ponytail: 2-space indent aligns with ▸/↳ tool block; red mark + default-color msg for hierarchy
    writeLine(`  ${ANSI.RED}⚠${ANSI.RESET} ${event.message || t('tui.unknownError')}`)
    aiTurnMarkerShown = false
    agentTurnProcessing.value = false
    isProcessing.value = false
    writePrompt()
  }
}

function formatArgs(args: Record<string, unknown>): string {
  if (!args || Object.keys(args).length === 0) return ''
  const parts = Object.entries(args)
    .slice(0, 3)
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
  const suffix = Object.keys(args).length > 3 ? ', ...' : ''
  return parts.join(', ') + suffix
}

// ponytail: line budget for multi-line tool results — keeps the TUI scannable
// without flattening structured output (6-dim scores, guide steps).
const MAX_RESULT_LINES = 12

/** Format a tool result as display lines.
 *  - short primitives / single-key objects: one line, 160-char cap (scannable)
 *  - multi-line text or structured JSON (object/array with >1 key/element):
 *    pretty-printed across lines, capped at MAX_RESULT_LINES with a dim overflow footer
 *  - errors: full text, never truncated (diagnostics must stay visible) */
function formatResultLines(result: unknown, isError = false): string[] {
  if (result === null || result === undefined) return [`${ANSI.DIM}(no result)${ANSI.RESET}`]

  // ponytail: omp/extension tools return {content:[{type:"text",text}], details?}.
  // The human-readable multi-line output (6-dim scores, guide steps) lives in
  // content[].text — pretty-printing the {content,details} envelope as JSON would
  // bury that text as an escaped single-line string. Extract it first; fall back to
  // details if no text content. Detection is content-based (shape check), not tool-name.
  const extracted = _extractToolText(result)
  let value: unknown = extracted ?? result

  // ponytail: robustness path — if the extracted text is itself a JSON string
  // (starts with {/[), parse it so JSON.stringify(obj, null, 2) produces real
  // indented lines with each key on its own line. The omp bridge / xhsagent-ext
  // actually emit human-readable pre-formatted text (not JSON), so this branch
  // is a no-op for evaluate/guide today; it exists for any future tool that
  // returns a JSON-string envelope. Free text and parse failures keep the raw
  // string untouched, which is what the human-readable colorizer below expects.
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        value = JSON.parse(trimmed)
      } catch {
        // not valid JSON — keep the raw string (e.g. guide free text)
      }
    }
  }

  const isObj = typeof value === 'object'
  const str = typeof value === 'string' ? value : JSON.stringify(value, null, 2)

  // Decide multi-line: explicit newlines, OR a structured object/array with more
  // than one member. Single-key objects ({draft_id: "x"}) stay single-line.
  const hasNewlines = str.includes('\n')
  const multiMember = isObj && _memberCount(value) > 1
  const multiline = hasNewlines || multiMember

  if (!multiline) {
    const flat = str.replace(/\s*\n\s*/g, ' ').trim()
    return [flat.length > 160 && !isError ? flat.slice(0, 160) + `${ANSI.DIM} …${ANSI.RESET}` : flat]
  }

  let lines = str.split('\n')
  // ponytail: errors bypass the line cap so full stacktraces/messages survive
  if (!isError && lines.length > MAX_RESULT_LINES) {
    const omitted = lines.length - MAX_RESULT_LINES
    lines = lines.slice(0, MAX_RESULT_LINES)
    lines.push(`${ANSI.DIM}… (${omitted} more lines)${ANSI.RESET}`)
  }
  // ponytail: semantic color — let the verdict jump out. Color by key/value
  // pattern (content-based), not by tool name, so any tool result with a
  // decision / *_score / bias_warning field benefits. Non-matching JSON lines
  // stay dim as before; non-JSON free text is also dim per-line.
  return lines.map((ln) => colorizeResultLine(ln))
}

/** Extract the human-readable text from an omp ToolResult envelope
 *  ({content:[{type:"text",text}], details?}). Returns the concatenated text,
 *  or null if the value isn't that shape (primitives, plain dicts, etc.). */
function _extractToolText(v: unknown): string | null {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return null
  const obj = v as Record<string, unknown>
  const content = obj.content
  if (!Array.isArray(content)) return null
  const texts: string[] = []
  for (const part of content) {
    if (part && typeof part === 'object' && (part as Record<string, unknown>).type === 'text') {
      const t = (part as Record<string, unknown>).text
      if (typeof t === 'string') texts.push(t)
    }
  }
  return texts.length > 0 ? texts.join('\n') : null
}

/** Count top-level members of a JSON value (object keys or array elements); 0 for primitives. */
function _memberCount(v: unknown): number {
  if (Array.isArray(v)) return v.length
  if (v && typeof v === 'object') return Object.keys(v as Record<string, unknown>).length
  return 0
}

/** Apply semantic color to a tool-result line based on its content.
 *
 *  Two line families are recognized — both detected by content (regex on the
 *  line text), never by tool name:
 *
 *  1. JSON-key form (from JSON.stringify(obj, null, 2)):
 *       `<indent>"<key>": <value>,?`
 *     - `"decision": "approved|needs_revision|rejected"` → verdict color
 *     - `overall_score` / any key ending in `_score` → bright cyan on value
 *     - `bias_warning` truthy (true / non-empty string) → bright magenta; falsy → dim
 *
 *  2. Human-readable form (the omp bridge / xhsagent-ext format evaluation
 *     tools actually emit — pre-formatted text, NOT JSON):
 *       `  Overall: <num>  Decision: <verdict>`  → cyan num + verdict color
 *       `  - <dimension>: <score>[ [BLOCKING]]`   → cyan score
 *       `  ⚠ Bias: <text>`                        → bright magenta (only present when truthy)
 *
 *  Every other line stays dim (the baseline multi-line look). This keeps the
 *  content-based principle: any tool emitting these patterns benefits, and
 *  free text (e.g. xhs_free_guide) is untouched. */
function colorizeResultLine(line: string): string {
  // ── JSON-key form: <indent>"<key>": <value>,? ──────────────────────────
  const jm = line.match(/^(\s*)"(decision|overall_score|\w+_score|bias_warning)"\s*:\s*(.+?)(,?)\s*$/)
  if (jm) {
    const [, indent, key, rawVal, comma] = jm
    if (key === 'decision') {
      const valMatch = rawVal.match(/^"(.+)"$/)
      const verdict = valMatch ? valMatch[1] : rawVal
      let color: string
      if (verdict === 'approved') color = ANSI.BRIGHT_GREEN
      else if (verdict === 'needs_revision') color = ANSI.BRIGHT_YELLOW
      else if (verdict === 'rejected') color = ANSI.RED
      else color = ANSI.DIM
      return `${indent}${ANSI.DIM}"${key}": ${color}${rawVal}${ANSI.RESET}${comma}`
    }
    if (key === 'overall_score' || key.endsWith('_score')) {
      return `${indent}${ANSI.DIM}"${key}": ${ANSI.BRIGHT_CYAN}${rawVal}${ANSI.RESET}${comma}`
    }
    // bias_warning truthy → magenta; falsy ("" / false / null) → dim
    const truthy = rawVal === 'true' || (rawVal.startsWith('"') && rawVal.length > 2)
    const color = key === 'bias_warning' && truthy ? ANSI.BRIGHT_MAGENTA : ANSI.DIM
    return `${indent}${ANSI.DIM}"${key}": ${color}${rawVal}${ANSI.RESET}${comma}`
  }

  // ── Human-readable form: the omp bridge / xhsagent-ext evaluate output ──
  // `  Overall: <num>  Decision: <verdict>` — Overall num cyan, Decision verdict-colored.
  // Matches "N/A" overall (no number to color) and any decision word.
  const od = line.match(/^(\s*Overall:\s*)(\S+)(\s+Decision:\s+)(\S+)\s*$/)
  if (od) {
    const [, preOverall, overallVal, midDecision, decisionVal] = od
    const overallColor = /\d/.test(overallVal) ? ANSI.BRIGHT_CYAN : ANSI.DIM
    let decisionColor: string
    if (decisionVal === 'approved') decisionColor = ANSI.BRIGHT_GREEN
    else if (decisionVal === 'needs_revision') decisionColor = ANSI.BRIGHT_YELLOW
    else if (decisionVal === 'rejected') decisionColor = ANSI.RED
    else decisionColor = ANSI.DIM
    return `${ANSI.DIM}${preOverall}${overallColor}${overallVal}${ANSI.RESET}${ANSI.DIM}${midDecision}${decisionColor}${decisionVal}${ANSI.RESET}`
  }

  // `  - <dimension>: <score>[ [BLOCKING]]` — score number cyan. Trailing
  // rationale (" — ...") or [BLOCKING] tag is left dim.
  const dim = line.match(/^(\s*-\s*[^:]+:\s*)(\d+(?:\.\d+)?)(.*)$/)
  if (dim) {
    const [, preScore, score, tail] = dim
    return `${ANSI.DIM}${preScore}${ANSI.BRIGHT_CYAN}${score}${ANSI.RESET}${ANSI.DIM}${tail}${ANSI.RESET}`
  }

  // `  ⚠ Bias: <text>` — only emitted when bias_warning is non-empty (truthy).
  const bias = line.match(/^(\s*⚠\s*Bias:\s*)(.+)$/)
  if (bias) {
    const [, pre, text] = bias
    return `${ANSI.DIM}${pre}${ANSI.BRIGHT_MAGENTA}${text}${ANSI.RESET}`
  }

  // not a semantic line — keep the dim baseline
  return `${ANSI.DIM}${line}${ANSI.RESET}`
}

// ── Command processing ──────────────────────────────────────────────────

async function processCommand(text: string) {
  const trimmed = text.trim()
  if (!trimmed) return

  // Echo: bright-blue prompt glyph + bright-white input (was all-dim)
  writeLine(`${ANSI.BRIGHT_BLUE}❯${ANSI.RESET} ${ANSI.BRIGHT_WHITE}${trimmed}${ANSI.RESET}`)

  if (mode.value === 'agent') {
    await processAgentCommand(trimmed)
  } else {
    await processCommandMode(trimmed)
  }
}

async function processAgentCommand(text: string) {
  isProcessing.value = true

  if (text.startsWith('/')) {
    const [cmd] = text.split(/\s+/)
    switch (cmd) {
      case '/start':
        if (isFreeCreationEntry.value) {
          sendFreeNewSession()
        } else {
          writeLineColored(t('tui.unknownCommand', { command: cmd }), ANSI.RED)
        }
        isProcessing.value = false; writePrompt()
        break
      case '/status':
        if (isFreeCreationEntry.value) {
          writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
          isProcessing.value = false; writePrompt()
          break
        }
        sendAgentMessage({ type: 'get_status' })
        isProcessing.value = false; writePrompt()
        break
      case '/new':
        if (isFreeCreationEntry.value) {
          sendFreeNewSession()
        } else {
          sendAgentMessage({ type: 'new_session' })
        }
        isProcessing.value = false; writePrompt()
        break
      case '/abort':
        requestAgentAbort()
        break
      case '/pause':
      case '/resume':
      case '/cancel':
      case '/approve':
      case '/reject':
        if (isFreeCreationEntry.value) {
          writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
        } else {
          writeLineColored(t('tui.unknownCommand', { command: cmd }), ANSI.RED)
        }
        isProcessing.value = false; writePrompt()
        break
      case '/mode':
        mode.value = 'command'
        writeLineColored(t('tui.modeSwitchedToCommand'), ANSI.YELLOW)
        isProcessing.value = false; writePrompt()
        break
      case '/help':
        showHelp(); isProcessing.value = false; writePrompt()
        break
      case '/clear':
        term?.clear(); writePrompt()
        isProcessing.value = false
        break
      case '/drafts': {
        const argStr = text.split(/\s+/).slice(1).join(' ').trim()
        await handleDrafts(argStr)
        isProcessing.value = false; writePrompt()
        break
      }
      case '/draft': {
        const parts = text.split(/\s+/)
        const draftId = parts.slice(1).join(' ').trim()
        await handleDraft(draftId)
        isProcessing.value = false; writePrompt()
        break
      }
      case '/delete': {
        const parts = text.split(/\s+/)
        const draftId = parts.slice(1).join(' ').trim()
        await handleDelete(draftId)
        isProcessing.value = false; writePrompt()
        break
      }
      case '/analytics': {
        const parts = text.split(/\s+/)
        const draftId = parts.slice(1).join(' ').trim()
        await handleAnalytics(draftId)
        isProcessing.value = false; writePrompt()
        break
      }
      case '/edit': {
        const parts = text.split(/\s+/)
        await handleEdit(parts.slice(1).join(' ').trim())
        isProcessing.value = false; writePrompt()
        break
      }
      case '/evaluate': {
        const parts = text.split(/\s+/)
        await handleEvaluate(parts.slice(1).join(' ').trim())
        isProcessing.value = false; writePrompt()
        break
      }
      case '/suggest': {
        await handleSuggest()
        isProcessing.value = false; writePrompt()
        break
      }
      default:
        writeLineColored(t('tui.unknownCommand', { command: cmd }), ANSI.RED)
        isProcessing.value = false; writePrompt()
    }
  } else {
    if (sendAgentMessage({ type: 'send_message', content: text })) {
      agentTurnProcessing.value = true
    } else {
      if (isFreeCreationEntry.value) {
        queueFreeAgentMessage(text)
      } else {
        writeLineColored(t('tui.agentUnavailable'), ANSI.YELLOW)
      }
      isProcessing.value = false
      writePrompt()
    }
  }
}

async function processCommandMode(text: string) {
  isProcessing.value = true
  try {
    if (text.startsWith('/')) {
      await processSlashCommand(text)
    } else if (isFreeCreationEntry.value) {
      // onclose falls back to command mode so the terminal remains usable.
      // Keep free-mode natural-language input semantics and hold it until the
      // agent reconnects instead of forcing the user to retype the message.
      queueFreeAgentMessage(text)
    } else {
      await handleStart(text)
    }
  } catch (err: any) {
    writeLineColored(`${err.message || err}`, ANSI.RED)
  } finally {
    isProcessing.value = false
    writePrompt()
  }
}

async function processSlashCommand(cmd: string) {
  const [command, ...args] = cmd.split(/\s+/)
  const arg = args.join(' ')

  switch (command) {
    case '/start':
      if (isFreeCreationEntry.value) {
        sendFreeNewSession()
      } else {
        await handleStart(arg || undefined)
      }
      break
    case '/status':
      if (isFreeCreationEntry.value) { writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW); break }
      await handleStatus(arg || activeThreadId.value || ''); break
    case '/pause':
      if (isFreeCreationEntry.value) { writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW); break }
      await handlePause(arg || activeThreadId.value || ''); break
    case '/resume':
      if (isFreeCreationEntry.value) { writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW); break }
      await handleResume(arg || activeThreadId.value || ''); break
    case '/cancel':
      if (isFreeCreationEntry.value) { writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW); break }
      await handleCancel(arg || activeThreadId.value || ''); break
    case '/approve':
      if (isFreeCreationEntry.value) { writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW); break }
      await handleApprove(arg || activeThreadId.value || ''); break
    case '/reject':
      if (isFreeCreationEntry.value) { writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW); break }
      await handleReject(activeThreadId.value || '', arg); break
    case '/analytics':
      await handleAnalytics(arg); break
    case '/edit':
      await handleEdit(arg); break
    case '/evaluate':
      await handleEvaluate(arg); break
    case '/suggest':
      await handleSuggest(); break
    case '/drafts':
      await handleDrafts(arg); break
    case '/draft':
      await handleDraft(arg); break
    case '/delete':
      await handleDelete(arg); break
    case '/mode':
      mode.value = 'agent'
      reconnectAttempts = 0
      connectAgentWs()
      writeLineColored(t('tui.modeSwitchingToAgent'), ANSI.YELLOW)
      break
    case '/help': showHelp(); break
    case '/clear': term?.clear(); writePrompt(); break
    default:
      writeLineColored(t('tui.unknownCommand', { command }), ANSI.RED)
  }
}

// ── Command mode handlers ──────────────────────────────────────────────

async function handleStart(topic?: string) {
  const accountId = await getCurrentAccountId()
  writeLineColored(t('tui.startingWorkflow', { topic: topic ? ` on topic: ${topic}` : '' }), ANSI.YELLOW)

  const result = await startWorkflow({
    account_id: accountId,
    phase: 'scouting',
    workflow_mode: 'trend',
    ...(topic ? { topic } : {}),
  })

  activeThreadId.value = result.thread_id
  writeLineColored(
    t('tui.workflowStarted', { threadId: result.thread_id, phase: result.phase, status: result.status }),
    ANSI.BRIGHT_GREEN,
  )
}

async function handleStatus(threadId: string) {
  if (!threadId) { writeLineColored(t('tui.noActiveWorkflow'), ANSI.RED); return }
  writeLineColored(t('tui.fetchingStatus', { threadId }), ANSI.YELLOW)

  const state = await getWorkflowStatus(threadId)
  const D = ANSI.DIM, G = ANSI.BRIGHT_GREEN, C = ANSI.BRIGHT_CYAN, W = ANSI.BRIGHT_WHITE, R = ANSI.RESET
  // ponytail: structured status — dim label + bright value, progress as block bar (visual at a glance)
  const pct = Math.max(0, Math.min(100, state.progress_percent ?? 0))
  const barW = 20
  const filled = Math.round((pct / 100) * barW)
  const bar = `${G}${'█'.repeat(filled)}${D}${'░'.repeat(barW - filled)}${R}`
  writeLine('')
  writeLine(`  ${D}${padLabel(t('tui.statusPhase'), 9)}${R}    ${C}${state.phase}${R}`)
  writeLine(`  ${D}${padLabel(t('tui.statusStatus'), 9)}${R}   ${W}${state.status}${R}`)
  writeLine(`  ${D}${padLabel(t('tui.statusProgress'), 9)}${R} ${bar} ${G}${pct}%${R}`)
  writeLine(`  ${D}${padLabel(t('tui.statusAgent'), 9)}${R}    ${state.current_agent || `${D}${t('tui.statusNone')}${R}`}`)
  writeLine(`  ${D}${padLabel(t('tui.statusNext'), 9)}${R}     ${state.next_steps?.length ? state.next_steps.join(', ') : `${D}${t('tui.statusNone')}${R}`}`)
  writeLine('')
}

async function handlePause(threadId: string) {
  if (!threadId) { writeLineColored(t('tui.noActiveWorkflow'), ANSI.RED); return }
  await pauseWorkflow(threadId)
  writeLineColored(t('tui.workflowPaused', { threadId }), ANSI.BRIGHT_GREEN)
}

async function handleResume(threadId: string) {
  if (!threadId) { writeLineColored(t('tui.noActiveWorkflow'), ANSI.RED); return }
  await resumeWorkflow(threadId)
  writeLineColored(t('tui.workflowResumed', { threadId }), ANSI.BRIGHT_GREEN)
}

async function handleCancel(threadId: string) {
  if (!threadId) { writeLineColored(t('tui.noActiveWorkflow'), ANSI.RED); return }
  await cancelWorkflow(threadId)
  writeLineColored(t('tui.workflowCancelled', { threadId }), ANSI.BRIGHT_GREEN)
  activeThreadId.value = null
}

async function handleApprove(threadId: string) {
  if (!threadId) { writeLineColored(t('tui.noActiveWorkflow'), ANSI.RED); return }
  await submitReview(threadId, { decision: 'approved' })
  writeLineColored(t('tui.contentApproved', { threadId }), ANSI.BRIGHT_GREEN)
}

async function handleReject(threadId: string, feedback: string) {
  if (!threadId) { writeLineColored(t('tui.noActiveWorkflow'), ANSI.RED); return }
  if (!feedback) { writeLineColored(t('tui.rejectUsage'), ANSI.RED); return }
  await submitReview(threadId, { decision: 'needs_revision', comments: feedback })
  writeLineColored(t('tui.contentRejected', { feedback }), ANSI.BRIGHT_GREEN)
}

const DRAFT_STATUS_FILTERS = new Set([
  'published', 'unpublished', 'publish_failed', 'evaluated', 'unevaluated',
])

/**
 * Parse `/drafts [status] [query...]` args. First token matching the status
 * whitelist is the filter; the rest (or all, if no status token) is the title
 * substring query. Returns normalized status + query strings.
 */
function parseDraftsArgs(argStr: string): { status: string; query: string } {
  const tokens = argStr.split(/\s+/).filter(Boolean)
  let status = 'all'
  let query = ''
  if (tokens.length > 0 && DRAFT_STATUS_FILTERS.has(tokens[0])) {
    status = tokens[0]
    query = tokens.slice(1).join(' ').trim()
  } else {
    query = tokens.join(' ').trim()
  }
  return { status, query }
}

/** Build the localized filter suffix for the drafts title line (e.g. ", published"). */
function draftsFilterLabel(status: string, query: string): string {
  const parts: string[] = []
  if (status !== 'all') {
    const key = `tui.draftsFilter${status.charAt(0).toUpperCase()}${status.slice(1)}`
    parts.push(t(key))
  }
  if (query) parts.push(t('tui.draftsFilterQuery', { q: query }))
  if (parts.length === 0) return ''
  return t('tui.draftsFilterSep', { filter: parts.join(' · ') })
}

/** Score → traffic-light color: green ≥80, yellow ≥60, red below (0–100 scale). */
function scoreColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return ANSI.DIM
  return score >= 80 ? ANSI.BRIGHT_GREEN : score >= 60 ? ANSI.BRIGHT_YELLOW : ANSI.RED
}

async function handleDrafts(argStr = '') {
  if (!isFreeCreationEntry.value) {
    writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
    return
  }
  const { status, query } = parseDraftsArgs(argStr)
  // client-side guard mirrors the server whitelist so a typo doesn't round-
  // trip a 400 — fail fast with the localized message before the request.
  if (status !== 'all' && !DRAFT_STATUS_FILTERS.has(status)) {
    writeLineColored(t('tui.draftsInvalidStatus', { status }), ANSI.RED)
    return
  }
  const accountId = await getCurrentAccountId()
  try {
    const params = new URLSearchParams()
    if (status !== 'all') params.set('status', status)
    if (query) params.set('q', query)
    const qs = params.toString() ? `?${params.toString()}` : ''
    const resp = await client.get(`/free/drafts/${accountId}${qs}`)
    const data = resp as unknown as {
      drafts: Array<{
        draft_id: string
        title: string
        created_at?: string | null
        updated_at?: string | null
        last_evaluation?: { overall_score?: number | null; decision?: string | null; degraded?: boolean } | null
        published?: boolean | null
      }>
      count?: number
      truncated?: boolean
    }
    writeLine('')
    const count = data.count ?? data.drafts?.length ?? 0
    const filterLabel = draftsFilterLabel(status, query)
    const w = cardWidth(termCols)
    writeBoxTitle(writeLine, t('tui.draftsListTitle', { accountId, count, filter: filterLabel }), { width: w })
    if (data.truncated) {
      writeLine(boxLine(`${ANSI.DIM}${t('tui.draftsTruncated')}${ANSI.RESET}`))
    }
    if (!data.drafts || data.drafts.length === 0) {
      // Guided empty state only when the list is genuinely empty (no filter
      // applied) — a filtered-empty (e.g. /drafts published) is expected and
      // stays a single dim line, no "create one" nudge.
      if (status === 'all' && !query) {
        writeEmptyState(writeLine, {
          width: w,
          icon: '✨',
          title: t('tui.draftsEmptyTitle'),
          hint: t('tui.draftsNoneHint'),
        })
      } else {
        writeLine(boxLine(`${ANSI.DIM}${t('tui.draftsNone')}${ANSI.RESET}`))
      }
    } else {
      // Row layout: G{id} + title (truncated to fit) + right-aligned badges + dim date
      const inner = w - 2 // "│ " prefix
      for (const d of data.drafts) {
        const rightPlain: string[] = []
        const rightColored: string[] = []
        // evaluation badge (only if last_evaluation present). A degraded
        // (fake-approved fallback) eval shows [degraded] — the score is
        // meaningless when the LLM failed.
        const le = d.last_evaluation
        if (le && le.degraded) {
          const b = t('tui.draftsBadgeDegraded')
          rightPlain.push(`[${b}]`)
          rightColored.push(badge(b, ANSI.BRIGHT_YELLOW))
        } else if (le && le.decision) {
          const decColor =
            le.decision === 'approved' ? ANSI.BRIGHT_GREEN
            : le.decision === 'needs_revision' ? ANSI.BRIGHT_YELLOW
            : ANSI.RED
          const score = le.overall_score != null ? le.overall_score : ''
          const b = t('tui.draftEvalBadge', { score, decision: le.decision })
          rightPlain.push(`[${b}]`)
          rightColored.push(badge(b, decColor))
        }
        // published badge
        if (d.published) {
          const b = t('tui.draftPublished')
          rightPlain.push(`[${b}]`)
          rightColored.push(badge(b, ANSI.BRIGHT_CYAN))
        }
        // updated_at (short, YYYY-MM-DDTHH:MM)
        if (d.updated_at) {
          const short = d.updated_at.slice(0, 16)
          rightPlain.push(short)
          rightColored.push(`${ANSI.DIM}${short}${ANSI.RESET}`)
        }
        const rightW = rightPlain.length ? getStringWidth(rightPlain.join(' ')) : 0
        const titleText = d.title || t('tui.draftUntitled')
        const titleBudget = Math.max(8, inner - getStringWidth(d.draft_id) - 2 - rightW - 2)
        const titleTrunc = truncateDisplay(titleText, titleBudget)
        const titlePart = d.title ? titleTrunc : `${ANSI.DIM}${titleTrunc}${ANSI.RESET}`
        const leftW = getStringWidth(d.draft_id) + 2 + getStringWidth(titleTrunc)
        const gap = rightW > 0 ? Math.max(2, inner - leftW - rightW) : 0
        const rightPart = rightColored.length ? `${' '.repeat(gap)}${rightColored.join(' ')}` : ''
        writeLine(boxLine(`${ANSI.BRIGHT_GREEN}${d.draft_id}${ANSI.RESET}: ${titlePart}${rightPart}`))
      }
    }
    writeLine(boxBottom(w))
    writeLine('')
  } catch (err: any) {
    writeError(writeLine, err.message || t('tui.draftsFetchFailed'))
  }
}

interface FreeDraftRecord {
  draft_id?: string
  account_id?: string
  title?: string
  body?: string
  hashtags?: string[]
  image_paths?: string[]
  niche?: string
  content_angle?: string
  target_audience?: string
  created_at?: string
  updated_at?: string
  last_evaluation?: { overall_score?: number; decision?: string; revision_hints?: string[]; degraded?: boolean; summary?: string | null } | null
  last_publish?: { status?: string; error?: string | null; error_type?: string | null; at?: string } | null
  published?: boolean
  post_id?: string
  post_url?: string
}

async function handleDraft(draftId: string) {
  if (!isFreeCreationEntry.value) {
    writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
    return
  }
  if (!draftId) {
    writeLineColored(t('tui.draftDetailMissing'), ANSI.RED)
    return
  }
  const accountId = await getCurrentAccountId()
  try {
    const resp = await client.get(`/free/draft/${draftId}?account_id=${encodeURIComponent(accountId)}`)
    const data = resp as unknown as { draft_id: string; draft: FreeDraftRecord }
    const draft = data.draft || {}
    const C = ANSI.BRIGHT_CYAN, G = ANSI.BRIGHT_GREEN, D = ANSI.DIM
    const Y = ANSI.BRIGHT_YELLOW, R = ANSI.RESET
    const w = cardWidth(termCols)
    writeLine('')
    writeBoxTitle(writeLine, t('tui.draftDetailTitle'), { width: w })
    // Primary fields as aligned kv rows — label column is CJK-aware padded
    const mainRows: Array<[string, string]> = [
      [t('tui.draftDetailDraftIdLabel'), `${G}${data.draft_id}${R}`],
    ]
    if (draft.account_id) {
      mainRows.push([t('tui.draftDetailAccountLabel'), `${draft.account_id}`])
    }
    mainRows.push([t('tui.draftDetailTitleLabel'), draft.title || `${D}${t('tui.draftUntitled')}${R}`])
    if (draft.hashtags && draft.hashtags.length > 0) {
      mainRows.push([t('tui.draftDetailHashtagsLabel'), `${G}${draft.hashtags.join(', ')}${R}`])
    }
    if (draft.image_paths && draft.image_paths.length > 0) {
      mainRows.push([t('tui.draftDetailImagesLabel'), `${draft.image_paths.join(', ')}`])
    }
    if (draft.niche) {
      mainRows.push([t('tui.draftDetailNicheLabel'), `${draft.niche}`])
    }
    if (draft.content_angle) {
      mainRows.push([t('tui.draftDetailAngleLabel'), `${draft.content_angle}`])
    }
    if (draft.target_audience) {
      mainRows.push([t('tui.draftDetailAudienceLabel'), `${draft.target_audience}`])
    }
    const mainLw = Math.max(...mainRows.map(([label]) => getStringWidth(label)))
    // Keep the original field order: body renders between title and hashtags
    for (const [label, value] of mainRows) {
      writeLine(boxLine(kvLine(label, value, { labelWidth: mainLw })))
      if (label === t('tui.draftDetailTitleLabel') && draft.body) {
        writeLine(boxLine(`${D}${t('tui.draftDetailBodyLabel')}${R}:`))
        // Wrap the body to the card width (CJK-aware) so long/multi-line text
        // stays inside the box instead of overflowing the terminal row
        for (const bodyLine of wrapDisplay(draft.body, w - 4, { hangingIndent: 2 })) {
          writeLine(boxLine(bodyLine ? `  ${bodyLine}` : ''))
        }
      }
    }
    // Status fields — render only if present (graceful for pre-#216 drafts)
    const hasStatus = draft.created_at || draft.updated_at || draft.last_evaluation || draft.published !== undefined
    if (hasStatus) {
      writeLine(boxLine(hr(w - 4)))
      if (draft.last_evaluation) {
        const score = draft.last_evaluation.overall_score
        const decision = draft.last_evaluation.decision
        const degraded = draft.last_evaluation.degraded
        if (degraded) {
          // Degraded (LLM timeout → fake-approved fallback): the 100/approved is
          // not a real score — surface the degradation + cause instead, and point
          // at re-running /evaluate (do not publish on a degraded verdict).
          writeLine(boxLine(`${Y}${t('tui.draftDetailEvalDegraded')}${R}`))
          if (draft.last_evaluation.summary) {
            writeLine(boxLine(`${D}${draft.last_evaluation.summary}${R}`))
          }
          writeLine(boxLine(`${Y}${t('tui.draftDetailReEvaluateHint', { id: data.draft_id })}${R}`))
        } else {
          const scoreStr = score !== undefined ? score.toFixed(1) : '?'
          const decisionColor = decision === 'approved' ? G : (decision === 'rejected' ? ANSI.RED : Y)
          writeLine(boxLine(`${D}${t('tui.draftDetailEvalLabel')}${R}: ${scoreColor(score)}${scoreStr}${R} ${decisionColor}(${decision || '?'})${R}`))
          // revision hints — only render if present + non-empty (graceful for
          // pre-#217 drafts without the revision_hints key)
          const hints = draft.last_evaluation.revision_hints
          if (hints && hints.length > 0) {
            writeLine(boxLine(`${D}${t('tui.draftDetailHintsLabel')}${R}:`))
            for (const hint of hints) {
              writeLine(boxLine(`  ${D}• ${hint}${R}`))
            }
            // Next-step hint for revise-able drafts — closes the evaluate→edit
            // loop. approved drafts already get an analytics hint below; only
            // needs_revision/rejected with concrete hints point at /edit→/evaluate.
            if (decision === 'needs_revision' || decision === 'rejected') {
              writeLine(boxLine(`${Y}${t('tui.draftDetailReviseHint', { id: data.draft_id })}${R}`))
            }
          }
        }
      }
      if (draft.published !== undefined) {
        const pubColor = draft.published ? G : D
        const pubStr = draft.published ? t('tui.draftDetailPublishedYes') : t('tui.draftDetailPublishedNo')
        writeLine(boxLine(`${D}${t('tui.draftDetailPublishedLabel')}${R}: ${pubColor}${pubStr}${R}`))
      }
      // Post URL + action hint — only when published with a post_id (PR #223 persists
      // post_id/post_url on real publish). Mock-published (dry-run) carries a
      // "mock_*" post_id → show the mock hint instead of the analytics hint.
      if (draft.post_url) {
        writeLine(boxLine(`${D}${t('tui.draftDetailPostUrlLabel')}${R}: ${C}${draft.post_url}${R}`))
      }
      const pid = draft.post_id || ''
      if (pid && pid.startsWith('mock_')) {
        writeLine(boxLine(`${Y}${t('tui.draftDetailMockPublishedHint')}${R}`))
      } else if (pid) {
        writeLine(boxLine(`${Y}${t('tui.draftDetailAnalyticsHint', { id: data.draft_id })}${R}`))
      }
      // Last publish outcome — on a failure, surface the durable cause + when
      // (#239 only surfaces it for the single publish turn; this persists it).
      // Success is already conveyed by the published/post_url/hint lines above,
      // so only render the failure case to avoid redundancy.
      const lp = draft.last_publish
      if (lp && lp.status && lp.status !== 'published' && lp.status !== 'mock_published') {
        const etype = lp.error_type ? ` (${lp.error_type})` : ''
        const detail = lp.error ? ` — ${lp.error}${etype}` : etype
        const at = lp.at ? `  ${D}${lp.at}${R}` : ''
        writeLine(boxLine(`${ANSI.RED}${t('tui.draftDetailLastPublishLabel')}${R}: ${ANSI.RED}${lp.status}${detail}${R}${at}`))
      }
      if (draft.created_at) {
        writeLine(boxLine(`${D}${t('tui.draftDetailCreatedLabel')}${R}: ${draft.created_at}`))
      }
      if (draft.updated_at) {
        writeLine(boxLine(`${D}${t('tui.draftDetailUpdatedLabel')}${R}: ${draft.updated_at}`))
      }
    }
    writeLine(boxBottom(w))
    writeLine('')
  } catch (err: any) {
    writeError(writeLine, err.message || t('tui.draftDetailFetchFailed'))
  }
}

async function handleDelete(draftId: string) {
  if (!isFreeCreationEntry.value) {
    writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
    return
  }
  if (!draftId) {
    writeLineColored(t('tui.draftDeleteUsage'), ANSI.RED)
    return
  }
  const accountId = await getCurrentAccountId()
  let title = ''
  // GET first so the user sees what is being deleted (acts as confirmation).
  // GET 400 (not found) aborts the delete — no silent success on a bad id.
  try {
    const resp = await client.get(`/free/draft/${draftId}?account_id=${encodeURIComponent(accountId)}`)
    const data = resp as unknown as { draft_id: string; draft: FreeDraftRecord }
    title = data.draft?.title || t('tui.draftUntitled')
    writeLineColored(t('tui.draftDeleting', { title }), ANSI.YELLOW)
  } catch (err: any) {
    writeError(writeLine, t('tui.draftNotFound'))
    return
  }
  try {
    await client.delete(`/free/draft/${draftId}?account_id=${encodeURIComponent(accountId)}`)
    writeLineColored(t('tui.draftDeleted', { title }), ANSI.BRIGHT_GREEN)
  } catch (err: any) {
    writeError(writeLine, err.message || t('tui.draftDeleteFailed'))
  }
}

async function handleAnalytics(draftId: string) {
  if (!isFreeCreationEntry.value) {
    writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
    return
  }
  if (!draftId) {
    writeLineColored(t('tui.analyticsMissing'), ANSI.RED)
    return
  }
  const accountId = await getCurrentAccountId()
  try {
    const resp = await client.get(`/free/analytics/${draftId}?account_id=${encodeURIComponent(accountId)}`)
    const data = resp as unknown as {
      draft_id: string
      post_id: string
      analytics: {
        post_id?: string
        views?: number
        likes?: number
        collects?: number
        comments?: number
        shares?: number
        engagement_rate?: number
        fetched_at?: string
      }
    }
    const a = data.analytics || {}
    const G = ANSI.BRIGHT_GREEN
    const w = cardWidth(termCols)
    writeLine('')
    writeBoxTitle(writeLine, t('tui.analyticsTitle'), { width: w })
    writeLine(boxLine(kvLine(t('tui.analyticsDraftIdLabel'), data.draft_id, { valueColor: G })))
    writeLine(boxLine(kvLine(t('tui.analyticsPostIdLabel'), data.post_id || '', { valueColor: '' })))
    writeLine(boxLine(hr(w - 4)))
    // Aligned metric rows; engagement rate is tier-colored (≥5 green, ≥2 yellow)
    const er = a.engagement_rate ?? 0
    const metricRows: Array<[string, string, string]> = [
      [t('tui.analyticsViewsLabel'), `${a.views ?? 0}`, G],
      [t('tui.analyticsLikesLabel'), `${a.likes ?? 0}`, G],
      [t('tui.analyticsCollectsLabel'), `${a.collects ?? 0}`, G],
      [t('tui.analyticsCommentsLabel'), `${a.comments ?? 0}`, G],
      [t('tui.analyticsSharesLabel'), `${a.shares ?? 0}`, G],
      [t('tui.analyticsEngagementLabel'), `${er.toFixed(2)}%`, er >= 5 ? G : er >= 2 ? ANSI.BRIGHT_YELLOW : ANSI.RED],
    ]
    const metricLw = Math.max(...metricRows.map(([label]) => getStringWidth(label)), getStringWidth(t('tui.analyticsFetchedAtLabel')))
    for (const [label, value, color] of metricRows) {
      writeLine(boxLine(kvLine(label, value, { labelWidth: metricLw, valueColor: color })))
    }
    if (a.fetched_at) {
      writeLine(boxLine(kvLine(t('tui.analyticsFetchedAtLabel'), a.fetched_at, { labelWidth: metricLw, valueColor: '' })))
    }
    writeLine(boxBottom(w))
    writeLine('')
  } catch (err: any) {
    writeError(writeLine, err.message || t('tui.analyticsFetchFailed'), t('tui.analyticsNotPublished'))
  }
}

// /suggest — creative suggestions (style/topic/format/timing) for free mode from
// the account's imported Creator Center stats (thread-less GET /free/suggestions).
// No draft_id needed — atomic data fetch only (no orchestration cue; what to do
// with the advice is the user's/agent's call). Cold-start note when no stats
// imported yet. Closes the discoverability gap: the route shipped but had no
// TUI command, so free users had to leave the TUI for the Settings panel.
async function handleSuggest() {
  if (!isFreeCreationEntry.value) {
    writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
    return
  }
  const accountId = await getCurrentAccountId()
  try {
    const resp = await client.get(`/free/suggestions/${encodeURIComponent(accountId)}`)
    const data = resp as unknown as {
      account_id: string
      suggestions: Array<{
        category?: string
        title?: string
        advice?: string
        priority?: number
        evidence?: string
      }>
      count?: number
      cold_start?: boolean
    }
    const suggestions = data.suggestions || []
    const G = ANSI.BRIGHT_GREEN, D = ANSI.DIM, W = ANSI.BRIGHT_WHITE
    const Y = ANSI.BRIGHT_YELLOW, R = ANSI.RESET
    const w = cardWidth(termCols)
    writeLine('')
    writeBoxTitle(writeLine, t('tui.suggestTitle'), { width: w })
    writeLine(boxLine(kvLine(t('tui.suggestCountLabel'), `${data.count ?? suggestions.length}`, { valueColor: G })))
    if (data.cold_start) {
      writeLine(boxLine(`${Y}${t('tui.suggestColdStart')}${R}`))
    }
    writeLine(boxLine(hr(w - 4)))
    if (!suggestions.length) {
      writeEmptyState(writeLine, { width: w, icon: '💡', title: t('tui.suggestEmpty') })
      writeLine(boxBottom(w))
      writeLine('')
      return
    }
    for (const s of suggestions) {
      const cat = s.category || '?'
      const title = s.title || cat
      writeLine(boxLine(`${badge(cat, Y)} ${W}${title}${R}`))
      if (s.advice) writeLine(boxLine(`  ${D}${s.advice}${R}`))
      if (s.evidence) writeLine(boxLine(`  ${D}${t('tui.suggestEvidenceLabel')}: ${s.evidence}${R}`))
    }
    writeLine(boxLine(`${D}${t('tui.suggestNextHint')}${R}`))
    writeLine(boxBottom(w))
    writeLine('')
  } catch (err: any) {
    writeError(writeLine, err.message || t('tui.suggestFetchFailed'))
  }
}

// /evaluate <id> — re-evaluate a free draft via the RQGM agent-as-a-judge panel
// (thread-less POST /free/evaluate). Renders a boxed summary of overall_score /
// decision / dimensions / bias_warning / revision_hints. The route writes the
// {overall_score, decision, revision_hints} triple back onto the draft's
// last_evaluation, so /drafts and /draft <id> reflect the new verdict after.
async function handleEvaluate(draftId: string) {
  if (!isFreeCreationEntry.value) {
    writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
    return
  }
  if (!draftId) {
    writeLineColored(t('tui.evaluateMissing'), ANSI.RED)
    return
  }
  const accountId = await getCurrentAccountId()
  try {
    const resp = await client.post('/free/evaluate', {
      account_id: accountId,
      draft_id: draftId,
    })
    const data = resp as unknown as {
      draft_id: string
      evaluation_result: {
        overall_score?: number | null
        decision?: string | null
        revision_hints?: string[] | null
        dimensions?: Array<{ dimension?: string; score?: number | null; is_blocking?: boolean; rationale?: string | null }>
        bias_warning?: string | null
      }
    }
    const ev = data.evaluation_result || {}
    const G = ANSI.BRIGHT_GREEN, D = ANSI.DIM
    const Y = ANSI.BRIGHT_YELLOW, M = ANSI.BRIGHT_MAGENTA, R = ANSI.RESET
    const score = ev.overall_score
    const scoreStr = score !== undefined && score !== null ? score.toFixed(1) : '?'
    const decision = ev.decision || ''
    const decisionColor = decision === 'approved' ? G
      : decision === 'rejected' ? ANSI.RED
      : decision === 'needs_revision' ? Y : D
    const w = cardWidth(termCols)
    writeLine('')
    writeBoxTitle(writeLine, t('tui.evaluateTitle'), { width: w })
    // Aligned kv rows; scores are tier-colored (≥80 green, ≥60 yellow, else red)
    const evalLw = Math.max(
      getStringWidth(t('tui.evaluateDraftIdLabel')),
      getStringWidth(t('tui.evaluateOverallLabel')),
      getStringWidth(t('tui.evaluateDecisionLabel')),
    )
    writeLine(boxLine(kvLine(t('tui.evaluateDraftIdLabel'), data.draft_id, { labelWidth: evalLw, valueColor: G })))
    writeLine(boxLine(kvLine(t('tui.evaluateOverallLabel'), scoreStr, { labelWidth: evalLw, valueColor: scoreColor(score) })))
    writeLine(boxLine(kvLine(t('tui.evaluateDecisionLabel'), decision || '?', { labelWidth: evalLw, valueColor: decisionColor })))
    const dims = ev.dimensions || []
    if (dims.length > 0) {
      writeLine(boxLine(hr(w - 4)))
      writeLine(boxLine(`${D}${t('tui.evaluateDimensionsLabel')}${R}:`))
      for (const d of dims) {
        const dScore = d.score !== undefined && d.score !== null ? d.score.toFixed(1) : '?'
        const blk = d.is_blocking ? ` ${ANSI.RED}[BLOCKING]${R}` : ''
        writeLine(boxLine(`  ${D}- ${d.dimension || '?'}: ${scoreColor(d.score)}${dScore}${R}${blk}${R}`))
      }
    }
    if (ev.bias_warning) {
      writeLine(boxLine(hr(w - 4)))
      writeLine(boxLine(`${D}⚠ ${t('tui.evaluateBiasLabel')}${R}: ${M}${ev.bias_warning}${R}`))
    }
    const hints = ev.revision_hints || []
    if (hints.length > 0) {
      writeLine(boxLine(`${D}${t('tui.evaluateHintsLabel')}${R}:`))
      for (const hint of hints) {
        writeLine(boxLine(`  ${D}• ${hint}${R}`))
      }
    }
    writeLine(boxLine(`${G}${t('tui.evaluateWrittenBack', { id: data.draft_id })}${R}`))
    writeLine(boxBottom(w))
    writeLine('')
  } catch (err: any) {
    writeError(writeLine, err.message || t('tui.evaluateFailed'))
  }
}

// /edit <id> <field> <value...> — single-line scalar-field edit (title, niche,
// content_angle, target_audience). body/hashtags/image_paths excluded (multi-
// line/list — agent handles via xhs_free_draft_update). PATCHes the existing
// /free/draft/{id} route; draft_id + created_at preserved, updated_at refreshed.
async function handleEdit(args: string) {
  if (!isFreeCreationEntry.value) {
    writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
    return
  }
  const parts = args.split(/\s+/).filter(Boolean)
  const draftId = parts[0] || ''
  const field = parts[1] || ''
  const value = parts.slice(2).join(' ').trim()
  if (!draftId || !field || !value) {
    writeLineColored(t('tui.editUsage'), ANSI.RED)
    return
  }
  const ALLOWED = ['title', 'niche', 'content_angle', 'target_audience']
  if (!ALLOWED.includes(field)) {
    writeLineColored(t('tui.editUnknownField', { field, allowed: ALLOWED.join(', ') }), ANSI.RED)
    return
  }
  const accountId = await getCurrentAccountId()
  try {
    const resp = await client.patch(
      `/free/draft/${draftId}?account_id=${encodeURIComponent(accountId)}`,
      { [field]: value },
    )
    const data = resp as unknown as { draft_id: string; draft: { updated_at?: string } }
    const D = ANSI.DIM, C = ANSI.BRIGHT_CYAN, R = ANSI.RESET
    writeLine('')
    writeLineColored(t('tui.editUpdated', { field, value }), ANSI.BRIGHT_GREEN)
    if (data.draft?.updated_at) {
      writeLine(`  ${D}${t('tui.draftDetailUpdatedLabel')}${R}: ${C}${data.draft.updated_at}${R}`)
    }
    writeLine('')
  } catch (err: any) {
    writeError(writeLine, err.message || t('tui.editFailed'))
  }
}

interface HelpRow {
  usage: string
  args?: string
  desc: string
  color?: string
}

function showHelp() {
  const G = ANSI.BRIGHT_GREEN, D = ANSI.DIM, R = ANSI.RESET
  const Y = ANSI.BRIGHT_YELLOW, B = ANSI.BRIGHT_BLUE
  const w = cardWidth(termCols)

  // Same entry sets as before — agent/command mode × free/non-free branches
  const sections: Array<{ title: string; rows: HelpRow[] }> = []
  if (mode.value === 'agent') {
    sections.push({ title: t('tui.helpAgentMode'), rows: [
      { usage: '<message>', desc: t('tui.helpDescMessage') },
      { usage: '/status', desc: t('tui.helpDescStatus') },
      { usage: '/new', desc: t('tui.helpDescNew') },
      { usage: '/abort', desc: t('tui.helpDescAbort') },
      { usage: '/mode', desc: t('tui.helpSwitchToCommand') },
    ] })
    if (isFreeCreationEntry.value) {
      sections.push({ title: t('tui.helpFreeDrafts'), rows: [
        { usage: '/drafts', args: '[status] [q]', desc: t('tui.helpDescDrafts') },
        { usage: '/draft', args: '<id>', desc: t('tui.helpDescDraft') },
        { usage: '/delete', args: '<id>', desc: t('tui.helpDescDelete') },
        { usage: '/edit', args: '<id> <f> <v>', desc: t('tui.helpDescEdit') },
        { usage: '/analytics', args: '<id>', desc: t('tui.helpDescAnalytics') },
        { usage: '/evaluate', args: '<id>', desc: t('tui.helpDescEvaluate') },
        { usage: '/suggest', desc: t('tui.helpDescSuggest') },
      ] })
    }
  } else if (isFreeCreationEntry.value) {
    sections.push({ title: t('tui.helpCommandMode'), rows: [
      { usage: '/start', desc: t('tui.freeNewSession') },
      { usage: '/drafts', args: '[status] [q]', desc: t('tui.helpDescDrafts') },
      { usage: '/draft', args: '<id>', desc: t('tui.helpDescDraft') },
      { usage: '/delete', args: '<id>', desc: t('tui.helpDescDelete') },
      { usage: '/edit', args: '<id> <field> <value>', desc: t('tui.helpDescEdit') },
      { usage: '/analytics', args: '<id>', desc: t('tui.helpDescAnalytics') },
      { usage: '/evaluate', args: '<id>', desc: t('tui.helpDescEvaluate') },
      { usage: '/suggest', desc: t('tui.helpDescSuggest') },
      { usage: '/mode', desc: t('tui.helpSwitchToAgent') },
    ] })
  } else {
    sections.push({ title: t('tui.helpCommandMode'), rows: [
      { usage: '/start', args: '[topic]', desc: t('tui.helpDescStart') },
      { usage: '/status', args: '[id]', desc: t('tui.helpDescStatusWorkflow') },
      { usage: '/pause', args: '[id]', desc: t('tui.helpDescPause') },
      { usage: '/resume', args: '[id]', desc: t('tui.helpDescResume') },
      { usage: '/cancel', args: '[id]', desc: t('tui.helpDescCancel') },
      { usage: '/approve', args: '[id]', desc: t('tui.helpDescApprove') },
      { usage: '/reject', args: '<msg>', desc: t('tui.helpDescReject') },
      { usage: '/mode', desc: t('tui.helpSwitchToAgent') },
    ] })
  }
  sections.push({ title: t('tui.helpShortcuts'), rows: [
    { usage: '/help', desc: t('tui.helpDescHelp') },
    { usage: '/clear', desc: t('tui.helpDescClear') },
    { usage: '↑/↓', desc: t('tui.helpDescHistory'), color: B },
    { usage: 'Tab', desc: t('tui.helpDescTab'), color: B },
    { usage: 'Ctrl+C', desc: t('tui.helpDescCtrlC'), color: B },
    { usage: 'Ctrl+U/W/K/A/E', desc: t('tui.helpDescLineEdit'), color: B },
    { usage: 'Ctrl+Shift+F', desc: t('tui.helpDescSearch'), color: B },
    { usage: 'Ctrl+Shift+C/V', desc: t('tui.helpDescCopyPaste'), color: B },
  ] })

  writeLine('')
  writeBoxTitle(writeLine, t('tui.helpTitle'), { width: w })
  for (const section of sections) {
    writeLine(boxLine(`${Y}${section.title}${R}`))
    // Usage column (usage + args) display-width aligned across the section
    const usageW = (r: HelpRow) => getStringWidth(r.usage) + (r.args ? 1 + getStringWidth(r.args) : 0)
    const uw = Math.max(...section.rows.map(usageW))
    for (const row of section.rows) {
      const argsPart = row.args ? ` ${D}${row.args}${R}` : ''
      const pad = ' '.repeat(Math.max(2, uw - usageW(row) + 2))
      writeLine(boxLine(`  ${row.color ?? G}${row.usage}${R}${argsPart}${pad}${D}${row.desc}${R}`))
    }
    writeLine(boxLine())
  }
  writeLine(boxBottom(w))
  writeLine('')
}

/** Original banner for non-free (trend/brief) mode — unchanged legacy layout. */
function renderLegacyBanner() {
  const W = ANSI.BRIGHT_CYAN, G = ANSI.BRIGHT_GREEN, D = ANSI.DIM, R = ANSI.RESET, Y = ANSI.BRIGHT_YELLOW
  const bannerWidth = Math.max(30, Math.min(termCols - 4, 50))
  writeLine('')
  writeLine(`${W}╭${'─'.repeat(bannerWidth)}╮${R}`)
  const bannerName = t('tui.bannerName')
  const bannerVersion = t('tui.bannerVersion')
  const bannerSubtitle = t('tui.bannerSubtitle')
  writeLine(`${W}│${R}  ${G}${bannerName}${R}  ${D}${bannerVersion}${R}${' '.repeat(Math.max(0, bannerWidth - getStringWidth(bannerName) - getStringWidth(bannerVersion) - 4))}${W}│${R}`)
  writeLine(`${W}│${R}  ${D}${bannerSubtitle}${R}${' '.repeat(Math.max(0, bannerWidth - getStringWidth(bannerSubtitle) - 2))}${W}│${R}`)
  writeLine(`${W}├${'─'.repeat(bannerWidth)}┤${R}`)
  const flowText = t('tui.workflowFlow')
  writeLine(`${W}│${R}  ${Y}${flowText}${R}${' '.repeat(Math.max(0, bannerWidth - getStringWidth(flowText) - 2))}${W}│${R}`)
  writeLine(`${W}╰${'─'.repeat(bannerWidth)}╯${R}`)
  writeLine('')
  writeLineColored(`  ${t('tui.terminalHint')}`, ANSI.DIM)
  writeLine('')
}

/** Free-mode hero: accent title card (cyan border, bright-white name, magenta
 *  version) with subtitle / flow / optional topic as boxed lines. */
function renderFreeWelcome() {
  const R = ANSI.RESET
  const w = cardWidth(termCols)
  const name = t('tui.bannerName')
  const version = t('tui.bannerVersion')
  const inner = w - 2
  const headW = getStringWidth(name) + getStringWidth(version) + 1
  const trail = Math.max(1, inner - 3 - headW)
  writeLine('')
  writeLine(`${ANSI.BRIGHT_CYAN}╭─${R} ${ANSI.BRIGHT_WHITE}${name}${R} ${ANSI.BRIGHT_MAGENTA}${version}${R} ${ANSI.BRIGHT_CYAN}${'─'.repeat(trail)}╮${R}`)
  writeLine(boxLine(`${ANSI.DIM}${t('tui.bannerSubtitle')}${R}`))
  writeLine(boxLine(`${ANSI.BRIGHT_YELLOW}${t('tui.freeFlow')}${R}`))
  if (freeCreationTopic.value) {
    writeLine(boxLine(`${ANSI.BRIGHT_CYAN}${t('tui.freeTopic', { topic: freeCreationTopic.value })}${R}`))
  }
  writeLine(boxBottom(w))
  writeLine('')
  writeLineColored(`  ${t('tui.freeWelcomeHint')}`, ANSI.DIM)
}

/** Free-mode command grid — Session / Drafts / Insights groups, two aligned
 *  columns per row. Replaces the old 9-line all-dim command dump. */
function renderFreeCommandGrid() {
  const R = ANSI.RESET, D = ANSI.DIM, C = ANSI.BRIGHT_CYAN, Y = ANSI.BRIGHT_YELLOW
  const groups: Array<{ label: string; cmds: Array<[string, string]> }> = [
    { label: t('tui.freeGroupSession'), cmds: [
      ['/start', t('tui.freeDescStart')],
      ['/mode', t('tui.freeDescMode')],
    ] },
    { label: t('tui.freeGroupDrafts'), cmds: [
      ['/drafts', t('tui.freeDescDrafts')],
      ['/draft', t('tui.freeDescDraft')],
      ['/edit', t('tui.freeDescEdit')],
      ['/delete', t('tui.freeDescDelete')],
    ] },
    { label: t('tui.freeGroupInsights'), cmds: [
      ['/analytics', t('tui.freeDescAnalytics')],
      ['/evaluate', t('tui.freeDescEvaluate')],
      ['/suggest', t('tui.freeDescSuggest')],
    ] },
  ]
  const groupW = Math.max(...groups.map((g) => getStringWidth(g.label)))
  const cmdW = Math.max(...groups.flatMap((g) => g.cmds.map(([cmd]) => getStringWidth(cmd))))
  const descW = Math.max(...groups.flatMap((g) => g.cmds.map(([, desc]) => getStringWidth(desc))))
  for (const g of groups) {
    for (let i = 0; i < g.cmds.length; i += 2) {
      // Group label shows on the first row of the group only
      const label = i === 0 ? `${Y}${padEndDisplay(g.label, groupW)}${R}` : ' '.repeat(groupW)
      const cells = g.cmds.slice(i, i + 2).map(([cmd, desc], idx, row) => {
        const descPart = idx === row.length - 1 ? desc : padEndDisplay(desc, descW)
        return `${C}${padEndDisplay(cmd, cmdW)}${R} ${D}${descPart}${R}`
      })
      writeLine(`  ${label}  ${cells.join('   ')}`)
    }
  }
}

// ── Status bar computed ────────────────────────────────────────────────

const modeLabel = computed(() => mode.value === 'agent' ? t('tui.modeLabelAgent') : t('tui.modeLabelCmd'))
const freeConnectionState = computed<'connected' | 'connecting' | 'disconnected'>(() => {
  if (wsConnected.value) return 'connected'
  if (wsConnecting.value) return 'connecting'
  return 'disconnected'
})
const freeConnectionLabel = computed(() => {
  if (!isFreeCreationEntry.value) return ''
  if (freeConnectionState.value === 'connected') return t('tui.agentConnectionConnected')
  if (freeConnectionState.value === 'connecting') return t('tui.agentConnectionConnecting')
  return t('tui.agentConnectionDisconnected')
})
const mobileInputPlaceholder = computed(() => {
  if (isFreeCreationEntry.value) {
    return wsConnected.value
      ? t('tui.messagePlaceholder')
      : t('tui.freeMessageQueuedPlaceholder')
  }
  return mode.value === 'agent' && wsConnected.value
    ? t('tui.messagePlaceholder')
    : t('tui.commandPlaceholder')
})
const accountContextLabel = computed(() => accountsStore.activeAccount?.name || t('tui.defaultAccount'))

// ── Lifecycle ───────────────────────────────────────────────────────────

let resizeObserver: ResizeObserver | null = null
let viewportHandler: (() => void) | null = null

onMounted(() => {
  term = new Terminal({
    cursorBlink: true,
    cursorStyle: 'block', // native terminal default
    fontSize: 14,
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Menlo', 'Consolas', 'Noto Sans Mono CJK SC', 'PingFang SC', 'Microsoft YaHei', 'WenQuanYi Micro Hei Mono', monospace",
    fontWeight: 'normal',
    fontWeightBold: 'bold',
    lineHeight: 1.2,
    letterSpacing: 0,
    smoothScrollDuration: 80,
    minimumContrastRatio: 4.5,
    drawBoldTextInBrightColors: true,
    theme: {
      // Tokyo Night palette — high contrast, easy on eyes
      background: '#1a1b26',
      foreground: '#a9b1d6',
      cursor: '#c0caf5',
      cursorAccent: '#1a1b26',
      selectionBackground: '#33467c',
      selectionForeground: '#c0caf5',
      // Standard colors (Tokyo Night variant)
      black: '#15161e',
      red: '#f7768e',
      green: '#9ece6a',
      yellow: '#e0af68',
      blue: '#7aa2f7',
      magenta: '#bb9af7',
      cyan: '#7dcfff',
      white: '#a9b1d6',
      // Bright colors
      brightBlack: '#414868',
      brightRed: '#f7768e',
      brightGreen: '#9ece6a',
      brightYellow: '#e0af68',
      brightBlue: '#7aa2f7',
      brightMagenta: '#bb9af7',
      brightCyan: '#7dcfff',
      brightWhite: '#c0caf5',
    },
    scrollback: 10000,
    convertEol: true,
    allowProposedApi: true,
  })

  fitAddon = new FitAddon()
  searchAddon = new SearchAddon()
  term.loadAddon(fitAddon)
  term.loadAddon(new WebLinksAddon())
  term.loadAddon(searchAddon)

  // WebGL renderer (desktop only — mobile often fails)
  if (!isMobile.value) {
    try {
      const webglAddon = new WebglAddon()
      webglAddon.onContextLoss(() => {
        webglAddon.dispose()
      })
      term.loadAddon(webglAddon)
    } catch {
      // DOM renderer fallback (default)
    }
  }

  if (termRef.value) {
    term.open(termRef.value)
    fitAddon.fit()
    term.focus() // native TUI: terminal grabs focus immediately
  }

  // IME composition tracking on the hidden textarea
  const textarea = (term as any).textarea as HTMLTextAreaElement | undefined
  if (textarea) {
    textarea.addEventListener('compositionstart', () => { isComposing = true })
    textarea.addEventListener('compositionend', () => { isComposing = false })
  }

  term.onData(handleTermData)
  setupKeyEventHandler()

  // Track terminal columns for adaptive markdown width
  termCols = term.cols
  term.onResize(({ cols }) => { termCols = cols })

  // Click terminal area → focus (native TUI: always captures input)
  termRef.value?.addEventListener('click', () => term?.focus())

  // Resize observer
  resizeObserver = new ResizeObserver(() => fitAddon?.fit())
  if (termRef.value) resizeObserver.observe(termRef.value)

  // Mobile: visualViewport soft keyboard adaptation
  if (isMobile.value && window.visualViewport) {
    viewportHandler = () => {
      const vv = window.visualViewport!
      // Adjust terminal container height when soft keyboard opens
      const container = termRef.value
      if (container) {
        container.style.height = `${vv.height}px`
        fitAddon?.fit()
      }
    }
    window.visualViewport.addEventListener('resize', viewportHandler)
    window.visualViewport.addEventListener('scroll', viewportHandler)
  }

  // Context menu on the terminal container
  if (termRef.value) {
    termRef.value.addEventListener('contextmenu', handleContextMenu)
  }

  // Click outside context menu to close it
  document.addEventListener('click', handleDocumentClick)

  // Welcome area — free mode gets the redesigned hero + grouped command grid;
  // non-free mode keeps the original banner unchanged.
  if (isFreeCreationEntry.value) {
    renderFreeWelcome()
  } else {
    renderLegacyBanner()
  }

  // Free mode: default to agent mode so plain text routes to omp conversation immediately.
  // Non-free (trend/brief) keeps command mode default — behavior unchanged.
  if (isFreeCreationEntry.value) {
    mode.value = 'agent'
    writeLineColored(`  ${t('tui.freeAgentReady')}`, ANSI.DIM)
    // Surface the free-mode TUI commands on first entry so the user knows
    // draft management exists without typing /help first (discoverability —
    // same class as the post_url hint). Compact grouped grid; full reference in /help.
    renderFreeCommandGrid()
  }

  // Try connecting to agent WebSocket
  connectAgentWs()

  // Resume active workflow if any (skipped in free creation mode — fully isolated from workflows)
  if (!isFreeCreationEntry.value && workflowStore.activeThreadId) {
    activeThreadId.value = workflowStore.activeThreadId
    writeLineColored(t('tui.resumingWorkflow', { threadId: workflowStore.activeThreadId }), ANSI.YELLOW)
  }

  writePrompt()
})

function handleDocumentClick(ev: MouseEvent) {
  // Close context menu on click outside
  if (contextMenuVisible.value) {
    const target = ev.target as HTMLElement
    if (!target.closest('.tui-context-menu')) {
      closeContextMenu()
    }
  }
}

onUnmounted(() => {
  disconnectAgentWs()
  document.removeEventListener('click', handleDocumentClick)
  if (termRef.value) {
    termRef.value.removeEventListener('contextmenu', handleContextMenu)
  }
  if (viewportHandler && window.visualViewport) {
    window.visualViewport.removeEventListener('resize', viewportHandler)
    window.visualViewport.removeEventListener('scroll', viewportHandler)
  }
  resizeObserver?.disconnect()
  term?.dispose()
  term = null
  fitAddon = null
  searchAddon = null
})
</script>

<template>
  <div class="tui-container h-[calc(100dvh-4rem)] flex flex-col" @click="closeContextMenu">
    <!-- Status bar — native TUI style -->
    <div class="tui-statusbar flex items-center gap-2 px-3 py-1 shrink-0">
      <div class="tui-status-dot" :class="freeConnectionState" />
      <span class="tui-status-label">{{ t('tui.statusLabel') }}</span>
      <span class="tui-mode-badge" :class="mode === 'agent' ? 'mode-agent' : 'mode-cmd'">{{ modeLabel }}</span>
      <span v-if="isFreeCreationEntry" class="tui-free-badge">{{ t('tui.freeModeBadge') }}</span>
      <span v-if="isFreeCreationEntry" class="tui-connection-state" :class="`state-${freeConnectionState}`" role="status" aria-live="polite">{{ freeConnectionLabel }}</span>
      <span v-if="isFreeCreationEntry && pendingAgentMessageCount > 0" class="tui-queue-state" role="status" aria-live="polite">{{ t('tui.queuePending', { count: pendingAgentMessageCount }) }}</span>
      <span v-if="activeThreadId" class="tui-thread-id">{{ activeThreadId.slice(0, 8) }}</span>
      <div class="flex-1" />
      <span v-if="isProcessing" class="tui-running-indicator">● {{ t('tui.processing') }}</span>
      <button
        class="tui-status-btn"
        :class="{ active: searchVisible }"
        :title="t('tui.searchShortcut')"
        @click.stop="toggleSearch"
      >⌕</button>
    </div>

    <!-- Guided shortcuts keep Free Creation discoverable without hiding the terminal.
         Quick actions + prompt chips share one "action deck" container. -->
    <div v-if="isFreeCreationEntry" class="tui-action-deck shrink-0">
      <div class="tui-quick-actions flex flex-wrap items-center gap-2 px-3 py-2">
        <span class="tui-account-context">{{ t('tui.accountContext', { account: accountContextLabel }) }}</span>
        <span class="tui-quick-label">{{ t('tui.quickActions') }}</span>
        <button v-if="agentTurnProcessing" class="tui-quick-btn tui-quick-btn-stop" @click.stop="requestAgentAbort()">{{ t('tui.quickStop') }}</button>
        <button class="tui-quick-btn" :disabled="isProcessing" @click.stop="runQuickAction('/start')">{{ t('tui.quickNewSession') }}</button>
        <button class="tui-quick-btn" :disabled="isProcessing" @click.stop="runQuickAction('/suggest')">{{ t('tui.quickSuggest') }}</button>
        <button class="tui-quick-btn" :disabled="isProcessing" @click.stop="runQuickAction('/drafts')">{{ t('tui.quickDrafts') }}</button>
        <button class="tui-quick-btn" :disabled="isProcessing" @click.stop="runQuickAction('/help')">{{ t('tui.quickHelp') }}</button>
        <button v-if="freeConnectionState === 'disconnected'" class="tui-quick-btn tui-quick-btn-retry" :disabled="isProcessing" @click.stop="retryFreeAgentConnection">{{ t('tui.quickReconnect') }}</button>
      </div>

      <div class="tui-prompt-actions flex items-center gap-2 px-3 py-2">
        <span class="tui-quick-label shrink-0">{{ t('tui.tryPrompts') }}</span>
        <div class="tui-prompt-scroll flex items-center gap-2">
          <button class="tui-prompt-btn shrink-0" :disabled="isProcessing" @click.stop="prefillFreePrompt(t('tui.promptWriteNote'))">{{ t('tui.promptWriteNote') }}</button>
          <button class="tui-prompt-btn shrink-0" :disabled="isProcessing" @click.stop="prefillFreePrompt(t('tui.promptFindTopics'))">{{ t('tui.promptFindTopics') }}</button>
          <button class="tui-prompt-btn shrink-0" :disabled="isProcessing" @click.stop="prefillFreePrompt(t('tui.promptImproveDraft'))">{{ t('tui.promptImproveDraft') }}</button>
        </div>
      </div>
    </div>

    <!-- Search bar — native terminal search -->
    <div v-if="searchVisible" class="tui-searchbar flex items-center gap-1 px-2 py-1 shrink-0" @click.stop>
      <input
        ref="searchInputRef"
        v-model="searchQuery"
        class="tui-search-input flex-1"
        :placeholder="t('tui.searchPlaceholder')"
        @input="onSearchInput"
        @keydown.enter="doSearch('next')"
        @keydown.shift.enter="doSearch('prev')"
        @keydown.escape="closeSearch"
      />
      <button class="tui-search-toggle" :class="{ active: searchCaseSensitive }" :title="t('tui.searchCaseSensitive')" @click="searchCaseSensitive = !searchCaseSensitive; onSearchInput()">Aa</button>
      <button class="tui-search-toggle" :class="{ active: searchRegex }" :title="t('tui.searchRegex')" @click="searchRegex = !searchRegex; onSearchInput()">.*</button>
      <span class="tui-search-info" :class="{ 'tui-search-info-empty': searchResultInfo }">{{ searchResultInfo }}</span>
      <button class="tui-search-nav" :title="t('tui.searchPrevious')" @click="doSearch('prev')">↑</button>
      <button class="tui-search-nav" :title="t('tui.searchNext')" @click="doSearch('next')">↓</button>
      <button class="tui-search-nav" :title="t('common.close')" @click="closeSearch">✕</button>
    </div>

    <!-- xterm.js container -->
    <div ref="termRef" class="tui-term-area flex-1 min-h-0" tabindex="0" @focus="term?.focus()" />

    <!-- Mobile input bar -->
    <div v-if="isMobile" class="tui-mobile-bar flex items-center gap-2 px-3 py-2 shrink-0">
      <input
        v-model="mobileInput"
        class="tui-mobile-input flex-1"
        :placeholder="mobileInputPlaceholder"
        enterkeyhint="send"
        @keydown.enter="submitMobileInput"
      />
      <button
        class="tui-mobile-send"
        :disabled="!mobileInput.trim()"
        :aria-label="t('tui.mobileSend')"
        @click="submitMobileInput"
      >↵</button>
    </div>

    <!-- Context menu -->
    <div
      v-if="contextMenuVisible"
      class="tui-context-menu fixed py-1 z-50 min-w-[160px]"
      :style="{ left: `${contextMenuPos.x}px`, top: `${contextMenuPos.y}px` }"
      @click.stop
    >
      <button v-if="contextMenuHasSelection" class="tui-menu-item" @click="menuCopy"><span class="tui-menu-icon">⧉</span>{{ t('tui.contextCopy') }}</button>
      <button class="tui-menu-item" @click="menuPaste"><span class="tui-menu-icon">⤓</span>{{ t('tui.contextPaste') }}</button>
      <button class="tui-menu-item" @click="menuSelectAll"><span class="tui-menu-icon">☐</span>{{ t('tui.contextSelectAll') }}</button>
      <div class="tui-menu-sep" />
      <button class="tui-menu-item" @click="menuSearch"><span class="tui-menu-icon">⌕</span>{{ t('tui.contextSearch') }}</button>
      <button class="tui-menu-item" @click="menuClear"><span class="tui-menu-icon">✕</span>{{ t('tui.contextClear') }}</button>
    </div>
  </div>
</template>

<style scoped>
/* ── Base container — full native terminal frame ────────────────────── */
.tui-container {
  background: #1a1b26;
  border: 1px solid #292e42;
  border-radius: 0;
}

/* ── Status bar — native terminal tab-bar feel ──────────────────────── */
.tui-statusbar {
  background: #16161e;
  border-bottom: 1px solid #292e42;
  /* ponytail: 1px brand accent strip under the bar — single subtle visual anchor */
  box-shadow: inset 2px 0 0 0 #7aa2f7;
  font-family: 'JetBrains Mono', 'Fira Code', 'Menlo', monospace;
  font-size: 11px;
  line-height: 1;
  user-select: none;
  -webkit-app-region: drag; /* ponytail: allows OS window drag on status bar */
}

.tui-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  transition: background 0.3s ease;
  flex-shrink: 0;
}
.tui-status-dot.connected {
  background: #9ece6a;
  box-shadow: 0 0 4px 1px #9ece6a40;
  animation: pulse-glow 2s ease-in-out infinite;
}
.tui-status-dot.disconnected {
  background: #414868;
}
.tui-status-dot.connecting {
  background: #e0af68;
  box-shadow: 0 0 4px 1px #e0af6840;
  animation: pulse-glow 1.2s ease-in-out infinite;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.tui-status-label {
  color: #7982a9;
  font-size: 11px;
  letter-spacing: 0.3px;
}

.tui-mode-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 2px;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  line-height: 1.4;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}
.tui-mode-badge.mode-agent {
  background: #9ece6a18;
  color: #9ece6a;
  border: 1px solid #9ece6a30;
}
.tui-mode-badge.mode-cmd {
  background: #e0af6818;
  color: #e0af68;
  border: 1px solid #e0af6830;
}

.tui-connection-state {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.2px;
  padding-left: 4px;
  white-space: nowrap;
}
.tui-connection-state.state-connected { color: #9ece6a; }
.tui-connection-state.state-connecting { color: #e0af68; }
.tui-connection-state.state-disconnected { color: #f7768e; }

/* Free-mode identity pill — brand blue→purple gradient, white text */
.tui-free-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  letter-spacing: 0.8px;
  color: #ffffff;
  background: linear-gradient(135deg, #7aa2f7, #bb9af7);
  white-space: nowrap;
}
.tui-queue-state {
  color: #e0af68;
  font-size: 10px;
  white-space: nowrap;
}

.tui-thread-id {
  color: #414868;
  font-size: 10px;
  margin-left: 4px;
  font-variant-numeric: tabular-nums;
}

.tui-running-indicator {
  color: #e0af68;
  font-size: 10px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
/* ponytail: stepping dots spinner — native-terminal "busy" feel, no JS frame loop */
.tui-running-indicator::after {
  content: '';
  width: 14px;
  text-align: left;
  animation: tui-dots 1.2s steps(4, end) infinite;
}
@keyframes tui-dots {
  0%   { content: '   '; }
  25%  { content: '.  '; }
  50%  { content: '.. '; }
  75%  { content: '...'; }
  100% { content: '   '; }
}

.tui-status-btn {
  min-width: 44px;
  min-height: 44px;
  color: #565f89;
  font-size: 12px;
  padding: 0 4px;
  cursor: pointer;
  background: none;
  border: none;
  transition: color 0.15s;
  -webkit-app-region: no-drag;
}
.tui-status-btn:hover { color: #a9b1d6; }
.tui-status-btn.active { color: #7aa2f7; }

/* ── Free-mode action deck — quick actions + prompt chips in one container ── */
.tui-action-deck {
  background: linear-gradient(180deg, #1c1f30 0%, #16161e 100%);
  border-top: 1px solid #7aa2f733;
  border-bottom: 1px solid #292e42;
  font-family: 'JetBrains Mono', 'Fira Code', 'Menlo', monospace;
  font-size: 11px;
}
.tui-account-context { color: #7dcfff; margin-right: 4px; }
.tui-quick-label { color: #565f89; }
.tui-quick-btn {
  min-height: 2.75rem;
  padding: 0.25rem 0.9rem;
  color: #a9b1d6;
  background: #1a1b26;
  border: 1px solid #3b4261;
  border-radius: 999px;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, transform 0.08s, box-shadow 0.15s;
}
.tui-quick-btn:hover:not(:disabled) {
  color: #c0caf5;
  border-color: #7aa2f7;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px #7aa2f730;
}
.tui-quick-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.tui-quick-btn-retry { color: #e0af68; border-color: #e0af6860; }
.tui-quick-btn-stop { color: #f7768e; border-color: #f7768e80; }
.tui-quick-btn-stop:hover:not(:disabled) { color: #ff9eaf; border-color: #f7768e; }

.tui-prompt-actions {
  border-top: 1px solid #292e4280;
  min-width: 0;
}
.tui-prompt-scroll {
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: thin;
}
.tui-prompt-btn {
  min-height: 2.75rem;
  padding: 0.25rem 0.9rem;
  color: #7dcfff;
  background: transparent;
  border: 1px dashed #3b426199;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s, border-color 0.15s, transform 0.08s;
}
.tui-prompt-btn:hover:not(:disabled) {
  color: #c0caf5;
  border-color: #7dcfff;
  transform: translateY(-1px);
}
.tui-prompt-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── Search bar — flat, terminal-native ─────────────────────────────── */
.tui-searchbar {
  background: #16161e;
  border-bottom: 1px solid #292e42;
  font-family: 'JetBrains Mono', 'Fira Code', 'Menlo', monospace;
  /* ponytail: slide-in on v-if mount — single transition, no JS */
  animation: tui-bar-in 0.15s ease-out;
  transition: background 0.2s ease, border-color 0.2s ease;
}
@keyframes tui-bar-in {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}
/* ponytail: focus-within lights the whole bar, not just the input border */
.tui-searchbar:focus-within {
  background: #1a1b26;
  border-bottom-color: #7aa2f7;
}

.tui-search-input {
  background: #1a1b26;
  color: #a9b1d6;
  font-size: 12px;
  min-height: 2.75rem;
  padding: 2px 10px;
  border-radius: 6px;
  border: 1px solid #3b4261;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.tui-search-input:focus {
  border-color: #7aa2f7;
  box-shadow: 0 0 0 2px #7aa2f730;
}
.tui-search-input::placeholder {
  color: #414868;
}

.tui-search-toggle {
  min-width: 44px;
  min-height: 44px;
  font-size: 10px;
  font-family: inherit;
  padding: 1px 4px;
  border-radius: 6px;
  color: #565f89;
  background: none;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}
.tui-search-toggle:hover { color: #a9b1d6; }
.tui-search-toggle.active {
  color: #c0caf5;
  border-color: #7aa2f7;
  background: #7aa2f720;
  box-shadow: 0 0 0 1px #7aa2f740;
}

.tui-search-info {
  color: #7982a9;
  font-size: 10px;
  font-weight: 600;
  min-width: 60px;
  text-align: center;
}
/* No-match state — warning color while "(not found)" is shown */
.tui-search-info.tui-search-info-empty { color: #f7768e; }

.tui-search-nav {
  min-width: 44px;
  min-height: 44px;
  font-size: 11px;
  font-family: inherit;
  color: #565f89;
  background: none;
  border: none;
  padding: 2px 4px;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.15s;
}
.tui-search-nav:hover {
  color: #c0caf5;
  background: #292e42;
}

/* ── Mobile input bar — pill input + gradient send, matches action deck ── */
.tui-mobile-bar {
  background: #16161e;
  border-top: 1px solid #292e42;
  padding-bottom: max(0.5rem, env(safe-area-inset-bottom));
}

.tui-mobile-input {
  background: #1a1b26;
  color: #a9b1d6;
  font-size: 14px;
  min-height: 2.75rem;
  padding: 6px 16px;
  border-radius: 999px;
  border: 1px solid #3b4261;
  font-family: 'JetBrains Mono', 'Menlo', monospace;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.tui-mobile-input:focus {
  border-color: #7aa2f7;
  box-shadow: 0 0 0 2px #7aa2f730;
}
.tui-mobile-input::placeholder {
  color: #414868;
}

.tui-mobile-send {
  min-width: 44px;
  min-height: 44px;
  background: linear-gradient(135deg, #7aa2f7, #bb9af7);
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 999px;
  border: none;
  cursor: pointer;
  font-family: inherit;
  transition: filter 0.15s, transform 0.08s;
}
.tui-mobile-send:hover {
  filter: brightness(1.12);
}
.tui-mobile-send:active {
  filter: brightness(0.92);
  transform: translateY(1px); /* ponytail: tactile press feedback */
}
.tui-mobile-send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
  transform: none;
  filter: none;
}

/* ── Context menu — modern floating card ────────────────────────────── */
.tui-context-menu {
  background: #1a1b26;
  border: 1px solid #3b4261;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5), 0 0 0 1px #7aa2f71a;
  font-family: 'JetBrains Mono', 'Menlo', monospace;
  padding: 4px;
  /* pop-in on open — same family as the search bar slide-in */
  animation: tui-menu-in 0.12s ease-out;
}
@keyframes tui-menu-in {
  from { opacity: 0; transform: translateY(-3px) scale(0.98); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

.tui-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  min-height: 2.75rem;
  padding: 4px 10px;
  font-size: 12px;
  color: #a9b1d6;
  background: none;
  border: none;
  border-radius: 5px;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.08s, color 0.08s, box-shadow 0.08s;
}
.tui-menu-icon {
  width: 16px;
  text-align: center;
  color: #565f89;
  transition: color 0.08s;
}
.tui-menu-item:hover {
  background: #292e42;
  color: #c0caf5;
  /* accent left bar marks the hovered row */
  box-shadow: inset 2px 0 0 0 #7aa2f7;
}
.tui-menu-item:hover .tui-menu-icon { color: #7aa2f7; }

.tui-menu-sep {
  height: 1px;
  background: #292e42;
  margin: 4px 8px;
}

/* ── xterm.js overrides — native terminal feel ──────────────────────── */
.tui-term-area {
  outline: none;
  cursor: text; /* native terminal cursor */
}

:deep(.xterm) {
  padding: 0 8px;
  height: 100%;
}

:deep(.xterm-viewport) {
  scrollbar-width: thin;
  scrollbar-color: #292e42 transparent;
}

:deep(.xterm-viewport::-webkit-scrollbar) {
  width: 5px;
}

:deep(.xterm-viewport::-webkit-scrollbar-track) {
  background: transparent;
}

:deep(.xterm-viewport::-webkit-scrollbar-thumb) {
  background: #292e42 !important;
  border-radius: 0 !important;
}

:deep(.xterm-viewport::-webkit-scrollbar-thumb:hover) {
  background: #414868 !important;
}

/* Active cursor — block style on focus, hollow on blur */
:deep(.xterm.focus .xterm-cursor-layer) {
  /* cursor styling handled by theme */
}

/* Dim cursor when unfocused — native terminal behavior */
:deep(.xterm:not(.focus) .xterm-cursor-layer) {
  opacity: 0.4;
}

/* Selection — keep xterm theme colors */
:deep(.xterm-selection) {
  /* Handled by xterm theme selectionBackground/selectionForeground */
}
</style>
