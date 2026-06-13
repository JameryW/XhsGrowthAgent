<script setup lang="ts">
import { onMounted, ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import WorkflowCardBody from '@/components/WorkflowCardBody.vue'
import { listWorkflows, getWorkflowStatus } from '@/api/workflow'
import type { WorkflowListItem, WorkflowPhase, WorkflowStatus, WorkflowStateResponse } from '@/types/workflow'

const { t } = useI18n()
const router = useRouter()

const workflows = ref<WorkflowListItem[]>([])
const workflowDetails = ref<Map<string, WorkflowStateResponse>>(new Map())
const loadingDetailIds = ref<Set<string>>(new Set())
const listLoaded = ref(false)
const error = ref<string | null>(null)

// Filter & sort state
type StatusFilter = 'all' | 'running' | 'completed' | 'needs_attention'
type ModeFilter = 'all' | 'trend' | 'brief'
type SortKey = 'updated' | 'progress' | 'created'

const statusFilter = ref<StatusFilter>('all')
const modeFilter = ref<ModeFilter>('all')
const sortKey = ref<SortKey>('updated')

// Pagination
const visibleCount = ref(8)
const ITEMS_PER_PAGE = 8

// Stats computed from list data (no detail fetch needed)
const stats = computed(() => {
  const all = workflows.value
  const running = all.filter(w => ['running', 'awaiting_review', 'awaiting_choice', 'awaiting_draft', 'awaiting_brief', 'awaiting_ripple_decision', 'awaiting_blogger_selection'].includes(w.status))
  const completed = all.filter(w => w.status === 'completed')
  const needsAttention = all.filter(w => ['error', 'stale', 'paused', 'cancelled'].includes(w.status))
  const avgProgress = all.length > 0
    ? Math.round(all.reduce((sum, w) => sum + w.progress_percent, 0) / all.length)
    : 0
  return {
    total: all.length,
    running: running.length,
    completed: completed.length,
    needsAttention: needsAttention.length,
    avgProgress,
  }
})

// Filtered + sorted workflows
const filteredWorkflows = computed(() => {
  let result = [...workflows.value]

  // Status filter
  if (statusFilter.value === 'running') {
    result = result.filter(w => ['running', 'awaiting_review', 'awaiting_choice', 'awaiting_draft', 'awaiting_brief', 'awaiting_ripple_decision', 'awaiting_blogger_selection'].includes(w.status))
  } else if (statusFilter.value === 'completed') {
    result = result.filter(w => w.status === 'completed')
  } else if (statusFilter.value === 'needs_attention') {
    result = result.filter(w => ['error', 'stale', 'paused', 'cancelled'].includes(w.status))
  }

  // Mode filter
  if (modeFilter.value !== 'all') {
    result = result.filter(w => w.workflow_mode === modeFilter.value)
  }

  // Sort
  if (sortKey.value === 'updated') {
    result.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
  } else if (sortKey.value === 'progress') {
    result.sort((a, b) => b.progress_percent - a.progress_percent)
  } else if (sortKey.value === 'created') {
    result.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
  }

  return result
})

const visibleWorkflows = computed(() => filteredWorkflows.value.slice(0, visibleCount.value))
const hasMore = computed(() => visibleCount.value < filteredWorkflows.value.length)

function loadMore() {
  visibleCount.value += ITEMS_PER_PAGE
}

// Fetch list first (fast), then lazy-load details for visible cards
async function fetchWorkflows() {
  error.value = null
  try {
    const result = await listWorkflows({ limit: 50 })
    workflows.value = result.workflows
    listLoaded.value = true
  } catch (e: any) {
    error.value = e.message
  }
}

// Lazy-load detail for a specific workflow
async function loadDetail(threadId: string) {
  if (workflowDetails.value.has(threadId) || loadingDetailIds.value.has(threadId)) return
  loadingDetailIds.value.add(threadId)
  try {
    const state = await getWorkflowStatus(threadId)
    workflowDetails.value.set(threadId, state)
  } catch {
    // Skip failed detail fetches
  } finally {
    loadingDetailIds.value.delete(threadId)
  }
}

// Load details for visible cards
function loadVisibleDetails() {
  for (const wf of visibleWorkflows.value) {
    loadDetail(wf.thread_id)
  }
}

// Watch visible list and load details on change
watch(visibleWorkflows, () => {
  loadVisibleDetails()
}, { immediate: true })

onMounted(fetchWorkflows)

function getDetail(threadId: string): WorkflowStateResponse | undefined {
  return workflowDetails.value.get(threadId)
}

function isDetailLoading(threadId: string): boolean {
  return loadingDetailIds.value.has(threadId)
}

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

const phaseAlias: Partial<Record<WorkflowPhase, string>> = {
  briefing: 'scouting',
  engaging: 'publishing',
}

function pipelineProgress(phase: WorkflowPhase): number {
  const mapped = phaseAlias[phase] || phase
  const idx = pipelineSteps.indexOf(mapped)
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

const isEmpty = computed(() => listLoaded.value && workflows.value.length === 0)

// Featured workflow: first completed or running workflow with the most progress
const featuredWorkflow = computed<WorkflowListItem | null>(() => {
  const completed = workflows.value.filter(w => w.status === 'completed' && !w.dry_run)
  if (completed.length > 0) return completed[0]
  const running = workflows.value.filter(w => w.status === 'running')
  if (running.length > 0) return running[0]
  return null
})

const featuredDetail = computed<WorkflowStateResponse | undefined>(() => {
  if (!featuredWorkflow.value) return undefined
  return workflowDetails.value.get(featuredWorkflow.value.thread_id)
})

// Pipeline step definitions (for both strip and ellipse)
type IconVariant = 'pink' | 'cyan' | 'purple' | 'peach' | 'white'

const howItWorksSteps: Array<{
  key: string
  icon: string
  color: string
  iconVariant: IconVariant
  borderColor: string
  iconColor: string
  glowColor: string
}> = [
  { key: 'scouting', icon: 'Search', color: 'bg-rose-500', iconVariant: 'pink', borderColor: 'border-rose-400', iconColor: 'text-rose-500', glowColor: 'rose' },
  { key: 'planning', icon: 'ClipboardList', color: 'bg-teal-500', iconVariant: 'cyan', borderColor: 'border-teal-400', iconColor: 'text-teal-500', glowColor: 'teal' },
  { key: 'creating', icon: 'Pencil', color: 'bg-amber-500', iconVariant: 'peach', borderColor: 'border-amber-400', iconColor: 'text-amber-500', glowColor: 'amber' },
  { key: 'reviewing', icon: 'Clock', color: 'bg-violet-500', iconVariant: 'purple', borderColor: 'border-violet-400', iconColor: 'text-violet-500', glowColor: 'violet' },
  { key: 'publishing', icon: 'Upload', color: 'bg-emerald-500', iconVariant: 'cyan', borderColor: 'border-emerald-400', iconColor: 'text-emerald-500', glowColor: 'emerald' },
  { key: 'analyzing', icon: 'BarChart3', color: 'bg-sky-500', iconVariant: 'cyan', borderColor: 'border-sky-400', iconColor: 'text-sky-500', glowColor: 'sky' },
]

// Node state classes for hover / active / completed effects
function nodeGlowClass(step: { glowColor: string }): string {
  const map: Record<string, string> = {
    rose: 'node-glow-rose',
    teal: 'node-glow-teal',
    amber: 'node-glow-amber',
    violet: 'node-glow-violet',
    emerald: 'node-glow-emerald',
    sky: 'node-glow-sky',
  }
  return map[step.glowColor] || ''
}

// Ellipse parameters for desktop loop layout
const ellipseRxPct = 36
const ellipseRyPct = 38
const nodeSize = 68

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

const containerW = ref(1200)
const loopContainer = ref<HTMLElement | null>(null)

const stepsVisible = ref(false)

onMounted(() => {
  const updateW = () => {
    if (loopContainer.value) containerW.value = loopContainer.value.clientWidth
  }
  updateW()
  window.addEventListener('resize', updateW)
  setTimeout(() => { stepsVisible.value = true }, 200)
})

const svgCx = computed(() => containerW.value / 2)
const svgCy = 210
const svgRx = computed(() => containerW.value * ellipseRxPct / 100)
const svgRy = computed(() => 420 * ellipseRyPct / 100)

const loopMotionPath = computed(() => {
  const cx = svgCx.value
  const topY = svgCy - svgRy.value
  const bottomY = svgCy + svgRy.value
  return `M${cx},${topY} A${svgRx.value},${svgRy.value} 0 1,1 ${cx},${bottomY} A${svgRx.value},${svgRy.value} 0 1,1 ${cx},${topY}`
})

function cardStatusColor(wf: WorkflowListItem): string {
  if (['running', 'awaiting_review', 'awaiting_choice', 'awaiting_draft', 'awaiting_brief', 'awaiting_ripple_decision', 'awaiting_blogger_selection'].includes(wf.status)) return 'liquid-glass-teal'
  if (wf.status === 'completed') return 'liquid-glass-emerald'
  if (wf.status === 'error') return 'liquid-glass-rose'
  return 'liquid-glass'
}

function cardDotClass(wf: WorkflowListItem): string {
  if (['running', 'awaiting_review', 'awaiting_choice', 'awaiting_draft', 'awaiting_brief', 'awaiting_ripple_decision', 'awaiting_blogger_selection'].includes(wf.status)) return 'bg-teal-500 animate-pulse'
  if (wf.status === 'completed') return 'bg-emerald-500'
  if (wf.status === 'error') return 'bg-rose-500'
  if (wf.status === 'paused') return 'bg-slate-400'
  return 'bg-amber-400'
}

function cardBadgeClass(wf: WorkflowListItem): string {
  if (['running', 'awaiting_review', 'awaiting_choice', 'awaiting_draft', 'awaiting_brief', 'awaiting_ripple_decision', 'awaiting_blogger_selection'].includes(wf.status)) return 'bg-teal-100 text-teal-700'
  if (wf.status === 'completed') return 'bg-emerald-100 text-emerald-700'
  if (wf.status === 'error') return 'bg-rose-100 text-rose-700'
  return 'bg-slate-100 text-slate-600'
}
</script>

<template>
  <div class="min-h-screen text-slate-800 relative overflow-hidden">
    <!-- Subtle decorative elements -->
    <div class="absolute top-0 right-0 w-[500px] h-[500px] pointer-events-none opacity-30" style="background: radial-gradient(circle, rgba(244,63,94,0.08) 0%, transparent 60%);" />
    <div class="absolute bottom-0 left-0 w-[400px] h-[400px] pointer-events-none opacity-20" style="background: radial-gradient(circle, rgba(20,184,166,0.08) 0%, transparent 60%);" />
    <!-- Subtle ambient orb -->
	    <div class="absolute top-[30%] left-[15%] w-[250px] h-[250px] rounded-full pointer-events-none opacity-[0.03] bg-violet-400" />

    <!-- Nav -->
    <nav class="relative z-20 liquid-glass-nav border-b border-white/15">
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

    <main class="max-w-[1200px] mx-auto px-3 md:px-6 py-4 md:py-6 relative z-10">
      <!-- Error -->
      <div v-if="error" class="rounded-xl p-8 liquid-glass-rose liquid-glass-hover text-center max-w-md w-full mx-auto">
        <div class="w-12 h-12 rounded-xl bg-rose-100 flex items-center justify-center mx-auto mb-4">
          <AppIcon name="AlertCircle" size="lg" variant="pink" />
        </div>
        <p class="text-sm text-rose-700 font-medium">{{ t('common.apiError') }}</p>
        <p class="text-xs text-rose-500/70 mt-2">{{ error }}</p>
        <button @click="fetchWorkflows" class="mt-4 px-5 py-2 rounded-lg bg-rose-600 text-white hover:bg-rose-700 text-xs font-medium transition-colors shadow-sm">{{ t('common.retry') }}</button>
      </div>

      <!-- Empty -->
      <div v-else-if="isEmpty" class="py-20 text-center max-w-md w-full mx-auto">
        <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center mx-auto mb-5 shadow-sm border border-slate-200/60">
          <AppIcon name="Inbox" size="lg" variant="cyan" />
        </div>
        <p class="text-sm text-slate-600 font-semibold">{{ t('showcase.empty') }}</p>
        <p class="text-xs text-slate-400 mt-1.5">{{ t('showcase.emptyDesc') }}</p>
      </div>

      <!-- Content -->
      <template v-else>
        <!-- ══════════════════════════════════════════════════════════════
             Layer 1: Closed-loop pipeline — elliptical loop animation
             ══════════════════════════════════════════════════════════════ -->
        <div class="mb-4 md:mb-6 relative">
          <div class="text-xs font-medium text-slate-400 uppercase tracking-widest mb-3">{{ t('showcase.pipelineLabel') }}</div>

          <!-- Desktop: elliptical loop with SVG path + circular nodes -->
          <div ref="loopContainer" class="hidden md:block relative" style="height: 420px;">
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
                <linearGradient id="comet-grad" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stop-color="#fff" stop-opacity="1" />
                  <stop offset="15%" stop-color="#f43f5e" stop-opacity="0.9" />
                  <stop offset="50%" stop-color="#8b5cf6" stop-opacity="0.3" />
                  <stop offset="100%" stop-color="#0ea5e9" stop-opacity="0" />
                </linearGradient>
                <filter id="comet-glow" x="-200%" y="-200%" width="500%" height="500%">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="b" />
                  <feMerge>
                    <feMergeNode in="b" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
                <filter id="arc-glow" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="b" />
                  <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              </defs>

              <!-- Layer 1: soft glow path -->
              <ellipse :cx="svgCx" :cy="svgCy" :rx="svgRx" :ry="svgRy" stroke="url(#loop-grad)" stroke-width="12" fill="none" opacity="0.06" filter="url(#arc-glow)">
                <animate attributeName="opacity" values="0.04;0.08;0.04" dur="6s" repeatCount="indefinite" />
              </ellipse>

              <!-- Layer 2: fine dashed flow -->
              <ellipse :cx="svgCx" :cy="svgCy" :rx="svgRx" :ry="svgRy" stroke="url(#loop-grad)" stroke-width="1.5" stroke-dasharray="16 8" stroke-linecap="round" fill="none" opacity="0.4">
                <animate attributeName="stroke-dashoffset" from="0" to="-48" dur="3s" repeatCount="indefinite" />
              </ellipse>

              <!-- Energy pulses at node positions -->
              <g opacity="0.25">
                <circle v-for="n in 6" :key="'pulse-'+n" :cx="svgCx + (Math.cos((n * 60 - 90) * Math.PI / 180) * svgRx)" :cy="svgCy + (Math.sin((n * 60 - 90) * Math.PI / 180) * svgRy)" r="0" fill="none" :stroke="['#f43f5e','#14b8a6','#f59e0b','#8b5cf6','#10b981','#0ea5e9'][n]" stroke-width="1">
                  <animate attributeName="r" values="0;10;0" :dur="`${4 + n * 0.5}s`" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="0;0.4;0" :dur="`${4 + n * 0.5}s`" repeatCount="indefinite" />
                </circle>
              </g>

              <!-- Comet -->
              <line x1="-60" y1="0" x2="0" y2="0" stroke="url(#comet-grad)" stroke-width="3" stroke-linecap="round" opacity="0.7" filter="url(#comet-glow)">
                <animateMotion dur="8s" repeatCount="indefinite" rotate="auto"><mpath href="#loop-motion-path" /></animateMotion>
              </line>
              <circle r="4" fill="#fff" opacity="0.9" filter="url(#comet-glow)">
                <animateMotion dur="8s" repeatCount="indefinite"><mpath href="#loop-motion-path" /></animateMotion>
              </circle>

              <path id="loop-motion-path" :d="loopMotionPath" fill="none" stroke="none" />
            </svg>

            <!-- Center label: glass highlight, not big card -->
            <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div class="text-center px-5 py-3 rounded-2xl node-center-glass">
                <div class="text-sm font-bold text-slate-500">&#x27F3; {{ t('showcase.closedLoop') }}</div>
                <div class="text-[10px] text-slate-400 mt-0.5">{{ t('showcase.closedLoopDesc') }}</div>
              </div>
            </div>

            <!-- Loop nodes: with hover glow, breathing ring, completed sweep -->
            <div
              v-for="(step, i) in howItWorksSteps"
              :key="step.key"
              class="absolute transition-all duration-700 ease-out group"
              :class="[stepsVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-50', nodeGlowClass(step)]"
              :style="stepStyle(i, containerW)"
            >
              <!-- Hover: outer glow -->
	              <div class="absolute inset-[-8px] rounded-full opacity-0 group-hover:opacity-50 transition-opacity duration-300 blur-md" :class="step.color" />
	              <!-- Node circle -->
	              <div class="w-[68px] h-[68px] rounded-full flex items-center justify-center bg-white border-2 shadow-lg transition-all duration-300 group-hover:scale-110 group-hover:shadow-xl relative z-10" :class="[step.borderColor, step.iconColor]">
	                <AppIcon :name="step.icon" size="lg" :variant="step.iconVariant" />
	              </div>
	              <div class="text-center mt-2">
                <div class="text-[11px] font-semibold text-slate-700 whitespace-nowrap">{{ phaseLabel(step.key as WorkflowPhase) }}</div>
              </div>
            </div>
          </div>

          <!-- Mobile: 2x3 grid with compact circular nodes + glow -->
          <div class="md:hidden">
            <div class="grid grid-cols-3 gap-4 mb-3">
              <div
                v-for="(step, i) in howItWorksSteps"
                :key="step.key"
                class="flex flex-col items-center text-center transition-all duration-500 ease-out group"
                :class="stepsVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-80'"
                :style="{ transitionDelay: `${i * 80}ms` }"
              >
                <!-- Mobile node glow -->
	                <div class="relative">
	                  <div class="absolute inset-[-6px] rounded-full opacity-10 group-hover:opacity-35 transition-opacity duration-300 blur-sm" :class="step.color" />
                  <div class="w-[48px] h-[48px] rounded-full flex items-center justify-center bg-white border-2 shadow-sm group-hover:shadow-md transition-all duration-300 group-hover:scale-105" :class="[step.borderColor, step.iconColor]">
                    <AppIcon :name="step.icon" size="md" :variant="step.iconVariant" />
                  </div>
                </div>
                <div class="text-[11px] font-bold text-slate-600 mt-1">{{ phaseLabel(step.key as WorkflowPhase) }}</div>
                <div class="text-[9px] text-slate-400 line-clamp-2 mt-0.5">{{ t(`showcase.steps.${step.key}`) }}</div>
              </div>
            </div>
            <!-- Mobile connecting lines: lightweight animated SVG -->
            <div class="flex items-center justify-center gap-2 py-1">
              <svg width="160" height="18" viewBox="0 0 160 18" fill="none" class="mobile-loop-svg">
                <defs>
                  <linearGradient id="mobile-loop-grad" x1="0" y1="9" x2="160" y2="9" gradientUnits="userSpaceOnUse">
                    <stop stop-color="#f43f5e" />
                    <stop offset="0.3" stop-color="#14b8a6" />
                    <stop offset="0.6" stop-color="#8b5cf6" />
                    <stop offset="1" stop-color="#f43f5e" />
                  </linearGradient>
                </defs>
                <path d="M6 9h148m0 0l-4-4m4 4l-4 4" stroke="url(#mobile-loop-grad)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.5" />
                <!-- Animated traveling dot -->
                <circle r="2.5" fill="#14b8a6" opacity="0.7">
                  <animateMotion dur="4s" repeatCount="indefinite" path="M6 9 L154 9" />
                  <animate attributeName="opacity" values="0.5;0.9;0.5" dur="2s" repeatCount="indefinite" />
                </circle>
                <circle r="2" fill="#8b5cf6" opacity="0.5">
                  <animateMotion dur="4s" repeatCount="indefinite" begin="2s" path="M6 9 L154 9" />
                  <animate attributeName="opacity" values="0.3;0.7;0.3" dur="2s" repeatCount="indefinite" />
                </circle>
              </svg>
              <span class="text-[10px] text-slate-400 font-medium">&#x27F3; {{ t('showcase.closedLoop') }}</span>
            </div>
          </div>
        </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 2: Stats — compact horizontal strip
             ══════════════════════════════════════════════════════════════ -->
        <div class="mb-5 md:mb-6 py-2.5 px-3 rounded-xl liquid-glass-inset flex items-center justify-center gap-5 md:gap-8">
          <div class="flex items-center gap-2">
            <div class="text-lg md:text-xl font-bold text-slate-700 tabular-nums">{{ stats.total }}</div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.total') }}</div>
          </div>
          <div class="w-px h-5 bg-slate-200/60" />
          <div class="flex items-center gap-2">
            <div class="text-lg md:text-xl font-bold text-teal-600 tabular-nums">{{ stats.running }}</div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.running') }}</div>
          </div>
          <div class="w-px h-5 bg-slate-200/60" />
          <div class="flex items-center gap-2">
            <div class="text-lg md:text-xl font-bold text-emerald-600 tabular-nums">{{ stats.completed }}</div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.completed') }}</div>
          </div>
          <template v-if="stats.needsAttention > 0">
            <div class="w-px h-5 bg-slate-200/60" />
            <div class="flex items-center gap-2">
              <div class="text-lg md:text-xl font-bold text-rose-600 tabular-nums">{{ stats.needsAttention }}</div>
              <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.needsAttention') }}</div>
            </div>
          </template>
          <div class="w-px h-5 bg-slate-200/60" />
          <div class="flex items-center gap-2">
            <div class="text-lg md:text-xl font-bold text-violet-600 tabular-nums">{{ stats.avgProgress }}%</div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.avgProgress') }}</div>
          </div>
        </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 3: Featured workflow
             ══════════════════════════════════════════════════════════════ -->
        <div v-if="featuredWorkflow && featuredDetail" class="mb-5 md:mb-6 rounded-xl liquid-glass-emerald liquid-glass-hover overflow-hidden cursor-pointer" @click="goReplay(featuredWorkflow.thread_id)">
          <div class="px-4 md:px-5 py-3 flex items-center justify-between border-b border-white/10 liquid-glass-inset">
            <div class="flex items-center gap-2">
              <span class="w-2.5 h-2.5 rounded-full bg-emerald-500" />
              <span class="text-sm font-semibold text-slate-800">{{ t('showcase.featured') }}</span>
              <span class="text-xs px-2 py-0.5 rounded-full bg-rose-50 text-rose-600">live</span>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-xs text-slate-400">{{ formatDate(featuredWorkflow.created_at) }}</span>
              <AppIcon name="ArrowRight" size="sm" variant="cyan" class="text-slate-400" />
            </div>
          </div>
          <WorkflowCardBody :detail="featuredDetail" />
        </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 4: Filter bar
             ══════════════════════════════════════════════════════════════ -->
        <div class="flex flex-wrap items-center gap-2 mb-4">
          <div class="flex items-center gap-1 p-0.5 rounded-lg bg-slate-100/80">
            <button
              v-for="f in ([
                { key: 'all', label: t('showcase.filter.all') },
                { key: 'running', label: t('showcase.stats.running') },
                { key: 'completed', label: t('showcase.stats.completed') },
                { key: 'needs_attention', label: t('showcase.stats.needsAttention') },
              ] as const)"
              :key="f.key"
              @click="statusFilter = f.key"
              class="px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors"
              :class="statusFilter === f.key ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
            >{{ f.label }}</button>
          </div>
          <div class="flex items-center gap-1 p-0.5 rounded-lg bg-slate-100/80">
            <button
              v-for="m in ([
                { key: 'all', label: t('showcase.filter.allMode') },
                { key: 'trend', label: 'Trend' },
                { key: 'brief', label: 'Brief' },
              ] as const)"
              :key="m.key"
              @click="modeFilter = m.key"
              class="px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors"
              :class="modeFilter === m.key ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
            >{{ m.label }}</button>
          </div>
          <select v-model="sortKey" class="px-2 py-1 rounded-lg bg-slate-100/80 text-[11px] text-slate-600 font-medium border-0 outline-none cursor-pointer">
            <option value="updated">{{ t('showcase.sort.updated') }}</option>
            <option value="progress">{{ t('showcase.sort.progress') }}</option>
            <option value="created">{{ t('showcase.sort.created') }}</option>
          </select>
        </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 5: Card grid
             ══════════════════════════════════════════════════════════════ -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div
            v-for="wf in visibleWorkflows"
            :key="wf.thread_id"
            class="rounded-xl liquid-glass-hover overflow-hidden cursor-pointer transition-shadow hover:shadow-md"
            :class="[cardStatusColor(wf)]"
            @click="goReplay(wf.thread_id)"
          >
            <!-- Card header -->
            <div class="px-4 md:px-5 py-2.5 flex items-center justify-between border-b border-white/10 liquid-glass-inset">
              <div class="flex items-center gap-1.5 min-w-0">
                <span class="w-2 h-2 rounded-full shrink-0" :class="cardDotClass(wf)" />
                <span class="text-xs font-semibold text-slate-800 truncate">{{ wf.label || phaseLabel(wf.phase) }}</span>
                <span class="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" :class="cardBadgeClass(wf)">{{ statusLabel(wf.status) }}</span>
                <span v-if="wf.workflow_mode" class="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600 shrink-0">{{ wf.workflow_mode }}</span>
              </div>
              <span class="text-[10px] text-slate-400 shrink-0 ml-2">{{ formatDate(wf.updated_at || wf.created_at) }}</span>
            </div>
            <!-- Progress bar -->
            <div class="px-4 pt-2 flex items-center gap-2">
              <div class="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div class="h-full rounded-full transition-all duration-500" :class="wf.status === 'completed' ? 'bg-emerald-400' : ['running', 'awaiting_review', 'awaiting_choice', 'awaiting_draft', 'awaiting_brief', 'awaiting_ripple_decision', 'awaiting_blogger_selection'].includes(wf.status) ? 'bg-teal-400' : 'bg-slate-300'" :style="{ width: `${wf.progress_percent}%` }" />
              </div>
              <span class="text-[10px] text-slate-400 tabular-nums shrink-0">{{ wf.progress_percent }}%</span>
            </div>
            <!-- Card body -->
            <div class="relative min-h-[60px]">
              <WorkflowCardBody v-if="getDetail(wf.thread_id)" :detail="getDetail(wf.thread_id)" />
              <div v-else-if="isDetailLoading(wf.thread_id)" class="px-4 py-4 space-y-2">
                <div class="h-3 w-3/4 rounded bg-slate-100 animate-pulse" />
                <div class="h-3 w-1/2 rounded bg-slate-100 animate-pulse" />
                <div class="h-3 w-2/3 rounded bg-slate-100 animate-pulse" />
              </div>
              <div v-else class="px-4 py-3 text-xs text-slate-400">{{ phaseLabel(wf.phase) }}</div>
            </div>
            <!-- Error message -->
            <div v-if="wf.error" class="px-4 pb-2">
              <p class="text-[10px] text-rose-500 line-clamp-1">{{ wf.error }}</p>
            </div>
            <!-- Card footer -->
            <div class="px-4 pb-2.5 pt-1 flex items-center justify-between">
              <div class="hidden md:flex items-center gap-0.5">
                <template v-for="(_step, i) in pipelineSteps" :key="i">
                  <div class="w-3 h-1 rounded-full transition-colors" :class="i < pipelineProgress(wf.phase) ? (wf.status === 'completed' ? 'bg-emerald-400' : 'bg-teal-400') : 'bg-slate-200'" />
                </template>
              </div>
              <span class="text-[10px] text-rose-500 font-medium ml-auto flex items-center gap-0.5 hover:text-rose-600">
                {{ t('showcase.viewDetail') }}
                <AppIcon name="ArrowRight" size="xs" variant="pink" />
              </span>
            </div>
          </div>
        </div>

        <!-- Load more -->
        <div v-if="hasMore" class="mt-6 text-center">
          <button @click="loadMore" class="px-6 py-2 rounded-lg liquid-glass hover:shadow-md text-xs font-medium text-slate-600 transition-shadow">
            {{ t('showcase.loadMore') }} ({{ filteredWorkflows.length - visibleCount }})
          </button>
        </div>

        <!-- No results after filter -->
        <div v-if="listLoaded && filteredWorkflows.length === 0 && workflows.length > 0" class="py-12 text-center">
          <p class="text-sm text-slate-400">{{ t('showcase.noResults') }}</p>
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

/* Node hover glow — per-color variant */
.node-glow-rose:hover { box-shadow: 0 0 20px 4px rgba(244, 63, 94, 0.15); }
.node-glow-teal:hover { box-shadow: 0 0 20px 4px rgba(20, 184, 166, 0.15); }
.node-glow-amber:hover { box-shadow: 0 0 20px 4px rgba(245, 158, 11, 0.15); }
.node-glow-violet:hover { box-shadow: 0 0 20px 4px rgba(139, 92, 246, 0.15); }
.node-glow-emerald:hover { box-shadow: 0 0 20px 4px rgba(16, 185, 129, 0.15); }
.node-glow-sky:hover { box-shadow: 0 0 20px 4px rgba(14, 165, 233, 0.15); }

/* Center glass highlight */
.node-center-glass {
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(30px) saturate(180%);
  -webkit-backdrop-filter: blur(30px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.35);
  box-shadow:
    0 1px 3px rgba(0, 0, 0, 0.04),
    0 4px 16px rgba(0, 0, 0, 0.02),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
}
</style>

<style>
</style>