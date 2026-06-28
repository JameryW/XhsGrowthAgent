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
    ? `${ANSI.DIM}...${ANSI.RESET} `
    : mode.value === 'agent' && wsConnected.value
      ? `${ANSI.BRIGHT_GREEN}🤖>${ANSI.RESET} `
      : `${ANSI.BRIGHT_CYAN}>${ANSI.RESET} `
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
      matchBackground: '#444444',
      matchBorder: '#888888',
      matchOverviewRuler: '#888888',
      activeMatchBackground: '#ff5f5f',
      activeMatchBorder: '#ff8787',
      activeMatchColorOverviewRuler: '#ff5f5f',
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
    writeLineColored('🤖 Agent mode connected', ANSI.BRIGHT_GREEN)
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
        writeLineColored(`⚠️ Agent disconnected, reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`, ANSI.YELLOW)
        reconnectTimer = setTimeout(connectAgentWs, 3000)
      } else {
        writeLineColored('⚠️ Agent disconnected after max retries, switched to command mode', ANSI.RED)
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
    writeLineColored('✅ Agent ready', ANSI.BRIGHT_GREEN)
    wsStatus.value = 'idle'
    writePrompt()
  } else if (type === 'agent_message') {
    const text = event.text as string
    const done = event.done as boolean
    if (!done && text) {
      const ansi = markdownToAnsi(text)
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
    writeLine(`${ANSI.BRIGHT_CYAN}🔧 ${toolName}${ANSI.DIM}(${argsStr})${ANSI.RESET}`)
  } else if (type === 'tool_result') {
    const toolName = event.tool_name as string
    const isError = event.is_error as boolean
    const resultStr = formatResult(event.result)
    if (isError) {
      writeLine(`${ANSI.RED}❌ ${toolName}: ${resultStr}${ANSI.RESET}`)
    } else {
      writeLine(`${ANSI.BRIGHT_GREEN}✅ ${toolName}: ${resultStr}${ANSI.RESET}`)
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
    writeLineColored(`⚠️ ${event.message || 'Unknown error'}`, ANSI.RED)
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

  writeLineColored(`$ ${trimmed}`, ANSI.DIM)

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
  const agentHelp = mode.value === 'agent' ? `
${ANSI.BRIGHT_CYAN}Agent mode:${ANSI.RESET}
  ${ANSI.DIM}<message>${ANSI.RESET}     Send message to AI agent
  ${ANSI.DIM}/status${ANSI.RESET}       Get agent status
  ${ANSI.DIM}/new${ANSI.RESET}          Start new session
  ${ANSI.DIM}/abort${ANSI.RESET}        Abort current turn
  ${ANSI.DIM}/mode${ANSI.RESET}         Switch to command mode` : ''
  const commandHelp = `
${ANSI.BRIGHT_CYAN}Command mode:${ANSI.RESET}
  ${ANSI.DIM}/start [topic]${ANSI.RESET}  Start workflow
  ${ANSI.DIM}/status [id]${ANSI.RESET}    Check workflow status
  ${ANSI.DIM}/pause [id]${ANSI.RESET}     Pause workflow
  ${ANSI.DIM}/resume [id]${ANSI.RESET}    Resume workflow
  ${ANSI.DIM}/cancel [id]${ANSI.RESET}    Cancel workflow
  ${ANSI.DIM}/approve [id]${ANSI.RESET}   Approve content
  ${ANSI.DIM}/reject <msg>${ANSI.RESET}   Reject with feedback
  ${ANSI.DIM}/mode${ANSI.RESET}           Switch to agent mode`
  const common = `
${ANSI.BRIGHT_CYAN}Common:${ANSI.RESET}
  ${ANSI.DIM}/help${ANSI.RESET}           Show this help
  ${ANSI.DIM}/clear${ANSI.RESET}          Clear terminal
  ${ANSI.DIM}↑/↓${ANSI.RESET}            Command history
  ${ANSI.DIM}Tab${ANSI.RESET}             Auto-complete
  ${ANSI.DIM}Ctrl+C${ANSI.RESET}         Abort/interrupt
  ${ANSI.DIM}Ctrl+U/W/K/A/E${ANSI.RESET} Line editing
  ${ANSI.DIM}Ctrl+Shift+F${ANSI.RESET}   Search
  ${ANSI.DIM}Ctrl+Shift+C/V${ANSI.RESET} Copy/Paste`
  writeLine(`[${mode.value} mode]${commandHelp}${agentHelp}${common}`)
}

// ── Status bar computed ────────────────────────────────────────────────

const modeLabel = computed(() => mode.value === 'agent' ? 'AGENT' : 'CMD')
const modeIndicatorColor = computed(() =>
  mode.value === 'agent' && wsConnected.value ? 'bg-emerald-400' : 'bg-amber-400',
)

// ── Lifecycle ───────────────────────────────────────────────────────────

let resizeObserver: ResizeObserver | null = null
let viewportHandler: (() => void) | null = null

onMounted(() => {
  term = new Terminal({
    cursorBlink: true,
    cursorStyle: 'block',
    fontSize: 14,
    fontFamily: "'Menlo', 'Consolas', 'Courier New', 'Noto Sans Mono CJK SC', 'PingFang SC', 'Microsoft YaHei', 'WenQuanYi Micro Hei Mono', monospace",
    lineHeight: 1.15,
    smoothScrollDuration: 100,
    minimumContrastRatio: 4.5,
    theme: {
      background: '#000000',
      foreground: '#e0e0e0',
      cursor: '#e0e0e0',
      cursorAccent: '#000000',
      selectionBackground: '#444444',
      black: '#000000',
      red: '#ff5f5f',
      green: '#5fff5f',
      yellow: '#ffff5f',
      blue: '#5f5fff',
      magenta: '#ff5fff',
      cyan: '#5fffff',
      white: '#e0e0e0',
      brightBlack: '#666666',
      brightRed: '#ff8787',
      brightGreen: '#87ff87',
      brightYellow: '#ffff87',
      brightBlue: '#8787ff',
      brightMagenta: '#ff87ff',
      brightCyan: '#87ffff',
      brightWhite: '#ffffff',
    },
    scrollback: 5000,
    convertEol: true,
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
  }

  // IME composition tracking on the hidden textarea
  const textarea = (term as any).textarea as HTMLTextAreaElement | undefined
  if (textarea) {
    textarea.addEventListener('compositionstart', () => { isComposing = true })
    textarea.addEventListener('compositionend', () => { isComposing = false })
  }

  term.onData(handleTermData)
  setupKeyEventHandler()

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

  // Welcome message
  writeLineColored(t('tui.welcome'), ANSI.BRIGHT_GREEN)
  writeLineColored(t('tui.welcomeHint'), ANSI.DIM)
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
  <div class="tui-container h-[calc(100dvh-4rem)] flex flex-col bg-black" @click="closeContextMenu">
    <!-- Status bar -->
    <div class="flex items-center gap-2 px-3 py-1 bg-black border-b border-zinc-800 shrink-0">
      <div class="w-2 h-2 rounded-full" :class="wsConnected ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'" />
      <span class="text-[10px] font-mono text-zinc-500">xhs-agent</span>
      <span class="text-[10px] font-mono px-1.5 py-0.5 rounded" :class="[modeIndicatorColor, 'text-black font-semibold']">{{ modeLabel }}</span>
      <span v-if="activeThreadId" class="text-[10px] font-mono text-zinc-600 ml-1">{{ activeThreadId }}</span>
      <span v-if="isProcessing" class="text-[10px] font-mono text-amber-400 ml-auto animate-pulse">● running</span>
      <!-- Search toggle button -->
      <button
        class="text-[10px] font-mono text-zinc-500 hover:text-zinc-300 ml-auto px-1"
        :class="{ 'text-zinc-300': searchVisible }"
        title="Ctrl+Shift+F"
        @click.stop="toggleSearch"
      >⌕</button>
    </div>

    <!-- Search bar -->
    <div v-if="searchVisible" class="flex items-center gap-1 px-2 py-1 bg-zinc-900 border-b border-zinc-700 shrink-0" @click.stop>
      <input
        ref="searchInputRef"
        v-model="searchQuery"
        class="flex-1 bg-zinc-800 text-zinc-200 text-xs px-2 py-1 rounded font-mono outline-none focus:ring-1 focus:ring-zinc-500"
        placeholder="Search..."
        @input="onSearchInput"
        @keydown.enter="doSearch('next')"
        @keydown.shift.enter="doSearch('prev')"
        @keydown.escape="closeSearch"
      />
      <button class="text-[10px] font-mono px-1 py-0.5 rounded text-zinc-400 hover:text-zinc-200" :class="{ 'text-cyan-400': searchCaseSensitive }" title="Case sensitive" @click="searchCaseSensitive = !searchCaseSensitive; onSearchInput()">Aa</button>
      <button class="text-[10px] font-mono px-1 py-0.5 rounded text-zinc-400 hover:text-zinc-200" :class="{ 'text-cyan-400': searchRegex }" title="Regex" @click="searchRegex = !searchRegex; onSearchInput()">.*</button>
      <span class="text-[10px] font-mono text-zinc-500">{{ searchResultInfo }}</span>
      <button class="text-[10px] font-mono text-zinc-400 hover:text-zinc-200" title="Previous" @click="doSearch('prev')">↑</button>
      <button class="text-[10px] font-mono text-zinc-400 hover:text-zinc-200" title="Next" @click="doSearch('next')">↓</button>
      <button class="text-[10px] font-mono text-zinc-400 hover:text-zinc-200" title="Close" @click="closeSearch">✕</button>
    </div>

    <!-- xterm.js container -->
    <div ref="termRef" class="flex-1 min-h-0" />

    <!-- Mobile input bar -->
    <div v-if="isMobile" class="flex items-center gap-2 px-2 py-2 bg-zinc-900 border-t border-zinc-700 shrink-0 safe-area-bottom">
      <input
        v-model="mobileInput"
        class="flex-1 bg-zinc-800 text-zinc-200 text-sm px-3 py-2 rounded-lg font-mono outline-none"
        :placeholder="mode === 'agent' && wsConnected ? '输入消息...' : '输入命令...'"
        enterkeyhint="send"
        @keydown.enter="submitMobileInput"
      />
      <button
        class="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg font-mono shrink-0"
        @click="submitMobileInput"
      >↵</button>
    </div>

    <!-- Context menu -->
    <div
      v-if="contextMenuVisible"
      class="tui-context-menu fixed bg-zinc-800 border border-zinc-600 rounded shadow-xl py-1 z-50 min-w-[140px]"
      :style="{ left: `${contextMenuPos.x}px`, top: `${contextMenuPos.y}px` }"
      @click.stop
    >
      <button v-if="contextMenuHasSelection" class="w-full text-left px-3 py-1.5 text-xs font-mono text-zinc-300 hover:bg-zinc-700" @click="menuCopy">Copy</button>
      <button class="w-full text-left px-3 py-1.5 text-xs font-mono text-zinc-300 hover:bg-zinc-700" @click="menuPaste">Paste</button>
      <button class="w-full text-left px-3 py-1.5 text-xs font-mono text-zinc-300 hover:bg-zinc-700" @click="menuSelectAll">Select All</button>
      <div class="border-t border-zinc-600 my-1" />
      <button class="w-full text-left px-3 py-1.5 text-xs font-mono text-zinc-300 hover:bg-zinc-700" @click="menuSearch">Search</button>
      <button class="w-full text-left px-3 py-1.5 text-xs font-mono text-zinc-300 hover:bg-zinc-700" @click="menuClear">Clear</button>
    </div>
  </div>
</template>

<style scoped>
/* Safe area for mobile notch/home indicator */
.safe-area-bottom {
  padding-bottom: max(0.5rem, env(safe-area-inset-bottom));
}
</style>
