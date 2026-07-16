<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, watch, defineAsyncComponent, defineComponent, h } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import CheckpointRail from '@/components/replay/CheckpointRail.vue'
import { useWorkflowStore, useAuthStore, useToastStore } from '@/stores'
import { getWorkflowStatus } from '@/api/workflow'
import { useWorkflowReplay } from '@/composables/useWorkflowReplay'
import { trackInteraction } from '@/utils/interactionTelemetry'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const workflowStore = useWorkflowStore()
const authStore = useAuthStore()
const toastStore = useToastStore()

const ReplayResultLoading = defineComponent({
  name: 'ReplayResultLoading',
  setup() {
    return () => h('div', {
      class: 'replay-result-loading liquid-glass rounded-xl p-4 space-y-3',
      role: 'status',
      'aria-busy': 'true',
    }, [
      h('div', { class: 'h-3 w-32 rounded bg-slate-200/80 animate-pulse' }),
      h('div', { class: 'h-16 w-full rounded-lg bg-slate-200/60 animate-pulse' }),
    ])
  },
})

const AgentResultTrend = defineAsyncComponent({
  loader: () => import('@/components/replay/AgentResultTrend.vue'),
  loadingComponent: ReplayResultLoading,
  delay: 80,
})
const AgentResultPlan = defineAsyncComponent({
  loader: () => import('@/components/replay/AgentResultPlan.vue'),
  loadingComponent: ReplayResultLoading,
  delay: 80,
})
const AgentResultCreative = defineAsyncComponent({
  loader: () => import('@/components/replay/AgentResultCreative.vue'),
  loadingComponent: ReplayResultLoading,
  delay: 80,
})
const AgentResultVisual = defineAsyncComponent({
  loader: () => import('@/components/replay/AgentResultVisual.vue'),
  loadingComponent: ReplayResultLoading,
  delay: 80,
})
const AgentResultPublish = defineAsyncComponent({
  loader: () => import('@/components/replay/AgentResultPublish.vue'),
  loadingComponent: ReplayResultLoading,
  delay: 80,
})
const AgentResultAnalytics = defineAsyncComponent({
  loader: () => import('@/components/replay/AgentResultAnalytics.vue'),
  loadingComponent: ReplayResultLoading,
  delay: 80,
})
const AgentResultRipple = defineAsyncComponent({
  loader: () => import('@/components/replay/AgentResultRipple.vue'),
  loadingComponent: ReplayResultLoading,
  delay: 80,
})

const threadId = route.params.threadId as string
const isAuthenticated = computed(() => authStore.isAuthenticated)

const {
  activeCheckpointId,
  replayCheckpoints,
  liveWorkflowState,
  workflowLabel,
  workflowMode,
  pipelineSteps,
  selectedCheckpoint,
  selectedAgent,
  resolvedShootingPlan,
  getNodeStatus,
  handleNodeClick: selectReplayPhase,
  isNodeSelected,
  hasDataForAgent,
  hasMeaningfulData,
  formatDate,
  workflowStatus,
  workflowProgress,
  hasCheckpointForPhase,
} = useWorkflowReplay()

const isWorkflowLoading = ref(true)
const workflowLoadError = ref<string | null>(null)
const threadNotFound = ref(false)
const isRetrying = ref(false)
const mobileCheckpointOpen = ref(false)
const checkpointLoadError = computed(() => workflowStore.replayCheckpointsError)
const isCheckpointLoading = computed(() => workflowStore.isLoadingCheckpoints)
const requestedCheckpointId = computed(() => {
  const value = route.query.checkpoint
  return typeof value === 'string' && value ? value : undefined
})

const phaseLabels = computed<Record<string, string>>(() => ({
  scouting: t('showcase.phase.scouting'),
  planning: t('showcase.phase.planning'),
  briefing: t('dashboard.timeline.briefing'),
  creating: t('showcase.phase.creating'),
  reviewing: t('showcase.phase.reviewing'),
  publishing: t('showcase.phase.publishing'),
  analyzing: t('showcase.phase.analyzing'),
}))

const phaseIcons = computed<Record<string, string>>(() => ({
  scouting: 'Search',
  planning: 'ClipboardList',
  briefing: 'FileText',
  creating: 'Pencil',
  reviewing: 'Clock',
  publishing: 'Upload',
  analyzing: 'BarChart3',
}))

const workflowStatusLabel = computed(() => {
  const key = `replay.workflowStatus.${workflowStatus.value}`
  const translated = t(key)
  return translated === key ? workflowStatus.value : translated
})

const agentLabelKeys: Record<string, string> = {
  trend_scout: 'showcase.phase.scouting',
  content_strategist: 'showcase.phase.planning',
  copywriter: 'showcase.phase.creating',
  draft_gate: 'dashboard.timeline.short.draft',
  brief_analyzer: 'dashboard.timeline.short.briefAnalyze',
  brief_gate: 'dashboard.timeline.short.briefGate',
  viral_matcher: 'dashboard.timeline.short.viralMatch',
  blogger_scout: 'dashboard.timeline.short.bloggerScout',
  blogger_gate: 'dashboard.timeline.short.bloggerGate',
  shooting_planner: 'dashboard.timeline.short.shootingPlan',
  visual_designer: 'dashboard.timeline.short.visual',
  content_analyzer: 'dashboard.timeline.short.contentAnalysis',
  version_generator: 'dashboard.timeline.short.versionGen',
  choice_gate: 'dashboard.timeline.short.choiceGate',
  review_gate: 'showcase.phase.reviewing',
  revise_content: 'dashboard.timeline.short.reviseContent',
  publisher: 'showcase.phase.publishing',
  engagement: 'dashboard.timeline.short.engagement',
  analyst: 'showcase.phase.analyzing',
  orchestrator: 'dashboard.timeline.orchestrator',
}

function agentLabel(agent: string): string {
  const key = agentLabelKeys[agent]
  return key ? t(key) : agent
}

const creativeAgents = new Set([
  'copywriter',
  'draft_gate',
  'viral_matcher',
  'blogger_scout',
  'blogger_gate',
  'choice_gate',
  'content_analyzer',
  'version_generator',
  'brief_analyzer',
  'brief_gate',
  'shooting_planner',
])
const reviewAgents = new Set(['review_gate', 'revise_content'])
const publishAgents = new Set(['publisher', 'engagement'])

function hasObjectData(value: unknown): boolean {
  return !!value && typeof value === 'object' && Object.keys(value as Record<string, unknown>).length > 0
}

// A live status can exist without any historical snapshots. Keep this flag
// scoped to replay data so the empty-checkpoint state is not presented as an
// actionable step picker.
const hasReplayData = computed(() => replayCheckpoints.value.length > 0)

const activePhaseLabel = computed(() => {
  const phase = selectedCheckpoint.value?.phase || liveWorkflowState.value?.phase
  if (selectedCheckpoint.value) return selectedAgentLabel.value
  return phase ? (phaseLabels.value[phase] || phase) : t('replay.clickHint')
})

