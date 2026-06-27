<script setup lang="ts">
/**
 * AgentTUI — terminal-style interactive page for XhsGrowthAgent.
 *
 * Two modes:
 * 1. Agent mode (default): WebSocket to omp bridge for AI agent conversation
 * 2. Command mode (fallback): direct API calls for workflow operations
 *
 * Mode auto-detected: if omp bridge is ready → agent mode, else command mode.
 */
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
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

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const authStore = useAuthStore()

// ── Terminal state ──────────────────────────────────────────────────────
interface TerminalLine {
  id: number
  type: 'input' | 'output' | 'error' | 'system' | 'progress' | 'review' | 'tool_call' | 'tool_result'
  text: string
  timestamp: Date
  data?: Record<string, unknown>
}

const lines = ref<TerminalLine[]>([])
const inputText = ref('')
const isProcessing = ref(false)
const activeThreadId = ref<string | null>(null)
const outputRef = ref<HTMLDivElement | null>(null)
let lineCounter = 0

function addLine(type: TerminalLine['type'], text: string, data?: Record<string, unknown>) {
  lines.value.push({ id: ++lineCounter, type, text, timestamp: new Date(), data })
  nextTick(() => {
    if (outputRef.value) outputRef.value.scrollTop = outputRef.value.scrollHeight
  })
}

// ── Mode detection ──────────────────────────────────────────────────────
type TuiMode = 'agent' | 'command'
const mode = ref<TuiMode>('command') // start command, switch to agent on ws connect

