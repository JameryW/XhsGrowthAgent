<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import CircularProgress from '@/components/CircularProgress.vue'
import AppIcon from '@/components/AppIcon.vue'
import MiniProgress from '@/components/MiniProgress.vue'
import { useWorkflowStore } from '@/stores'

const { t } = useI18n()
const workflowStore = useWorkflowStore()

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

// Use effectiveState progress (replay-aware) instead of global progressPercent
const workflowProgress = computed(() => {
  const es = workflowStore.effectiveState
  return es?.progress_percent ?? workflowStore.progressPercent
})
const isWaitingForUser = computed(() =>
  workflowStore.isAwaitingDraft ||
  workflowStore.isAwaitingChoice ||
  workflowStore.isAwaitingReview ||
  workflowStore.isAwaitingBrief ||
  workflowStore.isAwaitingBloggerSelection ||
  workflowStore.isAwaitingRippleDecision
)
const isStale = computed(() => workflowStore.isStale)
const statusLabel = computed(() => {
  const status = workflowStore.currentStatus
  const phase = workflowStore.currentPhase
  if (isStale.value) return t('workflow.staleDetected')
  if (phase === 'completed') return t('dashboard.phase.completed')
  if (phase === 'error') return t('dashboard.phase.error')
  if (status === 'paused') return t('workflow.tabPaused')
  if (status === 'cancelled') return t('dashboard.phase.cancelled')
  if (status === 'awaiting_ripple_decision') return t('showcase.status.awaitingRipple')
  if (status === 'awaiting_blogger_selection') return t('dashboard.phase.awaitingBlogger')
  if (status === 'awaiting_review') return t('dashboard.phase.awaitingReview')
  if (status === 'awaiting_choice') return t('dashboard.phase.awaitingChoice')
  if (status === 'awaiting_draft') return t('dashboard.phase.awaitingDraft')
  if (status === 'awaiting_brief') return t('dashboard.phase.awaitingBrief')
  if (isWaitingForUser.value) return t('dashboard.header.awaitingAction')
  if (workflowStore.isRunning) return t('dashboard.header.running')
  return t('dashboard.header.idle')
})
const currentStageLabel = computed(() => {
  if (workflowStore.isAwaitingDraft) return t('dashboard.phase.awaitingDraft')
  if (workflowStore.isAwaitingChoice) return t('dashboard.phase.awaitingChoice')
  if (workflowStore.isAwaitingReview) return t('dashboard.phase.awaitingReview')
  if (workflowStore.isAwaitingBrief) return t('dashboard.phase.awaitingBrief')
  if (workflowStore.isAwaitingRippleDecision) return t('showcase.status.awaitingRipple')
  if (workflowStore.isAwaitingBloggerSelection) return t('dashboard.phase.awaitingBlogger')

  const key = `dashboard.phase.${workflowStore.currentPhase}`
  const translated = t(key)
  return translated !== key ? translated : workflowStore.currentPhase
})

// Estimated time remaining calculation
const estimatedTimeRemaining = computed(() => {
  const phase = workflowStore.currentPhase
  if (isWaitingForUser.value || phase === 'completed' || phase === 'error' || phase === 'idle' || phase === 'reviewing') {
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
    return `~${seconds}s`
  }
  const minutes = Math.round(seconds / 60)
  return `~${minutes}m`
})
</script>