const pipelineNodes = computed(() => hasReplayData.value
  ? pipelineSteps.value.map((phase) => ({
      phase,
      icon: phaseIcons.value[phase],
      label: phaseLabels.value[phase] || phase,
      status: getNodeStatus(phase),
      selected: isNodeSelected(phase),
    }))
  : [])

const mobileCheckpointChips = computed(() =>
  workflowStore.replayCheckpoints.map((cp) => ({
    id: cp.checkpoint_id,
    label: agentLabel(cp.current_agent),
    active: cp.checkpoint_id === activeCheckpointId.value,
  }))
)

const selectedAgentLabel = computed(() => agentLabel(selectedAgent.value))
const isCreativeAgent = computed(() => creativeAgents.has(selectedAgent.value))
const isReviewAgent = computed(() => reviewAgents.has(selectedAgent.value))
const isPublishAgent = computed(() => publishAgents.has(selectedAgent.value))
const hasRippleResult = computed(() => {
  const cp = selectedCheckpoint.value
  return !!cp && (
    hasObjectData(cp.ripple_prediction) ||
    hasObjectData(cp.ripple_pmf) ||
    hasObjectData(cp.ripple_comparison)
  )
})
const hasSelectedAgentData = computed(() =>
  selectedCheckpoint.value ? hasDataForAgent(selectedAgent.value, selectedCheckpoint.value) : false
)

function artNodeStyle(index: number): Record<string, string> {
  const count = Math.max(pipelineNodes.value.length, 1)
  const angle = -90 + (index * 360) / count
  return {
    '--orbit-angle': `${angle}deg`,
    '--orbit-delay': `${index * 110}ms`,
  }
}

