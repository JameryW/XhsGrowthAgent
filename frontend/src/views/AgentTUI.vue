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
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import { SearchAddon } from '@xterm/addon-search'
import { WebglAddon } from '@xterm/addon-webgl'
import '@xterm/xterm/css/xterm.css'
import { useWorkflowStore } from '@/stores'
import { useAuthStore } from '@/stores/auth'
import {
  startWorkflow,
  pauseWorkflow,
  resumeWorkflow,
  cancelWorkflow,
  getWorkflowStatus,
} from '@/api/workflow'
import { submitReview } from '@/api/review'
import { markdownToAnsi, ANSI } from '@/utils/markdownToAnsi'

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const authStore = useAuthStore()

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
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/agent/ws`
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
const MAX_RECONNECT_ATTEMPTS = 3
const wsConnected = ref(false)
const wsStatus = ref<'idle' | 'running' | 'streaming'>('idle')

// ── CJK width calculation ─────────────────────────────────────────────
// ponytail: inline wcwidth — avoids relying on experimental term.unicode API
function getStringWidth(str: string): number {
  let width = 0
  for (const char of str) {
    const code = char.codePointAt(0)!
    // CJK ideographs, fullwidth forms, Hangul, etc. = width 2
    if (code >= 0x1100 && (
      code <= 0x115F ||
      code === 0x2329 || code === 0x232A ||
      (code >= 0x2E80 && code <= 0xA4CF && code !== 0x303F) ||
      (code >= 0xAC00 && code <= 0xD7A3) ||
      (code >= 0xF900 && code <= 0xFAFF) ||
      (code >= 0xFE10 && code <= 0xFE19) ||
      (code >= 0xFE30 && code <= 0xFE6F) ||
      (code >= 0xFF01 && code <= 0xFF60) ||
      (code >= 0xFFE0 && code <= 0xFFE6) ||
      (code >= 0x20000 && code <= 0x2FFFD) ||
      (code >= 0x30000 && code <= 0x3FFFD)
    )) {
      width += 2
    } else {
      width += 1
    }
  }
  return width
}

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
  '/approve', '/reject', '/mode', '/help', '/clear', '/new', '/abort',
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
    if (mode.value === 'agent' && isProcessing.value) {
      sendAgentMessage({ type: 'abort' })
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

// ── WebSocket ───────────────────────────────────────────────────────────

function connectAgentWs() {
  if (ws && ws.readyState === WebSocket.OPEN) return

  ws = new WebSocket(WS_URL)

  ws.onopen = () => {
    wsConnected.value = true
    reconnectAttempts = 0
    mode.value = 'agent'
    writeLineColored('⚡ Agent mode connected', ANSI.BRIGHT_GREEN)
    writePrompt()
  }

  ws.onmessage = (ev: MessageEvent) => {
    try {
      const event = JSON.parse(ev.data)
      handleAgentEvent(event)
    } catch { /* ignore malformed */ }
  }

  ws.onclose = () => {
    wsConnected.value = false
    if (mode.value === 'agent') {
      mode.value = 'command'
      if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts++
        writeLineColored(`⚠ Agent disconnected, reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`, ANSI.YELLOW)
        reconnectTimer = setTimeout(connectAgentWs, 3000)
      } else {
        writeLineColored('✗ Agent disconnected after max retries, switched to command mode', ANSI.RED)
        writePrompt()
      }
    }
  }

  ws.onerror = () => { /* onclose will fire */ }
}

function disconnectAgentWs() {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  ws?.close()
  ws = null
  wsConnected.value = false
}

function sendAgentMessage(msg: Record<string, unknown>) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg))
  }
}

function handleAgentEvent(event: Record<string, unknown>) {
  const type = event.type as string

  if (type === 'ready') {
    writeLineColored('✓ Agent ready', ANSI.BRIGHT_GREEN)
    wsStatus.value = 'idle'
    writePrompt()
  } else if (type === 'agent_message') {
    const text = event.text as string
    const done = event.done as boolean
    if (!done && text) {
      const ansi = markdownToAnsi(text, termCols)
      write(ansi)
    }
    if (done) {
      writeLine('')
      isProcessing.value = false
      writePrompt()
    }
  } else if (type === 'tool_call') {
    const toolName = event.tool_name as string
    const args = event.args as Record<string, unknown>
    const argsStr = formatArgs(args)
    writeLine(`${ANSI.BRIGHT_YELLOW}▸${ANSI.RESET} ${ANSI.BRIGHT_CYAN}${toolName}${ANSI.DIM}(${argsStr})${ANSI.RESET}`)
  } else if (type === 'tool_result') {
    const toolName = event.tool_name as string
    const isError = event.is_error as boolean
    const resultStr = formatResult(event.result)
    if (isError) {
      writeLine(`${ANSI.RED}✗${ANSI.RESET} ${ANSI.DIM}${toolName}:${ANSI.RESET} ${resultStr}`)
    } else {
      writeLine(`${ANSI.BRIGHT_GREEN}✓${ANSI.RESET} ${ANSI.DIM}${toolName}:${ANSI.RESET} ${resultStr}`)
    }
  } else if (type === 'status') {
    const status = event.status as string
    wsStatus.value = status as 'idle' | 'running' | 'streaming'
    if (status === 'running') isProcessing.value = true
    else if (status === 'idle') { isProcessing.value = false; writePrompt() }
  } else if (type === 'session_end') {
    isProcessing.value = false
    writePrompt()
  } else if (type === 'error') {
    writeLineColored(`⚠ ${event.message || 'Unknown error'}`, ANSI.RED)
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

function formatResult(result: unknown): string {
  if (result === null || result === undefined) return '(no result)'
  const str = typeof result === 'string' ? result : JSON.stringify(result)
  return str.length > 200 ? str.slice(0, 200) + '...' : str
}

// ── Command processing ──────────────────────────────────────────────────

async function processCommand(text: string) {
  const trimmed = text.trim()
  if (!trimmed) return

  writeLineColored(`❯ ${trimmed}`, ANSI.DIM)

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
      case '/status':
        sendAgentMessage({ type: 'get_status' })
        isProcessing.value = false; writePrompt()
        break
      case '/new':
        sendAgentMessage({ type: 'new_session' })
        isProcessing.value = false; writePrompt()
        break
      case '/abort':
        sendAgentMessage({ type: 'abort' })
        isProcessing.value = false; writePrompt()
        break
      case '/mode':
        mode.value = 'command'
        writeLineColored('Switched to command mode', ANSI.YELLOW)
        isProcessing.value = false; writePrompt()
        break
      case '/help':
        showHelp(); isProcessing.value = false; writePrompt()
        break
      case '/clear':
        term?.clear(); writePrompt()
        isProcessing.value = false
        break
      default:
        writeLineColored(t('tui.unknownCommand', { command: cmd }), ANSI.RED)
        isProcessing.value = false; writePrompt()
    }
  } else {
    sendAgentMessage({ type: 'send_message', content: text })
  }
}

async function processCommandMode(text: string) {
  isProcessing.value = true
  try {
    if (text.startsWith('/')) {
      await processSlashCommand(text)
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
    case '/start': await handleStart(arg || undefined); break
    case '/status': await handleStatus(arg || activeThreadId.value || ''); break
    case '/pause': await handlePause(arg || activeThreadId.value || ''); break
    case '/resume': await handleResume(arg || activeThreadId.value || ''); break
    case '/cancel': await handleCancel(arg || activeThreadId.value || ''); break
    case '/approve': await handleApprove(arg || activeThreadId.value || ''); break
    case '/reject': await handleReject(activeThreadId.value || '', arg); break
    case '/mode':
      mode.value = 'agent'
      reconnectAttempts = 0
      connectAgentWs()
      writeLineColored('Switching to agent mode...', ANSI.YELLOW)
      break
    case '/help': showHelp(); break
    case '/clear': term?.clear(); writePrompt(); break
    default:
      writeLineColored(t('tui.unknownCommand', { command }), ANSI.RED)
  }
}

// ── Command mode handlers ──────────────────────────────────────────────

async function handleStart(topic?: string) {
  const accountId = authStore.user?.id || 'default'
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
  writeLineColored(
    `Phase: ${state.phase}\nStatus: ${state.status}\nProgress: ${state.progress_percent ?? 0}%\nAgent: ${state.current_agent || 'none'}\nNext: ${state.next_steps?.join(', ') || 'none'}`,
    ANSI.BRIGHT_GREEN,
  )
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

function showHelp() {
  const C = ANSI.BRIGHT_CYAN, G = ANSI.BRIGHT_GREEN, D = ANSI.DIM, W = ANSI.BRIGHT_WHITE, R = ANSI.RESET
  const Y = ANSI.BRIGHT_YELLOW, B = ANSI.BRIGHT_BLUE

  const hw = Math.max(30, Math.min(termCols - 4, 52))
  writeLine('')
  writeLine(`${C}╭${'─'.repeat(hw)}╮${R}`)
  writeLine(`${C}│${R}  ${W}XHS Growth Agent — Help${R}${' '.repeat(Math.max(0, hw - 26))}${C}│${R}`)
  writeLine(`${C}╰${'─'.repeat(hw)}╯${R}`)

  const sep = `${D}${'─'.repeat(Math.min(38, hw - 2))}${R}`

  if (mode.value === 'agent') {
    writeLine('')
    writeLine(`  ${Y}Agent Mode${R}`)
    writeLine(`  ${sep}`)
    writeLine(`  ${G}<message>${R}      Send message to AI agent`)
    writeLine(`  ${G}/status${R}        Get agent status`)
    writeLine(`  ${G}/new${R}           Start new session`)
    writeLine(`  ${G}/abort${R}         Abort current turn`)
    writeLine(`  ${G}/mode${R}          Switch to command mode`)
  } else {
    writeLine('')
    writeLine(`  ${Y}Command Mode${R}`)
    writeLine(`  ${sep}`)
    writeLine(`  ${G}/start${R} ${D}[topic]${R}  Start workflow`)
    writeLine(`  ${G}/status${R} ${D}[id]${R}    Check workflow status`)
    writeLine(`  ${G}/pause${R} ${D}[id]${R}     Pause workflow`)
    writeLine(`  ${G}/resume${R} ${D}[id]${R}    Resume workflow`)
    writeLine(`  ${G}/cancel${R} ${D}[id]${R}    Cancel workflow`)
    writeLine(`  ${G}/approve${R} ${D}[id]${R}   Approve content`)
    writeLine(`  ${G}/reject${R} ${D}<msg>${R}   Reject with feedback`)
    writeLine(`  ${G}/mode${R}          Switch to agent mode`)
  }

  writeLine('')
  writeLine(`  ${Y}Shortcuts${R}`)
  writeLine(`  ${sep}`)
  writeLine(`  ${G}/help${R}            Show this help`)
  writeLine(`  ${G}/clear${R}           Clear terminal`)
  writeLine(`  ${B}↑/↓${R}              Command history`)
  writeLine(`  ${B}Tab${R}              Auto-complete`)
  writeLine(`  ${B}Ctrl+C${R}           Abort / interrupt`)
  writeLine(`  ${B}Ctrl+U/W/K/A/E${R}   Line editing`)
  writeLine(`  ${B}Ctrl+Shift+F${R}     Search`)
  writeLine(`  ${B}Ctrl+Shift+C/V${R}   Copy / Paste`)
  writeLine('')
}

// ── Status bar computed ────────────────────────────────────────────────

const modeLabel = computed(() => mode.value === 'agent' ? 'AGENT' : 'CMD')
// ponytail: modeIndicatorColor removed — mode badge uses :class binding directly

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

  // Welcome banner — native TUI feel with box drawing, adaptive width
  const W = ANSI.BRIGHT_CYAN, G = ANSI.BRIGHT_GREEN, D = ANSI.DIM, R = ANSI.RESET
  const bannerWidth = Math.max(30, Math.min(termCols - 4, 50))
  writeLine('')
  writeLine(`${W}╭${'─'.repeat(bannerWidth)}╮${R}`)
  writeLine(`${W}│${R}  ${G}XHS Growth Agent${R}  ${D}v1.0${R}${' '.repeat(Math.max(0, bannerWidth - 22))}${W}│${R}`)
  writeLine(`${W}│${R}  ${D}小红书内容增长智能体${R}${' '.repeat(Math.max(0, bannerWidth - 12))}${W}│${R}`)
  writeLine(`${W}╰${'─'.repeat(bannerWidth)}╯${R}`)
  writeLine('')
  writeLineColored(`  Type ${ANSI.BRIGHT_WHITE}/help${ANSI.RESET} for commands, or just start chatting.`, ANSI.DIM)
  writeLine('')

  // Try connecting to agent WebSocket
  connectAgentWs()

  // Resume active workflow if any
  if (workflowStore.activeThreadId) {
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
      <div class="tui-status-dot" :class="wsConnected ? 'connected' : 'disconnected'" />
      <span class="tui-status-label">xhs-agent</span>
      <span class="tui-mode-badge" :class="mode === 'agent' && wsConnected ? 'mode-agent' : 'mode-cmd'">{{ modeLabel }}</span>
      <span v-if="activeThreadId" class="tui-thread-id">{{ activeThreadId.slice(0, 8) }}</span>
      <div class="flex-1" />
      <span v-if="isProcessing" class="tui-running-indicator">● processing</span>
      <button
        class="tui-status-btn"
        :class="{ active: searchVisible }"
        title="Ctrl+Shift+F"
        @click.stop="toggleSearch"
      >⌕</button>
    </div>

    <!-- Search bar — native terminal search -->
    <div v-if="searchVisible" class="tui-searchbar flex items-center gap-1 px-2 py-1 shrink-0" @click.stop>
      <input
        ref="searchInputRef"
        v-model="searchQuery"
        class="tui-search-input flex-1"
        placeholder="Search..."
        @input="onSearchInput"
        @keydown.enter="doSearch('next')"
        @keydown.shift.enter="doSearch('prev')"
        @keydown.escape="closeSearch"
      />
      <button class="tui-search-toggle" :class="{ active: searchCaseSensitive }" title="Case sensitive" @click="searchCaseSensitive = !searchCaseSensitive; onSearchInput()">Aa</button>
      <button class="tui-search-toggle" :class="{ active: searchRegex }" title="Regex" @click="searchRegex = !searchRegex; onSearchInput()">.*</button>
      <span class="tui-search-info">{{ searchResultInfo }}</span>
      <button class="tui-search-nav" title="Previous" @click="doSearch('prev')">↑</button>
      <button class="tui-search-nav" title="Next" @click="doSearch('next')">↓</button>
      <button class="tui-search-nav" title="Close" @click="closeSearch">✕</button>
    </div>

    <!-- xterm.js container -->
    <div ref="termRef" class="tui-term-area flex-1 min-h-0" tabindex="0" @focus="term?.focus()" />

    <!-- Mobile input bar -->
    <div v-if="isMobile" class="tui-mobile-bar flex items-center gap-2 px-3 py-2 shrink-0">
      <input
        v-model="mobileInput"
        class="tui-mobile-input flex-1"
        :placeholder="mode === 'agent' && wsConnected ? '输入消息...' : '输入命令...'"
        enterkeyhint="send"
        @keydown.enter="submitMobileInput"
      />
      <button class="tui-mobile-send" @click="submitMobileInput">↵</button>
    </div>

    <!-- Context menu -->
    <div
      v-if="contextMenuVisible"
      class="tui-context-menu fixed py-1 z-50 min-w-[160px]"
      :style="{ left: `${contextMenuPos.x}px`, top: `${contextMenuPos.y}px` }"
      @click.stop
    >
      <button v-if="contextMenuHasSelection" class="tui-menu-item" @click="menuCopy">Copy</button>
      <button class="tui-menu-item" @click="menuPaste">Paste</button>
      <button class="tui-menu-item" @click="menuSelectAll">Select All</button>
      <div class="tui-menu-sep" />
      <button class="tui-menu-item" @click="menuSearch">Search</button>
      <button class="tui-menu-item" @click="menuClear">Clear</button>
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

.tui-thread-id {
  color: #414868;
  font-size: 10px;
  margin-left: 4px;
  font-variant-numeric: tabular-nums;
}

.tui-running-indicator {
  color: #e0af68;
  font-size: 10px;
  animation: pulse-glow 1.5s ease-in-out infinite;
}

.tui-status-btn {
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

/* ── Search bar — flat, terminal-native ─────────────────────────────── */
.tui-searchbar {
  background: #16161e;
  border-bottom: 1px solid #292e42;
  font-family: 'JetBrains Mono', 'Fira Code', 'Menlo', monospace;
}

.tui-search-input {
  background: #1a1b26;
  color: #a9b1d6;
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 0;
  border: 1px solid #292e42;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s;
}
.tui-search-input:focus {
  border-color: #7aa2f7;
  box-shadow: 0 0 0 1px #7aa2f720;
}
.tui-search-input::placeholder {
  color: #414868;
}

.tui-search-toggle {
  font-size: 10px;
  font-family: inherit;
  padding: 1px 4px;
  border-radius: 0;
  color: #565f89;
  background: none;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}
.tui-search-toggle:hover { color: #a9b1d6; }
.tui-search-toggle.active {
  color: #7aa2f7;
  border-color: #7aa2f740;
  background: #7aa2f710;
}

.tui-search-info {
  color: #414868;
  font-size: 10px;
  min-width: 60px;
  text-align: center;
}

.tui-search-nav {
  font-size: 11px;
  font-family: inherit;
  color: #565f89;
  background: none;
  border: none;
  padding: 2px 4px;
  cursor: pointer;
  border-radius: 0;
  transition: all 0.15s;
}
.tui-search-nav:hover {
  color: #a9b1d6;
  background: #292e42;
}

/* ── Mobile input bar — utilitarian, less rounded ───────────────────── */
.tui-mobile-bar {
  background: #16161e;
  border-top: 1px solid #292e42;
  padding-bottom: max(0.5rem, env(safe-area-inset-bottom));
}

.tui-mobile-input {
  background: #1a1b26;
  color: #a9b1d6;
  font-size: 14px;
  padding: 6px 10px;
  border-radius: 2px;
  border: 1px solid #292e42;
  font-family: 'JetBrains Mono', 'Menlo', monospace;
  outline: none;
  transition: border-color 0.15s;
}
.tui-mobile-input:focus {
  border-color: #7aa2f7;
}
.tui-mobile-input::placeholder {
  color: #414868;
}

.tui-mobile-send {
  background: #292e42;
  color: #a9b1d6;
  font-size: 13px;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 2px;
  border: 1px solid #3b4261;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s;
}
.tui-mobile-send:hover {
  background: #3b4261;
}
.tui-mobile-send:active {
  background: #565f89;
}

/* ── Context menu — sharp, flat, native ─────────────────────────────── */
.tui-context-menu {
  background: #1a1b26;
  border: 1px solid #3b4261;
  border-radius: 0;
  box-shadow: 4px 4px 0 #00000080;
  font-family: 'JetBrains Mono', 'Menlo', monospace;
  padding: 2px 0;
}

.tui-menu-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 4px 12px;
  font-size: 12px;
  color: #a9b1d6;
  background: none;
  border: none;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.08s;
}
.tui-menu-item:hover {
  background: #292e42;
  color: #c0caf5;
}

.tui-menu-sep {
  height: 1px;
  background: #292e42;
  margin: 2px 8px;
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
