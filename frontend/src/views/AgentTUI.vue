<script setup lang="ts">
/**
 * AgentTUI — xterm.js-powered terminal page for XhsGrowthAgent.
 *
 * Two modes:
 * 1. Agent mode (default): WebSocket to omp bridge for AI agent conversation
 * 2. Command mode (fallback): direct API calls for workflow operations
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Terminal } from 'xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import 'xterm/css/xterm.css'
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

// ── xterm.js setup ──────────────────────────────────────────────────────
const termRef = ref<HTMLDivElement | null>(null)
let term: Terminal | null = null
let fitAddon: FitAddon | null = null

// ── State ───────────────────────────────────────────────────────────────
const activeThreadId = ref<string | null>(null)
const isProcessing = ref(false)
const currentInput = ref('')
const cursorPos = ref(0)
const commandHistory = ref<string[]>([])
const historyIndex = ref(-1)

type TuiMode = 'agent' | 'command'
const mode = ref<TuiMode>('command')

// ── Agent mode: WebSocket ───────────────────────────────────────────────
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/agent/ws`
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
const MAX_RECONNECT_ATTEMPTS = 3
const wsConnected = ref(false)
const wsStatus = ref<'idle' | 'running' | 'streaming'>('idle')

// ponytail: streaming text accumulator removed — agent mode uses write() directly

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

/** Clear current input line and rewrite */
function refreshInputLine() {
  // Move to start of input, clear to end, write prompt + current input
  if (!term) return
  // Clear from cursor to end of line
  const inputLen = currentInput.value.length
  if (inputLen > 0 || cursorPos.value < inputLen) {
    term.write('\r\x1b[2K') // CR + clear line
  } else {
    term.write('\r\x1b[2K')
  }
  writePrompt()
  if (currentInput.value) {
    term.write(currentInput.value)
    // Position cursor
    const offset = currentInput.value.length - cursorPos.value
    if (offset > 0) term.write(`\x1b[${offset}D`)
  }
}

// ── Command history ─────────────────────────────────────────────────────

const MAX_HISTORY = 100

function pushHistory(cmd: string) {
  if (!cmd.trim()) return
  // Deduplicate consecutive
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

// ── Input handling ──────────────────────────────────────────────────────

function handleTermData(data: string) {
  if (!term) return

  // Process each character / escape sequence
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
    // Backspace
    if (cursorPos.value > 0) {
      const before = currentInput.value.slice(0, cursorPos.value - 1)
      const after = currentInput.value.slice(cursorPos.value)
      currentInput.value = before + after
      cursorPos.value--
      refreshInputLine()
    }
  } else if (data === '\t') {
    // Tab
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
    // Up arrow
    historyUp()
  } else if (data === '\x1b[B') {
    // Down arrow
    historyDown()
  } else if (data === '\x1b[C') {
    // Right arrow
    if (cursorPos.value < currentInput.value.length) {
      cursorPos.value++
      term.write('\x1b[C')
    }
  } else if (data === '\x1b[D') {
    // Left arrow
    if (cursorPos.value > 0) {
      cursorPos.value--
      term.write('\x1b[D')
    }
  } else if (code >= 32 && code < 127) {
    // Printable character
    const before = currentInput.value.slice(0, cursorPos.value)
    const after = currentInput.value.slice(cursorPos.value)
    currentInput.value = before + data + after
    cursorPos.value++
    if (after) {
      // Insert in middle: rewrite from cursor
      term.write(data + after)
      term.write(`\x1b[${after.length}D`)
    } else {
      term.write(data)
    }
  }
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
      // Render markdown as ANSI
      const ansi = markdownToAnsi(text)
      write(ansi)
    }
    if (done) {
      writeLine('')
      // ponytail: streaming done — reset accumulator if needed later
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

  // Echo command in dim color
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
  ${ANSI.DIM}Ctrl+C${ANSI.RESET}         Abort/interrupt`
  writeLine(`[${mode.value} mode]${commandHelp}${agentHelp}${common}`)
}

// ── Status bar computed ────────────────────────────────────────────────

const modeLabel = computed(() => mode.value === 'agent' ? 'AGENT' : 'CMD')
const modeIndicatorColor = computed(() =>
  mode.value === 'agent' && wsConnected.value ? 'bg-emerald-400' : 'bg-amber-400',
)

// ── Lifecycle ───────────────────────────────────────────────────────────

onMounted(() => {
  term = new Terminal({
    cursorBlink: true,
    cursorStyle: 'block',
    fontSize: 14,
    fontFamily: "'Menlo', 'Consolas', 'Courier New', monospace",
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
    allowProposedApi: true,
    scrollback: 5000,
    convertEol: true,
  })

  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)
  term.loadAddon(new WebLinksAddon())

  if (termRef.value) {
    term.open(termRef.value)
    fitAddon.fit()
  }

  term.onData(handleTermData)

  // Resize observer
  const ro = new ResizeObserver(() => fitAddon?.fit())
  if (termRef.value) ro.observe(termRef.value)
  // ponytail: store RO for cleanup — skip for now, page unmount kills it

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

onUnmounted(() => {
  disconnectAgentWs()
  term?.dispose()
  term = null
  fitAddon = null
})
</script>

<template>
  <div class="h-[calc(100vh-4rem)] flex flex-col bg-black">
    <!-- Minimal status bar -->
    <div class="flex items-center gap-2 px-3 py-1 bg-black border-b border-zinc-800 shrink-0">
      <div class="w-2 h-2 rounded-full" :class="wsConnected ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'" />
      <span class="text-[10px] font-mono text-zinc-500">xhs-agent</span>
      <span class="text-[10px] font-mono px-1.5 py-0.5 rounded" :class="[modeIndicatorColor, 'text-black font-semibold']">{{ modeLabel }}</span>
      <span v-if="activeThreadId" class="text-[10px] font-mono text-zinc-600 ml-1">{{ activeThreadId }}</span>
      <span v-if="isProcessing" class="text-[10px] font-mono text-amber-400 ml-auto animate-pulse">● running</span>
    </div>

    <!-- xterm.js container -->
    <div ref="termRef" class="flex-1 min-h-0" />
  </div>
</template>