const returnPath = computed(() => {
  const raw = route.query.from || route.query.returnTo
  if (typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//')) return raw
  return '/'
})

function goBack() {
  trackInteraction('replay_back', { source: typeof route.query.from === 'string' ? route.query.from : 'direct' })
  router.push(returnPath.value)
}

function goDashboard() {
  trackInteraction('replay_primary_cta_click', { source: 'replay', status: workflowStatus.value, mode: workflowMode.value })
  router.push({ name: 'dashboard', params: { threadId } })
}

async function copyCheckpointLink() {
  if (!activeCheckpointId.value) return
  const resolved = router.resolve({ name: 'replay', params: { threadId }, query: { ...route.query, checkpoint: activeCheckpointId.value } })
  const href = typeof window !== 'undefined' ? new URL(resolved.href, window.location.origin).toString() : resolved.href
  try {
    await navigator.clipboard.writeText(href)
    trackInteraction('replay_checkpoint_link_copy', { step: selectedCheckpoint.value?.step })
    toastStore.success(t('replay.linkCopied'))
  } catch {
    toastStore.error(t('replay.linkCopyFailed'))
  }
}

function isNotFoundError(error: any): boolean {
  return error?.response?.status === 404 || error?.status === 404 || error?.code === 'ERROR_WORKFLOW_NOT_FOUND' || /not found|不存在/i.test(error?.message || '')
}

async function loadReplay() {
  isWorkflowLoading.value = true
  workflowLoadError.value = null
  threadNotFound.value = false
  workflowStore.setThreadId(threadId)
  // Start both public requests together. A status failure must not prevent
  // the history request: historical replay remains useful when live state is
  // temporarily unavailable, while a 404 still renders the dedicated state.
  const statusTask = (async () => {
    try {
      const state = await getWorkflowStatus(threadId, { suppressToast: true })
      workflowStore.workflowStates.set(threadId, state)
    } catch (error: any) {
      workflowLoadError.value = error?.message || t('replay.workflowLoadFailed')
      threadNotFound.value = isNotFoundError(error)
      trackInteraction('replay_load_error', { error_type: threadNotFound.value ? 'thread_not_found' : 'workflow_status' })
    } finally {
      isWorkflowLoading.value = false
    }
  })()
  const checkpointTask = workflowStore.enterReplayMode(requestedCheckpointId.value)
  await Promise.all([statusTask, checkpointTask])
  if (threadNotFound.value) workflowStore.exitReplayMode()
}

async function retryReplay() {
  isRetrying.value = true
  try {
    await loadReplay()
  } finally {
    isRetrying.value = false
  }
}

function selectCheckpoint(id: string) {
  const checkpoint = replayCheckpoints.value.find(item => item.checkpoint_id === id)
  trackInteraction('replay_checkpoint_select', { step: checkpoint?.step, phase: checkpoint?.phase, mode: workflowMode.value })
  workflowStore.selectCheckpoint(id)
}

function selectPhase(phase: string) {
  trackInteraction('replay_phase_select', { phase, mode: workflowMode.value })
  selectReplayPhase(phase)
}

watch(activeCheckpointId, (id) => {
  if (!id || id === route.query.checkpoint) return
  void router.replace({ query: { ...route.query, checkpoint: id } })
})

watch(requestedCheckpointId, (id) => {
  if (!id || id === activeCheckpointId.value) return
  if (replayCheckpoints.value.some(checkpoint => checkpoint.checkpoint_id === id)) {
    workflowStore.selectCheckpoint(id)
  }
})

onMounted(() => {
  trackInteraction('replay_view', { source: typeof route.query.from === 'string' ? route.query.from : 'direct' })
  void loadReplay()
})

onUnmounted(() => {
  workflowStore.exitReplayMode()
})

// Right sidebar: final output summary — only L1 key facts
const latestFinalCheckpoint = computed(() => [...replayCheckpoints.value]
  .filter((cp) => cp.phase === 'completed' || Object.keys(cp.publish_result || {}).length > 0 || Object.keys(cp.analytics || {}).length > 0)
  .sort((a, b) => b.step - a.step)[0])

const finalSummary = computed(() => {
  const live = liveWorkflowState.value
  const liveIsFinal = live?.status === 'completed' || live?.phase === 'completed'
  const liveHasResult = Boolean(
    live?.copy_content?.selected_title ||
    live?.content_plan?.selected_topic ||
    Object.keys(live?.publish_result || {}).length ||
    Object.keys(live?.analytics || {}).length,
  )
  const state = liveIsFinal && liveHasResult ? live : latestFinalCheckpoint.value || live
  if (!state) return null
  return {
    title: state.copy_content?.selected_title,
    topic: state.content_plan?.selected_topic,
    brand: (state as any).brief_content?.brand_name,
    product: (state as any).brief_content?.product_name,
    hashtags: state.copy_content?.hashtags,
    publishUrl: (state.publish_result as any)?.post_url,
    publishStatus: (state.publish_result as any)?.status,
    views: (state.analytics as any)?.views,
    likes: (state.analytics as any)?.likes,
    engagementRate: (state.analytics as any)?.engagement_rate,
    viralProb: state.ripple_prediction?.viral_probability,
    pmfScore: state.ripple_pmf?.pmf_score,
  }
})
</script>

<template>
  <div class="replay-page min-h-screen text-slate-800 relative">
    <div class="replay-bg-grid" aria-hidden="true" />
    <div class="replay-bg-orb replay-bg-orb-a" aria-hidden="true" />
    <div class="replay-bg-orb replay-bg-orb-b" aria-hidden="true" />
    <!-- Nav — identity and global actions only -->
    <nav class="replay-nav relative z-20 liquid-glass-nav border-b border-white/15">
      <div class="max-w-[1400px] mx-auto px-4 md:px-8">
        <!-- Top row: back + title + actions -->
        <div class="h-12 flex items-center justify-between">
          <div class="flex items-center gap-2.5">
            <button type="button" @click="goBack" class="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 transition-colors hover:bg-slate-200" :aria-label="t('replay.back')">
              <AppIcon name="ArrowLeft" size="sm" variant="cyan" />
            </button>
            <div class="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-rose-500 to-amber-400 shadow-sm shadow-rose-500/20">
              <AppIcon name="Rocket" size="sm" variant="white" />
            </div>
            <div>
              <h1 class="text-base font-bold tracking-tight text-slate-800">{{ t('replay.title') }}</h1>
              <div class="flex items-center gap-1.5 -mt-0.5">
                <span v-if="workflowLabel" class="text-[10px] text-slate-500 font-medium truncate max-w-[100px]">{{ workflowLabel }}</span>
                <span class="text-[10px] text-slate-400 font-mono">{{ threadId.slice(-8) }}</span>
                <span v-if="workflowMode" class="replay-mode-badge text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600">{{ workflowMode }}</span>
                <span class="replay-status-badge text-[10px] px-1.5 py-0.5 rounded-full" :class="`replay-status-${workflowStatus}`">{{ workflowStatusLabel }}</span>
              </div>
              <p v-if="selectedCheckpoint" class="mt-1 text-[10px] text-slate-500 truncate max-w-[300px]">
                {{ t('replay.viewingCheckpoint', { step: selectedCheckpoint.step, agent: selectedAgentLabel, time: formatDate(selectedCheckpoint.created_at) }) }}
              </p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button v-if="selectedCheckpoint" type="button" @click="copyCheckpointLink" class="min-h-11 rounded-xl border border-slate-200 bg-white/70 px-3 text-[11px] font-medium text-slate-600 transition-colors hover:bg-white" :aria-label="t('replay.copyLink')">
              <AppIcon name="Link" size="xs" variant="cyan" />
              <span class="hidden sm:inline">{{ t('replay.copyLink') }}</span>
            </button>
            <button v-if="isAuthenticated" type="button" @click="goDashboard" class="min-h-11 rounded-xl bg-rose-500 px-3 text-[11px] font-medium text-white shadow-sm shadow-rose-500/20 transition-colors hover:bg-rose-600">
              {{ t('replay.goDashboard') }}
            </button>
          </div>
        </div>

      </div>
    </nav>

    <main class="replay-main relative z-10 mx-auto max-w-[1400px] px-4 py-5 md:px-8 md:py-7">
      <section v-if="isWorkflowLoading && !hasReplayData" class="replay-state-card liquid-glass p-5 mb-4" aria-busy="true">
        <div class="h-3 w-36 rounded bg-slate-200/80 animate-pulse" />
        <div class="mt-3 h-5 w-2/3 rounded bg-slate-200/70 animate-pulse" />
        <div class="mt-4 h-2 w-full rounded bg-slate-200/60 animate-pulse" />
        <p class="mt-3 text-xs text-slate-500">{{ t('replay.loadingWorkflow') }}</p>
      </section>
      <section v-if="threadNotFound" class="replay-state-card liquid-glass p-6 mb-4 text-center" role="alert">
        <AppIcon name="FileQuestion" size="lg" variant="cyan" aria-hidden="true" />
        <h2 class="mt-3 text-base font-semibold text-slate-800">{{ t('replay.threadNotFound') }}</h2>
        <p class="mt-1 text-xs text-slate-500">{{ t('replay.threadNotFoundDesc') }}</p>
        <button type="button" class="mt-4 min-h-11 rounded-xl bg-slate-800 px-4 text-xs font-medium text-white" @click="goBack">{{ t('replay.backToCases') }}</button>
      </section>
      <section v-else-if="workflowLoadError" class="replay-state-card replay-state-warning rounded-xl p-3 mb-4" role="status">
        <div class="flex items-start gap-2">
          <AppIcon name="AlertTriangle" size="sm" variant="peach" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <p class="text-xs font-semibold text-amber-800">{{ t('replay.liveStateUnavailable') }}</p>
            <p class="mt-1 text-[11px] text-amber-700">{{ t('replay.liveStateUnavailableDesc') }}</p>
          </div>
          <button type="button" class="min-h-11 shrink-0 rounded-lg px-3 text-[11px] font-medium text-amber-800 hover:bg-amber-100/60" :disabled="isRetrying" @click="retryReplay">{{ isRetrying ? t('common.loadingState') : t('common.retry') }}</button>
        </div>
      </section>
      <section v-if="checkpointLoadError" class="replay-state-card replay-state-error rounded-xl p-3 mb-4" role="alert">
        <div class="flex items-start gap-2">
          <AppIcon name="RefreshCw" size="sm" variant="pink" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <p class="text-xs font-semibold text-rose-800">{{ t('replay.checkpointLoadFailed') }}</p>
            <p class="mt-1 text-[11px] text-rose-700">{{ t('replay.checkpointLoadFailedDesc') }}</p>
          </div>
          <button type="button" class="min-h-11 shrink-0 rounded-lg px-3 text-[11px] font-medium text-rose-800 hover:bg-rose-100/60" :disabled="isRetrying" @click="retryReplay">{{ isRetrying ? t('common.loadingState') : t('common.retry') }}</button>
        </div>
      </section>
      <!-- Pipeline state is a workspace control, not a navigation decoration. -->
      <section v-if="!threadNotFound" class="replay-pipeline-panel liquid-glass-liquid mb-4 md:mb-5" :aria-label="t('replay.pipeline')">
        <div class="replay-pipeline-panel-head flex items-center justify-between gap-3">
          <div class="min-w-0">
            <p class="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{{ t('replay.pipeline') }}</p>
            <p class="mt-1 truncate text-sm font-semibold text-slate-700">
              {{ selectedCheckpoint ? selectedAgentLabel : liveWorkflowState ? (phaseLabels[liveWorkflowState.phase] || liveWorkflowState.phase) : hasReplayData ? t('replay.clickHint') : t('replay.noWorkflow') }}
            </p>
          </div>
          <div v-if="liveWorkflowState" class="replay-panel-progress flex shrink-0 items-center gap-2">
            <div class="h-1.5 w-20 overflow-hidden rounded-full bg-slate-200/80 sm:w-28">
              <span class="block h-full rounded-full bg-gradient-to-r from-teal-400 to-sky-400" :style="{ width: `${workflowProgress}%` }" />
            </div>
            <span class="text-[11px] font-mono text-slate-500">{{ workflowProgress }}%</span>
          </div>
        </div>
        <div v-if="hasReplayData" class="replay-pipeline flex items-center gap-1 overflow-x-auto scrollbar-thin pt-3">
          <div
            v-for="node in pipelineNodes"
            :key="node.phase"
            v-memo="[node.status, node.selected, node.label]"
            class="shrink-0"
          >
            <button
              type="button"
              @click="selectPhase(node.phase)"
              :disabled="!hasCheckpointForPhase(node.phase)"
              class="replay-pipeline-node flex min-h-11 items-center gap-1.5 rounded-xl px-2.5 text-[11px] font-medium transition-colors"
              :class="[
                node.selected
                  ? 'bg-slate-800 text-white'
                  : node.status === 'completed'
                    ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                    : node.status === 'running'
                      ? 'bg-amber-50 text-amber-700'
                      : node.status === 'error'
                        ? 'bg-red-50 text-red-700'
                        : 'bg-slate-50 text-slate-500 hover:bg-slate-100',
                { 'replay-pipeline-node-active': node.selected || node.status === 'running' },
              ]"
              :aria-pressed="node.selected"
              :aria-current="node.selected ? 'step' : undefined"
              :aria-disabled="!hasCheckpointForPhase(node.phase)"
              :title="!hasCheckpointForPhase(node.phase) ? t('replay.phaseUnavailable') : undefined"
            >
              <AppIcon :name="node.icon" size="xs" :variant="node.selected ? 'white' : 'cyan'" />
              {{ node.label }}
            </button>
          </div>
        </div>
        <div v-else class="replay-pipeline-empty mt-3 flex items-center gap-2 rounded-xl px-3 py-2.5 text-xs text-slate-400">
          <AppIcon name="Info" size="sm" variant="cyan" aria-hidden="true" />
          {{ t('replay.noWorkflowDesc') }}
        </div>
      </section>
      <!-- Two-column layout: rail | detail + summary -->
      <div v-if="!threadNotFound" class="replay-layout grid grid-cols-1 gap-4 lg:grid-cols-[minmax(170px,220px)_minmax(0,1fr)_minmax(220px,280px)] md:gap-5">
        <!-- Left: checkpoint rail -->
        <div class="replay-checkpoint-column hidden lg:block">
          <div v-if="hasReplayData" class="replay-rail-panel sticky top-20 max-h-[calc(100vh-8rem)] overflow-y-auto pr-1">
            <CheckpointRail />
          </div>
          <div v-else class="replay-rail-panel replay-rail-empty sticky top-20 text-center">
            <AppIcon name="Clock" size="sm" variant="cyan" aria-hidden="true" />
            <p class="mt-2 text-[11px] font-medium text-slate-500">{{ t('replay.checkpointsEmpty') }}</p>
          </div>
        </div>

        <!-- Mobile: checkpoint chips -->
        <div class="replay-mobile-rail lg:hidden">
          <div v-if="mobileCheckpointChips.length" class="space-y-2">
            <button type="button" class="replay-mobile-checkpoint-toggle flex min-h-11 w-full items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white/70 px-3 text-left" :aria-expanded="mobileCheckpointOpen" @click="mobileCheckpointOpen = !mobileCheckpointOpen">
              <span class="min-w-0 truncate text-xs font-medium text-slate-700">
                {{ selectedCheckpoint ? `${t('replay.step')} ${selectedCheckpoint.step} · ${selectedAgentLabel}` : t('replay.checkpoints') }}
              </span>
              <span class="shrink-0 text-[10px] font-medium text-teal-700">{{ mobileCheckpointOpen ? t('replay.closeCheckpoints') : t('replay.openCheckpoints') }}</span>
            </button>
            <div v-if="mobileCheckpointOpen" class="replay-mobile-checkpoint-list grid max-h-56 grid-cols-1 gap-1 overflow-y-auto pr-1">
              <button
                v-for="chip in mobileCheckpointChips"
                :key="chip.id"
                type="button"
                @click="selectCheckpoint(chip.id)"
                class="replay-mobile-chip flex min-h-11 items-center justify-between rounded-xl border px-3 text-left text-[10px] font-medium transition-colors"
                :class="chip.active ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-500 border-slate-200 hover:bg-slate-50'"
                :aria-pressed="chip.active"
              >
                <span>{{ chip.label }}</span><span class="font-mono opacity-70">{{ replayCheckpoints.find(cp => cp.checkpoint_id === chip.id)?.step }}</span>
              </button>
              <button v-if="workflowStore.hasMoreCheckpoints" type="button" :disabled="isCheckpointLoading" @click="workflowStore.loadMoreCheckpoints()" class="min-h-11 rounded-xl border border-slate-200 px-3 text-[10px] text-slate-400 hover:bg-slate-50">+{{ t('replay.loadMore') }}</button>
            </div>
          </div>
          <div v-else class="flex items-center gap-2 px-1 py-1 text-[11px] text-slate-400">
            <AppIcon name="Clock" size="xs" variant="cyan" aria-hidden="true" />
            {{ t('replay.checkpointsEmpty') }}
          </div>
        </div>

        <!-- Center: selected checkpoint detail -->
        <div class="replay-detail-column">
          <div v-if="isCheckpointLoading && !selectedCheckpoint" class="replay-state-card liquid-glass p-6" aria-busy="true">
            <div class="h-4 w-40 rounded bg-slate-200/80 animate-pulse" />
            <div class="mt-4 h-20 rounded-xl bg-slate-200/60 animate-pulse" />
            <p class="mt-3 text-xs text-slate-500">{{ t('replay.loadingCheckpoints') }}</p>
          </div>
          <div v-else-if="selectedCheckpoint" class="space-y-0">
            <!-- Checkpoint header — compact -->
            <div class="replay-detail-header flex items-center gap-2 mb-3">
              <span class="replay-detail-pulse h-2 w-2 rounded-full bg-teal-400" />
              <div class="min-w-0 text-sm font-semibold text-slate-800 truncate">{{ selectedAgentLabel }}</div>
              <span class="replay-step-badge text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">{{ t('replay.step') }} {{ selectedCheckpoint.step }}</span>
              <span v-if="selectedCheckpoint.created_at" class="ml-auto shrink-0 text-[10px] text-slate-400">{{ formatDate(selectedCheckpoint.created_at) }}</span>
            </div>

            <!-- Agent result content -->
            <div class="replay-result-stack space-y-3">
              <!-- Trend scout -->
              <AgentResultTrend v-if="selectedAgent === 'trend_scout'" :cp="selectedCheckpoint" />

              <!-- Content strategist -->
              <AgentResultPlan v-if="selectedAgent === 'content_strategist'" :cp="selectedCheckpoint" />

              <!-- Creating phase agents -->
              <AgentResultCreative
                v-if="isCreativeAgent"
                :cp="selectedCheckpoint"
                :shooting-plan="resolvedShootingPlan"
                :hide-draft="true"
              />

              <!-- Visual designer -->
              <AgentResultVisual v-if="selectedAgent === 'visual_designer'" :cp="selectedCheckpoint" />

              <!-- Review gate / revise -->
              <template v-if="isReviewAgent">
                <AgentResultCreative :cp="selectedCheckpoint" :shooting-plan="resolvedShootingPlan" :hide-draft="true" />
                <AgentResultVisual v-if="hasMeaningfulData(selectedCheckpoint.visual_plan)" :cp="selectedCheckpoint" />
              </template>

              <!-- Publishing -->
              <AgentResultPublish v-if="isPublishAgent" :cp="selectedCheckpoint" />

              <!-- Analytics -->
              <AgentResultAnalytics v-if="selectedAgent === 'analyst'" :cp="selectedCheckpoint" />

              <!-- Ripple (shown for any checkpoint that has ripple data) -->
              <AgentResultRipple
                v-if="hasRippleResult"
                :cp="selectedCheckpoint"
              />

              <!-- No data -->
              <div v-if="!hasSelectedAgentData" class="replay-no-data text-xs text-slate-400 text-center py-6">
                {{ t('replay.noData') }}
              </div>
            </div>
          </div>

          <!-- No checkpoint selected -->
          <div v-else-if="checkpointLoadError" class="replay-empty-state rounded-xl liquid-glass p-8 text-center" role="alert">
            <AppIcon name="RefreshCw" size="lg" variant="pink" />
            <p class="mt-3 text-sm font-semibold text-slate-700">{{ t('replay.checkpointLoadFailed') }}</p>
            <button type="button" class="mt-4 min-h-11 rounded-xl bg-slate-800 px-4 text-xs font-medium text-white" :disabled="isRetrying" @click="retryReplay">{{ isRetrying ? t('common.loadingState') : t('common.retry') }}</button>
          </div>
          <div v-else class="replay-empty-state rounded-xl liquid-glass p-8 text-center">
            <div class="w-12 h-12 rounded-xl bg-slate-100 flex items-center justify-center mx-auto mb-4">
              <AppIcon name="MousePointerClick" size="lg" variant="cyan" />
            </div>
            <p class="text-[10px] font-bold uppercase tracking-[0.18em] text-teal-600">{{ t('replay.inspectLabel') }}</p>
            <p class="mt-2 text-sm font-semibold text-slate-700">{{ hasReplayData ? t('replay.clickHint') : liveWorkflowState ? t('replay.checkpointsEmpty') : t('replay.noWorkflow') }}</p>
            <p class="mt-1.5 text-xs leading-5 text-slate-400">{{ hasReplayData ? t('replay.clickHintDesc') : t('replay.noWorkflowDesc') }}</p>
          </div>
        </div>

        <!-- Right: compact context and output summary -->
        <div class="replay-summary-column">
          <div class="sticky top-4 space-y-3">
            <!-- Replay context first: it explains the read-only surface. -->
            <div v-if="hasReplayData" class="replay-demo-banner rounded-xl liquid-glass-violet p-2.5">
              <div class="flex items-center gap-2">
                <div class="w-5 h-5 rounded bg-violet-100 flex items-center justify-center shrink-0">
                  <AppIcon name="History" size="xs" variant="purple" />
                </div>
                <div class="min-w-0">
                  <div class="text-[10px] text-violet-700 font-medium">{{ selectedCheckpoint ? t('replay.inspectLabel') : t('replay.mode') }}</div>
                  <p class="text-[10px] text-violet-500 line-clamp-1">{{ selectedCheckpoint ? selectedAgentLabel : t('replay.modeDesc') }}</p>
                </div>
              </div>
            </div>

            <div v-else class="replay-demo-banner replay-no-workflow-banner rounded-xl liquid-glass-inset p-3">
              <div class="flex items-start gap-2">
                <div class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-slate-100">
                  <AppIcon name="Info" size="xs" variant="cyan" />
                </div>
                <div class="min-w-0">
                  <div class="text-[10px] font-semibold text-slate-600">{{ t('replay.noWorkflow') }}</div>
                  <p class="mt-1 text-[10px] leading-4 text-slate-400">{{ t('replay.noWorkflowDesc') }}</p>
                </div>
              </div>
            </div>

            <!-- Final output — only L1 key facts -->
            <div v-if="hasReplayData" class="replay-summary-card replay-output-summary rounded-xl liquid-glass p-3 space-y-1.5">
              <div class="text-[10px] text-slate-400 font-medium uppercase tracking-widest">{{ t('replay.outputSummary') }}</div>
              <div v-if="finalSummary?.title" class="text-base font-bold text-slate-800 leading-snug">{{ finalSummary.title }}</div>
              <div v-if="finalSummary?.topic" class="text-xs text-slate-600">{{ finalSummary.topic }}</div>
              <div v-if="finalSummary?.brand" class="text-xs text-slate-500">{{ finalSummary.brand }}<span v-if="finalSummary.product"> / {{ finalSummary.product }}</span></div>
              <div v-if="finalSummary?.hashtags?.length" class="flex flex-wrap gap-1">
                <span v-for="tag in finalSummary?.hashtags || []" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
              </div>
              <p v-if="!finalSummary || (!finalSummary.title && !finalSummary.topic && !finalSummary.brand)" class="text-xs leading-5 text-slate-500">{{ t('replay.notGenerated') }}</p>
            </div>

            <!-- Key metrics — only if not already in analytics panel -->
            <div v-if="finalSummary && (finalSummary.viralProb != null || finalSummary.pmfScore != null)" class="replay-summary-card rounded-xl liquid-glass p-3 space-y-2">
              <div class="text-[10px] text-slate-400 font-medium uppercase tracking-widest">{{ t('replay.keyMetrics') }}</div>
              <div class="grid grid-cols-2 gap-1.5">
                <div v-if="finalSummary.viralProb != null" class="p-2 rounded-lg liquid-glass-inset text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.viralProb') }}</div>
                  <div class="text-sm font-bold" :class="finalSummary.viralProb >= 0.7 ? 'text-emerald-600' : finalSummary.viralProb >= 0.4 ? 'text-amber-600' : 'text-rose-600'">{{ (finalSummary.viralProb * 100).toFixed(0) }}%</div>
                </div>
                <div v-if="finalSummary.pmfScore != null" class="p-2 rounded-lg liquid-glass-inset text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.pmfLabel') }}</div>
                  <div class="text-sm font-bold" :class="finalSummary.pmfScore >= 0.7 ? 'text-emerald-600' : finalSummary.pmfScore >= 0.4 ? 'text-amber-600' : 'text-rose-600'">{{ (finalSummary.pmfScore * 100).toFixed(0) }}%</div>
                </div>
              </div>
            </div>

            <!-- Publish link -->
            <div v-if="finalSummary?.publishUrl" class="replay-summary-card rounded-xl liquid-glass p-3">
              <a :href="finalSummary.publishUrl" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 text-xs text-emerald-600 hover:text-emerald-700 font-medium">
                <AppIcon name="ExternalLink" size="sm" />
                {{ t('replay.viewPost') }}
              </a>
            </div>

          </div>
        </div>
      </div>
      <section
        v-if="hasReplayData"
        class="replay-creation-art liquid-glass-liquid mt-4 md:mt-5"
        :aria-label="t('replay.creationProcess')"
      >
        <div class="replay-creation-art-copy">
          <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-teal-600">{{ t('replay.creationProcess') }}</p>
          <h2 class="mt-2 text-xl font-bold tracking-tight text-slate-800">{{ activePhaseLabel }}</h2>
          <p class="mt-2 max-w-sm text-xs leading-5 text-slate-500">{{ t('replay.creationProcessDesc') }}</p>
          <div class="mt-4 inline-flex items-center gap-2 rounded-full border border-teal-200/70 bg-white/60 px-2.5 py-1.5 text-[10px] font-medium text-teal-700">
            <span class="replay-creation-signal h-1.5 w-1.5 rounded-full bg-teal-400" aria-hidden="true" />
            {{ t('replay.signalMoving') }}
          </div>
        </div>
        <div class="replay-creation-art-visual" aria-hidden="true">
          <div class="replay-art-ring replay-art-ring-outer" />
          <div class="replay-art-ring replay-art-ring-inner" />
          <div class="replay-art-core">
            <span class="replay-art-core-glow" />
            <span class="relative text-[9px] font-bold uppercase tracking-[0.18em] text-white">AI</span>
          </div>
          <span class="replay-art-signal" />
          <span
            v-for="(node, index) in pipelineNodes"
            :key="`art-${node.phase}`"
            class="replay-orbit-node"
            :class="{ 'replay-orbit-node-active': node.selected || node.status === 'running', 'replay-orbit-node-completed': node.status === 'completed' }"
            :style="artNodeStyle(index)"
          >
            <span class="replay-orbit-node-dot" />
            <span class="replay-orbit-node-label">{{ node.label }}</span>
          </span>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.replay-page {
  isolation: isolate;
  overflow-x: clip;
  --replay-ink: #1e293b;
  --replay-muted: #64748b;
  background:
    linear-gradient(135deg, rgba(255, 241, 242, 0.48), transparent 32%),
    linear-gradient(225deg, rgba(240, 253, 250, 0.5), transparent 36%),
    linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
}