<template>
  <div
    class="rounded-xl p-3 md:p-6 md:rounded-2xl relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm dark:bg-slate-900/80 dark:border-slate-700/50"
    role="region"
    :aria-label="t('dashboard.header.status')"
  >
    <div class="flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:gap-5">
      <!-- Progress & Logo -->
      <div class="flex items-center gap-3 md:gap-4">
        <CircularProgress :value="workflowProgress" variant="cyan" size="lg" show-value :aria-label="t('dashboard.header.progress')" />
        <div class="w-10 h-10 md:w-16 md:h-16 rounded-lg md:rounded-xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 flex items-center justify-center shadow-sm" aria-hidden="true">
          <AppIcon name="Rocket" size="lg" variant="white" class="md:hidden" />
          <AppIcon name="Rocket" size="xl" variant="white" class="hidden md:block" />
        </div>
      </div>

      <!-- Info -->
      <div class="flex-1 min-w-0 space-y-1 md:space-y-2">
        <div class="flex items-center gap-2 md:gap-3">
          <span class="px-2 py-1 rounded bg-teal-50 text-teal-600 text-xs uppercase tracking-wide font-medium">{{ t('dashboard.header.workflow') }}</span>
          <span v-if="workflowStore.workflowState?.label" class="text-sm font-medium text-slate-700 truncate">{{ workflowStore.workflowState.label }}</span>
          <span v-else class="text-xs text-slate-400 truncate">{{ workflowStore.currentThreadId || '—' }}</span>
          <span v-if="workflowStore.workflowState?.label && workflowStore.currentThreadId" class="text-[10px] text-slate-400 font-mono truncate">{{ workflowStore.currentThreadId.slice(-8) }}</span>
        </div>
        <div class="text-lg md:text-xl font-semibold text-slate-800">
          {{ currentStageLabel }}
        </div>
        <!-- Estimated time remaining -->
        <div v-if="timeRemainingDisplay" class="flex items-center gap-2 text-sm text-slate-500">
          <AppIcon name="Clock" size="sm" variant="cyan" aria-hidden="true" />
          <span>{{ timeRemainingDisplay }}</span>
        </div>
        <MiniProgress :value="workflowProgress" variant="cyan" class="max-w-full md:max-w-xs" aria-hidden="true" />
      </div>

      <!-- Status Badge with aria-live -->
      <div
        :class="[
          'px-3 py-2 md:px-4 md:py-2.5 rounded-lg border font-medium flex items-center gap-1.5 md:gap-2 transition-all duration-200 text-sm md:text-base',
          workflowStore.isRunning
            ? 'bg-gradient-to-r from-teal-500 to-teal-400 border-teal-200 text-white shadow-sm'
            : isStale
              ? 'bg-amber-50 border-amber-300 text-amber-700 dark:bg-amber-950/40 dark:border-amber-500/35 dark:text-amber-200'
              : workflowStore.currentPhase === 'completed'
                ? 'bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-950/40 dark:border-emerald-500/35 dark:text-emerald-200'
                : workflowStore.currentPhase === 'error'
                  ? 'bg-rose-50 border-rose-200 text-rose-700 dark:bg-rose-950/40 dark:border-rose-500/35 dark:text-rose-200'
                  : workflowStore.currentStatus === 'paused'
                    ? 'bg-slate-50 border-slate-300 text-slate-600 dark:bg-slate-800/70 dark:border-slate-600 dark:text-slate-300'
                    : workflowStore.currentStatus === 'cancelled'
                      ? 'bg-slate-50 border-slate-300 text-slate-500 dark:bg-slate-800/70 dark:border-slate-600 dark:text-slate-400'
                      : workflowStore.isAwaitingRippleDecision
                        ? 'bg-violet-50 border-violet-200 text-violet-700 dark:bg-violet-950/40 dark:border-violet-500/35 dark:text-violet-200'
                        : workflowStore.isAwaitingBloggerSelection
                          ? 'bg-indigo-50 border-indigo-200 text-indigo-700 dark:bg-indigo-950/40 dark:border-indigo-500/35 dark:text-indigo-200'
                          : isWaitingForUser
                            ? 'bg-amber-50 border-amber-200 text-amber-700 dark:bg-amber-950/40 dark:border-amber-500/35 dark:text-amber-200'
                            : 'bg-slate-50 border-slate-200 text-slate-500 dark:bg-slate-800/70 dark:border-slate-600 dark:text-slate-400'
        ]"
        role="status"
        aria-live="polite"
        :aria-label="statusLabel"
      >
        <AppIcon
          :name="workflowStore.isRunning ? 'Circle' : isStale ? 'AlertTriangle' : workflowStore.currentPhase === 'completed' ? 'CheckCircle' : workflowStore.currentPhase === 'error' ? 'AlertCircle' : workflowStore.isAwaitingRippleDecision ? 'Zap' : workflowStore.isAwaitingBloggerSelection ? 'Users' : isWaitingForUser ? 'Clock' : 'Minus'"
          size="sm"
          :variant="workflowStore.isRunning ? 'white' : workflowStore.currentPhase === 'completed' ? 'cyan' : workflowStore.currentPhase === 'error' ? 'pink' : isStale ? 'peach' : workflowStore.isAwaitingRippleDecision ? 'purple' : workflowStore.isAwaitingBloggerSelection ? 'purple' : 'cyan'"
          :animate="workflowStore.isRunning"
          aria-hidden="true"
        />
        <span>{{ statusLabel }}</span>
      </div>
    </div>
  </div>
</template>
