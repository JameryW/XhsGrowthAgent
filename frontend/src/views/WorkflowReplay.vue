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

function getNodeStatus(phase: string): NodeStatus {
  if (!effectiveState.value) return 'pending'
  const currentPhase = effectiveState.value.phase
  const currentStatus = effectiveState.value.status
  if (currentPhase === 'completed' || currentStatus === 'completed') return 'completed'
  const idx = pipelineSteps.indexOf(phase as any)
  const currentIdx = pipelineSteps.indexOf(currentPhase as any)
  if (idx < 0) return 'pending'
  if (currentIdx < 0) return 'pending'
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
  planning: 'content_strategist',
  creating: 'copywriter',
  reviewing: 'review_gate',
  publishing: 'publisher',
  analyzing: 'analyst',
}

function handleNodeClick(phase: string) {
  const agent = phaseAgentMap[phase] || phase
  const cpId = findCheckpointForAgent(agent)
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
  if (['copywriter', 'draft_gate', 'viral_matcher', 'blogger_scout', 'blogger_gate', 'visual_designer'].includes(agent)) return has(cp.copy_content) || has(cp.visual_plan)
  if (['review_gate', 'revise_content'].includes(agent)) return has(cp.copy_content)
  if (['publisher', 'engagement'].includes(agent)) return has(cp.publish_result)
  if (agent === 'analyst') return has(cp.analytics)
  return false
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

        <div class="px-4 md:px-5 py-4 space-y-3">
          <!-- Scouting: Trend data -->
          <template v-if="selectedAgent === 'trend_scout' && selectedCheckpoint.trend_data">
            <div v-if="selectedCheckpoint.trend_data.hot_topics?.length" class="mb-2">
              <div class="text-xs text-slate-400 font-medium mb-1.5">{{ t('showcase.detail.hotTopics') }}</div>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="ht in selectedCheckpoint.trend_data.hot_topics.slice(0, 5)" :key="ht.topic" class="text-[11px] px-2 py-0.5 rounded-full bg-rose-50 text-rose-600">
                  {{ ht.topic }} {{ ht.heat_score }}
                </span>
              </div>
            </div>
            <div v-if="selectedCheckpoint.trend_data.competitor_posts?.length" class="p-3 rounded-lg bg-slate-50 border border-slate-100">
              <div class="text-xs text-slate-400 mb-0.5 font-medium">{{ t('showcase.detail.topCompetitor') }}</div>
              <div class="text-xs text-slate-700">{{ selectedCheckpoint.trend_data.competitor_posts[0].title }}</div>
              <div class="text-[11px] text-slate-400 mt-0.5">
                {{ (selectedCheckpoint.trend_data.competitor_posts[0].likes / 1000).toFixed(1) }}k likes
              </div>
            </div>
          </template>

          <!-- Planning: Content plan -->
          <template v-if="selectedAgent === 'content_strategist' && selectedCheckpoint.content_plan">
            <div class="mb-2">
              <div class="text-base font-bold text-slate-800 leading-snug">{{ selectedCheckpoint.content_plan.selected_topic }}</div>
              <div class="text-xs text-slate-500 mt-1 line-clamp-2">{{ selectedCheckpoint.content_plan.content_angle }}</div>
            </div>
            <div class="flex flex-wrap gap-1.5">
              <span class="text-[11px] px-2 py-0.5 rounded-full bg-teal-50 text-teal-700">{{ selectedCheckpoint.content_plan.content_type }}</span>
              <span class="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">{{ selectedCheckpoint.content_plan.target_audience }}</span>
            </div>
          </template>

          <!-- Creating: Copy content -->
          <template v-if="['copywriter', 'draft_gate', 'viral_matcher', 'blogger_scout', 'blogger_gate', 'choice_gate'].includes(selectedAgent) && selectedCheckpoint.copy_content">
            <div v-if="selectedCheckpoint.copy_content.selected_title" class="mb-2">
              <div class="text-sm font-semibold text-rose-600 leading-snug">{{ selectedCheckpoint.copy_content.selected_title }}</div>
              <div v-if="selectedCheckpoint.copy_content.body_text" class="text-xs text-slate-500 mt-2 line-clamp-4 whitespace-pre-line">{{ selectedCheckpoint.copy_content.body_text }}</div>
              <div v-if="selectedCheckpoint.copy_content.hashtags?.length" class="flex flex-wrap gap-1 mt-2">
                <span v-for="tag in selectedCheckpoint.copy_content.hashtags.slice(0, 8)" :key="tag" class="text-[11px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-700">#{{ tag }}</span>
              </div>
            </div>
          </template>

          <!-- Visual plan -->
          <template v-if="selectedAgent === 'visual_designer'">
            <div v-if="selectedCheckpoint.copy_content?.selected_title" class="mb-2">
              <div class="text-sm font-semibold text-rose-600 leading-snug">{{ selectedCheckpoint.copy_content!.selected_title }}</div>
              <div v-if="selectedCheckpoint.copy_content.body_text" class="text-xs text-slate-500 mt-2 line-clamp-3 whitespace-pre-line">{{ selectedCheckpoint.copy_content!.body_text }}</div>
            </div>
            <div v-if="selectedCheckpoint.visual_plan" class="p-3 rounded-lg bg-slate-50 border border-slate-100">
              <div class="text-xs text-slate-400 mb-0.5 font-medium">{{ t('showcase.detail.visual') }}</div>
              <div class="text-xs text-slate-700">{{ selectedCheckpoint.visual_plan.layout_style }}</div>
              <div class="text-[11px] text-slate-400 mt-0.5">{{ t('showcase.detail.imageCount', { count: selectedCheckpoint.visual_plan.image_count }) }}</div>
              <div v-if="selectedCheckpoint.visual_plan.color_palette?.length" class="flex gap-1 mt-1">
                <div v-for="color in selectedCheckpoint.visual_plan.color_palette.slice(0, 5)" :key="color" class="w-4 h-4 rounded-full border border-white shadow-sm" :style="{ backgroundColor: color }" />
              </div>
            </div>
          </template>

          <!-- Review -->
          <template v-if="['review_gate', 'revise_content'].includes(selectedAgent) && selectedCheckpoint.copy_content">
            <div v-if="selectedCheckpoint.copy_content.selected_title" class="mb-2">
              <div class="text-sm font-semibold text-rose-600 leading-snug">{{ selectedCheckpoint.copy_content.selected_title }}</div>
              <div v-if="selectedCheckpoint.copy_content.body_text" class="text-xs text-slate-500 mt-2 line-clamp-4 whitespace-pre-line">{{ selectedCheckpoint.copy_content.body_text }}</div>
              <div v-if="selectedCheckpoint.copy_content.hashtags?.length" class="flex flex-wrap gap-1 mt-2">
                <span v-for="tag in selectedCheckpoint.copy_content.hashtags.slice(0, 8)" :key="tag" class="text-[11px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-700">#{{ tag }}</span>
              </div>
            </div>
          </template>

          <!-- Publishing -->
          <template v-if="['publisher', 'engagement'].includes(selectedAgent) && selectedCheckpoint.publish_result">
            <div class="p-3 rounded-lg bg-emerald-50 border border-emerald-100">
              <div class="text-xs text-emerald-600 font-medium mb-1">{{ t('showcase.status.completed') }}</div>
              <div v-if="(selectedCheckpoint.publish_result as any).post_url" class="text-xs text-slate-700">{{ (selectedCheckpoint.publish_result as any).post_url }}</div>
            </div>
          </template>

          <!-- Analytics -->
          <template v-if="selectedAgent === 'analyst' && selectedCheckpoint.analytics">
            <div v-if="(selectedCheckpoint.analytics as any).insights?.length">
              <div class="text-xs text-emerald-600 font-medium mb-1">{{ t('showcase.detail.insights') }}</div>
              <ul class="space-y-1">
                <li v-for="(insight, i) in (selectedCheckpoint.analytics as any).insights.slice(0, 3)" :key="i" class="text-xs text-slate-500 flex gap-1.5">
                  <span class="text-emerald-500">+</span>
                  <span class="line-clamp-2">{{ insight }}</span>
                </li>
              </ul>
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
