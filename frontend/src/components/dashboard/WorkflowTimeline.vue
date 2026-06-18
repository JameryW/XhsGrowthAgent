<script setup lang="ts">
import { computed, ref } from 'vue'
import WorkflowNode from '@/components/WorkflowNode.vue'
import AppIcon from '@/components/AppIcon.vue'
import { useWorkflowStore } from '@/stores'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const workflowStore = useWorkflowStore()

// Replay mode
const isReplayMode = computed(() => workflowStore.isReplayMode)
const activeCheckpointId = computed(() => workflowStore.activeCheckpointId)

function findCheckpointForAgent(agent: string): string | null {
  const checkpoints = workflowStore.replayCheckpoints
  const cp = checkpoints.find(c => c.current_agent === agent)
  if (cp) return cp.checkpoint_id
  return null
}

function handleNodeClick(agent: string) {
  if (!isReplayMode.value) return
  const cpId = findCheckpointForAgent(agent)
  if (cpId) {
    workflowStore.selectCheckpoint(cpId)
  }
}

function isNodeSelected(agent: string): boolean {
  if (!activeCheckpointId.value) return false
  const cpId = findCheckpointForAgent(agent)
  return cpId === activeCheckpointId.value
}

// Keyboard navigation state
const focusedIndex = ref(-1)
const showTimelineDetails = ref(false)

// ── Phase + sub-step structure ──

interface SubStep {
  icon: string
  label: string
  agent: string
  description: string
}

interface PhaseNode {
  icon: string
  label: string
  phase: string
  description: string
  agent: string
  subSteps: SubStep[]
}

const workflowMode = computed<'trend' | 'brief'>(() => workflowStore.workflowState?.workflow_mode || 'trend')

// Replay-aware state: use effectiveState when in replay mode
const es = computed(() => (isReplayMode.value ? workflowStore.effectiveState : workflowStore.workflowState) as any)

