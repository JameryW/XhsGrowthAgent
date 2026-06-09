<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { listWorkflows, getWorkflowStatus } from '@/api/workflow'
import type { WorkflowListItem, WorkflowPhase, WorkflowStatus, WorkflowStateResponse } from '@/types/workflow'

const { t } = useI18n()
const router = useRouter()

const workflows = ref<WorkflowListItem[]>([])
const workflowDetails = ref<Map<string, WorkflowStateResponse>>(new Map())
const isLoading = ref(true)
const error = ref<string | null>(null)

async function fetchWorkflows() {
  isLoading.value = true
  error.value = null
  try {
    const result = await listWorkflows({ limit: 50 })
    workflows.value = result.workflows
    // Load all details in parallel
    const promises = result.workflows.map(async (wf) => {
      try {
        const state = await getWorkflowStatus(wf.thread_id)
        workflowDetails.value.set(wf.thread_id, state)
      } catch {
        // Skip failed detail fetches
      }
    })
    await Promise.allSettled(promises)
  } catch (e: any) {
    error.value = e.message
  } finally {
    isLoading.value = false
  }
}

onMounted(fetchWorkflows)

function getDetail(threadId: string): WorkflowStateResponse | undefined {
  return workflowDetails.value.get(threadId)
}

const runningWorkflows = computed(() =>
  workflows.value.filter(w => ['running', 'awaiting_review', 'awaiting_choice', 'awaiting_draft', 'awaiting_brief', 'awaiting_ripple_decision', 'awaiting_blogger_selection'].includes(w.status))
)
const completedWorkflows = computed(() => workflows.value.filter(w => w.status === 'completed'))
const otherWorkflows = computed(() =>
  workflows.value.filter(w =>
    !['running', 'completed', 'awaiting_review', 'awaiting_choice', 'awaiting_draft', 'awaiting_brief', 'awaiting_ripple_decision', 'awaiting_blogger_selection'].includes(w.status)
  )
)

function statusLabel(status: WorkflowStatus): string {
  const map: Record<string, string> = {
    running: t('showcase.status.running'),
    completed: t('showcase.status.completed'),
    error: t('showcase.status.error'),
    cancelled: t('showcase.status.cancelled'),
    paused: t('showcase.status.paused'),
    stale: t('showcase.status.stale'),
    awaiting_review: t('showcase.status.awaitingReview'),
    awaiting_choice: t('showcase.status.awaitingChoice'),
    awaiting_draft: t('showcase.status.awaitingDraft'),
    awaiting_brief: t('showcase.status.awaitingBrief'),
    awaiting_ripple_decision: t('showcase.status.awaitingRipple'),
    awaiting_blogger_selection: t('showcase.status.awaitingBlogger'),
    idle: t('showcase.status.idle'),
  }
  return map[status] || status
}

function phaseLabel(phase: WorkflowPhase): string {
  const map: Record<string, string> = {
    idle: t('showcase.phase.idle'),
    scouting: t('showcase.phase.scouting'),
    planning: t('showcase.phase.planning'),
    creating: t('showcase.phase.creating'),
    briefing: t('showcase.phase.briefing'),
    reviewing: t('showcase.phase.reviewing'),
    publishing: t('showcase.phase.publishing'),
    analyzing: t('showcase.phase.analyzing'),
    engaging: t('showcase.phase.engaging'),
    completed: t('showcase.phase.completed'),
    error: t('showcase.phase.error'),
    paused: t('showcase.phase.paused'),
    cancelled: t('showcase.phase.cancelled'),
  }
  return map[phase] || phase
}

// Pipeline phase steps
const pipelineSteps = ['scouting', 'planning', 'creating', 'reviewing', 'publishing', 'analyzing']

function pipelineProgress(phase: WorkflowPhase): number {
  const idx = pipelineSteps.indexOf(phase)
  if (idx < 0) return phase === 'completed' ? 6 : 0
  return idx + 1
}

