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

const stepsVisible = ref(false)
onMounted(() => {
  setTimeout(() => { stepsVisible.value = true }, 200)
})

type IconVariant = 'pink' | 'cyan' | 'purple' | 'peach' | 'white'

// Pipeline step definitions
const howItWorksSteps: Array<{
  key: string
  icon: string
  color: string        // primary color class for glow
  iconVariant: IconVariant
  borderColor: string  // border color class for station node
  iconColor: string    // text color class for icon
}> = [
  { key: 'scouting', icon: 'Search', color: 'bg-rose-500', iconVariant: 'pink', borderColor: 'border-rose-400', iconColor: 'text-rose-500' },
  { key: 'planning', icon: 'ClipboardList', color: 'bg-teal-500', iconVariant: 'cyan', borderColor: 'border-teal-400', iconColor: 'text-teal-500' },
  { key: 'creating', icon: 'Pencil', color: 'bg-amber-500', iconVariant: 'peach', borderColor: 'border-amber-400', iconColor: 'text-amber-500' },
  { key: 'reviewing', icon: 'Clock', color: 'bg-violet-500', iconVariant: 'purple', borderColor: 'border-violet-400', iconColor: 'text-violet-500' },
  { key: 'publishing', icon: 'Upload', color: 'bg-emerald-500', iconVariant: 'cyan', borderColor: 'border-emerald-400', iconColor: 'text-emerald-500' },
  { key: 'analyzing', icon: 'BarChart3', color: 'bg-sky-500', iconVariant: 'cyan', borderColor: 'border-sky-400', iconColor: 'text-sky-500' },
]

// Ellipse parameters for desktop loop layout
const ellipseRxPct = 36   // semi-major axis as % of container width
const ellipseRyPct = 38   // semi-minor axis as % of container height
const nodeSize = 48       // circle node diameter in px

function stepStyle(i: number, containerW: number): Record<string, string> {
  const rx = containerW * ellipseRxPct / 100
  const ry = 420 * ellipseRyPct / 100
  const angleDeg = i * 60 - 90
  const angleRad = angleDeg * Math.PI / 180
  const x = rx * Math.cos(angleRad)
  const y = ry * Math.sin(angleRad)
  return {
    transitionDelay: `${i * 100}ms`,
    left: `calc(50% + ${x}px - ${nodeSize / 2}px)`,
    top: `calc(50% + ${y}px - ${nodeSize / 2}px)`,
  }
}

// Container width ref for responsive ellipse
const containerW = ref(1200)
const loopContainer = ref<HTMLElement | null>(null)

onMounted(() => {
  const updateW = () => {
    if (loopContainer.value) containerW.value = loopContainer.value.clientWidth
  }
  updateW()
  window.addEventListener('resize', updateW)
})

// SVG viewBox dimensions (match container)
const svgCx = computed(() => containerW.value / 2)
const svgCy = 210
const svgRx = computed(() => containerW.value * ellipseRxPct / 100)
const svgRy = computed(() => 420 * ellipseRyPct / 100)

// animateMotion path: full clockwise ellipse from top
const loopMotionPath = computed(() => {
  const cx = svgCx.value
  const topY = svgCy - svgRy.value
  const bottomY = svgCy + svgRy.value
  return `M${cx},${topY} A${svgRx.value},${svgRy.value} 0 1,1 ${cx},${bottomY} A${svgRx.value},${svgRy.value} 0 1,1 ${cx},${topY}`
})
</script>

