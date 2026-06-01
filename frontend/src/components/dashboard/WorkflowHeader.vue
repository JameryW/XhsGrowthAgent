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
const phaseOrder = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'completed'] as const

// Default time estimates per phase (in seconds) - based on typical execution
const phaseTimeEstimates: Record<string, number> = {
  idle: 0,
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

// Use unified progress from store (backend progress_percent with local fallback)
const workflowProgress = computed(() => workflowStore.progressPercent)
const isWaitingForUser = computed(() =>
  workflowStore.isAwaitingDraft ||
  workflowStore.isAwaitingChoice ||
  workflowStore.isAwaitingReview
)
const statusLabel = computed(() =>
  isWaitingForUser.value ? t('dashboard.header.awaitingAction') :
    workflowStore.isRunning ? t('dashboard.header.running') :
      t('dashboard.header.idle')
)
const currentStageLabel = computed(() => {
  if (workflowStore.isAwaitingDraft) return t('dashboard.phase.awaitingDraft')
  if (workflowStore.isAwaitingChoice) return t('dashboard.phase.awaitingChoice')
  if (workflowStore.isAwaitingReview) return t('dashboard.phase.awaitingReview')

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
    class="rounded-2xl p-4 md:p-6 relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm"
    role="region"
    :aria-label="t('dashboard.header.status')"
  >
    <div class="flex flex-col sm:flex-row items-start sm:items-center gap-4 sm:gap-5">
      <!-- Progress & Logo -->
      <div class="flex items-center gap-4">
        <CircularProgress :value="workflowProgress" variant="cyan" size="lg" show-value :aria-label="t('dashboard.header.progress')" />
        <div class="w-16 h-16 rounded-xl bg-gradient-to-br from-rose-400 via-rose-500 to-amber-400 flex items-center justify-center shadow-sm" aria-hidden="true">
          <AppIcon name="Rocket" size="xl" variant="white" />
        </div>
      </div>

      <!-- Info -->
      <div class="flex-1 space-y-2">
        <div class="flex items-center gap-3">
          <span class="px-2 py-1 rounded bg-teal-50 text-teal-600 text-xs uppercase tracking-wide font-medium">{{ t('dashboard.header.workflow') }}</span>
          <span class="text-xs text-slate-400">{{ workflowStore.currentThreadId || '—' }}</span>
        </div>
        <div class="text-xl font-semibold text-slate-800">
          {{ currentStageLabel }}
        </div>
        <!-- Estimated time remaining -->
        <div v-if="timeRemainingDisplay" class="flex items-center gap-2 text-sm text-slate-500">
          <AppIcon name="Clock" size="sm" variant="cyan" aria-hidden="true" />
          <span>{{ timeRemainingDisplay }}</span>
        </div>
        <MiniProgress :value="workflowProgress" variant="cyan" class="max-w-xs" aria-hidden="true" />
      </div>

      <!-- Status Badge with aria-live -->
      <div
        :class="[
          'px-4 py-2.5 rounded-lg border font-medium flex items-center gap-2 transition-all duration-200',
          workflowStore.isRunning
            ? 'bg-gradient-to-r from-teal-500 to-teal-400 border-teal-200 text-white shadow-sm'
            : isWaitingForUser
              ? 'bg-amber-50 border-amber-200 text-amber-700'
            : 'bg-slate-50 border-slate-200 text-slate-500'
        ]"
        role="status"
        aria-live="polite"
        :aria-label="statusLabel"
      >
        <AppIcon
          :name="workflowStore.isRunning ? 'Circle' : isWaitingForUser ? 'Clock' : 'Minus'"
          size="sm"
          :variant="workflowStore.isRunning ? 'white' : 'cyan'"
          :animate="workflowStore.isRunning"
          aria-hidden="true"
        />
        <span>{{ statusLabel }}</span>
      </div>
    </div>
  </div>
</template>