.replay-state-card {
  border: 1px solid rgba(255, 255, 255, 0.72);
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.replay-state-warning {
  border: 1px solid rgba(245, 158, 11, 0.28);
  background: rgba(255, 251, 235, 0.82);
}

.replay-state-error {
  border: 1px solid rgba(244, 63, 94, 0.24);
  background: rgba(255, 241, 242, 0.82);
}

.replay-status-badge { border: 1px solid transparent; }
.replay-status-running { color: #0f766e; background: #ccfbf1; border-color: #99f6e4; }
.replay-status-completed { color: #047857; background: #d1fae5; border-color: #a7f3d0; }
.replay-status-error { color: #be123c; background: #ffe4e6; border-color: #fecdd3; }
.replay-status-paused, .replay-status-stale { color: #a16207; background: #fef3c7; border-color: #fde68a; }
.replay-status-idle, .replay-status-cancelled { color: #475569; background: #f1f5f9; border-color: #e2e8f0; }

.replay-bg-grid {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(15, 23, 42, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(15, 23, 42, 0.035) 1px, transparent 1px);
  background-size: 44px 44px;
  -webkit-mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.86), rgba(0, 0, 0, 0.32));
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.86), rgba(0, 0, 0, 0.32));
}

.replay-bg-grid::after {
  content: '';
  position: absolute;
  top: -10%;
  bottom: -10%;
  left: -18%;
  width: 18%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
  transform: skewX(-18deg);
  mix-blend-mode: screen;
  animation: replay-grid-sweep 15s ease-in-out infinite;
}

.replay-bg-orb {
  position: absolute;
  z-index: 0;
  border-radius: 50%;
  pointer-events: none;
  filter: blur(34px);
  opacity: 0.62;
}

.replay-bg-orb-a {
  top: 8rem;
  left: -9rem;
  width: 28rem;
  height: 28rem;
  background: radial-gradient(circle, rgba(244, 63, 94, 0.16), transparent 68%);
  animation: replay-orb-drift-a 16s ease-in-out infinite alternate;
}

.replay-bg-orb-b {
  right: -10rem;
  bottom: 6rem;
  width: 32rem;
  height: 32rem;
  background: radial-gradient(circle, rgba(20, 184, 166, 0.15), transparent 68%);
  animation: replay-orb-drift-b 19s ease-in-out infinite alternate;
}

.replay-nav {
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 28px rgba(15, 23, 42, 0.05),
    inset 0 -1px 0 rgba(15, 23, 42, 0.04);
}

.replay-detail-pulse {
  box-shadow: 0 0 0 4px rgba(45, 212, 191, 0.12), 0 0 14px rgba(20, 184, 166, 0.45);
  animation: replay-pulse 2.8s ease-in-out infinite;
}

.replay-mode-badge {
  border: 1px solid rgba(196, 181, 253, 0.46);
  box-shadow: 0 0 12px rgba(139, 92, 246, 0.1);
}

.replay-pipeline {
  position: relative;
}

.replay-pipeline::before {
  content: '';
  position: absolute;
  right: 0;
  bottom: 0.1rem;
  left: 0;
  height: 1px;
  background: linear-gradient(90deg, rgba(244, 63, 94, 0.16), rgba(20, 184, 166, 0.35), rgba(139, 92, 246, 0.16));
  pointer-events: none;
}

.replay-pipeline-node {
  position: relative;
  border: 1px solid transparent;
  box-shadow: 0 1px 1px rgba(15, 23, 42, 0.02);
}

.replay-pipeline-node-active {
  overflow: hidden;
}

.replay-pipeline-node-active::after {
  content: '';
  position: absolute;
  inset: 0 auto 0 -34%;
  width: 28%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.52), transparent);
  transform: skewX(-18deg);
  animation: replay-node-sheen 2.8s ease-in-out infinite;
  pointer-events: none;
}

