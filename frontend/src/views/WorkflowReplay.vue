<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import CheckpointRail from '@/components/replay/CheckpointRail.vue'
import AgentResultTrend from '@/components/replay/AgentResultTrend.vue'
import AgentResultPlan from '@/components/replay/AgentResultPlan.vue'
import AgentResultCreative from '@/components/replay/AgentResultCreative.vue'
import AgentResultVisual from '@/components/replay/AgentResultVisual.vue'
import AgentResultPublish from '@/components/replay/AgentResultPublish.vue'
import AgentResultAnalytics from '@/components/replay/AgentResultAnalytics.vue'
import AgentResultRipple from '@/components/replay/AgentResultRipple.vue'
import { useWorkflowStore, useAuthStore } from '@/stores'
import { getWorkflowStatus } from '@/api/workflow'
import { useWorkflowReplay } from '@/composables/useWorkflowReplay'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const workflowStore = useWorkflowStore()
const authStore = useAuthStore()

const threadId = route.params.threadId as string
const isAuthenticated = computed(() => authStore.isAuthenticated)

const {
  activeCheckpointId,
  effectiveState,
  workflowLabel,
  workflowMode,
  pipelineSteps,
  selectedCheckpoint,
  selectedAgent,
  resolvedShootingPlan,
  getNodeStatus,
  handleNodeClick,
  isNodeSelected,
  hasDataForAgent,
  hasMeaningfulData,
  formatDate,
} = useWorkflowReplay()

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

