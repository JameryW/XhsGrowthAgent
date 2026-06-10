<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import WorkflowNode from '@/components/WorkflowNode.vue'
import { useWorkflowStore, useAuthStore } from '@/stores'
import { getWorkflowStatus } from '@/api/workflow'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const workflowStore = useWorkflowStore()
const authStore = useAuthStore()

const threadId = route.params.threadId as string
const activeCheckpointId = computed(() => workflowStore.activeCheckpointId)
const replayCheckpoints = computed(() => workflowStore.replayCheckpoints)
const effectiveState = computed(() => workflowStore.effectiveState)
const isAuthenticated = computed(() => authStore.isAuthenticated)

const pipelineSteps = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'analyzing'] as const

const phaseLabels: Record<string, string> = {
  scouting: t('showcase.phase.scouting'),
  planning: t('showcase.phase.planning'),
  creating: t('showcase.phase.creating'),
  reviewing: t('showcase.phase.reviewing'),
  publishing: t('showcase.phase.publishing'),
  analyzing: t('showcase.phase.analyzing'),
}

const agentLabels: Record<string, string> = {
  trend_scout: t('showcase.phase.scouting'),
  content_strategist: t('showcase.phase.planning'),
  copywriter: t('showcase.phase.creating'),
  draft_gate: 'Draft Gate',
  viral_matcher: 'Viral Match',
  blogger_scout: 'Blogger Scout',
  blogger_gate: 'Blogger Gate',
  visual_designer: 'Visual Design',
  content_analyzer: 'Content Analyzer',
  version_generator: 'Version Gen',
  choice_gate: 'Choice Gate',
  review_gate: t('showcase.phase.reviewing'),
  revise_content: 'Revise',
  publisher: t('showcase.phase.publishing'),
  engagement: 'Engagement',
  analyst: t('showcase.phase.analyzing'),
  orchestrator: 'Orchestrator',
  brief_parser: t('showcase.phase.briefing'),
}

const phaseIcons: Record<string, string> = {
  scouting: 'Search',
  planning: 'ClipboardList',
  creating: 'Pencil',
  reviewing: 'Clock',
  publishing: 'Upload',
  analyzing: 'BarChart3',
}

type NodeStatus = 'completed' | 'running' | 'pending' | 'error'

const phaseAlias: Record<string, string> = {
  briefing: 'scouting',
  engaging: 'publishing',
}

function phaseToIndex(phase: string): number {
  const mapped = phaseAlias[phase] || phase
  const idx = pipelineSteps.indexOf(mapped as any)
  return idx
}

function getNodeStatus(phase: string): NodeStatus {
  // In replay mode, determine status based on the selected checkpoint's position
  const cp = selectedCheckpoint.value
  if (cp) {
    const cpPhase = cp.phase

    // Workflow fully completed → all nodes completed
    if (cpPhase === 'completed') return 'completed'

    const idx = phaseToIndex(phase)
    const cpIdx = phaseToIndex(cpPhase)

    if (idx < 0 || cpIdx < 0) return 'pending'

    // Error: mark the error phase, prior completed
    if (cpPhase === 'error') {
      if (idx < cpIdx) return 'completed'
      if (idx === cpIdx) return 'error'
      return 'pending'
    }

    // Normal: prior phases completed, current running, later pending
    if (idx < cpIdx) return 'completed'
    if (idx === cpIdx) return 'running'
    return 'pending'
  }

  // Fallback: no checkpoint selected, use effectiveState
  if (!effectiveState.value) return 'pending'
  const currentPhase = effectiveState.value.phase
  const currentStatus = effectiveState.value.status

  if (currentPhase === 'completed' || currentStatus === 'completed') return 'completed'

  const idx = phaseToIndex(phase)
  const currentIdx = phaseToIndex(currentPhase)
  if (idx < 0 || currentIdx < 0) return 'pending'
  if (idx < currentIdx) return 'completed'
  if (idx === currentIdx) return 'running'
  return 'pending'
}

function findCheckpointForAgent(agent: string): string | null {
  const cp = replayCheckpoints.value.find(c => c.current_agent === agent)
  return cp ? cp.checkpoint_id : null
}

// Map phase to primary agent for checkpoint lookup
const phaseAgentMap: Record<string, string> = {
  scouting: 'trend_scout',
  briefing: 'brief_parser',
  planning: 'content_strategist',
  creating: 'version_generator',
  reviewing: 'review_gate',
  publishing: 'publisher',
  analyzing: 'analyst',
}

function handleNodeClick(phase: string) {
  const agent = phaseAgentMap[phase] || phase
  let cpId = findCheckpointForAgent(agent)
  // Fallback: if primary agent checkpoint not found, try other agents in this phase
  if (!cpId) {
    const phaseAgents: Record<string, string[]> = {
      creating: ['copywriter', 'draft_gate', 'viral_matcher', 'blogger_scout', 'blogger_gate', 'choice_gate', 'content_analyzer', 'version_generator'],
      reviewing: ['review_gate', 'revise_content'],
      publishing: ['publisher', 'engagement'],
    }
    for (const fallback of phaseAgents[phase] || []) {
      cpId = findCheckpointForAgent(fallback)
      if (cpId) break
    }
  }
  if (cpId) {
    workflowStore.selectCheckpoint(cpId)
  }
}

function isNodeSelected(phase: string): boolean {
  if (!activeCheckpointId.value) return false
  const agent = phaseAgentMap[phase] || phase
  const cpId = findCheckpointForAgent(agent)
  return cpId === activeCheckpointId.value
}

const selectedCheckpoint = computed<CheckpointSnapshot | null>(() => {
  if (!activeCheckpointId.value) return null
  return replayCheckpoints.value.find(c => c.checkpoint_id === activeCheckpointId.value) || null
})

const selectedAgent = computed(() => selectedCheckpoint.value?.current_agent || '')