const workflowPhases = computed<PhaseNode[]>(() => {
  const isBrief = workflowMode.value === 'brief'
  const trendCreatingSubSteps: SubStep[] = [
    { icon: 'Pencil', label: t('dashboard.timeline.short.copywriting'), agent: 'copywriter', description: t('dashboard.timeline.creatingDesc') },
    { icon: 'FileText', label: t('dashboard.timeline.short.draft'), agent: 'draft_gate', description: t('dashboard.timeline.draftDesc') },
    { icon: 'Flame', label: t('dashboard.timeline.short.viralMatch'), agent: 'viral_matcher', description: t('dashboard.timeline.viralMatchDesc') },
    { icon: 'Users', label: t('dashboard.timeline.short.bloggerScout'), agent: 'blogger_scout', description: t('dashboard.timeline.bloggerScoutDesc') },
    { icon: 'UserCheck', label: t('dashboard.timeline.short.bloggerGate'), agent: 'blogger_gate', description: t('dashboard.timeline.bloggerGateDesc') },
    { icon: 'Scan', label: t('dashboard.timeline.short.shootingPlan'), agent: 'shooting_planner', description: t('dashboard.timeline.shootingPlanDesc') },
    { icon: 'BarChart3', label: t('dashboard.timeline.short.contentAnalysis'), agent: 'content_analyzer', description: t('dashboard.timeline.contentAnalysisDesc') },
    { icon: 'Layers', label: t('dashboard.timeline.short.versionGen'), agent: 'version_generator', description: t('dashboard.timeline.versionGen') },
    { icon: 'CheckSquare', label: t('dashboard.timeline.short.choiceGate'), agent: 'choice_gate', description: t('dashboard.timeline.choiceGate') },
    { icon: 'Palette', label: t('dashboard.timeline.short.visual'), agent: 'visual_designer', description: t('dashboard.timeline.visualDesc') },
  ]
  const trendPlanningSubSteps: SubStep[] = [
    { icon: 'ClipboardList', label: t('dashboard.timeline.short.contentStrategy'), agent: 'content_strategist', description: t('dashboard.timeline.planningDesc') },
    { icon: 'Zap', label: t('dashboard.timeline.short.rippleGate'), agent: 'ripple_gate', description: t('dashboard.ripple.decisionPrompt') },
  ]
  const briefCreatingSubSteps: SubStep[] = [
    { icon: 'Flame', label: t('dashboard.timeline.short.viralMatch'), agent: 'viral_matcher', description: t('dashboard.timeline.viralMatchDesc') },
    { icon: 'Users', label: t('dashboard.timeline.short.bloggerScout'), agent: 'blogger_scout', description: t('dashboard.timeline.bloggerScoutDesc') },
    { icon: 'UserCheck', label: t('dashboard.timeline.short.bloggerGate'), agent: 'blogger_gate', description: t('dashboard.timeline.bloggerGateDesc') },
    { icon: 'Pencil', label: t('dashboard.timeline.short.copywriting'), agent: 'copywriter', description: t('dashboard.timeline.creatingDesc') },
    { icon: 'FileText', label: t('dashboard.timeline.short.draft'), agent: 'draft_gate', description: t('dashboard.timeline.draftDesc') },
    { icon: 'Scan', label: t('dashboard.timeline.short.shootingPlan'), agent: 'shooting_planner', description: t('dashboard.timeline.shootingPlanDesc') },
    { icon: 'BarChart3', label: t('dashboard.timeline.short.contentAnalysis'), agent: 'content_analyzer', description: t('dashboard.timeline.contentAnalysisDesc') },
    { icon: 'Layers', label: t('dashboard.timeline.short.versionGen'), agent: 'version_generator', description: t('dashboard.timeline.versionGen') },
    { icon: 'CheckSquare', label: t('dashboard.timeline.short.choiceGate'), agent: 'choice_gate', description: t('dashboard.timeline.choiceGate') },
    { icon: 'Palette', label: t('dashboard.timeline.short.visual'), agent: 'visual_designer', description: t('dashboard.timeline.visualDesc') },
  ]
  const phases: PhaseNode[] = []
  if (!isBrief) {
    phases.push({
      icon: 'Search', label: t('dashboard.timeline.scouting'), phase: 'scouting',
      description: t('dashboard.timeline.scoutingDesc'), agent: 'trend_scout',
      subSteps: [],
    })
    phases.push({
      icon: 'ClipboardList', label: t('dashboard.timeline.planning'), phase: 'planning',
      description: t('dashboard.timeline.planningDesc'), agent: 'content_strategist',
      subSteps: trendPlanningSubSteps,
    })
  } else {
    phases.push({
      icon: 'FileText', label: t('dashboard.timeline.briefing'), phase: 'briefing',
      description: t('dashboard.timeline.briefingDesc'), agent: 'brief_analyzer',
      subSteps: [
        { icon: 'FileText', label: t('dashboard.timeline.short.briefAnalyze'), agent: 'brief_analyzer', description: t('dashboard.timeline.briefAnalyzeDesc') },
        { icon: 'HelpCircle', label: t('dashboard.timeline.short.briefGate'), agent: 'brief_gate', description: t('dashboard.timeline.briefGateDesc') },
      ],
    })
  }
  phases.push({
    icon: 'Pencil', label: t('dashboard.timeline.creating'), phase: 'creating',
    description: t('dashboard.timeline.creatingDesc'), agent: isBrief ? 'viral_matcher' : 'copywriter',
    subSteps: isBrief ? briefCreatingSubSteps : trendCreatingSubSteps,
  })
  phases.push({
    icon: 'Clock', label: t('dashboard.timeline.reviewing'), phase: 'reviewing',
    description: t('dashboard.timeline.reviewingDesc'), agent: 'review_gate',
    subSteps: [
      { icon: 'Clock', label: t('dashboard.timeline.short.reviewGate'), agent: 'review_gate', description: t('dashboard.timeline.reviewingDesc') },
      { icon: 'RotateCcw', label: t('dashboard.timeline.short.reviseContent'), agent: 'revise_content', description: t('dashboard.timeline.reviseContentDesc') },
    ],
  })
  phases.push({
    icon: 'Upload', label: t('dashboard.timeline.publishing'), phase: 'publishing',
    description: t('dashboard.timeline.publishingDesc'), agent: 'publisher',
    subSteps: [
      { icon: 'Upload', label: t('dashboard.timeline.short.publisher'), agent: 'publisher', description: t('dashboard.timeline.publishingDesc') },
      { icon: 'MessageCircle', label: t('dashboard.timeline.short.engagement'), agent: 'engagement', description: t('dashboard.timeline.engaging') },
    ],
  })
  phases.push({
    icon: 'BarChart3', label: t('dashboard.timeline.analyzing'), phase: 'analyzing',
    description: t('dashboard.timeline.analyzingDesc'), agent: 'analyst',
    subSteps: [],
  })
  return phases
})

