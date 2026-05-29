<script setup lang="ts">
import { computed, ref } from 'vue'
import WorkflowNode from '@/components/WorkflowNode.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore } from '@/stores'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const workflowStore = useWorkflowStore()

// Keyboard navigation state
const focusedIndex = ref(-1)
const showTimelineDetails = ref(false)

// Memoized phase order for performance
const phaseOrder = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'analyzing', 'engaging', 'completed'] as const

// Progress calculation based on current phase
const workflowProgress = computed(() => {
  const currentPhase = workflowStore.currentPhase
  const currentIndex = phaseOrder.indexOf(currentPhase as any)
  if (currentIndex === -1) return 0
  return Math.round((currentIndex / (phaseOrder.length - 1)) * 100)
})

// Current agent from workflow state
const currentAgent = computed(() => workflowStore.workflowState?.current_agent || '')

// Has error
const hasError = computed(() => workflowStore.currentPhase === 'error' || !!workflowStore.workflowState?.error)
const errorMessage = computed(() => workflowStore.workflowState?.error || '')

// Agent timeline data
const agentTimeline = computed(() => workflowStore.agentTimeline)
const hasTimelineData = computed(() => agentTimeline.value.length > 0)

// Workflow nodes configuration
const workflowNodes = computed(() => [
  { icon: 'Search', label: t('dashboard.timeline.scouting'), phase: 'scouting', description: t('dashboard.timeline.scoutingDesc'), agent: 'trend_scout' },
  { icon: 'ClipboardList', label: t('dashboard.timeline.planning'), phase: 'planning', description: t('dashboard.timeline.planningDesc'), agent: 'content_strategist' },
  { icon: 'Pencil', label: t('dashboard.timeline.creating'), phase: 'creating', description: t('dashboard.timeline.creatingDesc'), agent: 'copywriter' },
  { icon: 'Palette', label: t('dashboard.timeline.visual'), phase: 'creating', description: t('dashboard.timeline.visualDesc'), agent: 'visual_designer' },
  { icon: 'Clock', label: t('dashboard.timeline.reviewing'), phase: 'reviewing', description: t('dashboard.timeline.reviewingDesc'), agent: 'review_gate' },
  { icon: 'Upload', label: t('dashboard.timeline.publishing'), phase: 'publishing', description: t('dashboard.timeline.publishingDesc'), agent: 'publisher' },
  { icon: 'BarChart3', label: t('dashboard.timeline.analyzing'), phase: 'analyzing', description: t('dashboard.timeline.analyzingDesc'), agent: 'analyst' },
])

// Use memoized phaseOrder for consistent lookup
const getNodeStatus = (phase: string) => {
  // If workflow has error and this is the current phase, show error
  if (hasError.value && phase === workflowStore.currentPhase) return 'error'

  const currentPhase = workflowStore.currentPhase
  const currentIndex = phaseOrder.indexOf(currentPhase as any)
  const nodeIndex = phaseOrder.indexOf(phase as any)

  if (nodeIndex < currentIndex) return 'completed'
  if (nodeIndex === currentIndex) return 'running'
  return 'pending'
}

function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

function formatTime(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return '—'
  }
}

// Keyboard navigation handlers
const handleKeyDown = (e: KeyboardEvent) => {
  const nodeCount = workflowNodes.value.length
  switch (e.key) {
    case 'ArrowRight':
      e.preventDefault()
      focusedIndex.value = Math.min(nodeCount - 1, focusedIndex.value + 1)
      break
    case 'ArrowLeft':
      e.preventDefault()
      focusedIndex.value = Math.max(0, focusedIndex.value - 1)
      break
    case 'Home':
      e.preventDefault()
      focusedIndex.value = 0
      break
    case 'End':
      e.preventDefault()
      focusedIndex.value = nodeCount - 1
      break
  }
}

const isFocused = (index: number) => focusedIndex.value === index
</script>

