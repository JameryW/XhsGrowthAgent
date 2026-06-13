<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import WorkflowNode from '@/components/WorkflowNode.vue'
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
  formatNum,
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

// Right sidebar: final output summary
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
  <div class="min-h-screen text-slate-800 relative overflow-hidden">
    <div class="absolute top-0 right-0 w-[500px] h-[500px] pointer-events-none opacity-30" style="background: radial-gradient(circle, rgba(244,63,94,0.08) 0%, transparent 60%);" />
    <div class="absolute bottom-0 left-0 w-[400px] h-[400px] pointer-events-none opacity-20" style="background: radial-gradient(circle, rgba(20,184,166,0.08) 0%, transparent 60%);" />

    <!-- Nav -->
    <nav class="relative z-20 liquid-glass-nav border-b border-white/15">
      <div class="max-w-[1400px] mx-auto px-4 md:px-8 h-14 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <button @click="goBack" class="w-8 h-8 rounded-lg bg-slate-100 hover:bg-slate-200 flex items-center justify-center transition-colors">
            <AppIcon name="ArrowLeft" size="sm" variant="cyan" />
          </button>
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-rose-500 to-amber-400 flex items-center justify-center shadow-md shadow-rose-500/20">
            <AppIcon name="Rocket" size="sm" variant="white" />
          </div>
          <div>
            <h1 class="text-sm font-bold tracking-tight text-slate-800">{{ t('replay.title') }}</h1>
            <div class="flex items-center gap-1.5 -mt-0.5">
              <span v-if="workflowLabel" class="text-[10px] text-slate-600 font-medium truncate max-w-[120px]">{{ workflowLabel }}</span>
              <span class="text-[10px] text-slate-400 font-mono">{{ threadId.slice(-8) }}</span>
              <span v-if="workflowMode" class="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600">{{ workflowMode }}</span>
            </div>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <div v-if="effectiveState" class="hidden md:flex items-center gap-2">
            <span class="text-[10px] text-slate-400">{{ t('replay.phase') }}:</span>
            <span class="text-[10px] font-medium text-slate-600">{{ phaseLabels[effectiveState.phase] || effectiveState.phase }}</span>
            <span class="text-[10px] text-slate-400">{{ effectiveState.progress_percent }}%</span>
          </div>
          <button v-if="isAuthenticated" @click="goDashboard" class="px-4 py-1.5 rounded-lg bg-rose-500 hover:bg-rose-600 text-xs font-medium text-white transition-colors shadow-sm shadow-rose-500/20">
            {{ t('replay.goDashboard') }}
          </button>
        </div>
      </div>
    </nav>

    <main class="max-w-[1400px] mx-auto px-4 md:px-8 py-4 md:py-6 relative z-10">
      <!-- Pipeline timeline -->
      <div class="liquid-glass rounded-xl p-3 md:p-4 mb-5">
        <div class="flex items-center gap-2 mb-3">
          <AppIcon name="GitBranch" size="md" variant="cyan" />
          <span class="text-xs text-slate-500 uppercase tracking-wide font-medium">{{ t('replay.pipeline') }}</span>
        </div>

        <div class="relative py-4">
          <div class="absolute top-1/2 left-0 right-0 h-1 bg-slate-100 rounded-full" />
          <div
            v-if="effectiveState"
            class="absolute top-1/2 left-0 h-1 rounded-full transition-all duration-500 bg-gradient-to-r from-rose-400 to-teal-400"
            :style="{ width: `${effectiveState.progress_percent}%` }"
          />
        </div>

        <div class="flex justify-between items-start relative px-1 md:px-4 overflow-x-auto -mx-3 md:mx-0">
          <div v-for="phase in pipelineSteps" :key="phase" class="min-w-[48px] md:min-w-0 flex-1">
            <WorkflowNode
              :icon="phaseIcons[phase]"
              :label="phaseLabels[phase]"
              :status="getNodeStatus(phase)"
              :clickable="true"
              :selected="isNodeSelected(phase)"
              @click="handleNodeClick(phase)"
            />
          </div>
        </div>
      </div>

      <!-- Three-column layout: rail | detail | summary -->
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <!-- Left: Checkpoint rail (3 cols desktop) -->
        <div class="lg:col-span-3 hidden lg:block">
          <div class="sticky top-20">
            <CheckpointRail />
          </div>
        </div>

        <!-- Mobile: checkpoint chips -->
        <div class="lg:hidden">
          <div class="flex items-center gap-1.5 overflow-x-auto pb-2 scrollbar-thin">
            <div class="text-[10px] text-slate-400 font-medium uppercase tracking-widest shrink-0 mr-1">{{ t('replay.checkpoints') }}</div>
            <button
              v-for="cp in workflowStore.replayCheckpoints"
              :key="cp.checkpoint_id"
              @click="workflowStore.selectCheckpoint(cp.checkpoint_id)"
              class="px-2 py-1 rounded-lg text-[10px] font-medium transition-colors whitespace-nowrap shrink-0 border"
              :class="cp.checkpoint_id === activeCheckpointId
                ? 'bg-violet-50 text-violet-700 border-violet-200 shadow-sm'
                : 'bg-white text-slate-500 border-slate-200 hover:bg-slate-50'"
            >
              {{ agentLabels[cp.current_agent] || cp.current_agent }}
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

        <!-- Center: Detail panel (6 cols desktop) -->
        <div class="lg:col-span-6">
          <div v-if="selectedCheckpoint" class="rounded-xl liquid-glass overflow-hidden">
            <!-- Checkpoint header -->
            <div class="px-4 md:px-5 py-3 flex items-center gap-2 border-b border-white/10 liquid-glass-inset">
              <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-400 to-indigo-400 flex items-center justify-center shadow-sm">
                <AppIcon name="Eye" size="sm" variant="white" />
              </div>
              <span class="text-sm font-semibold text-slate-800">{{ agentLabels[selectedAgent] || selectedAgent }}</span>
              <span class="text-xs px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">{{ t('replay.step') }} {{ selectedCheckpoint.step }}</span>
              <span v-if="selectedCheckpoint.created_at" class="text-xs text-slate-400 ml-auto">{{ formatDate(selectedCheckpoint.created_at) }}</span>
            </div>

            <!-- Agent result content -->
            <div class="px-4 md:px-5 py-4 space-y-4">
              <!-- Trend scout -->
              <AgentResultTrend v-if="selectedAgent === 'trend_scout'" :cp="selectedCheckpoint" />

              <!-- Content strategist -->
              <AgentResultPlan v-if="selectedAgent === 'content_strategist'" :cp="selectedCheckpoint" />

              <!-- Creating phase agents -->
              <AgentResultCreative
                v-if="['copywriter', 'draft_gate', 'viral_matcher', 'blogger_scout', 'blogger_gate', 'choice_gate', 'content_analyzer', 'version_generator', 'brief_analyzer', 'brief_gate', 'shooting_planner'].includes(selectedAgent)"
                :cp="selectedCheckpoint"
                :shooting-plan="resolvedShootingPlan"
                :hide-draft="true"
                :show-publish="true"
              />

              <!-- Visual designer -->
              <AgentResultVisual v-if="selectedAgent === 'visual_designer'" :cp="selectedCheckpoint" />

              <!-- Review gate / revise -->
              <template v-if="['review_gate', 'revise_content'].includes(selectedAgent)">
                <AgentResultCreative :cp="selectedCheckpoint" :shooting-plan="resolvedShootingPlan" :hide-draft="true" />
                <AgentResultVisual v-if="hasMeaningfulData(selectedCheckpoint.visual_plan)" :cp="selectedCheckpoint" />
              </template>

              <!-- Publishing -->
              <AgentResultPublish v-if="['publisher', 'engagement'].includes(selectedAgent)" :cp="selectedCheckpoint" />

              <!-- Analytics -->
              <AgentResultAnalytics v-if="selectedAgent === 'analyst'" :cp="selectedCheckpoint" />

              <!-- Ripple (shown for any checkpoint that has ripple data) -->
              <AgentResultRipple
                v-if="selectedCheckpoint.ripple_prediction && Object.keys(selectedCheckpoint.ripple_prediction).length > 0 || selectedCheckpoint.ripple_pmf && Object.keys(selectedCheckpoint.ripple_pmf).length > 0 || selectedCheckpoint.ripple_comparison && Object.keys(selectedCheckpoint.ripple_comparison).length > 0"
                :cp="selectedCheckpoint"
              />

              <!-- No data -->
              <div v-if="!hasDataForAgent(selectedAgent, selectedCheckpoint)" class="text-xs text-slate-400 text-center py-4">
                {{ t('replay.noData') }}
              </div>
            </div>
          </div>

          <!-- No checkpoint selected -->
          <div v-else class="rounded-xl liquid-glass p-8 text-center">
            <div class="w-12 h-12 rounded-xl bg-violet-100 flex items-center justify-center mx-auto mb-4">
              <AppIcon name="MousePointerClick" size="lg" variant="purple" />
            </div>
            <p class="text-sm text-slate-600 font-medium">{{ t('replay.clickHint') }}</p>
            <p class="text-xs text-slate-400 mt-1.5">{{ t('replay.clickHintDesc') }}</p>
          </div>
        </div>

        <!-- Right: Summary sidebar (3 cols desktop) -->
        <div class="lg:col-span-3">
          <div class="sticky top-4 space-y-3">
            <!-- Final output summary -->
            <div v-if="finalSummary && (finalSummary.title || finalSummary.topic || finalSummary.brand)" class="rounded-xl liquid-glass p-3 space-y-2">
              <div class="text-[10px] text-slate-400 font-medium uppercase tracking-widest">{{ t('replay.outputSummary') }}</div>
              <div v-if="finalSummary.title" class="text-sm font-semibold text-rose-600 leading-snug">{{ finalSummary.title }}</div>
              <div v-if="finalSummary.topic" class="text-xs text-slate-600">{{ finalSummary.topic }}</div>
              <div v-if="finalSummary.brand" class="text-xs text-slate-500">{{ finalSummary.brand }}<span v-if="finalSummary.product"> / {{ finalSummary.product }}</span></div>
              <div v-if="finalSummary.hashtags?.length" class="flex flex-wrap gap-1">
                <span v-for="tag in finalSummary.hashtags" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
              </div>
            </div>

            <!-- Key metrics -->
            <div v-if="finalSummary && (finalSummary.views != null || finalSummary.likes != null || finalSummary.viralProb != null || finalSummary.pmfScore != null)" class="rounded-xl liquid-glass p-3 space-y-2">
              <div class="text-[10px] text-slate-400 font-medium uppercase tracking-widest">{{ t('replay.keyMetrics') }}</div>
              <div class="grid grid-cols-2 gap-1.5">
                <div v-if="finalSummary.viralProb != null" class="p-1.5 rounded liquid-glass-inset text-center">
                  <div class="text-[9px] text-slate-400">{{ t('replay.viralProb') }}</div>
                  <div class="text-xs font-bold" :class="finalSummary.viralProb >= 0.7 ? 'text-emerald-600' : finalSummary.viralProb >= 0.4 ? 'text-amber-600' : 'text-rose-600'">{{ (finalSummary.viralProb * 100).toFixed(0) }}%</div>
                </div>
                <div v-if="finalSummary.pmfScore != null" class="p-1.5 rounded liquid-glass-inset text-center">
                  <div class="text-[9px] text-slate-400">PMF</div>
                  <div class="text-xs font-bold" :class="finalSummary.pmfScore >= 0.7 ? 'text-emerald-600' : finalSummary.pmfScore >= 0.4 ? 'text-amber-600' : 'text-rose-600'">{{ (finalSummary.pmfScore * 100).toFixed(0) }}%</div>
                </div>
                <div v-if="finalSummary.views != null" class="p-1.5 rounded liquid-glass-inset text-center">
                  <div class="text-[9px] text-slate-400">{{ t('replay.views') }}</div>
                  <div class="text-xs font-bold text-slate-700">{{ formatNum(finalSummary.views) }}</div>
                </div>
                <div v-if="finalSummary.likes != null" class="p-1.5 rounded bg-pink-50 text-center">
                  <div class="text-[9px] text-slate-400">{{ t('replay.likes') }}</div>
                  <div class="text-xs font-bold text-pink-600">{{ formatNum(finalSummary.likes) }}</div>
                </div>
                <div v-if="finalSummary.engagementRate != null" class="p-1.5 rounded bg-teal-50 text-center col-span-2">
                  <div class="text-[9px] text-slate-400">{{ t('showcase.detail.engagementRate') }}</div>
                  <div class="text-xs font-bold text-teal-600">{{ (finalSummary.engagementRate * 100).toFixed(1) }}%</div>
                </div>
              </div>
            </div>

            <!-- Publish link -->
            <div v-if="finalSummary?.publishUrl" class="rounded-xl liquid-glass p-3">
              <a :href="finalSummary.publishUrl" target="_blank" rel="noopener" class="inline-flex items-center gap-1.5 text-xs text-emerald-600 hover:text-emerald-700 font-medium">
                <AppIcon name="ExternalLink" size="sm" />
                {{ t('replay.viewPost') }}
              </a>
              <div v-if="finalSummary.publishStatus" class="text-[10px] text-slate-400 mt-1">{{ finalSummary.publishStatus }}</div>
            </div>

            <!-- Replay banner (compact) -->
            <div class="rounded-xl liquid-glass-violet p-2.5">
              <div class="flex items-center gap-2">
                <div class="w-6 h-6 rounded-md bg-violet-100 flex items-center justify-center shrink-0">
                  <AppIcon name="History" size="sm" variant="purple" />
                </div>
                <div class="min-w-0">
                  <div class="text-[11px] text-violet-700 font-medium">{{ t('replay.mode') }}</div>
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