// ── Agent mode: WebSocket ───────────────────────────────────────────────
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/agent/ws`
let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
const MAX_RECONNECT_ATTEMPTS = 3
const wsConnected = ref(false)
const wsStatus = ref<'idle' | 'running' | 'streaming'>('idle')

function connectAgentWs() {
  if (ws && ws.readyState === WebSocket.OPEN) return

  ws = new WebSocket(WS_URL)

  ws.onopen = () => {
    wsConnected.value = true
    reconnectAttempts = 0
    mode.value = 'agent'
    addLine('system', '🤖 Agent mode connected')
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
        addLine('system', `⚠️ Agent disconnected, reconnecting (${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})...`)
        reconnectTimer = setTimeout(connectAgentWs, 3000)
      } else {
        addLine('system', '⚠️ Agent disconnected after max retries, switched to command mode')
      }
    }
  }

  ws.onerror = () => {
    // onclose will fire after this
  }
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

// Accumulator for streaming agent messages
let currentAgentText = ''

function handleAgentEvent(event: Record<string, unknown>) {
  const type = event.type as string

  if (type === 'ready') {
    addLine('system', '✅ Agent ready')
    wsStatus.value = 'idle'
  } else if (type === 'agent_message') {
    const text = event.text as string
    const done = event.done as boolean
    if (!done && text) {
      // Append to current line or create new
      const lastLine = lines.value[lines.value.length - 1]
      if (lastLine && lastLine.type === 'output' && lastLine.data?.streaming) {
        currentAgentText += text
        lastLine.text = currentAgentText
      } else {
        currentAgentText = text
        addLine('output', text, { streaming: true, message_id: event.message_id })
      }
    }
    if (done) {
      // Mark streaming complete
      const lastLine = lines.value[lines.value.length - 1]
      if (lastLine && lastLine.data?.streaming) {
        delete lastLine.data.streaming
      }
      currentAgentText = ''
      isProcessing.value = false
    }
  } else if (type === 'tool_call') {
    const toolName = event.tool_name as string
    const args = event.args as Record<string, unknown>
    addLine('tool_call', `🔧 ${toolName}(${formatArgs(args)})`, event as unknown as Record<string, unknown>)
  } else if (type === 'tool_result') {
    const toolName = event.tool_name as string
    const isError = event.is_error as boolean
    const resultStr = formatResult(event.result)
    addLine('tool_result',
      isError ? `❌ ${toolName}: ${resultStr}` : `✅ ${toolName}: ${resultStr}`,
      event as unknown as Record<string, unknown>,
    )
  } else if (type === 'status') {
    const status = event.status as string
    wsStatus.value = status as 'idle' | 'running' | 'streaming'
    if (status === 'running') {
      isProcessing.value = true
    } else if (status === 'idle') {
      isProcessing.value = false
    }
  } else if (type === 'session_end') {
    isProcessing.value = false
  } else if (type === 'error') {
    addLine('error', `⚠️ ${event.message || 'Unknown error'}`)
    isProcessing.value = false
  }
}

function formatArgs(args: Record<string, unknown>): string {
  if (!args || Object.keys(args).length === 0) return ''
  const parts = Object.entries(args)
    .slice(0, 3) // ponytail: show first 3 args
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
  const suffix = Object.keys(args).length > 3 ? ', ...' : ''
  return parts.join(', ') + suffix
}

function formatResult(result: unknown): string {
  if (result === null || result === undefined) return '(no result)'
  const str = typeof result === 'string' ? result : JSON.stringify(result)
  // ponytail: truncate long results
  return str.length > 200 ? str.slice(0, 200) + '...' : str
}

// ── SSE subscription (command mode) ────────────────────────────────────
const SSE_EVENTS = [
  'workflow_started', 'workflow_completed', 'workflow_error',
  'phase_changed', 'agent_started', 'agent_completed',
  'review_requested', 'progress_update',
] as const

let eventSource: EventSource | null = null

function handleSSEData(data: Record<string, unknown>) {
  if (data.phase || data.progress_percent !== undefined) {
    addLine('progress', `[${data.phase || '?'}] ${data.progress_percent ?? 0}%${data.current_agent ? ` (agent: ${data.current_agent})` : ''}`)
  }
  if (data.status === 'awaiting_review') {
    addLine('review', t('tui.reviewPending'))
  }
}

function subscribeSSE(threadId: string) {
  if (eventSource) eventSource.close()
  eventSource = new EventSource(`/api/workflow/stream/${threadId}`)

  for (const eventType of SSE_EVENTS) {
    eventSource.addEventListener(eventType, (msg: MessageEvent) => {
      try {
        const data = JSON.parse(msg.data)
        handleSSEData(data)
      } catch { /* ignore malformed */ }
    })
  }

  eventSource.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data)
      handleSSEData(data)
    } catch { /* ignore malformed */ }
  }
}

function unsubscribeSSE() {
  eventSource?.close()
  eventSource = null
}

// ── Command processing ──────────────────────────────────────────────────

async function processCommand(text: string) {
  const trimmed = text.trim()
  if (!trimmed) return

  addLine('input', `$ ${trimmed}`)

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
        isProcessing.value = false
        break
      case '/new':
        sendAgentMessage({ type: 'new_session' })
        isProcessing.value = false
        break
      case '/abort':
        sendAgentMessage({ type: 'abort' })
        isProcessing.value = false
        break
      case '/mode':
        mode.value = 'command'
        addLine('system', 'Switched to command mode')
        isProcessing.value = false
        break
      case '/help':
        showHelp()
        isProcessing.value = false
        break
      case '/clear':
        lines.value = []
        isProcessing.value = false
        break
      default:
        addLine('error', t('tui.unknownCommand', { command: cmd }))
        isProcessing.value = false
    }
  } else {
    // Natural language → send to agent
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
    addLine('error', `${err.message || err}`)
  } finally {
    isProcessing.value = false
  }
}

async function processSlashCommand(cmd: string) {
  const [command, ...args] = cmd.split(/\s+/)
  const arg = args.join(' ')

  switch (command) {
    case '/start':
      await handleStart(arg || undefined)
      break
    case '/status':
      await handleStatus(arg || activeThreadId.value || '')
      break
    case '/pause':
      await handlePause(arg || activeThreadId.value || '')
      break
    case '/resume':
      await handleResume(arg || activeThreadId.value || '')
      break
    case '/cancel':
      await handleCancel(arg || activeThreadId.value || '')
      break
    case '/approve':
      await handleApprove(arg || activeThreadId.value || '')
      break
    case '/reject':
      await handleReject(activeThreadId.value || '', arg)
      break
    case '/mode':
      mode.value = 'agent'
      reconnectAttempts = 0
      connectAgentWs()
      addLine('system', 'Switching to agent mode...')
      break
    case '/help':
      showHelp()
      break
    case '/clear':
      lines.value = []
      break
    default:
      addLine('error', t('tui.unknownCommand', { command }))
  }
}

// ── Command mode handlers ──────────────────────────────────────────────

async function handleStart(topic?: string) {
  const accountId = authStore.user?.id || 'default'
  addLine('system', t('tui.startingWorkflow', { topic: topic ? ` on topic: ${topic}` : '' }))

  const result = await startWorkflow({
    account_id: accountId,
    phase: 'scouting',
    workflow_mode: 'trend',
    ...(topic ? { topic } : {}),
  })

  activeThreadId.value = result.thread_id
  addLine('output', t('tui.workflowStarted', {
    threadId: result.thread_id,
    phase: result.phase,
    status: result.status,
  }))

  subscribeSSE(result.thread_id)
}

async function handleStatus(threadId: string) {
  if (!threadId) { addLine('error', t('tui.noActiveWorkflow')); return }
  addLine('system', t('tui.fetchingStatus', { threadId }))

  const state = await getWorkflowStatus(threadId)
  addLine('output',
    `Phase: ${state.phase}\n` +
    `Status: ${state.status}\n` +
    `Progress: ${state.progress_percent ?? 0}%\n` +
    `Agent: ${state.current_agent || 'none'}\n` +
    `Next: ${state.next_steps?.join(', ') || 'none'}`,
    state as unknown as Record<string, unknown>,
  )
}

async function handlePause(threadId: string) {
  if (!threadId) { addLine('error', t('tui.noActiveWorkflow')); return }
  await pauseWorkflow(threadId)
  addLine('output', t('tui.workflowPaused', { threadId }))
  unsubscribeSSE()
}

async function handleResume(threadId: string) {
  if (!threadId) { addLine('error', t('tui.noActiveWorkflow')); return }
  await resumeWorkflow(threadId)
  addLine('output', t('tui.workflowResumed', { threadId }))
  subscribeSSE(threadId)
}

async function handleCancel(threadId: string) {
  if (!threadId) { addLine('error', t('tui.noActiveWorkflow')); return }
  await cancelWorkflow(threadId)
  addLine('output', t('tui.workflowCancelled', { threadId }))
  unsubscribeSSE()
  activeThreadId.value = null
}

async function handleApprove(threadId: string) {
  if (!threadId) { addLine('error', t('tui.noActiveWorkflow')); return }
  await submitReview(threadId, { decision: 'approved' })
  addLine('output', t('tui.contentApproved', { threadId }))
}

async function handleReject(threadId: string, feedback: string) {
  if (!threadId) { addLine('error', t('tui.noActiveWorkflow')); return }
  if (!feedback) { addLine('error', t('tui.rejectUsage')); return }
  await submitReview(threadId, { decision: 'needs_revision', comments: feedback })
  addLine('output', t('tui.contentRejected', { feedback }))
}

function showHelp() {
  const agentHelp = mode.value === 'agent' ? `