function formatDate(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function goDashboard() { router.push('/login') }
function goReplay(threadId: string) { router.push({ name: 'replay', params: { threadId } }) }

function formatNum(n?: number): string {
  if (n === undefined || n === null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

const isEmpty = computed(() => !isLoading.value && workflows.value.length === 0)
</script>

<template>
  <div class="min-h-screen bg-gradient-to-b from-slate-50 to-white text-slate-800 relative overflow-hidden">
    <!-- Subtle decorative elements -->
    <div class="absolute top-0 right-0 w-[500px] h-[500px] pointer-events-none opacity-30" style="background: radial-gradient(circle, rgba(244,63,94,0.08) 0%, transparent 60%);" />
    <div class="absolute bottom-0 left-0 w-[400px] h-[400px] pointer-events-none opacity-20" style="background: radial-gradient(circle, rgba(20,184,166,0.08) 0%, transparent 60%);" />

    <!-- Nav -->
    <nav class="relative z-20 bg-white/70 backdrop-blur-lg border-b border-slate-200/60">
      <div class="max-w-6xl mx-auto px-4 md:px-8 h-14 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-rose-500 to-amber-400 flex items-center justify-center shadow-md shadow-rose-500/20">
            <AppIcon name="Rocket" size="sm" variant="white" />
          </div>
          <div>
            <h1 class="text-sm font-bold tracking-tight text-slate-800">{{ t('showcase.title') }}</h1>
            <p class="text-[10px] text-slate-400 -mt-0.5">{{ t('showcase.subtitle') }}</p>
          </div>
        </div>
        <button @click="goDashboard" class="px-4 py-1.5 rounded-lg bg-rose-500 hover:bg-rose-600 text-xs font-medium text-white transition-colors shadow-sm shadow-rose-500/20">
          {{ t('showcase.dashboard') }}
        </button>
      </div>
    </nav>

    <main class="max-w-6xl mx-auto px-4 md:px-8 py-6 md:py-8 relative z-10" :class="error || isEmpty ? 'flex items-center justify-center min-h-[calc(100vh-3.5rem)]' : ''">
      <!-- Loading -->
      <div v-if="isLoading" class="space-y-4 animate-in">
        <div class="h-6 w-40 rounded-lg bg-slate-100 animate-pulse" />
        <div class="h-16 rounded-xl bg-slate-100 animate-pulse" />
        <div class="h-48 rounded-xl bg-slate-100 animate-pulse" />
        <div class="h-48 rounded-xl bg-slate-100 animate-pulse" />
      </div>

      <!-- Error -->
      <div v-else-if="error" class="rounded-xl p-8 bg-rose-50 border border-rose-200/60 text-center max-w-md w-full">
        <div class="w-12 h-12 rounded-xl bg-rose-100 flex items-center justify-center mx-auto mb-4">
          <AppIcon name="AlertCircle" size="lg" variant="pink" />
        </div>
        <p class="text-sm text-rose-700 font-medium">{{ t('common.apiError') }}</p>
        <p class="text-xs text-rose-500/70 mt-2">{{ error }}</p>
        <button @click="fetchWorkflows" class="mt-4 px-5 py-2 rounded-lg bg-rose-600 text-white hover:bg-rose-700 text-xs font-medium transition-colors shadow-sm">{{ t('common.retry') }}</button>
      </div>

      <!-- Empty -->
      <div v-else-if="isEmpty" class="py-20 text-center max-w-md w-full">
        <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center mx-auto mb-5 shadow-sm border border-slate-200/60">
          <AppIcon name="Inbox" size="lg" variant="cyan" />
        </div>
        <p class="text-sm text-slate-600 font-semibold">{{ t('showcase.empty') }}</p>
        <p class="text-xs text-slate-400 mt-1.5">{{ t('showcase.emptyDesc') }}</p>
      </div>

      <!-- Content -->
      <template v-else>
        <!-- Summary bar -->
        <div class="flex items-center gap-4 mb-6 text-xs">
          <span class="flex items-center gap-1.5 text-teal-600 font-medium">
            <span class="w-2 h-2 rounded-full bg-teal-500 animate-pulse" />
            {{ runningWorkflows.length }} {{ t('showcase.stats.running') }}
          </span>
          <span class="flex items-center gap-1.5 text-emerald-600 font-medium">
            <span class="w-2 h-2 rounded-full bg-emerald-500" />
            {{ completedWorkflows.length }} {{ t('showcase.stats.completed') }}
          </span>
          <span v-if="otherWorkflows.length > 0" class="flex items-center gap-1.5 text-slate-400">
            {{ otherWorkflows.length }} {{ t('showcase.stats.other') }}
          </span>
        </div>

        <!-- Workflow cards -->
        <div class="space-y-4 md:space-y-5">
          <!-- Active workflows -->
          <template v-if="runningWorkflows.length > 0">
            <div v-for="wf in runningWorkflows" :key="wf.thread_id" class="rounded-xl bg-white border border-teal-200/50 shadow-sm overflow-hidden hover:shadow-md transition-shadow cursor-pointer" @click="goReplay(wf.thread_id)">
              <!-- Card header -->
              <div class="px-4 md:px-5 py-3 flex items-center justify-between border-b border-slate-100 bg-teal-50/40">
                <div class="flex items-center gap-2">
                  <span class="w-2.5 h-2.5 rounded-full bg-teal-500 animate-pulse" />
                  <span class="text-sm font-semibold text-slate-800">{{ phaseLabel(wf.phase) }}</span>
                  <span class="text-xs px-2 py-0.5 rounded-full bg-teal-100 text-teal-700">{{ statusLabel(wf.status) }}</span>
                  <span v-if="wf.dry_run" class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">dry-run</span>
                </div>
                <div class="flex items-center gap-3">
                  <!-- Pipeline -->
                  <div class="hidden md:flex items-center gap-1">
                    <template v-for="(_step, i) in pipelineSteps" :key="i">
                      <div class="w-4 h-1.5 rounded-full transition-colors" :class="i < pipelineProgress(wf.phase) ? 'bg-teal-500' : 'bg-slate-200'" />
                    </template>
                  </div>
                  <span class="text-xs text-slate-500 tabular-nums font-medium">{{ wf.progress_percent }}%</span>
                  <span class="text-xs text-slate-400">{{ formatDate(wf.created_at) }}</span>
                </div>
              </div>
              <!-- Card body -->
              <div class="px-4 md:px-5 py-4">
                <template v-if="getDetail(wf.thread_id)">
                  <div class="md:grid md:grid-cols-5 md:gap-4 space-y-3 md:space-y-0">
                    <!-- Left: main content -->
                    <div class="md:col-span-3 space-y-2">
                      <div v-if="getDetail(wf.thread_id)!.content_plan?.selected_topic" class="mb-1">
                        <div class="text-base font-bold text-slate-800 leading-snug">{{ getDetail(wf.thread_id)!.content_plan!.selected_topic }}</div>
                        <div v-if="getDetail(wf.thread_id)!.content_plan?.content_angle" class="text-xs text-slate-500 mt-1 line-clamp-2">{{ getDetail(wf.thread_id)!.content_plan!.content_angle }}</div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.copy_content?.selected_title">
                        <div class="text-sm font-semibold text-rose-600 leading-snug">{{ getDetail(wf.thread_id)!.copy_content!.selected_title }}</div>
                        <div v-if="getDetail(wf.thread_id)!.copy_content?.body_text" class="text-xs text-slate-500 mt-1.5 line-clamp-4 whitespace-pre-line">{{ getDetail(wf.thread_id)!.copy_content!.body_text }}</div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.copy_content?.hashtags?.length" class="flex flex-wrap gap-1">
                        <span v-for="tag in getDetail(wf.thread_id)!.copy_content!.hashtags!.slice(0, 10)" :key="tag" class="text-[11px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-700">#{{ tag }}</span>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.content_plan?.key_points?.length" class="space-y-0.5">
                        <div v-for="(point, i) in getDetail(wf.thread_id)!.content_plan!.key_points!.slice(0, 3)" :key="i" class="text-xs text-slate-500 flex gap-1">
                          <span class="text-cyan-400">▸</span>
                          <span class="line-clamp-1">{{ point }}</span>
                        </div>
                      </div>
                    </div>
                    <!-- Right: metadata -->
                    <div class="md:col-span-2 space-y-2">
                      <div v-if="getDetail(wf.thread_id)!.trend_data?.hot_topics?.length">
                        <div class="text-[10px] text-slate-400 font-medium mb-1 uppercase tracking-wide">{{ t('showcase.detail.hotTopics') }}</div>
                        <div class="flex flex-wrap gap-1">
                          <span v-for="ht in getDetail(wf.thread_id)!.trend_data!.hot_topics!.slice(0, 4)" :key="ht.topic" class="text-[11px] px-1.5 py-0.5 rounded-full bg-rose-50 text-rose-600">{{ ht.topic }}</span>
                        </div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.trend_data?.trending_keywords?.length">
                        <div class="text-[10px] text-slate-400 font-medium mb-1 uppercase tracking-wide">{{ t('replay.trendingKeywords') }}</div>
                        <div class="flex flex-wrap gap-1">
                          <span v-for="kw in getDetail(wf.thread_id)!.trend_data!.trending_keywords!.slice(0, 5)" :key="kw" class="text-[11px] px-1.5 py-0.5 rounded-md bg-pink-50 text-pink-600 border border-pink-100">{{ kw }}</span>
                        </div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.visual_plan" class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                        <div class="text-[10px] text-slate-400 font-medium mb-0.5">{{ t('showcase.detail.visual') }}</div>
                        <div class="text-xs text-slate-700">{{ getDetail(wf.thread_id)!.visual_plan!.layout_style }}</div>
                        <div class="text-[11px] text-slate-400">{{ t('showcase.detail.imageCount', { count: getDetail(wf.thread_id)!.visual_plan!.image_count }) }}</div>
                        <div v-if="getDetail(wf.thread_id)!.visual_plan!.color_palette?.length" class="flex gap-1 mt-1">
                          <div v-for="color in getDetail(wf.thread_id)!.visual_plan!.color_palette!.slice(0, 5)" :key="color" class="w-3.5 h-3.5 rounded-full border border-white shadow-sm" :style="{ backgroundColor: color }" />
                        </div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.ripple_prediction && Object.keys(getDetail(wf.thread_id)!.ripple_prediction!).length > 0" class="p-2 rounded-lg bg-violet-50 border border-violet-100">
                        <div class="text-[10px] text-violet-500 font-medium mb-0.5">Ripple</div>
                        <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.viral_probability != null">{{ t('replay.viralProb') }} {{ (getDetail(wf.thread_id)!.ripple_prediction!.viral_probability! * 100).toFixed(1) }}%</div>
                        <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.estimated_reach != null">{{ t('replay.estReach') }} {{ formatNum(getDetail(wf.thread_id)!.ripple_prediction!.estimated_reach!) }}</div>
                      </div>
                    </div>
                  </div>
                </template>
                <div v-else class="text-xs text-slate-400">{{ t('common.loadingState') }}</div>
              </div>
            </div>
          </template>

          <!-- Completed workflows -->
          <template v-if="completedWorkflows.length > 0">
            <div v-for="wf in completedWorkflows" :key="wf.thread_id" class="rounded-xl bg-white border border-emerald-200/40 shadow-sm overflow-hidden hover:shadow-md transition-shadow cursor-pointer" @click="goReplay(wf.thread_id)">
              <!-- Card header -->
              <div class="px-4 md:px-5 py-3 flex items-center justify-between border-b border-slate-100 bg-emerald-50/30">
                <div class="flex items-center gap-2">
                  <span class="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                  <span class="text-sm font-semibold text-slate-800">{{ t('showcase.status.completed') }}</span>
                  <span v-if="wf.dry_run" class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">dry-run</span>
                  <span v-else class="text-xs px-2 py-0.5 rounded-full bg-rose-50 text-rose-600">live</span>
                </div>
                <div class="flex items-center gap-3">
                  <div class="hidden md:flex items-center gap-1">
                    <div v-for="_s in pipelineSteps" :key="_s" class="w-4 h-1.5 rounded-full bg-emerald-400" />
                  </div>
                  <span class="text-xs text-slate-400">{{ formatDate(wf.created_at) }}</span>
                </div>
              </div>
              <!-- Card body -->
              <div class="px-4 md:px-5 py-4">
                <template v-if="getDetail(wf.thread_id)">
                  <div class="md:grid md:grid-cols-5 md:gap-4 space-y-3 md:space-y-0">
                    <!-- Left: main content -->
                    <div class="md:col-span-3 space-y-2">
                      <div v-if="getDetail(wf.thread_id)!.content_plan?.selected_topic" class="mb-1">
                        <div class="text-base font-bold text-slate-800 leading-snug">{{ getDetail(wf.thread_id)!.content_plan!.selected_topic }}</div>
                        <div v-if="getDetail(wf.thread_id)!.content_plan?.content_angle" class="text-xs text-slate-500 mt-1 line-clamp-2">{{ getDetail(wf.thread_id)!.content_plan!.content_angle }}</div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.copy_content?.selected_title">
                        <div class="text-sm font-semibold text-rose-600 leading-snug">{{ getDetail(wf.thread_id)!.copy_content!.selected_title }}</div>
                        <div v-if="getDetail(wf.thread_id)!.copy_content?.body_text" class="text-xs text-slate-500 mt-1.5 line-clamp-5 whitespace-pre-line">{{ getDetail(wf.thread_id)!.copy_content!.body_text }}</div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.copy_content?.hashtags?.length" class="flex flex-wrap gap-1">
                        <span v-for="tag in getDetail(wf.thread_id)!.copy_content!.hashtags!" :key="tag" class="text-[11px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-700">#{{ tag }}</span>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.content_plan?.key_points?.length" class="space-y-0.5">
                        <div v-for="(point, i) in getDetail(wf.thread_id)!.content_plan!.key_points!.slice(0, 3)" :key="i" class="text-xs text-slate-500 flex gap-1">
                          <span class="text-cyan-400">▸</span>
                          <span class="line-clamp-1">{{ point }}</span>
                        </div>
                      </div>
                    </div>
                    <!-- Right: metadata -->
                    <div class="md:col-span-2 space-y-2">
                      <div v-if="getDetail(wf.thread_id)!.trend_data?.hot_topics?.length">
                        <div class="text-[10px] text-slate-400 font-medium mb-1 uppercase tracking-wide">{{ t('showcase.detail.hotTopics') }}</div>
                        <div class="flex flex-wrap gap-1">
                          <span v-for="ht in getDetail(wf.thread_id)!.trend_data!.hot_topics!.slice(0, 5)" :key="ht.topic" class="text-[11px] px-1.5 py-0.5 rounded-full bg-rose-50 text-rose-600">{{ ht.topic }}</span>
                        </div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.trend_data?.trending_keywords?.length">
                        <div class="text-[10px] text-slate-400 font-medium mb-1 uppercase tracking-wide">{{ t('replay.trendingKeywords') }}</div>
                        <div class="flex flex-wrap gap-1">
                          <span v-for="kw in getDetail(wf.thread_id)!.trend_data!.trending_keywords!.slice(0, 5)" :key="kw" class="text-[11px] px-1.5 py-0.5 rounded-md bg-pink-50 text-pink-600 border border-pink-100">{{ kw }}</span>
                        </div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.trend_data?.competitor_posts?.[0]" class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                        <div class="text-[10px] text-slate-400 font-medium mb-0.5">{{ t('showcase.detail.topCompetitor') }}</div>
                        <div class="text-xs text-slate-700">{{ getDetail(wf.thread_id)!.trend_data!.competitor_posts![0].title }}</div>
                        <div class="text-[11px] text-slate-400 mt-0.5">{{ (getDetail(wf.thread_id)!.trend_data!.competitor_posts![0].likes / 1000).toFixed(1) }}k likes</div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.visual_plan" class="p-2 rounded-lg bg-slate-50 border border-slate-100">
                        <div class="text-[10px] text-slate-400 font-medium mb-0.5">{{ t('showcase.detail.visual') }}</div>
                        <div class="text-xs text-slate-700">{{ getDetail(wf.thread_id)!.visual_plan!.layout_style }}</div>
                        <div class="text-[11px] text-slate-400">{{ t('showcase.detail.imageCount', { count: getDetail(wf.thread_id)!.visual_plan!.image_count }) }}</div>
                      </div>
                      <div v-if="(getDetail(wf.thread_id)!.analytics as any)?.views !== undefined" class="grid grid-cols-2 gap-1.5">
                        <div class="p-1.5 rounded bg-slate-50 text-center">
                          <div class="text-[10px] text-slate-400">Views</div>
                          <div class="text-xs font-bold text-slate-700">{{ formatNum((getDetail(wf.thread_id)!.analytics as any).views) }}</div>
                        </div>
                        <div class="p-1.5 rounded bg-pink-50 text-center">
                          <div class="text-[10px] text-slate-400">Likes</div>
                          <div class="text-xs font-bold text-pink-600">{{ formatNum((getDetail(wf.thread_id)!.analytics as any).likes) }}</div>
                        </div>
                      </div>
                      <div v-if="(getDetail(wf.thread_id)!.analytics as any)?.insights?.length">
                        <div class="text-[10px] text-emerald-500 font-medium mb-0.5">{{ t('showcase.detail.insights') }}</div>
                        <ul class="space-y-0.5">
                          <li v-for="(insight, i) in (getDetail(wf.thread_id)!.analytics as any).insights.slice(0, 3)" :key="i" class="text-xs text-slate-500 flex gap-1">
                            <span class="text-emerald-500">+</span>
                            <span class="line-clamp-1">{{ insight }}</span>
                          </li>
                        </ul>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.ripple_prediction && Object.keys(getDetail(wf.thread_id)!.ripple_prediction!).length > 0" class="p-2 rounded-lg bg-violet-50 border border-violet-100">
                        <div class="text-[10px] text-violet-500 font-medium mb-0.5">Ripple</div>
                        <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.viral_probability != null">{{ t('replay.viralProb') }} {{ (getDetail(wf.thread_id)!.ripple_prediction!.viral_probability! * 100).toFixed(1) }}%</div>
                        <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.estimated_reach != null">{{ t('replay.estReach') }} {{ formatNum(getDetail(wf.thread_id)!.ripple_prediction!.estimated_reach!) }}</div>
                      </div>
                    </div>
                  </div>
                </template>
                <div v-else class="text-xs text-slate-400">{{ t('common.loadingState') }}</div>
              </div>
            </div>
          </template>

          <!-- Other workflows -->
          <template v-if="otherWorkflows.length > 0">
            <div v-for="wf in otherWorkflows" :key="wf.thread_id" class="rounded-xl bg-white border border-slate-200/60 shadow-sm p-4 hover:shadow-md transition-shadow cursor-pointer" @click="goReplay(wf.thread_id)">
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-slate-400" />
                <span class="text-sm text-slate-600 font-mono">{{ wf.thread_id.slice(0, 8) }}</span>
                <span class="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">{{ statusLabel(wf.status) }}</span>
                <span class="text-xs text-slate-400">{{ formatDate(wf.created_at) }}</span>
              </div>
              <div v-if="wf.error" class="mt-2 text-xs text-rose-500">{{ wf.error }}</div>
            </div>
          </template>
        </div>

        <!-- Footer -->
        <div class="mt-10 py-4 text-center text-xs text-slate-400 border-t border-slate-200/60">
          {{ t('showcase.footer') }}
        </div>
      </template>
    </main>
  </div>
</template>