.replay-pipeline-node:hover {
  transform: translateY(-1px);
  border-color: rgba(148, 163, 184, 0.24);
  box-shadow: 0 5px 12px rgba(15, 23, 42, 0.06);
}

.replay-main {
  min-width: 0;
  max-width: 1240px;
}

.replay-pipeline-panel {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  padding: 0.9rem 1rem 0.75rem;
  border-radius: 1.5rem;
  border: 1px solid rgba(255, 255, 255, 0.74);
  box-shadow:
    0 2px 4px rgba(15, 23, 42, 0.035),
    0 16px 34px rgba(15, 23, 42, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

.replay-pipeline-panel::before {
  content: '';
  position: absolute;
  top: 0;
  right: 1.25rem;
  left: 1.25rem;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(244, 63, 94, 0.44), rgba(20, 184, 166, 0.48), rgba(14, 165, 233, 0.38), rgba(139, 92, 246, 0.4));
  opacity: 0.72;
  pointer-events: none;
}

.replay-pipeline-panel-head {
  position: relative;
  z-index: 1;
}

.replay-progress-strip {
  position: relative;
  z-index: 1;
}

.replay-progress-track {
  position: relative;
  height: 0.4rem;
  overflow: visible;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.76);
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.08);
}

.replay-progress-fill {
  display: block;
  width: var(--replay-progress, 0%);
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #fb7185 0%, #2dd4bf 55%, #38bdf8 100%);
  box-shadow: 0 0 13px rgba(45, 212, 191, 0.26);
  transition: width 0.55s cubic-bezier(0.22, 1, 0.36, 1);
}