Agent mode commands:
  <message>     Send message to AI agent
  /status       Get agent status
  /new          Start new session
  /abort        Abort current turn
  /mode         Switch to command mode` : ''
  const commandHelp = `
Command mode commands:
  /start [topic]  Start workflow
  /status [id]    Check workflow status
  /pause [id]     Pause workflow
  /resume [id]    Resume workflow
  /cancel [id]    Cancel workflow
  /approve [id]   Approve content
  /reject <msg>   Reject with feedback
  /mode           Switch to agent mode`
  const common = `
Common:
  /help           Show this help
  /clear          Clear terminal`
  addLine('output', `[${mode.value} mode]${commandHelp}${agentHelp}${common}`)
}

// ── Input handling ──────────────────────────────────────────────────────

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    const text = inputText.value
    inputText.value = ''
    processCommand(text)
  }
}

// ── Lifecycle ───────────────────────────────────────────────────────────

onMounted(() => {
  addLine('system', t('tui.welcome'))
  addLine('system', t('tui.welcomeHint'))
  // Try connecting to agent WebSocket
  connectAgentWs()
  // Fallback: if workflow store has active thread
  if (workflowStore.activeThreadId) {
    activeThreadId.value = workflowStore.activeThreadId
    addLine('system', t('tui.resumingWorkflow', { threadId: workflowStore.activeThreadId }))
  }
})

onUnmounted(() => {
  disconnectAgentWs()
  unsubscribeSSE()
})

// ── Styling helpers ─────────────────────────────────────────────────────

const lineClass = (type: TerminalLine['type']) => ({
  'text-emerald-400': type === 'output',
  'text-rose-400': type === 'error',
  'text-amber-400': type === 'system',
  'text-cyan-400': type === 'progress',
  'text-violet-400': type === 'review',
  'text-slate-300': type === 'input',
  'text-blue-400': type === 'tool_call',
  'text-teal-400': type === 'tool_result',
})

const promptSymbol = computed(() => {
  if (isProcessing.value) return '...'
  if (mode.value === 'agent') return '🤖>'
  return '>'
})

const modeLabel = computed(() => mode.value === 'agent' ? 'AGENT' : 'CMD')
const modeIndicatorColor = computed(() =>
  mode.value === 'agent' && wsConnected.value ? 'bg-emerald-400' : 'bg-amber-400',
)
</script>

<template>
  <div class="h-[calc(100vh-4rem)] flex flex-col bg-slate-950 rounded-xl overflow-hidden border border-slate-800">
    <!-- Header bar -->
    <div class="flex items-center gap-2 px-4 py-2 bg-slate-900 border-b border-slate-800">
      <div class="w-2.5 h-2.5 rounded-full" :class="wsConnected ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'" />
      <span class="text-xs font-mono text-slate-400">xhs-agent</span>
      <span class="text-[10px] font-mono px-1.5 py-0.5 rounded" :class="[modeIndicatorColor, 'text-slate-900']">{{ modeLabel }}</span>
      <span v-if="activeThreadId" class="text-[10px] font-mono text-slate-500 ml-2">{{ activeThreadId }}</span>
      <div class="ml-auto flex gap-1.5">
        <template v-if="mode === 'agent'">
          <button class="text-[10px] font-mono px-1.5 py-0.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors" @click="sendAgentMessage({ type: 'get_status' })">/status</button>
          <button class="text-[10px] font-mono px-1.5 py-0.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors" @click="sendAgentMessage({ type: 'abort' })">/abort</button>
          <button class="text-[10px] font-mono px-1.5 py-0.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors" @click="processCommand('/mode')">/mode</button>
        </template>
        <template v-else>
          <button
            v-for="cmd in ['/status', '/pause', '/cancel']"
            :key="cmd"
            class="text-[10px] font-mono px-1.5 py-0.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
            @click="processCommand(cmd + ' ' + (activeThreadId || ''))"
            :disabled="!activeThreadId"
          >
            {{ cmd }}
          </button>
          <button class="text-[10px] font-mono px-1.5 py-0.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors" @click="processCommand('/mode')">/mode</button>
        </template>
      </div>
    </div>

    <!-- Output area -->
    <div ref="outputRef" class="flex-1 overflow-y-auto p-4 font-mono text-xs leading-relaxed space-y-1">
      <div
        v-for="line in lines"
        :key="line.id"
        class="whitespace-pre-wrap break-words"
        :class="lineClass(line.type)"
      >
        <span class="text-slate-600 mr-2">{{ line.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }}</span>
        {{ line.text }}
      </div>
    </div>

    <!-- Input area -->
    <div class="flex items-center gap-2 px-4 py-3 bg-slate-900 border-t border-slate-800">
      <span class="text-emerald-400 font-mono text-sm">{{ promptSymbol }}</span>
      <input
        v-model="inputText"
        type="text"
        class="flex-1 bg-transparent text-slate-200 font-mono text-sm outline-none placeholder:text-slate-600"
        :placeholder="isProcessing ? t('tui.processing') : (mode === 'agent' ? 'Ask the AI agent...' : t('tui.inputPlaceholder'))"
        :disabled="isProcessing"
        @keydown="handleKeydown"
      />
    </div>
  </div>
</template>