<template>
  <div class="min-h-screen bg-gradient-to-b from-slate-50 to-white text-slate-800 relative overflow-hidden">
    <!-- Subtle decorative elements -->
    <div class="absolute top-0 right-0 w-[500px] h-[500px] pointer-events-none opacity-30" style="background: radial-gradient(circle, rgba(244,63,94,0.08) 0%, transparent 60%);" />
    <div class="absolute bottom-0 left-0 w-[400px] h-[400px] pointer-events-none opacity-20" style="background: radial-gradient(circle, rgba(20,184,166,0.08) 0%, transparent 60%);" />

    <!-- Nav -->
    <nav class="relative z-20 bg-white border-b border-slate-200/60">
      <div class="max-w-[1200px] mx-auto px-3 md:px-6 h-14 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-rose-500 to-amber-400 flex items-center justify-center shadow-md shadow-rose-500/20">
            <AppIcon name="Rocket" size="sm" variant="white" />
          </div>
          <div>
            <h1 class="text-base font-bold tracking-tight text-slate-800">{{ t('showcase.title') }}</h1>
            <p class="text-[11px] text-slate-400 -mt-0.5">{{ t('showcase.subtitle') }}</p>
          </div>
        </div>
        <button @click="goDashboard" class="px-4 py-1.5 rounded-lg bg-rose-500 hover:bg-rose-600 text-xs font-medium text-white transition-colors shadow-sm shadow-rose-500/20">
          {{ t('showcase.dashboard') }}
        </button>
      </div>
    </nav>

    <main class="max-w-[1200px] mx-auto px-3 md:px-6 py-4 md:py-6 relative z-10" :class="error || isEmpty ? 'flex items-center justify-center min-h-[calc(100vh-3.5rem)]' : ''">
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
        <!-- Hero: title + subtitle -->
        <div class="mb-6 md:mb-8">
          <h2 class="text-2xl md:text-3xl font-bold text-slate-800 tracking-tight">{{ t('showcase.heroTitle') }}</h2>
          <p class="text-sm text-slate-500 mt-1.5 max-w-lg">{{ t('showcase.heroDesc') }}</p>
        </div>

        <!-- Closed-loop pipeline: elliptical loop with circular nodes -->
        <div class="mb-8 md:mb-10 relative">
          <!-- Section title -->
          <div class="text-xs font-medium text-slate-400 uppercase tracking-widest mb-3">{{ t('showcase.pipelineLabel') }}</div>

          <!-- Desktop: elliptical loop with SVG path + circular nodes -->
          <div ref="loopContainer" class="hidden md:block relative" style="height: 420px;">
            <!-- Background SVG: elliptical path + comet animation -->
            <svg class="absolute inset-0 w-full h-full pointer-events-none" :viewBox="`0 0 ${containerW} 420`" preserveAspectRatio="xMidYMid meet" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="loop-grad" x1="0" :y1="svgCy" :x2="containerW" :y2="svgCy" gradientUnits="userSpaceOnUse">
                  <stop stop-color="#f43f5e" />
                  <stop offset="0.2" stop-color="#f59e0b" />
                  <stop offset="0.4" stop-color="#10b981" />
                  <stop offset="0.6" stop-color="#0ea5e9" />
                  <stop offset="0.8" stop-color="#8b5cf6" />
                  <stop offset="1" stop-color="#f43f5e" />
                </linearGradient>
                <!-- Comet gradient: bright head → fading tail -->
                <linearGradient id="comet-grad" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stop-color="#fff" stop-opacity="1" />
                  <stop offset="20%" stop-color="#f43f5e" stop-opacity="0.9" />
                  <stop offset="60%" stop-color="#8b5cf6" stop-opacity="0.3" />
                  <stop offset="100%" stop-color="#0ea5e9" stop-opacity="0" />
                </linearGradient>
                <!-- Soft glow for the comet head -->
                <filter id="comet-glow" x="-200%" y="-200%" width="500%" height="500%">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="b" />
                  <feMerge>
                    <feMergeNode in="b" />
                    <feMergeNode in="b" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
                <!-- Subtle ambient glow for the arc -->
                <filter id="arc-glow" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="b" />
                  <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              </defs>

              <!-- Soft ambient glow arc -->
              <ellipse :cx="svgCx" :cy="svgCy" :rx="svgRx" :ry="svgRy" stroke="url(#loop-grad)" stroke-width="8" fill="none" opacity="0.07" filter="url(#arc-glow)">
                <animate attributeName="opacity" values="0.05;0.09;0.05" dur="5s" repeatCount="indefinite" />
              </ellipse>

              <!-- Main elliptical loop path: clean flowing dashed line -->
              <ellipse :cx="svgCx" :cy="svgCy" :rx="svgRx" :ry="svgRy" stroke="url(#loop-grad)" stroke-width="1.5" stroke-dasharray="16 8" stroke-linecap="round" fill="none" opacity="0.45">
                <animate attributeName="stroke-dashoffset" from="0" to="-48" dur="3s" repeatCount="indefinite" />
              </ellipse>

              <!-- Single comet: bright head with elongated gradient trail -->
              <!-- Trail line (elongated behind the comet) -->
              <line x1="-50" y1="0" x2="0" y2="0" stroke="url(#comet-grad)" stroke-width="3" stroke-linecap="round" opacity="0.8" filter="url(#comet-glow)">
                <animateMotion dur="6s" repeatCount="indefinite" rotate="auto"><mpath href="#loop-motion-path" /></animateMotion>
              </line>
              <!-- Comet head: bright core -->
              <circle r="4" fill="#fff" opacity="0.95" filter="url(#comet-glow)">
                <animateMotion dur="6s" repeatCount="indefinite"><mpath href="#loop-motion-path" /></animateMotion>
              </circle>
              <!-- Comet outer halo -->
              <circle r="8" fill="none" stroke="#f43f5e" stroke-width="1.5" opacity="0.4">
                <animateMotion dur="6s" repeatCount="indefinite"><mpath href="#loop-motion-path" /></animateMotion>
                <animate attributeName="r" values="6;10;6" dur="1.5s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.3;0.5;0.3" dur="1.5s" repeatCount="indefinite" />
              </circle>

              <!-- Second comet (offset, different color) -->
              <line x1="-40" y1="0" x2="0" y2="0" stroke="url(#comet-grad)" stroke-width="2.5" stroke-linecap="round" opacity="0.7" filter="url(#comet-glow)">
                <animateMotion dur="6s" repeatCount="indefinite" begin="3s" rotate="auto"><mpath href="#loop-motion-path" /></animateMotion>
              </line>
              <circle r="3.5" fill="#fff" opacity="0.9" filter="url(#comet-glow)">
                <animateMotion dur="6s" repeatCount="indefinite" begin="3s"><mpath href="#loop-motion-path" /></animateMotion>
              </circle>
              <circle r="7" fill="none" stroke="#14b8a6" stroke-width="1.5" opacity="0.35">
                <animateMotion dur="6s" repeatCount="indefinite" begin="3s"><mpath href="#loop-motion-path" /></animateMotion>
                <animate attributeName="r" values="5;9;5" dur="1.8s" repeatCount="indefinite" />
                <animate attributeName="opacity" values="0.25;0.45;0.25" dur="1.8s" repeatCount="indefinite" />
              </circle>

              <path id="loop-motion-path" :d="loopMotionPath" fill="none" stroke="none" />
            </svg>

            <!-- Center label -->
            <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div class="text-center px-5 py-3 rounded-2xl bg-white/70 backdrop-blur-sm border border-slate-200/40 shadow-sm">
                <div class="text-sm font-bold text-slate-500">&#x27F3; {{ t('showcase.closedLoop') }}</div>
                <div class="text-[10px] text-slate-400 mt-0.5">{{ t('showcase.closedLoopDesc') }}</div>
              </div>
            </div>

            <!-- Step nodes: station-style markers on the ellipse orbit -->
            <div
              v-for="(step, i) in howItWorksSteps"
              :key="step.key"
              class="absolute transition-all duration-700 ease-out group"
              :class="stepsVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-50'"
              :style="stepStyle(i, containerW)"
            >
              <!-- Outer glow ring (subtle, on hover) -->
              <div class="absolute inset-[-6px] rounded-full opacity-0 group-hover:opacity-30 transition-opacity duration-300 blur-sm" :class="step.color" />
              <!-- Station node: white bg with colored border and icon -->
              <div class="w-[48px] h-[48px] rounded-full flex items-center justify-center bg-white border-2 shadow-md transition-all duration-300 group-hover:scale-110 group-hover:shadow-lg relative z-10" :class="[step.borderColor, step.iconColor]">
                <AppIcon :name="step.icon" size="md" :variant="step.iconVariant" />
              </div>
              <!-- Label below the node -->
              <div class="text-center mt-2">
                <div class="text-[11px] font-semibold text-slate-700 whitespace-nowrap">{{ phaseLabel(step.key as WorkflowPhase) }}</div>
              </div>
            </div>
          </div>

          <!-- Mobile: 2x3 grid with compact circular nodes -->
          <div class="md:hidden">
            <div class="grid grid-cols-3 gap-4 mb-3">
              <div
                v-for="(step, i) in howItWorksSteps"
                :key="step.key"
                class="flex flex-col items-center text-center transition-all duration-500 ease-out"
                :class="stepsVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-80'"
                :style="{ transitionDelay: `${i * 80}ms` }"
              >
                <div class="w-[40px] h-[40px] rounded-full flex items-center justify-center bg-white border-2 shadow-sm" :class="[step.borderColor, step.iconColor]">
                  <AppIcon :name="step.icon" size="sm" :variant="step.iconVariant" />
                </div>
                <div class="text-[11px] font-bold text-slate-600 mt-1">{{ phaseLabel(step.key as WorkflowPhase) }}</div>
                <div class="text-[9px] text-slate-400 line-clamp-2 mt-0.5">{{ t(`showcase.steps.${step.key}`) }}</div>
              </div>
            </div>
            <div class="flex items-center justify-center gap-2 py-1">
              <svg width="140" height="14" viewBox="0 0 140 14" fill="none"><path d="M6 7h128m0 0l-4-4m4 4l-4 4" stroke="#8b5cf6" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.4" /></svg>
              <span class="text-[10px] text-slate-400 font-medium">&#x27F3; {{ t('showcase.closedLoop') }}</span>
            </div>
          </div>
        </div>

        <!-- Workflow cards section -->
        <div class="space-y-4 md:space-y-5">
          <!-- Section title -->
          <div class="flex items-center justify-between">
            <h3 class="text-base font-bold text-slate-800">{{ t('showcase.sectionTitle') }}</h3>
            <div class="flex items-center gap-3 text-xs">
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
          </div>
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
                        <div v-if="getDetail(wf.thread_id)!.copy_content?.body_text" class="text-xs text-slate-500 mt-1.5 line-clamp-6 whitespace-pre-line">{{ getDetail(wf.thread_id)!.copy_content!.body_text }}</div>
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
                          <span v-for="ht in getDetail(wf.thread_id)!.trend_data!.hot_topics!" :key="ht.topic" class="text-[11px] px-1.5 py-0.5 rounded-full bg-rose-50 text-rose-600">{{ ht.topic }}</span>
                        </div>
                      </div>
                      <div v-if="getDetail(wf.thread_id)!.trend_data?.trending_keywords?.length">
                        <div class="text-[10px] text-slate-400 font-medium mb-1 uppercase tracking-wide">{{ t('replay.trendingKeywords') }}</div>
                        <div class="flex flex-wrap gap-1">
                          <span v-for="kw in getDetail(wf.thread_id)!.trend_data!.trending_keywords!" :key="kw" class="text-[11px] px-1.5 py-0.5 rounded-md bg-pink-50 text-pink-600 border border-pink-100">{{ kw }}</span>
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
                        <div class="grid grid-cols-2 gap-x-3 gap-y-0.5">
                          <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.viral_probability != null">{{ t('replay.viralProb') }} {{ (getDetail(wf.thread_id)!.ripple_prediction!.viral_probability! * 100).toFixed(1) }}%</div>
                          <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.estimated_reach != null">{{ t('replay.estReach') }} {{ formatNum(getDetail(wf.thread_id)!.ripple_prediction!.estimated_reach!) }}</div>
                          <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.estimated_engagement != null">{{ t('replay.estEngagement') }} {{ formatNum(getDetail(wf.thread_id)!.ripple_prediction!.estimated_engagement!) }}</div>
                          <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.confidence != null">{{ t('replay.confidence') }} {{ (getDetail(wf.thread_id)!.ripple_prediction!.confidence! * 100).toFixed(1) }}%</div>
                          <div class="text-xs text-violet-700 col-span-2" v-if="getDetail(wf.thread_id)!.ripple_prediction!.verdict">{{ t('replay.verdict') }} {{ getDetail(wf.thread_id)!.ripple_prediction!.verdict }}</div>
                        </div>
                        <div v-if="getDetail(wf.thread_id)!.ripple_pmf?.pmf_score != null" class="mt-1 pt-1 border-t border-violet-100">
                          <div class="text-xs text-violet-700">{{ t('dashboard.ripple.pmfScore') }} {{ (getDetail(wf.thread_id)!.ripple_pmf!.pmf_score! * 100).toFixed(1) }}%</div>
                        </div>
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
                          <span v-for="kw in getDetail(wf.thread_id)!.trend_data!.trending_keywords!" :key="kw" class="text-[11px] px-1.5 py-0.5 rounded-md bg-pink-50 text-pink-600 border border-pink-100">{{ kw }}</span>
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
                        <div v-if="(getDetail(wf.thread_id)!.analytics as any).collects !== undefined" class="p-1.5 rounded bg-amber-50 text-center">
                          <div class="text-[10px] text-slate-400">{{ t('showcase.detail.collects') }}</div>
                          <div class="text-xs font-bold text-amber-600">{{ formatNum((getDetail(wf.thread_id)!.analytics as any).collects) }}</div>
                        </div>
                        <div v-if="(getDetail(wf.thread_id)!.analytics as any).comments !== undefined" class="p-1.5 rounded bg-teal-50 text-center">
                          <div class="text-[10px] text-slate-400">{{ t('showcase.detail.comments') }}</div>
                          <div class="text-xs font-bold text-teal-600">{{ formatNum((getDetail(wf.thread_id)!.analytics as any).comments) }}</div>
                        </div>
                        <div v-if="(getDetail(wf.thread_id)!.analytics as any).engagement_rate !== undefined" class="p-1.5 rounded bg-violet-50 text-center col-span-2">
                          <div class="text-[10px] text-slate-400">{{ t('showcase.detail.engagementRate') }}</div>
                          <div class="text-xs font-bold text-violet-600">{{ ((getDetail(wf.thread_id)!.analytics as any).engagement_rate * 100).toFixed(1) }}%</div>
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
                        <div class="grid grid-cols-2 gap-x-3 gap-y-0.5">
                          <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.viral_probability != null">{{ t('replay.viralProb') }} {{ (getDetail(wf.thread_id)!.ripple_prediction!.viral_probability! * 100).toFixed(1) }}%</div>
                          <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.estimated_reach != null">{{ t('replay.estReach') }} {{ formatNum(getDetail(wf.thread_id)!.ripple_prediction!.estimated_reach!) }}</div>
                          <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.estimated_engagement != null">{{ t('replay.estEngagement') }} {{ formatNum(getDetail(wf.thread_id)!.ripple_prediction!.estimated_engagement!) }}</div>
                          <div class="text-xs text-violet-700" v-if="getDetail(wf.thread_id)!.ripple_prediction!.confidence != null">{{ t('replay.confidence') }} {{ (getDetail(wf.thread_id)!.ripple_prediction!.confidence! * 100).toFixed(1) }}%</div>
                          <div class="text-xs text-violet-700 col-span-2" v-if="getDetail(wf.thread_id)!.ripple_prediction!.verdict">{{ t('replay.verdict') }} {{ getDetail(wf.thread_id)!.ripple_prediction!.verdict }}</div>
                        </div>
                        <div v-if="getDetail(wf.thread_id)!.ripple_pmf?.pmf_score != null" class="mt-1 pt-1 border-t border-violet-100">
                          <div class="text-xs text-violet-700">{{ t('dashboard.ripple.pmfScore') }} {{ (getDetail(wf.thread_id)!.ripple_pmf!.pmf_score! * 100).toFixed(1) }}%</div>
                        </div>
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

<style scoped>
@keyframes breathe {
  0%, 100% { transform: scale(1); opacity: 0.12; }
  50% { transform: scale(1.15); opacity: 0.22; }
}
</style>