// Progress tracking (replay-aware)
const workflowProgress = computed(() => {
  const es = workflowStore.effectiveState
  return es?.progress_percent ?? workflowStore.progressPercent
})

const currentAgent = computed(() => {
  const status = workflowStore.currentStatus
  const nextNode = workflowStore.nextNodes[0]
  if (status === 'awaiting_draft') return nextNode || 'draft_gate'
  if (status === 'awaiting_choice') return nextNode || 'choice_gate'
  if (status === 'awaiting_review') return nextNode || 'review_gate'
  if (status === 'awaiting_brief') return nextNode || 'brief_gate'
  if (status === 'awaiting_ripple_decision') return nextNode || 'ripple_gate'
  if (status === 'awaiting_blogger_selection') return nextNode || 'blogger_gate'
  return es.value?.current_agent || nextNode || ''
})

const hasError = computed(() => workflowStore.currentPhase === 'error' || !!es.value?.error)
const errorMessage = computed(() => es.value?.error || '')
const agentTimeline = computed(() => workflowStore.agentTimeline)
const hasTimelineData = computed(() => agentTimeline.value.length > 0)

type NodeStatus = 'completed' | 'running' | 'pending' | 'error'

const phaseOrder = computed<string[]>(() => {
  const isBrief = workflowMode.value === 'brief'
  const base = isBrief
    ? ['briefing', 'creating', 'reviewing', 'publishing', 'analyzing', 'engaging', 'completed']
    : ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'analyzing', 'engaging', 'completed']
  return base
})

const agentOrder = computed<string[]>(() => {
  const isBrief = workflowMode.value === 'brief'
  if (isBrief) {
    return [
      'brief_analyzer', 'brief_gate',
      'viral_matcher', 'blogger_scout', 'blogger_gate',
      'copywriter', 'draft_gate',
      'shooting_planner', 'content_analyzer', 'version_generator', 'choice_gate', 'visual_designer',
      'review_gate', 'revise_content', 'publisher', 'engagement', 'analyst',
    ]
  }
  return [
    'trend_scout', 'content_strategist', 'ripple_gate', 'copywriter', 'draft_gate',
    'viral_matcher', 'blogger_scout', 'blogger_gate',
    'shooting_planner', 'content_analyzer', 'version_generator', 'choice_gate', 'visual_designer',
    'review_gate', 'revise_content', 'publisher', 'engagement', 'analyst',
  ]
})

const hasData = (value: unknown) =>
  !!value && typeof value === 'object' && Object.keys(value as Record<string, unknown>).length > 0

const agentIndex = (agent: string) => agentOrder.value.indexOf(agent)