const agentLabels: Record<string, string> = {
  trend_scout: t('showcase.phase.scouting'),
  content_strategist: t('showcase.phase.planning'),
  copywriter: t('showcase.phase.creating'),
  draft_gate: t('dashboard.timeline.short.draft'),
  brief_analyzer: t('dashboard.timeline.short.briefAnalyze'),
  brief_gate: t('dashboard.timeline.short.briefGate'),
  viral_matcher: t('dashboard.timeline.short.viralMatch'),
  blogger_scout: t('dashboard.timeline.short.bloggerScout'),
  blogger_gate: t('dashboard.timeline.short.bloggerGate'),
  shooting_planner: t('dashboard.timeline.short.shootingPlan'),
  visual_designer: t('dashboard.timeline.short.visual'),
  content_analyzer: t('dashboard.timeline.short.contentAnalysis'),
  version_generator: t('dashboard.timeline.short.versionGen'),
  choice_gate: t('dashboard.timeline.short.choiceGate'),
  review_gate: t('showcase.phase.reviewing'),
  revise_content: t('dashboard.timeline.short.reviseContent'),
  publisher: t('showcase.phase.publishing'),
  engagement: t('dashboard.timeline.short.engagement'),
  analyst: t('showcase.phase.analyzing'),
  orchestrator: t('dashboard.timeline.orchestrator'),
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

const pipelineNodes = computed(() =>
  pipelineSteps.value.map((phase) => ({
    phase,
    icon: phaseIcons.value[phase],
    label: phaseLabels.value[phase] || phase,
    status: getNodeStatus(phase),
    selected: isNodeSelected(phase),
  }))
)

const mobileCheckpointChips = computed(() =>
  workflowStore.replayCheckpoints.map((cp) => ({
    id: cp.checkpoint_id,
    label: agentLabels[cp.current_agent] || cp.current_agent,
    active: cp.checkpoint_id === activeCheckpointId.value,
  }))
)

const selectedAgentLabel = computed(() => agentLabels[selectedAgent.value] || selectedAgent.value)
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

function goBack() { router.push('/') }
function goDashboard() { router.push('/dashboard') }

onMounted(async () => {
  try {
    const state = await getWorkflowStatus(threadId)
    workflowStore.workflowStates.set(threadId, state)
    workflowStore.setThreadId(threadId)
  } catch {
    // Continue — replay works with checkpoints alone
  }
  workflowStore.enterReplayMode()
})

onUnmounted(() => {
  workflowStore.exitReplayMode()
})

// Right sidebar: final output summary — only L1 key facts
const finalSummary = computed(() => {
  const cp = selectedCheckpoint.value
  if (!cp) return null
  return {
    title: cp.copy_content?.selected_title,
    topic: cp.content_plan?.selected_topic,
    brand: (cp as any).brief_content?.brand_name,
    product: (cp as any).brief_content?.product_name,
    hashtags: cp.copy_content?.hashtags,
    publishUrl: (cp.publish_result as any)?.post_url,
    publishStatus: (cp.publish_result as any)?.status,
    views: (cp.analytics as any)?.views,
    likes: (cp.analytics as any)?.likes,
    engagementRate: (cp.analytics as any)?.engagement_rate,
    viralProb: cp.ripple_prediction?.viral_probability,
    pmfScore: cp.ripple_pmf?.pmf_score,
  }
})
</script>

<template>
  <div class="replay-page min-h-screen text-slate-800 relative overflow-hidden">
    <!-- Nav — includes inline pipeline -->
    <nav class="relative z-20 liquid-glass-nav border-b border-white/15">
      <div class="max-w-[1400px] mx-auto px-4 md:px-8">
        <!-- Top row: back + title + actions -->
        <div class="h-12 flex items-center justify-between">
          <div class="flex items-center gap-2.5">
            <button @click="goBack" class="w-7 h-7 rounded-lg bg-slate-100 hover:bg-slate-200 flex items-center justify-center transition-colors">
              <AppIcon name="ArrowLeft" size="sm" variant="cyan" />
            </button>
            <div class="w-7 h-7 rounded-lg bg-gradient-to-br from-rose-500 to-amber-400 flex items-center justify-center shadow-sm shadow-rose-500/20">
              <AppIcon name="Rocket" size="sm" variant="white" />
            </div>
            <div>
              <h1 class="text-sm font-bold tracking-tight text-slate-800">{{ t('replay.title') }}</h1>
              <div class="flex items-center gap-1.5 -mt-0.5">
                <span v-if="workflowLabel" class="text-[10px] text-slate-500 font-medium truncate max-w-[100px]">{{ workflowLabel }}</span>
                <span class="text-[10px] text-slate-400 font-mono">{{ threadId.slice(-8) }}</span>
                <span v-if="workflowMode" class="text-[10px] px-1 py-0 rounded bg-violet-50 text-violet-600">{{ workflowMode }}</span>
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <div v-if="effectiveState" class="hidden md:flex items-center gap-1.5">
              <span class="text-[10px] text-slate-400">{{ t('replay.phase') }}:</span>
              <span class="text-[10px] font-medium text-slate-600">{{ phaseLabels[effectiveState.phase] || effectiveState.phase }}</span>
              <span class="text-[10px] text-slate-400">{{ effectiveState.progress_percent }}%</span>
            </div>
            <button v-if="isAuthenticated" @click="goDashboard" class="px-3 py-1 rounded-lg bg-rose-500 hover:bg-rose-600 text-[11px] font-medium text-white transition-colors shadow-sm shadow-rose-500/20">
              {{ t('replay.goDashboard') }}
            </button>
          </div>
        </div>

        <!-- Pipeline timeline (inline in nav) -->
        <div class="h-10 flex items-center gap-1 overflow-x-auto scrollbar-thin -mx-2 px-2">
          <div
            v-for="node in pipelineNodes"
            :key="node.phase"
            v-memo="[node.status, node.selected, node.label]"
            class="shrink-0"
          >
            <button
              @click="handleNodeClick(node.phase)"
              class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-colors"
              :class="node.selected
                ? 'bg-slate-800 text-white'
                : node.status === 'completed'
                  ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                  : node.status === 'running'
                    ? 'bg-amber-50 text-amber-700'
                    : node.status === 'error'
                      ? 'bg-red-50 text-red-700'
                      : 'bg-slate-50 text-slate-500 hover:bg-slate-100'"
            >
              <AppIcon :name="node.icon" size="xs" :variant="node.selected ? 'white' : 'cyan'" />
              {{ node.label }}
            </button>
          </div>
        </div>
      </div>
    </nav>

    <main class="max-w-[1400px] mx-auto px-4 md:px-8 py-4 md:py-5 relative z-10">
      <!-- Two-column layout: rail | detail + summary -->
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <!-- Left: Checkpoint rail (2 cols desktop) -->
        <div class="lg:col-span-2 hidden lg:block">
          <div class="sticky top-20 max-h-[calc(100vh-8rem)] overflow-y-auto pr-1">
            <CheckpointRail />
          </div>
        </div>

        <!-- Mobile: checkpoint chips -->
        <div class="lg:hidden">
          <div class="flex items-center gap-1.5 overflow-x-auto pb-2 scrollbar-thin">
            <div class="text-[10px] text-slate-400 font-medium uppercase tracking-widest shrink-0 mr-1">{{ t('replay.checkpoints') }}</div>
            <button
              v-for="chip in mobileCheckpointChips"
              :key="chip.id"
              v-memo="[chip.active, chip.label]"
              @click="workflowStore.selectCheckpoint(chip.id)"
              class="px-2 py-1 rounded-lg text-[10px] font-medium transition-colors whitespace-nowrap shrink-0 border"
              :class="chip.active
                ? 'bg-slate-800 text-white border-slate-800'
                : 'bg-white text-slate-500 border-slate-200 hover:bg-slate-50'"
            >
              {{ chip.label }}
            </button>
            <button
              v-if="workflowStore.hasMoreCheckpoints"
              @click="workflowStore.loadMoreCheckpoints()"
              class="px-2 py-1 rounded-lg text-[10px] text-slate-400 border border-slate-200 hover:bg-slate-50 shrink-0"
            >
              +{{ t('replay.loadMore') }}
            </button>
          </div>
        </div>

        <!-- Center: Detail panel (7 cols desktop) -->
        <div class="lg:col-span-7">
          <div v-if="selectedCheckpoint" class="space-y-0">
            <!-- Checkpoint header — compact -->
            <div class="flex items-center gap-2 mb-3">
              <div class="text-sm font-semibold text-slate-800">{{ selectedAgentLabel }}</div>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">Step {{ selectedCheckpoint.step }}</span>
              <span v-if="selectedCheckpoint.created_at" class="text-[10px] text-slate-400 ml-auto">{{ formatDate(selectedCheckpoint.created_at) }}</span>
            </div>

            <!-- Agent result content -->
            <div class="space-y-3">
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
              <div v-if="!hasSelectedAgentData" class="text-xs text-slate-400 text-center py-6">
                {{ t('replay.noData') }}
              </div>
            </div>
          </div>

          <!-- No checkpoint selected -->
          <div v-else class="rounded-xl liquid-glass p-8 text-center">
            <div class="w-12 h-12 rounded-xl bg-slate-100 flex items-center justify-center mx-auto mb-4">
              <AppIcon name="MousePointerClick" size="lg" variant="cyan" />
            </div>
            <p class="text-sm text-slate-600 font-medium">{{ t('replay.clickHint') }}</p>
            <p class="text-xs text-slate-400 mt-1.5">{{ t('replay.clickHintDesc') }}</p>
          </div>
        </div>

        <!-- Right: Summary sidebar (3 cols desktop) -->
        <div class="lg:col-span-3">
          <div class="sticky top-4 space-y-3">
            <!-- Final output — only L1 key facts -->
            <div v-if="finalSummary && (finalSummary.title || finalSummary.topic || finalSummary.brand)" class="rounded-xl liquid-glass p-3 space-y-1.5">
              <div class="text-[10px] text-slate-400 font-medium uppercase tracking-widest">{{ t('replay.outputSummary') }}</div>
              <div v-if="finalSummary.title" class="text-base font-bold text-slate-800 leading-snug">{{ finalSummary.title }}</div>
              <div v-if="finalSummary.topic" class="text-xs text-slate-600">{{ finalSummary.topic }}</div>
              <div v-if="finalSummary.brand" class="text-xs text-slate-500">{{ finalSummary.brand }}<span v-if="finalSummary.product"> / {{ finalSummary.product }}</span></div>
              <div v-if="finalSummary.hashtags?.length" class="flex flex-wrap gap-1">
                <span v-for="tag in finalSummary.hashtags" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
              </div>
            </div>

            <!-- Key metrics — only if not already in analytics panel -->
            <div v-if="finalSummary && (finalSummary.viralProb != null || finalSummary.pmfScore != null)" class="rounded-xl liquid-glass p-3 space-y-2">
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
            <div v-if="finalSummary?.publishUrl" class="rounded-xl liquid-glass p-3">
              <a :href="finalSummary.publishUrl" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 text-xs text-emerald-600 hover:text-emerald-700 font-medium">
                <AppIcon name="ExternalLink" size="sm" />
                {{ t('replay.viewPost') }}
              </a>
            </div>

            <!-- Replay banner (compact) -->
            <div class="rounded-xl liquid-glass-violet p-2.5">
              <div class="flex items-center gap-2">
                <div class="w-5 h-5 rounded bg-violet-100 flex items-center justify-center shrink-0">
                  <AppIcon name="History" size="xs" variant="purple" />
                </div>
                <div class="min-w-0">
                  <div class="text-[10px] text-violet-700 font-medium">{{ t('replay.mode') }}</div>
                  <p class="text-[10px] text-violet-500 line-clamp-1">{{ t('replay.modeDesc') }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.replay-page {
  background:
    linear-gradient(135deg, rgba(255, 241, 242, 0.48), transparent 32%),
    linear-gradient(225deg, rgba(240, 253, 250, 0.5), transparent 36%),
    linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
}

.replay-page :deep(.liquid-glass-inset) {
  background: rgba(248, 250, 252, 0.66);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border-color: rgba(226, 232, 240, 0.72);
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
}
</style>
