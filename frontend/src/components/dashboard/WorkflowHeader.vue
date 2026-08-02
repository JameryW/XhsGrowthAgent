<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore } from '@/stores'

const { t } = useI18n()
const workflowStore = useWorkflowStore()
const now = ref(Date.now())
let clockTimer: ReturnType<typeof setInterval> | null = null

// Memoized phase order for performance
const phaseOrder = ['briefing', 'scouting', 'planning', 'creating', 'reviewing', 'publishing', 'analyzing', 'engaging', 'completed'] as const

// Default time estimates per phase (in seconds) - based on typical execution
const phaseTimeEstimates: Record<string, number> = {
  idle: 0,
  briefing: 45,
  scouting: 30,
  planning: 45,
  creating: 90,
  reviewing: 0, // User-controlled, no estimate
  publishing: 20,
  analyzing: 30,
  engaging: 15,
  completed: 0,
  error: 0,
}

// DB-03: unified displayProgress — replay shows inspected checkpoint,
// live uses the high-water mark so a phase regression never animates backward.
const workflowProgress = computed(() => workflowStore.displayProgress)
const isWaitingForUser = computed(() =>
  workflowStore.isAwaitingDraft ||
  workflowStore.isAwaitingChoice ||
  workflowStore.isAwaitingReview ||
  workflowStore.isAwaitingBrief ||
  workflowStore.isAwaitingBloggerSelection ||
  workflowStore.isAwaitingRippleDecision
)

const runningAgent = computed(() => {
  if (workflowStore.isReplayMode || !workflowStore.isRunning) return null
  return workflowStore.agentTimeline.find(entry => !entry.completed_at) || null
})

function formatElapsed(seconds: number): string {
  if (seconds < 60) return t('dashboard.header.elapsedSeconds', { seconds: Math.max(0, Math.floor(seconds)) })
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = Math.floor(seconds % 60)
  return t('dashboard.header.elapsedMinutes', { minutes, seconds: remainingSeconds })
}

const runningAgentElapsed = computed(() => {
  const entry = runningAgent.value
  if (!entry) return null
  const startedAt = Date.parse(entry.started_at)
  if (!Number.isFinite(startedAt)) return null
  return Math.max(0, (now.value - startedAt) / 1000)
})

const runningAgentElapsedDisplay = computed(() => {
  const seconds = runningAgentElapsed.value
  if (seconds === null || !runningAgent.value) return ''
  return t('dashboard.header.agentElapsed', {
    agent: runningAgent.value.agent,
    duration: formatElapsed(seconds),
  })
})

const hasEtaSample = computed(() =>
  !workflowStore.isReplayMode && workflowStore.agentTimeline.some(entry =>
    !!entry.completed_at && typeof entry.duration_seconds === 'number' && entry.duration_seconds > 0,
  ),
)

// Estimated time remaining calculation
const estimatedTimeRemaining = computed(() => {
  const phase = workflowStore.currentPhase
  if (!hasEtaSample.value || isWaitingForUser.value || phase === 'completed' || phase === 'error' || phase === 'idle' || phase === 'reviewing') {
    return null
  }

  // Sum remaining phases' estimates
  const currentIndex = phaseOrder.indexOf(phase as any)
  if (currentIndex === -1) return null

  let remainingSeconds = 0
  for (let i = currentIndex; i < phaseOrder.length; i++) {
    remainingSeconds += phaseTimeEstimates[phaseOrder[i]] || 0
  }

  // Adjust based on current progress (if we're 50% through a phase, halve its estimate)
  const progressPercent = workflowProgress.value
  const phaseProgress = progressPercent % 20 // Approximate progress within phase
  if (phaseProgress > 0 && remainingSeconds > 0) {
    const currentPhaseEstimate = phaseTimeEstimates[phase] || 0
    const phaseProgressFraction = phaseProgress / 20
    remainingSeconds -= Math.round(currentPhaseEstimate * phaseProgressFraction)
  }

  return remainingSeconds > 0 ? remainingSeconds : null
})

// Format time remaining as human-readable string
const timeRemainingDisplay = computed(() => {
  const seconds = estimatedTimeRemaining.value
  if (seconds === null) return ''

  if (seconds < 60) {
    return t('dashboard.header.etaSeconds', { seconds })
  }
  const minutes = Math.round(seconds / 60)
  return t('dashboard.header.etaMinutes', { minutes })
})

onMounted(() => {
  clockTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
  clockTimer = null
})
</script>

<template>
  <!-- Identity + live telemetry strip. Status, phase and progress are owned
       by the state hero directly above — this header used to repeat them
       (status badge, stage label, circular + mini progress bars). -->
  <div
    class="rounded-xl p-3 md:px-4 md:py-3 relative overflow-hidden bg-white/90 backdrop-blur-sm border border-slate-200/50 shadow-sm dark-explicit dark:bg-slate-900/80 dark:border-slate-700/50"
    role="region"
    :aria-label="t('dashboard.header.status')"
  >
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <span class="px-2 py-1 rounded bg-teal-50 text-teal-600 text-xs uppercase tracking-wide font-medium dark-explicit dark:bg-teal-950/40 dark:text-teal-300">{{ t('dashboard.header.workflow') }}</span>
      <span v-if="workflowStore.workflowState?.label" class="text-sm font-medium text-slate-700 truncate dark-explicit dark:text-slate-200">{{ workflowStore.workflowState.label }}</span>
      <span v-else class="text-xs text-slate-400 truncate">{{ workflowStore.currentThreadId || '—' }}</span>
      <span v-if="workflowStore.workflowState?.label && workflowStore.currentThreadId" class="text-[10px] text-slate-400 font-mono truncate">{{ workflowStore.currentThreadId.slice(-8) }}</span>
      <!-- Agent elapsed ticks every second — deliberately NOT an aria-live
           region, otherwise screen readers re-announce it on every tick. -->
      <div v-if="runningAgentElapsedDisplay" class="flex items-center gap-1.5 text-xs text-slate-500">
        <AppIcon name="Clock" size="sm" variant="cyan" aria-hidden="true" />
        <span>{{ runningAgentElapsedDisplay }}</span>
      </div>
      <div v-if="timeRemainingDisplay" class="flex items-center gap-1.5 text-xs text-slate-500">
        <AppIcon name="Clock" size="sm" variant="cyan" aria-hidden="true" />
        <span>{{ timeRemainingDisplay }}</span>
      </div>
    </div>
  </div>
</template>