.replay-progress-signal {
  position: absolute;
  top: 50%;
  left: var(--replay-position, 0%);
  width: 0.78rem;
  height: 0.78rem;
  border: 2px solid rgba(255, 255, 255, 0.94);
  border-radius: 999px;
  background: #14b8a6;
  box-shadow: 0 0 0 4px rgba(20, 184, 166, 0.14), 0 0 14px rgba(20, 184, 166, 0.52);
  transform: translate(-50%, -50%);
  animation: replay-signal-breathe 1.9s ease-in-out infinite;
  transition: left 0.55s cubic-bezier(0.22, 1, 0.36, 1);
}

.replay-pipeline-empty {
  border: 1px dashed rgba(148, 163, 184, 0.26);
  background: rgba(248, 250, 252, 0.44);
}

.replay-pipeline-panel > .replay-pipeline {
  position: relative;
  z-index: 1;
}

.replay-creation-art {
  position: relative;
  display: grid;
  grid-template-columns: minmax(13rem, 0.72fr) minmax(18rem, 1.28fr);
  min-height: 15rem;
  overflow: hidden;
  padding: 1.2rem 1.35rem;
  border-radius: 1.5rem;
  border: 1px solid rgba(255, 255, 255, 0.78);
  background:
    radial-gradient(circle at 76% 44%, rgba(45, 212, 191, 0.16), transparent 25%),
    linear-gradient(118deg, rgba(255, 255, 255, 0.74), rgba(240, 253, 250, 0.34));
  box-shadow:
    0 2px 4px rgba(15, 23, 42, 0.035),
    0 18px 38px rgba(15, 23, 42, 0.07),
    inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.replay-creation-art::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.55;
  background-image:
    linear-gradient(rgba(20, 184, 166, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(20, 184, 166, 0.045) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: linear-gradient(90deg, transparent, #000 48%, #000 84%, transparent);
}

.replay-creation-art-copy {
  position: relative;
  z-index: 2;
  align-self: center;
  padding-right: 1rem;
}

.replay-creation-art-visual {
  --orbit-radius: clamp(6.7rem, 16vw, 9.8rem);
  position: relative;
  min-height: 12.5rem;
  isolation: isolate;
}

.replay-art-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  width: calc(var(--orbit-radius) * 2);
  aspect-ratio: 1;
  border: 1px solid rgba(20, 184, 166, 0.18);
  border-radius: 50%;
  transform: translate(-50%, -50%);
}

.replay-art-ring-outer {
  border-style: dashed;
  animation: replay-art-spin 24s linear infinite;
}

.replay-art-ring-inner {
  width: calc(var(--orbit-radius) * 1.42);
  border-color: rgba(14, 165, 233, 0.2);
  box-shadow: 0 0 0 1rem rgba(20, 184, 166, 0.025), 0 0 3rem rgba(45, 212, 191, 0.08);
  animation: replay-art-spin-reverse 17s linear infinite;
}

.replay-art-core {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 3.1rem;
  height: 3.1rem;
  border: 1px solid rgba(255, 255, 255, 0.78);
  border-radius: 1.1rem;
  background: linear-gradient(145deg, #0f766e, #0ea5a4 54%, #38bdf8);
  box-shadow: 0 0 0 0.6rem rgba(20, 184, 166, 0.08), 0 0.8rem 2rem rgba(13, 148, 136, 0.24);
  transform: translate(-50%, -50%);
  z-index: 2;
}

.replay-art-core-glow {
  position: absolute;
  inset: -0.35rem;
  border-radius: 1.3rem;
  background: rgba(45, 212, 191, 0.35);
  filter: blur(0.8rem);
  animation: replay-core-breathe 2.8s ease-in-out infinite;
  z-index: -1;
}

.replay-art-signal {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0.55rem;
  height: 0.55rem;
  border: 2px solid rgba(255, 255, 255, 0.9);
  border-radius: 50%;
  background: #fb7185;
  box-shadow: 0 0 0 0.25rem rgba(251, 113, 133, 0.15), 0 0 1rem rgba(251, 113, 133, 0.46);
  transform: translate(-50%, -50%) rotate(0deg) translateX(var(--orbit-radius));
  animation: replay-art-signal-orbit 8s linear infinite;
  z-index: 3;
}

.replay-orbit-node {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  align-items: center;
  gap: 0.35rem;
  color: #64748b;
  transform: translate(-50%, -50%) rotate(var(--orbit-angle)) translateY(calc(-1 * var(--orbit-radius)));
  animation: replay-orbit-drift 4.8s var(--orbit-delay) ease-in-out infinite alternate;
}

.replay-orbit-node-dot {
  display: block;
  width: 0.62rem;
  height: 0.62rem;
  flex: 0 0 auto;
  border: 2px solid rgba(255, 255, 255, 0.9);
  border-radius: 50%;
  background: #cbd5e1;
  box-shadow: 0 0 0 0.22rem rgba(148, 163, 184, 0.12);
}

.replay-orbit-node-label {
  white-space: nowrap;
  padding: 0.28rem 0.5rem;
  border: 1px solid rgba(255, 255, 255, 0.68);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.58);
  font-size: 0.625rem;
  font-weight: 600;
  box-shadow: 0 0.3rem 0.8rem rgba(15, 23, 42, 0.05);
  transform: rotate(calc(var(--orbit-angle) * -1));
}

.replay-orbit-node-completed .replay-orbit-node-dot {
  background: #34d399;
  box-shadow: 0 0 0 0.22rem rgba(52, 211, 153, 0.13), 0 0 0.8rem rgba(52, 211, 153, 0.25);
}

.replay-orbit-node-active .replay-orbit-node-dot {
  background: #14b8a6;
  box-shadow: 0 0 0 0.3rem rgba(20, 184, 166, 0.16), 0 0 1rem rgba(20, 184, 166, 0.48);
  animation: replay-pulse 1.8s ease-in-out infinite;
}

.replay-orbit-node-active .replay-orbit-node-label {
  color: #0f766e;
  border-color: rgba(20, 184, 166, 0.35);
  background: rgba(240, 253, 250, 0.84);
}

.replay-creation-signal {
  box-shadow: 0 0 0 0.22rem rgba(45, 212, 191, 0.15), 0 0 0.7rem rgba(20, 184, 166, 0.4);
  animation: replay-pulse 1.8s ease-in-out infinite;
}

.replay-layout,
.replay-detail-column,
.replay-summary-column,
.replay-result-stack {
  min-width: 0;
}

.replay-rail-panel {
  padding: 0.85rem 0.55rem 0.85rem 0.75rem;
  border: 1px solid rgba(255, 255, 255, 0.74);
  border-radius: 1.25rem;
  background: rgba(255, 255, 255, 0.42);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 12px 28px rgba(15, 23, 42, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.75);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.replay-mobile-rail {
  min-width: 0;
  padding: 0.55rem 0.6rem 0.25rem;
  border: 1px solid rgba(255, 255, 255, 0.74);
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.42);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

.replay-mobile-chip {
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
}

.replay-detail-header {
  min-height: 3.25rem;
  padding: 0.65rem 0.8rem;
  border: 1px solid rgba(255, 255, 255, 0.78);
  border-radius: 1rem;
  background: linear-gradient(105deg, rgba(255, 255, 255, 0.78), rgba(240, 253, 250, 0.42));
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 8px 20px rgba(15, 23, 42, 0.04),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

.replay-step-badge {
  border: 1px solid rgba(226, 232, 240, 0.76);
}

.replay-result-stack :deep(.liquid-glass),
.replay-result-stack :deep(.liquid-glass-rose),
.replay-result-stack :deep(.liquid-glass-emerald),
.replay-result-stack :deep(.liquid-glass-violet),
.replay-result-stack :deep(.liquid-glass-teal) {
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.035),
    0 12px 28px rgba(15, 23, 42, 0.045),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.replay-empty-state,
.replay-no-data {
  border: 1px dashed rgba(148, 163, 184, 0.3);
  background: rgba(255, 255, 255, 0.44);
}

.replay-rail-empty {
  min-height: 7rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.replay-no-workflow-banner {
  border-style: dashed;
}

.replay-summary-card {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.72);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.035),
    0 10px 24px rgba(15, 23, 42, 0.045),
    inset 0 1px 0 rgba(255, 255, 255, 0.74);
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.replay-summary-card::before {
  content: '';
  position: absolute;
  top: 0;
  right: 1rem;
  left: 1rem;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(244, 63, 94, 0.5), rgba(20, 184, 166, 0.55), rgba(139, 92, 246, 0.45));
  opacity: 0.62;
}

.replay-summary-card:hover {
  transform: translateY(-2px);
  box-shadow:
    0 4px 8px rgba(15, 23, 42, 0.05),
    0 16px 30px rgba(15, 23, 42, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.82);
}

.replay-demo-banner {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(196, 181, 253, 0.42);
  box-shadow: 0 8px 20px rgba(139, 92, 246, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

.replay-demo-banner::after {
  content: '';
  position: absolute;
  top: -40%;
  bottom: -40%;
  left: -24%;
  width: 18%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.52), transparent);
  transform: skewX(-18deg);
  animation: replay-banner-sheen 6s ease-in-out infinite;
  pointer-events: none;
}

@keyframes replay-pulse {
  0%, 100% { opacity: 0.62; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.08); }
}

@keyframes replay-grid-sweep {
  0%, 15% { transform: translateX(0) skewX(-18deg); opacity: 0; }
  28% { opacity: 0.5; }
  72% { opacity: 0.5; }
  88%, 100% { transform: translateX(820%) skewX(-18deg); opacity: 0; }
}

@keyframes replay-orb-drift-a {
  from { transform: translate(0, 0) scale(0.96); }
  to { transform: translate(54px, 32px) scale(1.06); }
}

@keyframes replay-orb-drift-b {
  from { transform: translate(0, 0) scale(1); }
  to { transform: translate(-44px, -36px) scale(1.08); }
}

@keyframes replay-banner-sheen {
  0%, 32% { transform: translateX(0) skewX(-18deg); opacity: 0; }
  46% { opacity: 0.7; }
  66%, 100% { transform: translateX(620%) skewX(-18deg); opacity: 0; }
}

@keyframes replay-node-sheen {
  0%, 34% { transform: translateX(0) skewX(-18deg); opacity: 0; }
  48% { opacity: 0.72; }
  67%, 100% { transform: translateX(520%) skewX(-18deg); opacity: 0; }
}

@keyframes replay-signal-breathe {
  0%, 100% { box-shadow: 0 0 0 4px rgba(20, 184, 166, 0.1), 0 0 10px rgba(20, 184, 166, 0.34); }
  50% { box-shadow: 0 0 0 7px rgba(20, 184, 166, 0.16), 0 0 18px rgba(20, 184, 166, 0.58); }
}

@keyframes replay-art-spin {
  to { transform: translate(-50%, -50%) rotate(360deg); }
}

@keyframes replay-art-spin-reverse {
  to { transform: translate(-50%, -50%) rotate(-360deg); }
}

@keyframes replay-art-signal-orbit {
  to { transform: translate(-50%, -50%) rotate(360deg) translateX(var(--orbit-radius)); }
}

@keyframes replay-orbit-drift {
  from { transform: translate(-50%, -50%) rotate(var(--orbit-angle)) translateY(calc(-1 * var(--orbit-radius))); }
  to { transform: translate(-50%, -50%) rotate(var(--orbit-angle)) translateY(calc(-1 * var(--orbit-radius) - 0.18rem)); }
}

@keyframes replay-core-breathe {
  0%, 100% { opacity: 0.48; transform: scale(0.92); }
  50% { opacity: 0.88; transform: scale(1.08); }
}

@media (max-width: 767px) {
  .replay-page {
    overflow-x: clip;
  }

  .replay-main {
    padding-top: 0.9rem;
  }

  .replay-pipeline-panel {
    padding-inline: 0.7rem;
    border-radius: 1.25rem;
  }

  .replay-layout {
    gap: 0.75rem;
  }

  .replay-summary-column .sticky {
    position: static;
  }

  .replay-detail-header {
    padding-inline: 0.65rem;
  }

  .replay-summary-card:hover,
  .replay-pipeline-node:hover {
    transform: none;
  }

  .replay-creation-art {
    grid-template-columns: 1fr;
    gap: 0.4rem;
    padding: 1rem;
  }

  .replay-creation-art-copy {
    padding-right: 0;
  }

  .replay-creation-art-visual {
    min-height: 12rem;
  }

  .replay-bg-orb {
    opacity: 0.38;
    filter: blur(42px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .replay-page :deep(*) {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }

  .replay-bg-grid::after,
  .replay-bg-orb,
  .replay-detail-pulse,
  .replay-demo-banner::after,
  .replay-pipeline-node-active::after,
  .replay-progress-signal,
  .replay-art-ring-outer,
  .replay-art-ring-inner,
  .replay-art-signal,
  .replay-orbit-node,
  .replay-art-core-glow,
  .replay-orbit-node-active .replay-orbit-node-dot,
  .replay-creation-signal {
    animation: none !important;
  }
}

.replay-page :deep(.liquid-glass-inset) {
  background: rgba(248, 250, 252, 0.66);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border-color: rgba(226, 232, 240, 0.72);
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
}
</style>