function isSubStepCompleted(agent: string): boolean {
  const status = workflowStore.currentStatus
  if (status === 'completed') return true
  if (agent === 'trend_scout') return hasData(workflowStore.trendData)
  if (agent === 'content_strategist') return hasData(workflowStore.contentPlan)
  if (agent === 'ripple_gate') {
    if (status === 'awaiting_ripple_decision') return false
    return (
      hasData(es.value?.ripple_prediction) ||
      hasData(es.value?.ripple_pmf) ||
      agentIndex(currentAgent.value) > agentIndex('ripple_gate')
    )
  }
  if (agent === 'copywriter') return hasData(workflowStore.copyContent)
  if (agent === 'draft_gate') return hasData(es.value?.draft_content)
  if (agent === 'brief_analyzer') return hasData(es.value?.brief_content)
  if (agent === 'brief_gate') return hasData(es.value?.brief_clarification) || hasData(es.value?.brief_content)
  if (agent === 'shooting_planner') return hasData(es.value?.shooting_plan)
  if (agent === 'content_analyzer') return hasData(es.value?.optimization_analysis)
  if (agent === 'version_generator') return (es.value?.content_versions?.length > 0)
  if (agent === 'choice_gate') {
    if (status === 'awaiting_choice') return false
    return hasData(es.value?.content_versions) && agentIndex(currentAgent.value) > agentIndex('choice_gate')
  }
  if (agent === 'visual_designer') {
    return (
      status === 'awaiting_review' ||
      currentAgent.value === 'review_gate' ||
      (currentAgent.value === 'visual_designer' && hasData(es.value?.visual_plan))
    )
  }
  if (agent === 'review_gate') {
    return (
      workflowStore.currentPhase !== 'reviewing' &&
      status !== 'awaiting_review' &&
      agentIndex(currentAgent.value) > agentIndex('review_gate')
    )
  }
  if (agent === 'publisher') return hasData(es.value?.publish_result)
  if (agent === 'analyst') return hasData(es.value?.analytics)
  if (agent === 'revise_content') return false
  if (agent === 'engagement') {
    return workflowStore.currentPhase === 'completed' || agentIndex(currentAgent.value) > agentIndex('engagement')
  }
  return false
}

function getStatus(agent: string): NodeStatus {
  if (hasError.value && agent === currentAgent.value) return 'error'
  const activeIdx = agentIndex(currentAgent.value)
  const nodeIdx = agentIndex(agent)
  if (activeIdx >= 0 && nodeIdx >= 0) {
    if (nodeIdx < activeIdx) return 'completed'
    if (nodeIdx > activeIdx) return 'pending'
    if (isSubStepCompleted(agent)) return 'completed'
    return 'running'
  }
  if (isSubStepCompleted(agent)) return 'completed'
  const currentPhaseIdx = phaseOrder.value.indexOf(workflowStore.currentPhase)
  const briefAgents = new Set(['brief_analyzer', 'brief_gate'])
  const planningAgents = new Set(['content_strategist', 'ripple_gate'])
  const reviewAgents = new Set(['review_gate', 'revise_content'])
  const publishAgents = new Set(['publisher', 'engagement'])
  let nodePhase: string
  if (agent === 'trend_scout') nodePhase = 'scouting'
  else if (workflowMode.value === 'brief' && briefAgents.has(agent)) nodePhase = 'briefing'
  else if (planningAgents.has(agent)) nodePhase = 'planning'
  else if (reviewAgents.has(agent)) nodePhase = 'reviewing'
  else if (publishAgents.has(agent)) nodePhase = 'publishing'
  else if (agent === 'analyst') nodePhase = 'analyzing'
  else nodePhase = 'creating'
  const nodePhaseIdx = phaseOrder.value.indexOf(nodePhase)
  if (nodePhaseIdx < currentPhaseIdx) return 'completed'
  if (nodePhaseIdx === currentPhaseIdx) return 'running'
  return 'pending'
}

function getPhaseStatus(phase: PhaseNode): NodeStatus {
  if (phase.subSteps.length > 0) {
    const statuses = phase.subSteps.map(s => getStatus(s.agent))
    if (statuses.some(s => s === 'error')) return 'error'
    if (statuses.some(s => s === 'running')) return 'running'
    if (statuses.every(s => s === 'completed')) return 'completed'
    return 'pending'
  }
  return getStatus(phase.agent)
}