function formatDate(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function hasDataForAgent(agent: string, cp: CheckpointSnapshot): boolean {
  const has = (v: unknown) => !!v && typeof v === 'object' && Object.keys(v as Record<string, unknown>).length > 0
  if (agent === 'trend_scout') return has(cp.trend_data)
  if (agent === 'content_strategist') return has(cp.content_plan)
  if (['copywriter', 'draft_gate', 'viral_matcher', 'blogger_scout', 'blogger_gate', 'choice_gate', 'content_analyzer', 'version_generator'].includes(agent)) return has(cp.copy_content) || has(cp.visual_plan)
  if (agent === 'visual_designer') return has(cp.copy_content) || has(cp.visual_plan)
  if (['review_gate', 'revise_content'].includes(agent)) return has(cp.copy_content)
  if (['publisher', 'engagement'].includes(agent)) return has(cp.publish_result)
  if (agent === 'analyst') return has(cp.analytics)
  return false
}

function formatNum(n?: number): string {
  if (n === undefined || n === null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
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
</script>

<template>
  <div class="min-h-screen bg-gradient-to-b from-slate-50 to-white text-slate-800 relative overflow-hidden">
    <div class="absolute top-0 right-0 w-[500px] h-[500px] pointer-events-none opacity-30" style="background: radial-gradient(circle, rgba(244,63,94,0.08) 0%, transparent 60%);" />
    <div class="absolute bottom-0 left-0 w-[400px] h-[400px] pointer-events-none opacity-20" style="background: radial-gradient(circle, rgba(20,184,166,0.08) 0%, transparent 60%);" />

    <!-- Nav -->
    <nav class="relative z-20 bg-white/70 backdrop-blur-lg border-b border-slate-200/60">
      <div class="max-w-6xl mx-auto px-4 md:px-8 h-14 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <button @click="goBack" class="w-8 h-8 rounded-lg bg-slate-100 hover:bg-slate-200 flex items-center justify-center transition-colors">
            <AppIcon name="ArrowLeft" size="sm" variant="cyan" />
          </button>
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-rose-500 to-amber-400 flex items-center justify-center shadow-md shadow-rose-500/20">
            <AppIcon name="Rocket" size="sm" variant="white" />
          </div>
          <div>
            <h1 class="text-sm font-bold tracking-tight text-slate-800">{{ t('replay.title') }}</h1>
            <p class="text-[10px] text-slate-400 -mt-0.5 font-mono">{{ threadId.slice(0, 8) }}</p>
          </div>
        </div>
        <button v-if="isAuthenticated" @click="goDashboard" class="px-4 py-1.5 rounded-lg bg-rose-500 hover:bg-rose-600 text-xs font-medium text-white transition-colors shadow-sm shadow-rose-500/20">
          {{ t('replay.goDashboard') }}
        </button>
      </div>
    </nav>

    <main class="max-w-6xl mx-auto px-4 md:px-8 py-6 md:py-8 relative z-10">
      <!-- Replay banner -->
      <div class="rounded-xl p-3 md:p-4 bg-gradient-to-r from-violet-50 to-indigo-50 border border-violet-200/50 mb-5">
        <div class="flex items-center gap-2 md:gap-3">
          <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-violet-100 flex items-center justify-center flex-shrink-0">
            <AppIcon name="History" size="md" variant="purple" />
          </div>
          <div class="min-w-0">
            <div class="text-violet-700 font-semibold text-sm">{{ t('replay.mode') }}</div>
            <p class="text-violet-500 text-xs">{{ t('replay.modeDesc') }}</p>
          </div>
        </div>
      </div>

      <!-- Pipeline timeline -->
      <div class="bg-white/98 backdrop-blur-sm rounded-xl p-3 md:p-6 border border-slate-200/50 shadow-sm mb-5">
        <div class="flex items-center gap-2 mb-3 md:mb-5">
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

        <div class="flex justify-between items-start relative px-1 md:px-4">
          <div v-for="phase in pipelineSteps" :key="phase" class="min-w-[60px] md:min-w-0 flex-1">
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

      <!-- Node state panel -->
      <div v-if="selectedCheckpoint" class="rounded-xl bg-white border border-slate-200/50 shadow-sm overflow-hidden">
        <div class="px-4 md:px-5 py-3 flex items-center gap-2 border-b border-slate-100 bg-slate-50/40">
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-400 to-indigo-400 flex items-center justify-center shadow-sm">
            <AppIcon name="Eye" size="sm" variant="white" />
          </div>
          <span class="text-sm font-semibold text-slate-800">{{ agentLabels[selectedAgent] || selectedAgent }}</span>
          <span class="text-xs px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">Step {{ selectedCheckpoint.step }}</span>
          <span v-if="selectedCheckpoint.created_at" class="text-xs text-slate-400 ml-auto">{{ formatDate(selectedCheckpoint.created_at) }}</span>
        </div>

        <div class="px-4 md:px-5 py-4 space-y-4">
          <!-- ═══ SCOUTING ═══ -->
          <template v-if="selectedAgent === 'trend_scout' && selectedCheckpoint.trend_data">
            <div v-if="selectedCheckpoint.trend_data.hot_topics?.length">
              <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('showcase.detail.hotTopics') }}</div>
              <div class="space-y-1.5">
                <div v-for="ht in selectedCheckpoint.trend_data.hot_topics" :key="ht.topic" class="flex items-center justify-between p-2 rounded-lg bg-slate-50 border border-slate-100">
                  <span class="text-xs font-medium text-slate-700">{{ ht.topic }}</span>
                  <div class="flex items-center gap-2">
                    <span class="text-[11px] px-1.5 py-0.5 rounded" :class="ht.heat_score >= 80 ? 'bg-rose-50 text-rose-600' : ht.heat_score >= 60 ? 'bg-amber-50 text-amber-600' : 'bg-slate-100 text-slate-500'">{{ ht.heat_score }}</span>
                    <span v-if="ht.growth_rate != null" class="text-[11px]" :class="ht.growth_rate > 0 ? 'text-emerald-500' : 'text-rose-500'">{{ ht.growth_rate > 0 ? '+' : '' }}{{ (ht.growth_rate * 100).toFixed(0) }}%</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="selectedCheckpoint.trend_data.trending_keywords?.length">
              <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.trendingKeywords') }}</div>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="kw in selectedCheckpoint.trend_data.trending_keywords" :key="kw" class="text-[11px] px-2 py-0.5 rounded-md bg-pink-50 text-pink-600 border border-pink-100">{{ kw }}</span>
              </div>
            </div>
            <div v-if="selectedCheckpoint.trend_data.competitor_posts?.length">
              <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('showcase.detail.topCompetitor') }}</div>
              <div class="space-y-1.5">
                <div v-for="post in selectedCheckpoint.trend_data.competitor_posts" :key="post.title" class="p-2.5 rounded-lg bg-slate-50 border border-slate-100">
                  <div class="text-xs text-slate-700 font-medium">{{ post.title }}</div>
                  <div class="text-[11px] text-slate-400 mt-0.5 flex gap-3">
                    <span>{{ (post.likes / 1000).toFixed(1) }}k likes</span>
                    <span>{{ post.comments }} comments</span>
                    <span>{{ post.author }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="selectedCheckpoint.trend_data.niche_opportunities?.length">
              <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.nicheOpportunities') }}</div>
              <div class="space-y-1.5">
                <div v-for="opp in selectedCheckpoint.trend_data.niche_opportunities" :key="opp.topic" class="flex items-center justify-between p-2 rounded-lg bg-violet-50 border border-violet-100">
                  <span class="text-xs text-slate-700">{{ opp.topic }}</span>
                  <div class="flex items-center gap-2 text-[11px]">
                    <span class="text-violet-600 font-medium">{{ t('replay.potential') }} {{ opp.potential_score }}</span>
                    <span class="text-slate-400">{{ opp.entry_barrier }}</span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- ═══ PLANNING ═══ -->
          <template v-if="selectedAgent === 'content_strategist' && selectedCheckpoint.content_plan">
            <div>
              <div class="text-base font-bold text-slate-800 leading-snug">{{ selectedCheckpoint.content_plan.selected_topic }}</div>
              <div class="text-xs text-slate-500 mt-1">{{ selectedCheckpoint.content_plan.content_angle }}</div>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
              <div v-if="selectedCheckpoint.content_plan.content_type" class="p-2 rounded-lg bg-teal-50 border border-teal-100">
                <div class="text-[10px] text-teal-500 font-medium">{{ t('replay.contentType') }}</div>
                <div class="text-xs text-teal-700 font-medium">{{ selectedCheckpoint.content_plan.content_type }}</div>
              </div>
              <div v-if="selectedCheckpoint.content_plan.target_audience" class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.targetAudience') }}</div>
                <div class="text-xs text-slate-700">{{ selectedCheckpoint.content_plan.target_audience }}</div>
              </div>
              <div v-if="selectedCheckpoint.content_plan.urgency" class="p-2 rounded-lg bg-rose-50 border border-rose-100">
                <div class="text-[10px] text-rose-500 font-medium">{{ t('replay.urgency') }}</div>
                <div class="text-xs text-rose-700 font-medium">{{ selectedCheckpoint.content_plan.urgency }}</div>
              </div>
              <div v-if="selectedCheckpoint.content_plan.suggested_timing" class="p-2 rounded-lg bg-amber-50 border border-amber-100">
                <div class="text-[10px] text-amber-500 font-medium">{{ t('replay.suggestedTiming') }}</div>
                <div class="text-xs text-amber-700">{{ selectedCheckpoint.content_plan.suggested_timing }}</div>
              </div>
            </div>
            <div v-if="selectedCheckpoint.content_plan.key_points?.length">
              <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.keyPoints') }}</div>
              <div class="space-y-1">
                <div v-for="(point, i) in selectedCheckpoint.content_plan.key_points" :key="i" class="text-xs text-slate-600 flex gap-1.5">
                  <span class="text-cyan-400">▸</span>
                  <span>{{ point }}</span>
                </div>
              </div>
            </div>
            <div v-if="selectedCheckpoint.content_plan.hashtags?.length" class="flex flex-wrap gap-1.5">
              <span v-for="tag in selectedCheckpoint.content_plan.hashtags" :key="tag" class="text-[11px] px-2 py-0.5 rounded-md bg-cyan-50 text-cyan-600 border border-cyan-100">#{{ tag }}</span>
            </div>
          </template>

          <!-- ═══ CREATING (copywriter + sub-agents) ═══ -->
          <template v-if="['copywriter', 'draft_gate', 'viral_matcher', 'blogger_scout', 'blogger_gate', 'choice_gate', 'content_analyzer', 'version_generator'].includes(selectedAgent) && selectedCheckpoint.copy_content">
            <div v-if="selectedCheckpoint.copy_content.selected_title" class="text-sm font-semibold text-rose-600 leading-snug">{{ selectedCheckpoint.copy_content.selected_title }}</div>
            <div v-if="selectedCheckpoint.copy_content.title_candidates?.length && selectedCheckpoint.copy_content.title_candidates.length > 1">
              <div class="text-xs text-slate-400 font-medium mb-1">{{ t('replay.titleCandidates') }}</div>
              <div class="space-y-0.5">
                <div v-for="(title, i) in selectedCheckpoint.copy_content.title_candidates" :key="i" class="text-xs" :class="title === selectedCheckpoint.copy_content.selected_title ? 'text-violet-600 font-semibold' : 'text-slate-500'">
                  {{ i + 1 }}. {{ title }}
                </div>
              </div>
            </div>
            <div v-if="selectedCheckpoint.copy_content.body_text" class="p-3 rounded-lg bg-slate-50 border border-slate-100">
              <p class="text-xs text-slate-600 whitespace-pre-line">{{ selectedCheckpoint.copy_content.body_text }}</p>
            </div>
            <div v-if="selectedCheckpoint.copy_content.hashtags?.length" class="flex flex-wrap gap-1.5">
              <span v-for="tag in selectedCheckpoint.copy_content.hashtags" :key="tag" class="text-[11px] px-2 py-0.5 rounded-md bg-teal-50 text-teal-600 border border-teal-100">#{{ tag }}</span>
            </div>
            <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
              <div v-if="selectedCheckpoint.copy_content.cta" class="p-2 rounded-lg bg-rose-50 border border-rose-100">
                <div class="text-[10px] text-rose-500 font-medium">CTA</div>
                <div class="text-xs text-rose-700">{{ selectedCheckpoint.copy_content.cta }}</div>
              </div>
              <div v-if="selectedCheckpoint.copy_content.tone" class="p-2 rounded-lg bg-violet-50 border border-violet-100">
                <div class="text-[10px] text-violet-500 font-medium">{{ t('replay.tone') }}</div>
                <div class="text-xs text-violet-700">{{ selectedCheckpoint.copy_content.tone }}</div>
              </div>
              <div v-if="selectedCheckpoint.copy_content.emoji_usage?.length" class="p-2 rounded-lg bg-amber-50 border border-amber-100">
                <div class="text-[10px] text-amber-500 font-medium">{{ t('replay.emoji') }}</div>
                <div class="text-xs text-amber-700">{{ selectedCheckpoint.copy_content.emoji_usage.join(' ') }}</div>
              </div>
            </div>

            <!-- Draft content (user-submitted draft) -->
            <div v-if="selectedCheckpoint.draft_content?.text" class="p-3 rounded-lg bg-blue-50 border border-blue-100">
              <div class="text-[10px] text-blue-500 font-medium mb-1">{{ t('replay.draftContent') }}</div>
              <div v-if="selectedCheckpoint.draft_content.title" class="text-xs font-semibold text-blue-700 mb-0.5">{{ selectedCheckpoint.draft_content.title }}</div>
              <div v-if="selectedCheckpoint.draft_content.text" class="text-xs text-blue-600 whitespace-pre-line line-clamp-6">{{ selectedCheckpoint.draft_content.text }}</div>
              <div v-if="selectedCheckpoint.draft_content.hashtags?.length" class="flex flex-wrap gap-1 mt-1">
                <span v-for="tag in selectedCheckpoint.draft_content.hashtags" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-600">#{{ tag }}</span>
              </div>
            </div>

            <!-- Optimization analysis -->
            <div v-if="selectedCheckpoint.optimization_analysis && (selectedCheckpoint.optimization_analysis.gaps?.length || selectedCheckpoint.optimization_analysis.suggestions?.length || selectedCheckpoint.optimization_analysis.viral_patterns?.length)" class="p-3 rounded-lg bg-violet-50 border border-violet-100">
              <div class="text-[10px] text-violet-500 font-medium mb-1.5">{{ t('replay.optimizationAnalysis') }}</div>
              <div v-if="selectedCheckpoint.optimization_analysis.gaps?.length" class="mb-2">
                <div class="text-[10px] text-violet-400 mb-0.5">{{ t('replay.gapAnalysis') }}</div>
                <div class="space-y-1">
                  <div v-for="(gap, i) in selectedCheckpoint.optimization_analysis.gaps" :key="i" class="text-xs flex gap-1.5">
                    <span class="shrink-0 px-1 rounded text-[10px] font-medium" :class="gap.severity === 'high' ? 'bg-red-100 text-red-600' : gap.severity === 'medium' ? 'bg-amber-100 text-amber-600' : 'bg-green-100 text-green-600'">{{ gap.severity }}</span>
                    <div>
                      <div class="text-slate-700 font-medium">{{ gap.dimension }}</div>
                      <div class="text-slate-500">{{ gap.description }}</div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="selectedCheckpoint.optimization_analysis.suggestions?.length" class="mb-2">
                <div class="text-[10px] text-violet-400 mb-0.5">{{ t('replay.suggestions') }}</div>
                <div class="space-y-1">
                  <div v-for="(sug, i) in selectedCheckpoint.optimization_analysis.suggestions" :key="i" class="text-xs flex gap-1.5">
                    <span class="shrink-0 text-violet-400">P{{ sug.priority }}</span>
                    <div>
                      <div class="text-slate-700">{{ sug.action }}</div>
                      <div class="text-slate-500 text-[11px]">{{ sug.reasoning }}</div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-if="selectedCheckpoint.optimization_analysis.viral_patterns?.length">
                <div class="text-[10px] text-violet-400 mb-0.5">{{ t('replay.viralPatterns') }}</div>
                <div class="flex flex-wrap gap-1">
                  <span v-for="p in selectedCheckpoint.optimization_analysis.viral_patterns" :key="p" class="text-[11px] px-1.5 py-0.5 rounded-md bg-violet-100 text-violet-600">{{ p }}</span>
                </div>
              </div>
            </div>

            <!-- Content versions (A/B/C) -->
            <div v-if="selectedCheckpoint.content_versions?.length">
              <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.contentVersions') }} ({{ selectedCheckpoint.content_versions.length }})</div>
              <div class="space-y-2">
                <div v-for="(ver, i) in selectedCheckpoint.content_versions" :key="ver.version_id || i" class="p-2.5 rounded-lg border" :class="ver.version_type === 'A' ? 'bg-rose-50 border-rose-100' : ver.version_type === 'B' ? 'bg-blue-50 border-blue-100' : 'bg-emerald-50 border-emerald-100'">
                  <div class="flex items-center justify-between mb-1">
                    <div class="flex items-center gap-1.5">
                      <span class="text-[10px] font-bold px-1.5 py-0.5 rounded" :class="ver.version_type === 'A' ? 'bg-rose-200 text-rose-700' : ver.version_type === 'B' ? 'bg-blue-200 text-blue-700' : 'bg-emerald-200 text-emerald-700'">{{ t('review.versionLabel', { n: ver.version_type || (i + 1) }) }}</span>
                      <span class="text-xs font-semibold" :class="ver.version_type === 'A' ? 'text-rose-700' : ver.version_type === 'B' ? 'text-blue-700' : 'text-emerald-700'">{{ ver.title }}</span>
                    </div>
                    <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">{{ ver.predicted_score }}{{ t('versionCompare.scoreUnit') }}</span>
                  </div>
                  <div v-if="ver.body" class="text-xs text-slate-600 whitespace-pre-line line-clamp-4 mb-1">{{ ver.body }}</div>
                  <div v-if="ver.changes_summary" class="text-[11px] text-slate-400 mb-1">↻ {{ ver.changes_summary }}</div>
                  <div class="flex flex-wrap gap-1">
                    <span v-for="tag in ver.hashtags" :key="tag" class="text-[10px] px-1 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
                    <span v-if="ver.style_suggestion" class="text-[10px] px-1 py-0.5 rounded bg-violet-50 text-violet-600">{{ ver.style_suggestion }}</span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- ═══ VISUAL DESIGNER ═══ -->
          <template v-if="selectedAgent === 'visual_designer'">
            <template v-if="selectedCheckpoint.copy_content">
              <div v-if="selectedCheckpoint.copy_content.selected_title" class="text-sm font-semibold text-rose-600 leading-snug">{{ selectedCheckpoint.copy_content!.selected_title }}</div>
              <div v-if="selectedCheckpoint.copy_content.body_text" class="p-3 rounded-lg bg-slate-50 border border-slate-100">
                <p class="text-xs text-slate-600 whitespace-pre-line">{{ selectedCheckpoint.copy_content!.body_text }}</p>
              </div>
            </template>
            <div v-if="selectedCheckpoint.visual_plan">
              <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('showcase.detail.visual') }}</div>
              <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
                <div class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                  <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.layout') }}</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.visual_plan.layout_style }}</div>
                </div>
                <div class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                  <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.imageCount') }}</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.visual_plan.image_count }}</div>
                </div>
                <div v-if="selectedCheckpoint.visual_plan.font_suggestion" class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                  <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.font') }}</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.visual_plan.font_suggestion }}</div>
                </div>
              </div>
              <div v-if="selectedCheckpoint.visual_plan.color_palette?.length" class="mt-2">
                <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.colorPalette') }}</div>
                <div class="flex gap-1.5">
                  <div v-for="color in selectedCheckpoint.visual_plan.color_palette" :key="color" class="w-6 h-6 rounded-full border-2 border-white shadow-sm" :style="{ backgroundColor: color }" :title="color" />
                </div>
              </div>
              <div v-if="selectedCheckpoint.visual_plan.cover_prompt" class="mt-2 p-2.5 rounded-lg bg-slate-50 border border-slate-100">
                <div class="text-[10px] text-slate-400 font-medium mb-0.5">{{ t('replay.coverPrompt') }}</div>
                <div class="text-xs text-slate-600">{{ selectedCheckpoint.visual_plan.cover_prompt }}</div>
              </div>
              <div v-if="selectedCheckpoint.visual_plan.image_prompts?.length" class="mt-2">
                <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.imagePrompts') }}</div>
                <div class="space-y-1">
                  <div v-for="(prompt, i) in selectedCheckpoint.visual_plan.image_prompts" :key="i" class="text-xs text-slate-500 flex gap-1">
                    <span class="text-slate-300 shrink-0">{{ i + 1 }}.</span>
                    <span class="line-clamp-2">{{ prompt }}</span>
                  </div>
                </div>
              </div>
              <div v-if="selectedCheckpoint.visual_plan.brand_elements?.length" class="mt-2 flex flex-wrap gap-1.5">
                <span v-for="el in selectedCheckpoint.visual_plan.brand_elements" :key="el" class="text-[11px] px-2 py-0.5 rounded-md bg-amber-50 text-amber-600 border border-amber-100">{{ el }}</span>
              </div>
            </div>
          </template>

          <!-- ═══ REVIEWING ═══ -->
          <template v-if="['review_gate', 'revise_content'].includes(selectedAgent) && selectedCheckpoint.copy_content">
            <div v-if="selectedCheckpoint.copy_content.selected_title" class="text-sm font-semibold text-rose-600 leading-snug">{{ selectedCheckpoint.copy_content.selected_title }}</div>
            <div v-if="selectedCheckpoint.copy_content.body_text" class="p-3 rounded-lg bg-slate-50 border border-slate-100">
              <p class="text-xs text-slate-600 whitespace-pre-line">{{ selectedCheckpoint.copy_content.body_text }}</p>
            </div>
            <div v-if="selectedCheckpoint.copy_content.hashtags?.length" class="flex flex-wrap gap-1.5">
              <span v-for="tag in selectedCheckpoint.copy_content.hashtags" :key="tag" class="text-[11px] px-2 py-0.5 rounded-md bg-teal-50 text-teal-600 border border-teal-100">#{{ tag }}</span>
            </div>
            <div class="grid grid-cols-2 gap-2">
              <div v-if="selectedCheckpoint.copy_content.cta" class="p-2 rounded-lg bg-rose-50 border border-rose-100">
                <div class="text-[10px] text-rose-500 font-medium">CTA</div>
                <div class="text-xs text-rose-700">{{ selectedCheckpoint.copy_content.cta }}</div>
              </div>
              <div v-if="selectedCheckpoint.copy_content.tone" class="p-2 rounded-lg bg-violet-50 border border-violet-100">
                <div class="text-[10px] text-violet-500 font-medium">{{ t('replay.tone') }}</div>
                <div class="text-xs text-violet-700">{{ selectedCheckpoint.copy_content.tone }}</div>
              </div>
            </div>
          </template>

          <!-- ═══ PUBLISHING ═══ -->
          <template v-if="['publisher', 'engagement'].includes(selectedAgent) && selectedCheckpoint.publish_result">
            <div class="grid grid-cols-2 gap-2">
              <div v-if="(selectedCheckpoint.publish_result as any).post_id" class="p-2 rounded-lg bg-emerald-50 border border-emerald-100">
                <div class="text-[10px] text-emerald-500 font-medium">Post ID</div>
                <div class="text-xs text-emerald-700 font-mono">{{ (selectedCheckpoint.publish_result as any).post_id }}</div>
              </div>
              <div v-if="(selectedCheckpoint.publish_result as any).status" class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.status') }}</div>
                <div class="text-xs font-medium" :class="(selectedCheckpoint.publish_result as any).status === 'published' ? 'text-emerald-600' : 'text-amber-600'">{{ (selectedCheckpoint.publish_result as any).status }}</div>
              </div>
              <div v-if="(selectedCheckpoint.publish_result as any).published_at" class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                <div class="text-[10px] text-slate-400 font-medium">{{ t('replay.publishedAt') }}</div>
                <div class="text-xs text-slate-600">{{ new Date((selectedCheckpoint.publish_result as any).published_at).toLocaleString() }}</div>
              </div>
            </div>
            <div v-if="(selectedCheckpoint.publish_result as any).post_url" class="mt-1">
              <a :href="(selectedCheckpoint.publish_result as any).post_url" target="_blank" rel="noopener" class="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-50 text-emerald-600 text-xs font-medium hover:bg-emerald-100 transition-colors border border-emerald-100">
                <AppIcon name="ExternalLink" size="sm" />
                {{ t('replay.viewPost') }}
              </a>
            </div>
          </template>

          <!-- ═══ ANALYTICS ═══ -->
          <template v-if="selectedAgent === 'analyst' && selectedCheckpoint.analytics">
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <div v-if="(selectedCheckpoint.analytics as any).views !== undefined" class="p-2.5 rounded-lg bg-slate-50 border border-slate-100 text-center">
                <div class="text-[10px] text-slate-400">Views</div>
                <div class="text-base font-bold text-slate-700">{{ formatNum((selectedCheckpoint.analytics as any).views) }}</div>
              </div>
              <div v-if="(selectedCheckpoint.analytics as any).likes !== undefined" class="p-2.5 rounded-lg bg-pink-50 border border-pink-100 text-center">
                <div class="text-[10px] text-slate-400">Likes</div>
                <div class="text-base font-bold text-pink-600">{{ formatNum((selectedCheckpoint.analytics as any).likes) }}</div>
              </div>
              <div v-if="(selectedCheckpoint.analytics as any).collects !== undefined" class="p-2.5 rounded-lg bg-amber-50 border border-amber-100 text-center">
                <div class="text-[10px] text-slate-400">Collects</div>
                <div class="text-base font-bold text-amber-600">{{ formatNum((selectedCheckpoint.analytics as any).collects) }}</div>
              </div>
              <div v-if="(selectedCheckpoint.analytics as any).engagement_rate !== undefined" class="p-2.5 rounded-lg bg-teal-50 border border-teal-100 text-center">
                <div class="text-[10px] text-slate-400">Engagement</div>
                <div class="text-base font-bold text-teal-600">{{ ((selectedCheckpoint.analytics as any).engagement_rate * 100).toFixed(1) }}%</div>
              </div>
            </div>
            <div v-if="(selectedCheckpoint.analytics as any).comments !== undefined || (selectedCheckpoint.analytics as any).shares !== undefined" class="grid grid-cols-2 gap-2">
              <div v-if="(selectedCheckpoint.analytics as any).comments !== undefined" class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                <div class="text-[10px] text-slate-400">Comments</div>
                <div class="text-xs font-semibold text-slate-700">{{ (selectedCheckpoint.analytics as any).comments }}</div>
              </div>
              <div v-if="(selectedCheckpoint.analytics as any).shares !== undefined" class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                <div class="text-[10px] text-slate-400">Shares</div>
                <div class="text-xs font-semibold text-slate-700">{{ (selectedCheckpoint.analytics as any).shares }}</div>
              </div>
            </div>
            <div v-if="(selectedCheckpoint.analytics as any).insights?.length">
              <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('showcase.detail.insights') }}</div>
              <ul class="space-y-1">
                <li v-for="(insight, i) in (selectedCheckpoint.analytics as any).insights" :key="i" class="text-xs text-slate-500 flex gap-1.5">
                  <span class="text-emerald-500">+</span>
                  <span>{{ insight }}</span>
                </li>
              </ul>
            </div>
          </template>

          <!-- ═══ RIPPLE PREDICTION ═══ -->
          <template v-if="selectedCheckpoint.ripple_prediction && Object.keys(selectedCheckpoint.ripple_prediction).length > 0">
            <div class="p-3 rounded-lg bg-violet-50 border border-violet-100">
              <div class="text-xs text-violet-600 font-medium mb-2">Ripple {{ t('replay.prediction') }}</div>
              <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
                <div v-if="selectedCheckpoint.ripple_prediction.viral_probability != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.viralProb') }}</div>
                  <div class="text-base font-bold" :class="selectedCheckpoint.ripple_prediction.viral_probability >= 0.7 ? 'text-emerald-600' : selectedCheckpoint.ripple_prediction.viral_probability >= 0.4 ? 'text-amber-600' : 'text-rose-600'">
                    {{ (selectedCheckpoint.ripple_prediction.viral_probability * 100).toFixed(1) }}%
                  </div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.estimated_reach != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.estReach') }}</div>
                  <div class="text-base font-bold text-indigo-700">{{ formatNum(selectedCheckpoint.ripple_prediction.estimated_reach) }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.estimated_engagement != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.estEngagement') }}</div>
                  <div class="text-base font-bold text-indigo-700">{{ formatNum(selectedCheckpoint.ripple_prediction.estimated_engagement) }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.confidence != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.confidence') }}</div>
                  <div class="text-base font-bold text-slate-700">{{ (selectedCheckpoint.ripple_prediction.confidence * 100).toFixed(0) }}%</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.total_waves != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.totalWaves') }}</div>
                  <div class="text-base font-bold text-slate-700">{{ selectedCheckpoint.ripple_prediction.total_waves }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.phase" class="p-2 rounded bg-white/60">
                  <div class="text-[10px] text-slate-400">{{ t('replay.phase') }}</div>
                  <div class="text-xs font-medium text-slate-700">{{ selectedCheckpoint.ripple_prediction.phase }}</div>
                </div>
              </div>
              <div v-if="selectedCheckpoint.ripple_prediction.verdict" class="mt-2 flex items-center justify-between text-xs">
                <span class="text-slate-500">{{ t('replay.verdict') }}</span>
                <span class="font-medium text-slate-700">{{ selectedCheckpoint.ripple_prediction.verdict }}</span>
              </div>
              <div v-if="selectedCheckpoint.ripple_prediction.prediction_summary" class="mt-1.5 p-2 rounded bg-white/60 text-xs text-slate-600">{{ selectedCheckpoint.ripple_prediction.prediction_summary }}</div>
              <!-- Relative estimates -->
              <div v-if="selectedCheckpoint.ripple_prediction.views_relative || selectedCheckpoint.ripple_prediction.engagements_relative || selectedCheckpoint.ripple_prediction.favorites_relative" class="mt-2 grid grid-cols-2 gap-1.5">
                <div v-if="selectedCheckpoint.ripple_prediction.views_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Views</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_prediction.views_relative }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.engagements_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Engagements</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_prediction.engagements_relative }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.favorites_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Favorites</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_prediction.favorites_relative }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.comments_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Comments</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_prediction.comments_relative }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.shares_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Shares</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_prediction.shares_relative }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_prediction.follows_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Follows</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_prediction.follows_relative }}</div>
                </div>
              </div>
              <!-- Spread path -->
              <div v-if="selectedCheckpoint.ripple_prediction.spread_path?.length" class="mt-2">
                <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.spreadPhases') }}</div>
                <div class="space-y-0.5">
                  <div v-for="(sp, i) in selectedCheckpoint.ripple_prediction.spread_path" :key="i" class="text-xs text-slate-600 flex gap-1.5">
                    <span class="w-4 h-4 rounded-full bg-violet-100 text-violet-600 flex items-center justify-center text-[10px] font-medium shrink-0">{{ i + 1 }}</span>
                    <span>{{ typeof sp === 'object' ? (sp.phase || sp.name || JSON.stringify(sp)) : String(sp) }}</span>
                  </div>
                </div>
              </div>
              <!-- Key influencers -->
              <div v-if="selectedCheckpoint.ripple_prediction.key_influencers?.length" class="mt-2">
                <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.keyInfluencers') }}</div>
                <div class="flex flex-wrap gap-1.5">
                  <span v-for="(inf, i) in selectedCheckpoint.ripple_prediction.key_influencers" :key="i" class="text-[11px] px-2 py-0.5 rounded-md bg-violet-100 text-violet-600 border border-violet-200">
                    {{ typeof inf === 'object' ? (inf.name || inf.handle || JSON.stringify(inf)) : String(inf) }}
                  </span>
                </div>
              </div>
            </div>
          </template>

          <!-- ═══ RIPPLE PMF ═══ -->
          <template v-if="selectedCheckpoint.ripple_pmf && Object.keys(selectedCheckpoint.ripple_pmf).length > 0">
            <div class="p-3 rounded-lg bg-indigo-50 border border-indigo-100">
              <div class="text-xs text-indigo-600 font-medium mb-2">Ripple PMF</div>
              <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
                <div v-if="selectedCheckpoint.ripple_pmf.pmf_score != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">PMF Score</div>
                  <div class="text-base font-bold" :class="selectedCheckpoint.ripple_pmf.pmf_score >= 0.7 ? 'text-emerald-600' : selectedCheckpoint.ripple_pmf.pmf_score >= 0.4 ? 'text-amber-600' : 'text-rose-600'">
                    {{ (selectedCheckpoint.ripple_pmf.pmf_score * 100).toFixed(0) }}%
                  </div>
                </div>
                <div v-if="selectedCheckpoint.ripple_pmf.confidence != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.confidence') }}</div>
                  <div class="text-base font-bold text-indigo-700">{{ (selectedCheckpoint.ripple_pmf.confidence * 100).toFixed(0) }}%</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_pmf.total_waves != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.totalWaves') }}</div>
                  <div class="text-base font-bold text-slate-700">{{ selectedCheckpoint.ripple_pmf.total_waves }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_pmf.phase" class="p-2 rounded bg-white/60">
                  <div class="text-[10px] text-slate-400">{{ t('replay.phase') }}</div>
                  <div class="text-xs font-medium text-slate-700">{{ selectedCheckpoint.ripple_pmf.phase }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_pmf.score_source" class="p-2 rounded bg-white/60">
                  <div class="text-[10px] text-slate-400">{{ t('replay.scoreSource') }}</div>
                  <div class="text-xs font-medium text-slate-700">{{ selectedCheckpoint.ripple_pmf.score_source }}</div>
                </div>
              </div>
              <div v-if="selectedCheckpoint.ripple_pmf.verdict" class="mt-2 flex items-center justify-between text-xs">
                <span class="text-slate-500">{{ t('replay.verdict') }}</span>
                <span class="font-medium text-slate-700">{{ selectedCheckpoint.ripple_pmf.verdict }}</span>
              </div>
              <div v-if="selectedCheckpoint.ripple_pmf.prediction_summary" class="mt-1.5 p-2 rounded bg-white/60 text-xs text-slate-600">{{ selectedCheckpoint.ripple_pmf.prediction_summary }}</div>
              <div v-if="selectedCheckpoint.ripple_pmf.risk_factors?.length" class="mt-2">
                <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.riskFactors') }}</div>
                <div class="space-y-0.5">
                  <div v-for="risk in selectedCheckpoint.ripple_pmf.risk_factors" :key="risk" class="text-xs text-slate-500 flex gap-1.5">
                    <span class="text-rose-400">⚠</span>
                    <span>{{ risk }}</span>
                  </div>
                </div>
              </div>
              <div v-if="selectedCheckpoint.ripple_pmf.improvement_strategies?.length" class="mt-2">
                <div class="text-[10px] text-slate-400 font-medium mb-1">{{ t('replay.improvementStrategies') }}</div>
                <div class="space-y-0.5">
                  <div v-for="strategy in selectedCheckpoint.ripple_pmf.improvement_strategies" :key="strategy" class="text-xs text-slate-500 flex gap-1.5">
                    <span class="text-cyan-400">💡</span>
                    <span>{{ strategy }}</span>
                  </div>
                </div>
              </div>
              <!-- PMF relative estimates -->
              <div v-if="selectedCheckpoint.ripple_pmf.views_relative || selectedCheckpoint.ripple_pmf.engagements_relative || selectedCheckpoint.ripple_pmf.favorites_relative" class="mt-2 grid grid-cols-2 gap-1.5">
                <div v-if="selectedCheckpoint.ripple_pmf.views_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Views</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_pmf.views_relative }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_pmf.engagements_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Engagements</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_pmf.engagements_relative }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_pmf.favorites_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Favorites</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_pmf.favorites_relative }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_pmf.comments_relative" class="p-1.5 rounded bg-white/40">
                  <div class="text-[10px] text-slate-400">Comments</div>
                  <div class="text-xs text-slate-700">{{ selectedCheckpoint.ripple_pmf.comments_relative }}</div>
                </div>
              </div>
            </div>
          </template>

          <!-- ═══ RIPPLE COMPARISON ═══ -->
          <template v-if="selectedCheckpoint.ripple_comparison && Object.keys(selectedCheckpoint.ripple_comparison).length > 0">
            <div class="p-3 rounded-lg bg-amber-50 border border-amber-100">
              <div class="text-xs text-amber-600 font-medium mb-2">Ripple {{ t('replay.comparison') }}</div>
              <div class="grid grid-cols-2 gap-2">
                <div v-if="selectedCheckpoint.ripple_comparison.predicted_reach != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.predictedReach') }}</div>
                  <div class="text-base font-bold text-sky-700">{{ formatNum(selectedCheckpoint.ripple_comparison.predicted_reach) }}</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_comparison.actual_engagement_rate != null" class="p-2 rounded bg-white/60 text-center">
                  <div class="text-[10px] text-slate-400">{{ t('replay.actualEngRate') }}</div>
                  <div class="text-base font-bold text-slate-700">{{ (selectedCheckpoint.ripple_comparison.actual_engagement_rate * 100).toFixed(1) }}%</div>
                </div>
                <div v-if="selectedCheckpoint.ripple_comparison.reach_deviation != null" class="p-2 rounded bg-white/60">
                  <div class="text-[10px] text-slate-400">{{ t('replay.reachDeviation') }}</div>
                  <div class="text-xs font-semibold" :class="selectedCheckpoint.ripple_comparison.reach_deviation > 0 ? 'text-emerald-600' : 'text-rose-600'">
                    {{ selectedCheckpoint.ripple_comparison.reach_deviation > 0 ? '+' : '' }}{{ (selectedCheckpoint.ripple_comparison.reach_deviation * 100).toFixed(1) }}%
                  </div>
                </div>
                <div v-if="selectedCheckpoint.ripple_comparison.engagement_deviation != null" class="p-2 rounded bg-white/60">
                  <div class="text-[10px] text-slate-400">{{ t('replay.engDeviation') }}</div>
                  <div class="text-xs font-semibold" :class="selectedCheckpoint.ripple_comparison.engagement_deviation > 0 ? 'text-emerald-600' : 'text-rose-600'">
                    {{ selectedCheckpoint.ripple_comparison.engagement_deviation > 0 ? '+' : '' }}{{ (selectedCheckpoint.ripple_comparison.engagement_deviation * 100).toFixed(1) }}%
                  </div>
                </div>
              </div>
              <div v-if="selectedCheckpoint.ripple_comparison.accuracy_rating" class="mt-2 flex items-center justify-between text-xs">
                <span class="text-slate-500">{{ t('replay.accuracyRating') }}</span>
                <span class="font-medium" :class="selectedCheckpoint.ripple_comparison.accuracy_rating === '准确' || selectedCheckpoint.ripple_comparison.accuracy_rating === 'accurate' ? 'text-emerald-600' : 'text-amber-600'">{{ selectedCheckpoint.ripple_comparison.accuracy_rating }}</span>
              </div>
              <div v-if="selectedCheckpoint.ripple_comparison.calibration_insight" class="mt-1.5 p-2 rounded bg-white/60 text-xs text-amber-700">{{ selectedCheckpoint.ripple_comparison.calibration_insight }}</div>
            </div>
          </template>

          <!-- No data -->
          <div v-if="!hasDataForAgent(selectedAgent, selectedCheckpoint)" class="text-xs text-slate-400 text-center py-4">
            {{ t('replay.noData') }}
          </div>
        </div>
      </div>

      <!-- No checkpoint selected -->
      <div v-else class="rounded-xl bg-white border border-slate-200/50 shadow-sm p-8 text-center">
        <div class="w-12 h-12 rounded-xl bg-violet-100 flex items-center justify-center mx-auto mb-4">
          <AppIcon name="MousePointerClick" size="lg" variant="purple" />
        </div>
        <p class="text-sm text-slate-600 font-medium">{{ t('replay.clickHint') }}</p>
        <p class="text-xs text-slate-400 mt-1.5">{{ t('replay.clickHintDesc') }}</p>
      </div>
    </main>
  </div>
</template>
