<script setup lang="ts">
/**
 * AgentTUI — terminal-style interactive page for XhsGrowthAgent workflows.
 * Provides a TUI-like experience: command input + output display,
 * real-time progress via SSE, and review interactions.
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
  type: 'input' | 'output' | 'error' | 'system' | 'progress' | 'review'
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

// ── SSE subscription ────────────────────────────────────────────────────
/** SSE event types sent by the backend (EventType enum values). */
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
  // Same-origin: axios client uses baseURL '/api', but EventSource needs full path
  eventSource = new EventSource(`/api/workflow/stream/${threadId}`)

  // Backend sends named SSE events (event: phase_changed, etc.)
  // Must use addEventListener — onmessage only catches unnamed events
  for (const eventType of SSE_EVENTS) {
    eventSource.addEventListener(eventType, (msg: MessageEvent) => {
      try {
        const data = JSON.parse(msg.data)
        handleSSEData(data)
      } catch { /* ignore malformed */ }
    })
  }

  // Fallback for unnamed events
  eventSource.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data)
      handleSSEData(data)
    } catch { /* ignore malformed */ }
  }

  // Don't close on error — EventSource auto-reconnects
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
  isProcessing.value = true

  try {
    if (trimmed.startsWith('/')) {
      await processSlashCommand(trimmed)
    } else {
      // Natural language → treat as "start workflow with this topic"
      await handleStart(trimmed)
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

// ── Command handlers ────────────────────────────────────────────────────

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

  // Subscribe to SSE for real-time progress
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
  addLine('output', t('tui.helpText'))
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
  // Check for active workflow from store
  if (workflowStore.activeThreadId) {
    activeThreadId.value = workflowStore.activeThreadId
    addLine('system', t('tui.resumingWorkflow', { threadId: workflowStore.activeThreadId }))
  }
})

onUnmounted(() => {
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
})

const promptSymbol = computed(() => isProcessing.value ? '...' : '>')
</script>

<template>
  <div class="h-[calc(100vh-4rem)] flex flex-col bg-slate-950 rounded-xl overflow-hidden border border-slate-800">
    <!-- Header bar -->
    <div class="flex items-center gap-2 px-4 py-2 bg-slate-900 border-b border-slate-800">
      <div class="w-2.5 h-2.5 rounded-full" :class="activeThreadId ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'" />
      <span class="text-xs font-mono text-slate-400">xhs-agent</span>
      <span v-if="activeThreadId" class="text-[10px] font-mono text-slate-500 ml-2">{{ activeThreadId }}</span>
      <div class="ml-auto flex gap-1.5">
        <button
          v-for="cmd in ['/status', '/pause', '/cancel']"
          :key="cmd"
          class="text-[10px] font-mono px-1.5 py-0.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"
          @click="processCommand(cmd + ' ' + (activeThreadId || ''))"
          :disabled="!activeThreadId"
        >
          {{ cmd }}
        </button>
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
        :placeholder="isProcessing ? t('tui.processing') : t('tui.inputPlaceholder')"
        :disabled="isProcessing"
        @keydown="handleKeydown"
      />
    </div>
  </div>
</template>