<template>
  <div
    class="bg-white/98 backdrop-blur-sm rounded-2xl p-6 border border-slate-200/50 shadow-sm"
    role="region"
    :aria-label="t('dashboard.timeline.title')"
    @keydown="handleKeyDown"
  >
    <div class="flex items-center gap-2 mb-5">
      <AppIcon name="GitBranch" size="md" variant="cyan" aria-hidden="true" />
      <span class="text-xs text-slate-500 uppercase tracking-wide font-medium">{{ t('dashboard.timeline.title') }}</span>
      <span v-if="currentAgent" class="text-xs px-2 py-0.5 rounded-full bg-cyan-50 text-cyan-600 border border-cyan-100">
        {{ currentAgent }}
      </span>
      <span class="text-xs text-slate-400 ml-auto">{{ t('dashboard.timeline.keyboardHint') }}</span>
    </div>

    <!-- Error banner -->
    <div v-if="hasError" class="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-100 flex items-center gap-2">
      <AppIcon name="AlertTriangle" size="sm" variant="pink" />
      <span class="text-sm text-rose-600">{{ errorMessage || t('dashboard.timeline.workflowError') }}</span>
    </div>

    <!-- Progress line with ARIA -->
    <div class="relative py-4" role="progressbar" :aria-valuenow="workflowProgress" aria-valuemin="0" aria-valuemax="100" :aria-label="`${t('dashboard.timeline.progress')} ${workflowProgress}%`">
      <div class="absolute top-1/2 left-0 right-0 h-1 bg-slate-100 rounded-full" aria-hidden="true" />
      <div
        class="absolute top-1/2 left-0 h-1 rounded-full transition-all duration-500"
        :class="hasError ? 'bg-rose-400' : 'bg-gradient-to-r from-rose-400 to-teal-400'"
        :style="{ width: `${workflowProgress}%` }"
        aria-hidden="true"
      />
    </div>

    <!-- Nodes with keyboard navigation -->
    <div class="flex justify-between items-center relative px-4" role="list" :aria-label="t('dashboard.timeline.stages')">
      <WorkflowNode
        v-for="(node, index) in workflowNodes"
        :key="`${node.phase}-${index}`"
        :icon="node.icon"
        :label="node.label"
        :status="getNodeStatus(node.phase)"
        :focused="isFocused(index)"
        role="listitem"
        :tabindex="isFocused(index) ? 0 : -1"
        :aria-label="`${node.label} - ${getNodeStatus(node.phase) === 'completed' ? t('dashboard.timeline.completed') : getNodeStatus(node.phase) === 'running' ? t('dashboard.timeline.running') : getNodeStatus(node.phase) === 'error' ? t('dashboard.timeline.error') : t('dashboard.timeline.pending')}`"
        :aria-describedby="`node-desc-${index}`"
      />

      <!-- Hidden descriptions for screen readers -->
      <div v-for="(node, index) in workflowNodes" :key="`desc-${index}`" :id="`node-desc-${index}`" class="sr-only">
        {{ node.description }}
      </div>
    </div>

    <!-- Agent Timeline Details -->
    <div v-if="hasTimelineData" class="mt-5 border-t border-slate-100 pt-4">
      <button
        class="flex items-center justify-between w-full mb-3"
        @click="showTimelineDetails = !showTimelineDetails"
      >
        <div class="flex items-center gap-2">
          <AppIcon name="Clock" size="sm" variant="cyan" />
          <span class="text-xs text-slate-600 uppercase tracking-wide font-medium">
            {{ t('dashboard.timeline.agentDetails') }}
          </span>
          <span class="text-xs px-1.5 py-0.5 rounded bg-cyan-50 text-cyan-600 font-medium">
            {{ agentTimeline.length }}
          </span>
        </div>
        <AppIcon :name="showTimelineDetails ? 'ChevronUp' : 'ChevronDown'" size="sm" variant="cyan" />
      </button>

      <div v-if="showTimelineDetails" class="space-y-2">
        <div
          v-for="entry in agentTimeline"
          :key="`${entry.agent}-${entry.started_at}`"
          class="flex items-center gap-3 p-2.5 rounded-lg border transition-colors"
          :class="entry.status === 'error' ? 'bg-rose-50/50 border-rose-100' : 'bg-slate-50/50 border-slate-100'"
        >
          <!-- Status indicator -->
          <span
            class="w-2 h-2 rounded-full flex-shrink-0"
            :class="entry.status === 'error' ? 'bg-rose-500' : 'bg-emerald-500'"
          />

          <!-- Agent name -->
          <span class="text-sm font-medium text-slate-700 w-32 truncate">{{ entry.agent }}</span>

          <!-- Timing -->
          <div class="flex-1 flex items-center gap-4 text-xs text-slate-500">
            <span>{{ formatTime(entry.started_at) }}</span>
            <span class="text-slate-300">→</span>
            <span>{{ formatTime(entry.completed_at) }}</span>
          </div>

          <!-- Duration -->
          <span
            class="text-xs font-medium px-2 py-0.5 rounded"
            :class="entry.duration_seconds > 30 ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-600'"
          >
            {{ formatDuration(entry.duration_seconds) }}
          </span>

          <!-- Error indicator -->
          <span v-if="entry.error" class="text-xs text-rose-500 truncate max-w-[150px]" :title="entry.error">
            {{ entry.error }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
