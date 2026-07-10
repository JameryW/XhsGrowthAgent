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
import client from '@/api/client'
import { markdownToAnsi, ANSI } from '@/utils/markdownToAnsi'

const { t } = useI18n()
const route = useRoute()
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
  '/approve', '/reject', '/mode', '/help', '/clear', '/new', '/abort', '/drafts', '/draft', '/delete',
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
        writeLineColored(t('tui.agentDisconnected', { cur: reconnectAttempts, max: MAX_RECONNECT_ATTEMPTS }), ANSI.YELLOW)
        reconnectTimer = setTimeout(connectAgentWs, 3000)
      } else {
        writeLineColored(t('tui.agentDisconnectedMax'), ANSI.RED)
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
      // ponytail: dim rule closes the AI reply block, separates it from the next prompt
      writeLine('')
      writeLineColored(`${'─'.repeat(Math.max(8, Math.min(termCols - 2, 40)))}`, ANSI.DIM)
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
    const indent = '    '
    for (const ln of lines.slice(1)) writeLine(`${indent}${ln}`)
  } else if (type === 'status') {
    const status = event.status as string
    wsStatus.value = status as 'idle' | 'running' | 'streaming'
    if (status === 'running') isProcessing.value = true
    else if (status === 'idle') { isProcessing.value = false; writePrompt() }
  } else if (type === 'session_end') {
    isProcessing.value = false
    writePrompt()
  } else if (type === 'error') {
    // ponytail: 2-space indent aligns with ▸/↳ tool block; red mark + default-color msg for hierarchy
    writeLine(`  ${ANSI.RED}⚠${ANSI.RESET} ${event.message || t('tui.unknownError')}`)
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
      case '/drafts':
        await handleDrafts()
        isProcessing.value = false; writePrompt()
        break
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
    } else if (isFreeCreationEntry.value) {
      writeLineColored(t('tui.freeAgentUnavailable'), ANSI.YELLOW)
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
        sendAgentMessage({ type: 'new_session' })
        writeLineColored(t('tui.freeNewSession'), ANSI.BRIGHT_GREEN)
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

async function handleDrafts() {
  if (!isFreeCreationEntry.value) {
    writeLineColored(t('tui.freeWorkflowOpDisabled'), ANSI.YELLOW)
    return
  }
  const accountId = authStore.user?.id || 'default'
  try {
    const resp = await client.get(`/free/drafts/${accountId}`)
    const data = resp as unknown as {
      drafts: Array<{
        draft_id: string
        title: string
        created_at?: string | null
        updated_at?: string | null
        last_evaluation?: { overall_score?: number | null; decision?: string | null } | null
        published?: boolean | null
      }>
    }
    writeLine('')
    writeLineColored(t('tui.draftsListTitle', { accountId }), ANSI.BRIGHT_CYAN)
    if (!data.drafts || data.drafts.length === 0) {
      writeLineColored(`  ${t('tui.draftsNone')}`, ANSI.DIM)
    } else {
      for (const d of data.drafts) {
        const titlePart = d.title
          ? d.title
          : `${ANSI.DIM}${t('tui.draftUntitled')}${ANSI.RESET}`
        let line = `  ${ANSI.BRIGHT_GREEN}${d.draft_id}${ANSI.RESET}: ${titlePart}`
        // evaluation badge (only if last_evaluation present)
        const le = d.last_evaluation
        if (le && le.decision) {
          const decColor =
            le.decision === 'approved' ? ANSI.BRIGHT_GREEN
            : le.decision === 'needs_revision' ? ANSI.BRIGHT_YELLOW
            : ANSI.RED
          const score = le.overall_score != null ? le.overall_score : ''
          line += `  ${decColor}[${t('tui.draftEvalBadge', { score, decision: le.decision })}]${ANSI.RESET}`
        }
        // published badge
        if (d.published) {
          line += `  ${ANSI.BRIGHT_CYAN}[${t('tui.draftPublished')}]${ANSI.RESET}`
        }
        // updated_at (short, YYYY-MM-DDTHH:MM)
        if (d.updated_at) {
          const short = d.updated_at.slice(0, 16)
          line += `  ${ANSI.DIM}${short}${ANSI.RESET}`
        }
        writeLine(line)
      }
    }
    writeLine('')
  } catch (err: any) {
    writeLineColored(err.message || t('tui.draftsFetchFailed'), ANSI.RED)
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
  last_evaluation?: { overall_score?: number; decision?: string; revision_hints?: string[] } | null
  published?: boolean
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
  const accountId = authStore.user?.id || 'default'
  try {
    const resp = await client.get(`/free/draft/${draftId}?account_id=${encodeURIComponent(accountId)}`)
    const data = resp as unknown as { draft_id: string; draft: FreeDraftRecord }
    const draft = data.draft || {}
    const C = ANSI.BRIGHT_CYAN, G = ANSI.BRIGHT_GREEN, D = ANSI.DIM, W = ANSI.BRIGHT_WHITE
    const Y = ANSI.BRIGHT_YELLOW, R = ANSI.RESET
    writeLine('')
    writeLine(`${C}╭${'─'.repeat(52)}╮${R}`)
    writeLine(`${C}│${R} ${W}${t('tui.draftDetailTitle')}${R}${' '.repeat(Math.max(0, 51 - getStringWidth(t('tui.draftDetailTitle'))))}${C}│${R}`)
    writeLine(`${C}╰${'─'.repeat(52)}╯${R}`)
    writeLine(`  ${D}${t('tui.draftDetailDraftIdLabel')}${R}: ${G}${data.draft_id}${R}`)
    if (draft.account_id) {
      writeLine(`  ${D}${t('tui.draftDetailAccountLabel')}${R}: ${draft.account_id}`)
    }
    writeLine(`  ${D}${t('tui.draftDetailTitleLabel')}${R}: ${draft.title || `${D}${t('tui.draftUntitled')}${R}`}`)
    if (draft.body) {
      writeLine(`  ${D}${t('tui.draftDetailBodyLabel')}${R}:`)
      writeLine(`    ${draft.body}`)
    }
    if (draft.hashtags && draft.hashtags.length > 0) {
      writeLine(`  ${D}${t('tui.draftDetailHashtagsLabel')}${R}: ${G}${draft.hashtags.join(', ')}${R}`)
    }
    if (draft.image_paths && draft.image_paths.length > 0) {
      writeLine(`  ${D}${t('tui.draftDetailImagesLabel')}${R}: ${draft.image_paths.join(', ')}`)
    }
    if (draft.niche) {
      writeLine(`  ${D}${t('tui.draftDetailNicheLabel')}${R}: ${draft.niche}`)
    }
    if (draft.content_angle) {
      writeLine(`  ${D}${t('tui.draftDetailAngleLabel')}${R}: ${draft.content_angle}`)
    }
    if (draft.target_audience) {
      writeLine(`  ${D}${t('tui.draftDetailAudienceLabel')}${R}: ${draft.target_audience}`)
    }
    // Status fields — render only if present (graceful for pre-#216 drafts)
    const hasStatus = draft.created_at || draft.updated_at || draft.last_evaluation || draft.published !== undefined
    if (hasStatus) {
      writeLine(`  ${D}${'─'.repeat(20)}${R}`)
      if (draft.last_evaluation) {
        const score = draft.last_evaluation.overall_score
        const decision = draft.last_evaluation.decision
        const scoreStr = score !== undefined ? score.toFixed(1) : '?'
        const decisionColor = decision === 'approved' ? G : (decision === 'rejected' ? ANSI.RED : Y)
        writeLine(`  ${D}${t('tui.draftDetailEvalLabel')}${R}: ${decisionColor}${scoreStr} (${decision || '?'})${R}`)
        // revision hints — only render if present + non-empty (graceful for
        // pre-#217 drafts without the revision_hints key)
        const hints = draft.last_evaluation.revision_hints
        if (hints && hints.length > 0) {
          writeLine(`  ${D}${t('tui.draftDetailHintsLabel')}${R}:`)
          for (const hint of hints) {
            writeLine(`    ${D}• ${hint}${R}`)
          }
        }
      }
      if (draft.published !== undefined) {
        const pubColor = draft.published ? G : D
        const pubStr = draft.published ? t('tui.draftDetailPublishedYes') : t('tui.draftDetailPublishedNo')
        writeLine(`  ${D}${t('tui.draftDetailPublishedLabel')}${R}: ${pubColor}${pubStr}${R}`)
      }
      if (draft.created_at) {
        writeLine(`  ${D}${t('tui.draftDetailCreatedLabel')}${R}: ${draft.created_at}`)
      }
      if (draft.updated_at) {
        writeLine(`  ${D}${t('tui.draftDetailUpdatedLabel')}${R}: ${draft.updated_at}`)
      }
    }
    writeLine('')
  } catch (err: any) {
    writeLineColored(err.message || t('tui.draftDetailFetchFailed'), ANSI.RED)
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
  const accountId = authStore.user?.id || 'default'
  let title = ''
  // GET first so the user sees what is being deleted (acts as confirmation).
  // GET 400 (not found) aborts the delete — no silent success on a bad id.
  try {
    const resp = await client.get(`/free/draft/${draftId}?account_id=${encodeURIComponent(accountId)}`)
    const data = resp as unknown as { draft_id: string; draft: FreeDraftRecord }
    title = data.draft?.title || t('tui.draftUntitled')
    writeLineColored(t('tui.draftDeleting', { title }), ANSI.YELLOW)
  } catch (err: any) {
    writeLineColored(t('tui.draftNotFound'), ANSI.RED)
    return
  }
  try {
    await client.delete(`/free/draft/${draftId}?account_id=${encodeURIComponent(accountId)}`)
    writeLineColored(t('tui.draftDeleted', { title }), ANSI.BRIGHT_GREEN)
  } catch (err: any) {
    writeLineColored(err.message || t('tui.draftDeleteFailed'), ANSI.RED)
  }
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
    if (isFreeCreationEntry.value) {
      writeLine(`  ${G}/start${R}         ${D}${t('tui.freeNewSession')}${R}`)
      writeLine(`  ${G}/mode${R}          Switch to agent mode`)
    } else {
      writeLine(`  ${G}/start${R} ${D}[topic]${R}  Start workflow`)
      writeLine(`  ${G}/status${R} ${D}[id]${R}    Check workflow status`)
      writeLine(`  ${G}/pause${R} ${D}[id]${R}     Pause workflow`)
      writeLine(`  ${G}/resume${R} ${D}[id]${R}    Resume workflow`)
      writeLine(`  ${G}/cancel${R} ${D}[id]${R}    Cancel workflow`)
      writeLine(`  ${G}/approve${R} ${D}[id]${R}   Approve content`)
      writeLine(`  ${G}/reject${R} ${D}<msg>${R}   Reject with feedback`)
      writeLine(`  ${G}/mode${R}          Switch to agent mode`)
    }
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
const isFreeCreationEntry = computed(() => route.query.mode === 'free')
const freeCreationTopic = computed(() => (
  typeof route.query.topic === 'string' ? route.query.topic : ''
))

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
  const W = ANSI.BRIGHT_CYAN, G = ANSI.BRIGHT_GREEN, D = ANSI.DIM, R = ANSI.RESET, Y = ANSI.BRIGHT_YELLOW
  const bannerWidth = Math.max(30, Math.min(termCols - 4, 50))
  writeLine('')
  writeLine(`${W}╭${'─'.repeat(bannerWidth)}╮${R}`)
  writeLine(`${W}│${R}  ${G}XHS Growth Agent${R}  ${D}v1.0${R}${' '.repeat(Math.max(0, bannerWidth - 22))}${W}│${R}`)
  writeLine(`${W}│${R}  ${D}小红书内容增长智能体${R}${' '.repeat(Math.max(0, bannerWidth - 12))}${W}│${R}`)
  writeLine(`${W}├${'─'.repeat(bannerWidth)}┤${R}`)
  const flowText = isFreeCreationEntry.value ? t('tui.freeFlow') : t('tui.workflowFlow')
  writeLine(`${W}│${R}  ${Y}${flowText}${R}${' '.repeat(Math.max(0, bannerWidth - getStringWidth(flowText) - 2))}${W}│${R}`)
  writeLine(`${W}╰${'─'.repeat(bannerWidth)}╯${R}`)
  writeLine('')
  writeLineColored(`  ${isFreeCreationEntry.value ? t('tui.freeWelcomeHint') : t('tui.terminalHint')}`, ANSI.DIM)
  if (isFreeCreationEntry.value && freeCreationTopic.value) {
    writeLineColored(`  ${t('tui.freeTopic', { topic: freeCreationTopic.value })}`, ANSI.DIM)
  }
  writeLine('')

  // Free mode: default to agent mode so plain text routes to omp conversation immediately.
  // Non-free (trend/brief) keeps command mode default — behavior unchanged.
  if (isFreeCreationEntry.value) {
    mode.value = 'agent'
    writeLineColored(`  ${t('tui.freeAgentReady')}`, ANSI.DIM)
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
  background: #7aa2f7;
  color: #1a1b26;
  font-size: 13px;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 2px;
  border: 1px solid #89b4fa;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s, transform 0.08s;
}
.tui-mobile-send:hover {
  background: #89b4fa;
}
.tui-mobile-send:active {
  background: #565f89;
  transform: translateY(1px); /* ponytail: tactile press feedback */
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