function shouldExpandSubSteps(phase: PhaseNode): boolean {
  if (phase.subSteps.length === 0) return false
  const phaseStatus = getPhaseStatus(phase)
  if (phaseStatus === 'running') return true
  if (phaseStatus === 'completed') {
    // Only expand completed phase if it contains a currently running substep
    return phase.subSteps.some(s => getStatus(s.agent) === 'running')
  }
  return false
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

const handleKeyDown = (e: KeyboardEvent) => {
  const nodeCount = workflowPhases.value.length
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

// Substep section labels
const substepSectionLabels = computed<Record<string, string>>(() => ({
  briefing: t('dashboard.timeline.substepSections.briefing'),
  planning: t('dashboard.timeline.substepSections.planning'),
  creating: workflowMode.value === 'brief' ? t('dashboard.timeline.substepSections.creatingBrief') : t('dashboard.timeline.substepSections.creatingTrend'),
  reviewing: t('dashboard.timeline.substepSections.reviewing'),
  publishing: t('dashboard.timeline.substepSections.publishing'),
}))
</script>

<template>
  <div
    class="bg-white/98 backdrop-blur-sm rounded-xl p-3 md:p-6 md:rounded-2xl border border-slate-200/50 shadow-sm"
    role="region"
    :aria-label="t('dashboard.timeline.title')"
    @keydown="handleKeyDown"
  >
    <div class="flex items-center gap-2 mb-3 md:mb-5">
      <AppIcon name="GitBranch" size="md" variant="cyan" aria-hidden="true" />
      <span class="text-xs text-slate-500 uppercase tracking-wide font-medium">{{ t('dashboard.timeline.title') }}</span>
      <span v-if="currentAgent" class="text-xs px-2 py-0.5 rounded-full bg-cyan-50 text-cyan-600 border border-cyan-100 hidden sm:inline">
        {{ currentAgent }}
      </span>
      <span class="text-xs text-slate-400 ml-auto hidden sm:inline">{{ t('dashboard.timeline.keyboardHint') }}</span>
    </div>

    <!-- Error banner -->
    <div v-if="hasError" class="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-100 flex items-center gap-2">
      <AppIcon name="AlertTriangle" size="sm" variant="pink" />
      <span class="text-sm text-rose-600">{{ errorMessage || t('dashboard.timeline.workflowError') }}</span>
    </div>

    <!-- Progress line -->
    <div class="relative py-4" role="progressbar" :aria-valuenow="workflowProgress" aria-valuemin="0" aria-valuemax="100" :aria-label="`${t('dashboard.timeline.progress')} ${workflowProgress}%`">
      <div class="absolute top-1/2 left-0 right-0 h-1 bg-slate-100 rounded-full" aria-hidden="true" />
      <div
        class="absolute top-1/2 left-0 h-1 rounded-full transition-all duration-500"
        :class="hasError ? 'bg-rose-400' : 'bg-gradient-to-r from-rose-400 to-teal-400'"
        :style="{ width: `${workflowProgress}%` }"
        aria-hidden="true"
      />
    </div>

    <!-- Main phase nodes -->
    <div class="flex justify-between items-start relative px-1 md:px-4 overflow-x-auto -mx-3 md:mx-0 scrollbar-thin" role="list" :aria-label="t('dashboard.timeline.stages')">
      <div
        v-for="(phase, index) in workflowPhases"
        :key="phase.phase"
        class="min-w-[56px] md:min-w-0 flex-1 shrink-0 md:shrink"
        role="listitem"
      >
        <WorkflowNode
          :icon="phase.subSteps.length > 0 && shouldExpandSubSteps(phase) ? 'ChevronDown' : phase.icon"
          :label="phase.label"
          :status="getPhaseStatus(phase)"
          :focused="isFocused(index)"
          :clickable="isReplayMode"
          :selected="isNodeSelected(phase.agent)"
          :tabindex="isFocused(index) ? 0 : -1"
          :aria-label="`${phase.label} - ${getPhaseStatus(phase) === 'completed' ? t('dashboard.timeline.completed') : getPhaseStatus(phase) === 'running' ? t('dashboard.timeline.running') : getPhaseStatus(phase) === 'error' ? t('dashboard.timeline.error') : t('dashboard.timeline.pending')}`"
          @click="handleNodeClick(phase.agent)"
        />
      </div>
    </div>

    <!-- Expanded substeps (with transition) -->
    <div class="mt-2 space-y-2">
      <TransitionGroup name="substep-expand">
        <div
          v-for="phase in workflowPhases"
          :key="`sub-${phase.phase}`"
        >
          <div
            v-if="shouldExpandSubSteps(phase)"
            class="mt-2 mx-1 md:mx-6 p-2.5 md:p-3 rounded-xl bg-slate-50/80 border border-slate-100"
          >
            <div class="flex items-center gap-1.5 mb-2">
              <AppIcon name="Layers" size="sm" variant="cyan" />
              <span class="text-[11px] text-slate-500 font-medium uppercase tracking-wide">{{ substepSectionLabels[phase.phase] || phase.label }}</span>
            </div>
            <div class="flex flex-wrap gap-2 md:gap-3 justify-center">
              <template v-for="(step, si) in phase.subSteps" :key="step.agent">
                <!-- SVG connector arrow between steps (from PR #54) -->
                <div v-if="si > 0" class="hidden md:flex items-center text-slate-300 -mx-0.5">
                  <svg width="16" height="8" viewBox="0 0 16 8" class="opacity-40">
                    <line x1="0" y1="4" x2="12" y2="4" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2 2" />
                    <polyline points="10,1 13,4 10,7" fill="none" stroke="currentColor" stroke-width="1.5" />
                  </svg>
                </div>
                <div
                  class="flex flex-col items-center gap-0.5 md:gap-1 min-w-[40px] md:min-w-[48px]"
                  :data-agent="step.agent"
                  :data-status="getStatus(step.agent)"
                  :class="[
                    isReplayMode ? 'cursor-pointer' : '',
                    isReplayMode && isNodeSelected(step.agent) ? 'ring-2 ring-violet-400 ring-offset-1 ring-offset-slate-50 rounded-lg' : '',
                  ]"
                  :title="step.description"
                  @click="isReplayMode && handleNodeClick(step.agent)"
                >
                  <!-- Substep icon with gradient style (from PR #54) -->
                  <div
                    class="w-7 h-7 md:w-9 md:h-9 rounded-lg flex items-center justify-center transition-all duration-200"
                    :class="{
                      'bg-gradient-to-br from-rose-400 to-amber-400 shadow-sm': getStatus(step.agent) === 'completed',
                      'bg-gradient-to-br from-amber-300 to-amber-400 shadow-sm animate-pulse': getStatus(step.agent) === 'running',
                      'bg-slate-100 border border-slate-200': getStatus(step.agent) === 'pending',
                      'bg-gradient-to-br from-rose-400 to-rose-500 shadow-sm': getStatus(step.agent) === 'error',
                    }"
                  >
                    <AppIcon
                      :name="getStatus(step.agent) === 'running' ? 'Loader2' : step.icon"
                      size="sm"
                      :variant="getStatus(step.agent) === 'pending' ? 'cyan' : 'white'"
                      :animate="getStatus(step.agent) === 'running'"
                    />
                  </div>
                  <!-- Substep label -->
                  <span
                    class="text-[10px] md:text-xs leading-tight text-center"
                    :class="{
                      'text-slate-800': getStatus(step.agent) === 'completed',
                      'text-amber-600 font-semibold': getStatus(step.agent) === 'running',
                      'text-slate-400': getStatus(step.agent) === 'pending',
                      'text-rose-600 font-semibold': getStatus(step.agent) === 'error',
                    }"
                  >{{ step.label }}</span>
                </div>
              </template>
            </div>
          </div>
        </div>
      </TransitionGroup>
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
          <span
            class="w-2 h-2 rounded-full flex-shrink-0"
            :class="entry.status === 'error' ? 'bg-rose-500' : 'bg-emerald-500'"
          />
          <span class="text-sm font-medium text-slate-700 w-32 truncate">{{ entry.agent }}</span>
          <div class="flex-1 flex items-center gap-4 text-xs text-slate-500">
            <span>{{ formatTime(entry.started_at) }}</span>
            <span class="text-slate-300">→</span>
            <span>{{ formatTime(entry.completed_at) }}</span>
          </div>
          <span
            class="text-xs font-medium px-2 py-0.5 rounded"
            :class="entry.duration_seconds > 30 ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-600'"
          >
            {{ formatDuration(entry.duration_seconds) }}
          </span>
          <span v-if="entry.error" class="text-xs text-rose-500 truncate max-w-[150px]" :title="entry.error">
            {{ entry.error }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Expand/collapse transition for substep panel */
.substep-expand-enter-active {
  transition: all 0.25s ease-out;
  overflow: hidden;
}
.substep-expand-leave-active {
  transition: all 0.2s ease-in;
  overflow: hidden;
}
.substep-expand-enter-from,
.substep-expand-leave-to {
  opacity: 0;
  max-height: 0;
  margin-top: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.substep-expand-enter-to,
.substep-expand-leave-from {
  opacity: 1;
  max-height: 200px;
}

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
