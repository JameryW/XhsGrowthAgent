<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import AnimatedCounter from '@/components/AnimatedCounter.vue'
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
const statsReady = ref(false)

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
const DETAIL_CONCURRENCY = 3
const RUNNING_STATUSES: WorkflowStatus[] = [
  'running',
  'awaiting_review',
  'awaiting_choice',
  'awaiting_draft',
  'awaiting_brief',
  'awaiting_ripple_decision',
  'awaiting_blogger_selection',
]
const NEEDS_ATTENTION_STATUSES: WorkflowStatus[] = ['error', 'stale', 'paused', 'cancelled']

const pendingDetailIds = new Set<string>()
let activeDetailLoads = 0
let detailPumpTimer: number | null = null

function isRunningStatus(status: WorkflowStatus): boolean {
  return RUNNING_STATUSES.includes(status)
}

function isNeedsAttentionStatus(status: WorkflowStatus): boolean {
  return NEEDS_ATTENTION_STATUSES.includes(status)
}

// Stats computed from list data (no detail fetch needed)
const stats = computed(() => {
  const all = workflows.value
  const running = all.filter(w => isRunningStatus(w.status))
  const completed = all.filter(w => w.status === 'completed')
  const needsAttention = all.filter(w => isNeedsAttentionStatus(w.status))
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
    result = result.filter(w => isRunningStatus(w.status))
  } else if (statusFilter.value === 'completed') {
    result = result.filter(w => w.status === 'completed')
  } else if (statusFilter.value === 'needs_attention') {
    result = result.filter(w => isNeedsAttentionStatus(w.status))
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
    await nextTick()
    statsReady.value = true
  } catch (e: any) {
    error.value = e.message
  }
}

function queueDetail(threadId: string) {
  if (workflowDetails.value.has(threadId) || loadingDetailIds.value.has(threadId)) return
  pendingDetailIds.add(threadId)
  loadingDetailIds.value.add(threadId)
  scheduleDetailPump()
}

function scheduleDetailPump() {
  if (detailPumpTimer !== null) return
  detailPumpTimer = window.setTimeout(() => {
    detailPumpTimer = null
    pumpDetailQueue()
  }, 24)
}

function pumpDetailQueue() {
  while (activeDetailLoads < DETAIL_CONCURRENCY && pendingDetailIds.size > 0) {
    const threadId = pendingDetailIds.values().next().value as string
    pendingDetailIds.delete(threadId)
    activeDetailLoads += 1

    getWorkflowStatus(threadId)
      .then((state) => {
        workflowDetails.value.set(threadId, state)
      })
      .catch(() => {
        // Skip failed detail fetches
      })
      .finally(() => {
        loadingDetailIds.value.delete(threadId)
        activeDetailLoads -= 1
        if (pendingDetailIds.size > 0) scheduleDetailPump()
      })
  }
}

// Load details for visible cards with a small concurrency cap to keep first paint responsive.
function loadVisibleDetails() {
  if (featuredWorkflow.value) {
    queueDetail(featuredWorkflow.value.thread_id)
  }
  for (const wf of visibleWorkflows.value) {
    queueDetail(wf.thread_id)
  }
}

onMounted(fetchWorkflows)

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

function goDashboard() { router.push({ path: '/login', query: { redirect: '/start' } }) }
function goReplay(threadId: string) { router.push({ name: 'replay', params: { threadId } }) }

const isEmpty = computed(() => listLoaded.value && workflows.value.length === 0)

// Featured workflow: weighted scoring from filtered pool
const MAX_RECENCY_SECONDS = 7 * 24 * 3600 // 7 days

function featuredScore(wf: WorkflowListItem): number {
  const progressScore = wf.progress_percent / 100
  const updatedMs = new Date(wf.updated_at || wf.created_at).getTime()
  const ageSeconds = (Date.now() - updatedMs) / 1000
  const recencyScore = Math.max(0, 1 - ageSeconds / MAX_RECENCY_SECONDS)
  return 0.6 * progressScore + 0.4 * recencyScore
}

// Urgency ranking for needs_attention mode (higher = more urgent)
const ATTENTION_URGENCY: Record<string, number> = {
  error: 4,
  stale: 3,
  paused: 2,
  cancelled: 1,
}

type FeaturedMode = 'normal' | 'needs_attention'

const featuredMode = computed<FeaturedMode | null>(() => {
  if (statusFilter.value === 'needs_attention') return 'needs_attention'
  return 'normal'
})

const featuredWorkflow = computed<WorkflowListItem | null>(() => {
  // Pool: use filteredWorkflows (follows statusFilter + modeFilter)
  const pool = filteredWorkflows.value

  if (featuredMode.value === 'needs_attention') {
    // Needs attention: pick most urgent, break ties by recency
    const attention = pool
      .filter(w => w.status in ATTENTION_URGENCY)
      .sort((a, b) => {
        const urgencyDiff = (ATTENTION_URGENCY[b.status] || 0) - (ATTENTION_URGENCY[a.status] || 0)
        if (urgencyDiff !== 0) return urgencyDiff
        return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      })
    return attention[0] || null
  }

  // Normal mode: completed + all active statuses, exclude dry_run, score-based
  const eligible = pool.filter(w => {
    if (w.dry_run) return false
    return w.status === 'completed' || isRunningStatus(w.status)
  })

  if (eligible.length === 0) return null
  return eligible.reduce((best, wf) => featuredScore(wf) > featuredScore(best) ? wf : best, eligible[0])
})

const featuredDetail = computed<WorkflowStateResponse | undefined>(() => {
  if (!featuredWorkflow.value) return undefined
  return workflowDetails.value.get(featuredWorkflow.value.thread_id)
})

// Watch visible list and load details on change
watch([visibleWorkflows, featuredWorkflow], () => {
  loadVisibleDetails()
}, { immediate: true })

// Pipeline step definitions (for both strip and ellipse)
type IconVariant = 'pink' | 'cyan' | 'purple' | 'peach' | 'white'

const howItWorksSteps: Array<{
  key: string
  icon: string
  color: string
  iconVariant: IconVariant
  borderColor: string
  iconColor: string
}> = [
  { key: 'scouting', icon: 'Search', color: 'bg-rose-500', iconVariant: 'pink', borderColor: 'border-rose-200', iconColor: 'text-rose-500' },
  { key: 'planning', icon: 'ClipboardList', color: 'bg-teal-500', iconVariant: 'cyan', borderColor: 'border-teal-200', iconColor: 'text-teal-500' },
  { key: 'creating', icon: 'Pencil', color: 'bg-amber-500', iconVariant: 'peach', borderColor: 'border-amber-200', iconColor: 'text-amber-500' },
  { key: 'reviewing', icon: 'Clock', color: 'bg-violet-500', iconVariant: 'purple', borderColor: 'border-violet-200', iconColor: 'text-violet-500' },
  { key: 'publishing', icon: 'Upload', color: 'bg-emerald-500', iconVariant: 'cyan', borderColor: 'border-emerald-200', iconColor: 'text-emerald-500' },
  { key: 'analyzing', icon: 'BarChart3', color: 'bg-sky-500', iconVariant: 'cyan', borderColor: 'border-sky-200', iconColor: 'text-sky-500' },
]

function nodeGlowClass(step: { color: string }): string {
  const map: Record<string, string> = {
    'bg-rose-500': 'node-glow-rose',
    'bg-teal-500': 'node-glow-teal',
    'bg-amber-500': 'node-glow-amber',
    'bg-violet-500': 'node-glow-violet',
    'bg-emerald-500': 'node-glow-emerald',
    'bg-sky-500': 'node-glow-sky',
  }
  return map[step.color] || ''
}

// Ellipse parameters for desktop loop layout
const ellipseRxPct = 36
const ellipseRyPct = 38
const nodeSize = 88
const containerW = ref(1200)
const loopContainer = ref<HTMLElement | null>(null)
const stepsVisible = ref(false)

function stepStyle(i: number, containerWidth: number): Record<string, string> {
  const rx = containerWidth * ellipseRxPct / 100
  const ry = 460 * ellipseRyPct / 100
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

const updateLoopWidth = () => {
  if (loopContainer.value) containerW.value = loopContainer.value.clientWidth
}

onMounted(() => {
  updateLoopWidth()
  window.addEventListener('resize', updateLoopWidth)
  window.setTimeout(() => { stepsVisible.value = true }, 200)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateLoopWidth)
})

const svgCx = computed(() => containerW.value / 2)
const svgCy = 230
const svgRx = computed(() => containerW.value * ellipseRxPct / 100)
const svgRy = computed(() => 460 * ellipseRyPct / 100)

const loopMotionPath = computed(() => {
  const cx = svgCx.value
  const topY = svgCy - svgRy.value
  const bottomY = svgCy + svgRy.value
  return `M${cx},${topY} A${svgRx.value},${svgRy.value} 0 1,1 ${cx},${bottomY} A${svgRx.value},${svgRy.value} 0 1,1 ${cx},${topY}`
})

function cardStatusColor(wf: WorkflowListItem): string {
  if (isRunningStatus(wf.status)) return 'liquid-glass-teal'
  if (wf.status === 'completed') return 'liquid-glass-emerald'
  if (wf.status === 'error') return 'liquid-glass-rose'
  return 'liquid-glass'
}

function cardDotClass(wf: WorkflowListItem): string {
  if (isRunningStatus(wf.status)) return 'bg-teal-500 animate-pulse'
  if (wf.status === 'completed') return 'bg-emerald-500'
  if (wf.status === 'error') return 'bg-rose-500'
  if (wf.status === 'paused') return 'bg-slate-400'
  return 'bg-amber-400'
}

function cardBadgeClass(wf: WorkflowListItem): string {
  if (isRunningStatus(wf.status)) return 'bg-teal-100 text-teal-700'
  if (wf.status === 'completed') return 'bg-emerald-100 text-emerald-700'
  if (wf.status === 'error') return 'bg-rose-100 text-rose-700'
  return 'bg-slate-100 text-slate-600'
}

function cardProgressClass(wf: WorkflowListItem): string {
  if (wf.status === 'completed') return 'bg-emerald-400'
  if (isRunningStatus(wf.status)) return 'bg-teal-400'
  return 'bg-slate-300'
}

const visibleCards = computed(() =>
  visibleWorkflows.value.map((wf) => ({
    wf,
    detail: workflowDetails.value.get(wf.thread_id),
    isLoading: loadingDetailIds.value.has(wf.thread_id),
    statusClass: cardStatusColor(wf),
    dotClass: cardDotClass(wf),
    badgeClass: cardBadgeClass(wf),
    progressClass: cardProgressClass(wf),
    pipelineProgress: pipelineProgress(wf.phase),
    title: wf.label || phaseLabel(wf.phase),
    updatedLabel: formatDate(wf.updated_at || wf.created_at),
    phaseText: phaseLabel(wf.phase),
    statusText: statusLabel(wf.status),
  }))
)

// Deterministic pseudo-random (mulberry32) so constellation lines are stable across renders
function mulberry32(seed: number) {
  return function () {
    seed |= 0
    seed = (seed + 0x6D2B79F5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// Constellation: ~20 nodes, connect each to its 2 nearest neighbors → faint line skeleton
const constellationPath = computed(() => {
  const rnd = mulberry32(20260621)
  const W = 1200, H = 800, N = 20
  const pts = Array.from({ length: N }, () => ({ x: rnd() * W, y: rnd() * H }))
  const lines: string[] = []
  const brand = ['244,63,94', '20,184,166', '139,92,246', '245,158,11', '14,165,233']
  pts.forEach((p, i) => {
    const dists = pts
      .map((q, j) => ({ j, d: (q.x - p.x) ** 2 + (q.y - p.y) ** 2 }))
      .filter(o => o.j !== i)
      .sort((a, b) => a.d - b.d)
      .slice(0, 2)
    dists.forEach(o => {
      if (i < o.j) {
        const c = brand[(i + o.j) % brand.length]
        lines.push(`M${p.x.toFixed(1)},${p.y.toFixed(1)}L${pts[o.j].x.toFixed(1)},${pts[o.j].y.toFixed(1)}`)
        void c
      }
    })
  })
  return lines.join(' ')
})

const constellationDots = computed(() => {
  const rnd = mulberry32(20260621)
  const W = 1200, H = 800, N = 20
  return Array.from({ length: N }, () => ({ cx: +(rnd() * W).toFixed(1), cy: +(rnd() * H).toFixed(1) }))
})

</script>

<template>
  <div class="showcase-page min-h-screen text-slate-800 relative overflow-hidden">
    <!-- Ambient background layers -->
    <div class="showcase-bg-grid" aria-hidden="true" />
    <div class="showcase-bg-mesh" aria-hidden="true" />
    <div class="showcase-bg-dots" aria-hidden="true" />
    <div class="showcase-aurora" aria-hidden="true" />
    <svg class="showcase-constellation" aria-hidden="true" preserveAspectRatio="none" viewBox="0 0 1200 800">
      <path class="constellation-lines" :d="constellationPath" fill="none" stroke="url(#const-grad)" stroke-width="0.6" stroke-linecap="round" />
      <circle v-for="(d, i) in constellationDots" :key="i" :cx="d.cx" :cy="d.cy" r="1.1" fill="url(#const-grad)" />
      <defs>
        <linearGradient id="const-grad" x1="0" y1="0" x2="1200" y2="800" gradientUnits="userSpaceOnUse">
          <stop stop-color="rgba(244,63,94,0.22)" />
          <stop offset="0.5" stop-color="rgba(139,92,246,0.22)" />
          <stop offset="1" stop-color="rgba(14,165,233,0.22)" />
        </linearGradient>
      </defs>
    </svg>
    <div class="showcase-glow-amber" aria-hidden="true" />
    <div class="showcase-glow-emerald" aria-hidden="true" />
    <div class="showcase-particles" aria-hidden="true" />
    <!-- Ambient glow orbs -->
    <div class="showcase-glow-mid" aria-hidden="true" />
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
          <!-- Desktop: elliptical loop with SVG path + circular nodes -->
          <div ref="loopContainer" class="hidden md:block relative" style="height: 460px;">
            <svg class="absolute inset-0 w-full h-full pointer-events-none" :viewBox="`0 0 ${containerW} 460`" preserveAspectRatio="xMidYMid meet" fill="none" xmlns="http://www.w3.org/2000/svg">
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
                  <stop offset="18%" stop-color="#f43f5e" stop-opacity="0.82" />
                  <stop offset="55%" stop-color="#8b5cf6" stop-opacity="0.24" />
                  <stop offset="100%" stop-color="#0ea5e9" stop-opacity="0" />
                </linearGradient>
                <filter id="comet-glow" x="-160%" y="-160%" width="420%" height="420%">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="2.2" result="b" />
                  <feMerge>
                    <feMergeNode in="b" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
                <filter id="arc-glow" x="-16%" y="-16%" width="132%" height="132%">
                  <feGaussianBlur in="SourceGraphic" stdDeviation="1.6" result="b" />
                  <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              </defs>

              <!-- Layer 1: soft glow path -->
              <ellipse :cx="svgCx" :cy="svgCy" :rx="svgRx" :ry="svgRy" stroke="url(#loop-grad)" stroke-width="10" fill="none" opacity="0.055" filter="url(#arc-glow)">
                <animate attributeName="opacity" values="0.035;0.07;0.035" dur="7s" repeatCount="indefinite" />
              </ellipse>

              <!-- Layer 2: fine dashed flow -->
              <ellipse :cx="svgCx" :cy="svgCy" :rx="svgRx" :ry="svgRy" stroke="url(#loop-grad)" stroke-width="1.5" stroke-dasharray="16 8" stroke-linecap="round" fill="none" opacity="0.22">
                <animate attributeName="stroke-dashoffset" from="0" to="-48" dur="6.5s" repeatCount="indefinite" />
              </ellipse>

              <!-- Comet -->
              <line x1="-56" y1="0" x2="0" y2="0" stroke="url(#comet-grad)" stroke-width="2.5" stroke-linecap="round" opacity="0.5" filter="url(#comet-glow)">
                <animateMotion dur="10s" repeatCount="indefinite" rotate="auto"><mpath href="#loop-motion-path" /></animateMotion>
              </line>
              <circle r="3.5" fill="#fff" opacity="0.8" filter="url(#comet-glow)">
                <animateMotion dur="10s" repeatCount="indefinite"><mpath href="#loop-motion-path" /></animateMotion>
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
              <div class="absolute inset-[-8px] rounded-full opacity-0 group-hover:opacity-40 transition-opacity duration-300 blur-sm" :class="step.color" />
              <!-- Node circle -->
              <div class="w-[88px] h-[88px] rounded-full flex items-center justify-center bg-white/90 border-2 shadow-md transition-all duration-300 group-hover:scale-105 group-hover:shadow-lg relative z-10" :class="[step.borderColor, step.iconColor]">
                <span class="node-sweep" :style="{ animationDelay: `${i * 0.9}s` }" />
                <AppIcon :name="step.icon" size="lg" :variant="step.iconVariant" />
              </div>
              <div class="text-center mt-2">
                <div class="text-xs font-semibold text-slate-700 whitespace-nowrap">{{ phaseLabel(step.key as WorkflowPhase) }}</div>
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
                  <div class="absolute inset-[-6px] rounded-full opacity-10 group-hover:opacity-28 transition-opacity duration-300 blur-sm" :class="step.color" />
                  <div class="w-[48px] h-[48px] rounded-full flex items-center justify-center bg-white/90 border-2 shadow-sm group-hover:shadow-md transition-all duration-300 group-hover:scale-105" :class="[step.borderColor, step.iconColor]">
                    <span class="node-sweep node-sweep-sm" :style="{ animationDelay: `${i * 0.9}s` }" />
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
                  <animateMotion dur="5.5s" repeatCount="indefinite" path="M6 9 L154 9" />
                  <animate attributeName="opacity" values="0.5;0.85;0.5" dur="2.4s" repeatCount="indefinite" />
                </circle>
                <circle r="2" fill="#8b5cf6" opacity="0.5">
                  <animateMotion dur="5.5s" repeatCount="indefinite" begin="2.75s" path="M6 9 L154 9" />
                  <animate attributeName="opacity" values="0.3;0.65;0.3" dur="2.4s" repeatCount="indefinite" />
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
            <div class="text-lg md:text-xl font-bold text-slate-700"><AnimatedCounter :value="statsReady ? stats.total : 0" :duration="800" /></div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.total') }}</div>
          </div>
          <div class="w-px h-5 bg-slate-200/60" />
          <div class="flex items-center gap-2">
            <div class="text-lg md:text-xl font-bold text-teal-600"><AnimatedCounter :value="statsReady ? stats.running : 0" :duration="800" /></div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.running') }}</div>
          </div>
          <div class="w-px h-5 bg-slate-200/60" />
          <div class="flex items-center gap-2">
            <div class="text-lg md:text-xl font-bold text-emerald-600"><AnimatedCounter :value="statsReady ? stats.completed : 0" :duration="800" /></div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.completed') }}</div>
          </div>
          <template v-if="stats.needsAttention > 0">
            <div class="w-px h-5 bg-slate-200/60" />
            <div class="flex items-center gap-2">
              <div class="text-lg md:text-xl font-bold text-rose-600"><AnimatedCounter :value="statsReady ? stats.needsAttention : 0" :duration="800" /></div>
              <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.needsAttention') }}</div>
            </div>
          </template>
          <div class="w-px h-5 bg-slate-200/60" />
          <div class="flex items-center gap-2">
            <div class="text-lg md:text-xl font-bold text-violet-600"><AnimatedCounter :value="statsReady ? stats.avgProgress : 0" :duration="800" />%</div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.avgProgress') }}</div>
          </div>
        </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 3: Featured workflow
             ══════════════════════════════════════════════════════════════ -->
        <div v-if="featuredWorkflow && featuredDetail" class="showcase-featured mb-5 md:mb-6 rounded-xl overflow-hidden cursor-pointer transition-shadow hover:shadow-md"
             :class="[featuredMode === 'needs_attention' ? 'liquid-glass-rose liquid-glass-hover' : 'liquid-glass-emerald liquid-glass-hover']"
             @click="goReplay(featuredWorkflow.thread_id)">
          <div class="px-4 md:px-5 py-3 flex items-center justify-between border-b border-white/10 liquid-glass-inset">
            <div class="flex items-center gap-2">
              <span v-if="featuredMode === 'needs_attention'" class="w-2.5 h-2.5 rounded-full bg-rose-500 animate-pulse" />
              <span v-else class="w-2.5 h-2.5 rounded-full bg-emerald-500" />
              <span class="text-sm font-semibold text-slate-800">{{ featuredMode === 'needs_attention' ? t('showcase.featuredAttention') : t('showcase.featured') }}</span>
              <span v-if="featuredMode === 'needs_attention'" class="text-xs px-2 py-0.5 rounded-full bg-rose-100 text-rose-600">⚠</span>
              <span v-else class="text-xs px-2 py-0.5 rounded-full bg-rose-50 text-rose-600">{{ t('showcase.featuredLive') }}</span>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-xs text-slate-400">{{ formatDate(featuredWorkflow.updated_at || featuredWorkflow.created_at) }}</span>
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
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div
            v-for="(card, idx) in visibleCards"
            :key="card.wf.thread_id"
            v-memo="[card.wf.thread_id, card.wf.status, card.wf.progress_percent, card.detail, card.isLoading]"
            class="showcase-card rounded-xl liquid-glass-hover overflow-hidden cursor-pointer transition-shadow hover:shadow-md"
            :class="[card.statusClass]"
            :style="{ animationDelay: `${(idx % ITEMS_PER_PAGE) * 60}ms` }"
            @click="goReplay(card.wf.thread_id)"
          >
            <!-- Card header with integrated progress -->
            <div class="px-4 md:px-5 py-2.5 flex items-center justify-between border-b border-white/10 liquid-glass-inset">
              <div class="flex items-center gap-1.5 min-w-0 flex-1">
                <span class="w-2 h-2 rounded-full shrink-0" :class="card.dotClass" />
                <span class="text-xs font-semibold text-slate-800 truncate">{{ card.title }}</span>
                <span class="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" :class="card.badgeClass">{{ card.statusText }}</span>
                <span v-if="card.wf.workflow_mode" class="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600 shrink-0">{{ card.wf.workflow_mode }}</span>
                <!-- Inline progress bar + percent -->
                <div class="hidden sm:flex items-center gap-1.5 ml-1">
                  <div class="w-16 h-1 bg-slate-100 rounded-full overflow-hidden">
                    <div class="h-full rounded-full transition-all duration-500" :class="card.progressClass" :style="{ width: `${card.wf.progress_percent}%` }" />
                  </div>
                  <span class="text-[10px] text-slate-400 tabular-nums shrink-0">{{ card.wf.progress_percent }}%</span>
                </div>
              </div>
              <span class="text-[10px] text-slate-400 shrink-0 ml-2">{{ card.updatedLabel }}</span>
            </div>
            <!-- Card body -->
            <div class="relative min-h-[60px]">
              <WorkflowCardBody v-if="card.detail" :detail="card.detail" />
              <div v-else-if="card.isLoading" class="px-4 py-4 space-y-2">
                <div class="h-3 w-3/4 rounded bg-slate-100 animate-pulse" />
                <div class="h-3 w-1/2 rounded bg-slate-100 animate-pulse" />
                <div class="h-3 w-2/3 rounded bg-slate-100 animate-pulse" />
              </div>
              <div v-else class="px-4 py-3 text-xs text-slate-400">{{ card.phaseText }}</div>
            </div>
            <!-- Error message -->
            <div v-if="card.wf.error" class="px-4 pb-2">
              <p class="text-[10px] text-rose-500 line-clamp-1">{{ card.wf.error }}</p>
            </div>
            <!-- Card footer -->
            <div class="px-4 pb-2.5 pt-1 flex items-center justify-between">
              <div class="hidden md:flex items-center gap-0.5">
                <template v-for="(_step, i) in pipelineSteps" :key="i">
                  <div class="w-3 h-1 rounded-full transition-colors" :class="i < card.pipelineProgress ? (card.wf.status === 'completed' ? 'bg-emerald-400' : 'bg-teal-400') : 'bg-slate-200'" />
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
.showcase-page {
  background:
    linear-gradient(135deg, rgba(255, 241, 242, 0.54), transparent 34%),
    linear-gradient(225deg, rgba(240, 253, 250, 0.58), transparent 38%),
    linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
}

.showcase-page::before,
.showcase-page::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
}

.showcase-page::before {
  width: 600px;
  height: 600px;
  top: -120px;
  left: -80px;
  background: radial-gradient(circle, rgba(244, 63, 94, 0.08) 0%, transparent 70%);
  animation: glow-drift-1 12s ease-in-out infinite alternate;
}

.showcase-page::after {
  width: 500px;
  height: 500px;
  bottom: -100px;
  right: -60px;
  background: radial-gradient(circle, rgba(14, 165, 233, 0.08) 0%, transparent 70%);
  animation: glow-drift-2 15s ease-in-out infinite alternate;
}

@keyframes glow-drift-1 {
  0% { transform: translate(0, 0); opacity: 0.6; }
  50% { transform: translate(60px, 40px); opacity: 0.9; }
  100% { transform: translate(-30px, 80px); opacity: 0.5; }
}

@keyframes glow-drift-2 {
  0% { transform: translate(0, 0); opacity: 0.5; }
  50% { transform: translate(-50px, -30px); opacity: 0.85; }
  100% { transform: translate(40px, -60px); opacity: 0.55; }
}

.showcase-glow-mid {
  position: absolute;
  width: 450px;
  height: 450px;
  top: 40%;
  left: 45%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.06) 0%, transparent 70%);
  animation: glow-drift-3 10s ease-in-out infinite alternate;
}

@keyframes glow-drift-3 {
  0% { transform: translate(0, 0); opacity: 0.4; }
  50% { transform: translate(30px, -50px); opacity: 0.75; }
  100% { transform: translate(-40px, 30px); opacity: 0.45; }
}

.showcase-card {
  position: relative;
  content-visibility: auto;
  contain-intrinsic-size: 280px;
  animation: showcase-card-in 0.5s cubic-bezier(0.22, 1, 0.36, 1) backwards;
}

.showcase-card::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(120deg, rgba(244, 63, 94, 0.42), rgba(20, 184, 166, 0.42), rgba(139, 92, 246, 0.42));
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.showcase-card:hover::after {
  opacity: 1;
}

@keyframes showcase-card-in {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}

.node-glow-rose:hover { box-shadow: 0 0 16px 3px rgba(244, 63, 94, 0.12); }
.node-glow-teal:hover { box-shadow: 0 0 16px 3px rgba(20, 184, 166, 0.12); }
.node-glow-amber:hover { box-shadow: 0 0 16px 3px rgba(245, 158, 11, 0.12); }
.node-glow-violet:hover { box-shadow: 0 0 16px 3px rgba(139, 92, 246, 0.12); }
.node-glow-emerald:hover { box-shadow: 0 0 16px 3px rgba(16, 185, 129, 0.12); }
.node-glow-sky:hover { box-shadow: 0 0 16px 3px rgba(14, 165, 233, 0.12); }

/* Traveling spotlight ring — staggered delay creates a highlight sweeping around the loop */
.node-sweep {
  position: absolute;
  inset: -2px;
  border-radius: 9999px;
  border: 2px solid currentColor;
  opacity: 0;
  pointer-events: none;
  animation: node-sweep 5.4s ease-out infinite;
}

.node-sweep-sm {
  inset: -1px;
  border-width: 1.5px;
}

@keyframes node-sweep {
  0%, 100% { opacity: 0; transform: scale(1); }
  8% { opacity: 0.55; }
  38% { opacity: 0; transform: scale(1.45); }
}

.node-center-glass {
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.78), rgba(255, 255, 255, 0.46)),
    rgba(255, 255, 255, 0.58);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  border: 1px solid rgba(255, 255, 255, 0.55);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 10px 28px rgba(15, 23, 42, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

/* Featured card — subtle animated gradient border to mark the focal card */
.showcase-featured {
  position: relative;
}

.showcase-featured::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(120deg, rgba(244, 63, 94, 0.55), rgba(16, 185, 129, 0.55), rgba(139, 92, 246, 0.55));
  background-size: 200% 100%;
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  animation: gradient-shift 6s ease infinite;
  opacity: 0.6;
  pointer-events: none;
  z-index: 1;
}

/* ── Background enrichment layers (z-0, behind content z-10) ── */

/* Structural: fine grid skeleton (whole-page visible) */
.showcase-bg-grid {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(15, 23, 42, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(15, 23, 42, 0.035) 1px, transparent 1px);
  background-size: 48px 48px;
  opacity: 0.9;
  -webkit-mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.85), rgba(0, 0, 0, 0.3));
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.85), rgba(0, 0, 0, 0.3));
}

/* Structural: drifting mesh blobs (two brand-tinted radial blobs) */
.showcase-bg-mesh {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: 0.7;
}
.showcase-bg-mesh::before,
.showcase-bg-mesh::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  filter: blur(48px);
}
.showcase-bg-mesh::before {
  width: 46vw;
  height: 46vw;
  top: 22%;
  left: -8%;
  background: radial-gradient(circle, rgba(244, 63, 94, 0.16) 0%, transparent 60%);
  animation: showcase-mesh-drift-a 18s ease-in-out infinite alternate;
}
.showcase-bg-mesh::after {
  width: 40vw;
  height: 40vw;
  bottom: 18%;
  right: -6%;
  background: radial-gradient(circle, rgba(20, 184, 166, 0.16) 0%, transparent 60%);
  animation: showcase-mesh-drift-b 21s ease-in-out infinite alternate;
}

@keyframes showcase-mesh-drift-a {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(60px, -40px) scale(1.08); }
}
@keyframes showcase-mesh-drift-b {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(-50px, 50px) scale(1.06); }
}

/* Structural: constellation lines + dots (faint skeleton) */
.showcase-constellation {
  position: absolute;
  inset: 0;
  z-index: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  opacity: 0.6;
}

.showcase-bg-dots {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image: radial-gradient(circle, rgba(15, 23, 42, 0.07) 1px, transparent 1px);
  background-size: 18px 18px;
  opacity: 0.7;
}

.showcase-aurora {
  position: absolute;
  top: -8%;
  left: 50%;
  width: 1100px;
  height: 640px;
  z-index: 0;
  pointer-events: none;
  background: conic-gradient(from 180deg at 50% 50%,
    rgba(244, 63, 94, 0.16),
    rgba(20, 184, 166, 0.16),
    rgba(139, 92, 246, 0.16),
    rgba(245, 158, 11, 0.13),
    rgba(244, 63, 94, 0.16));
  filter: blur(44px);
  opacity: 0.65;
  animation: showcase-aurora-rotate 24s linear infinite;
}

@keyframes showcase-aurora-rotate {
  from { transform: translateX(-50%) rotate(0deg); }
  to { transform: translateX(-50%) rotate(360deg); }
}

.showcase-glow-amber,
.showcase-glow-emerald {
  position: absolute;
  border-radius: 50%;
  pointer-events: none;
  z-index: 0;
}

.showcase-glow-amber {
  width: 520px;
  height: 520px;
  top: 6%;
  right: 4%;
  opacity: 0.7;
  background: radial-gradient(circle, rgba(245, 158, 11, 0.18) 0%, transparent 78%);
  animation: glow-drift-amber 14s ease-in-out infinite alternate;
}

.showcase-glow-emerald {
  width: 480px;
  height: 480px;
  bottom: 4%;
  left: 6%;
  opacity: 0.7;
  background: radial-gradient(circle, rgba(16, 185, 129, 0.18) 0%, transparent 78%);
  animation: glow-drift-emerald 16s ease-in-out infinite alternate;
}

@keyframes glow-drift-amber {
  0% { transform: translate(0, 0); opacity: 0.7; }
  50% { transform: translate(-40px, 30px); opacity: 0.9; }
  100% { transform: translate(30px, -20px); opacity: 0.6; }
}

@keyframes glow-drift-emerald {
  0% { transform: translate(0, 0); opacity: 0.7; }
  50% { transform: translate(45px, -35px); opacity: 0.88; }
  100% { transform: translate(-25px, 25px); opacity: 0.55; }
}

.showcase-particles {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: 0.7;
  background-image:
    radial-gradient(1.6px 1.6px at 6% 14%, rgba(244, 63, 94, 0.6), transparent),
    radial-gradient(1.4px 1.4px at 22% 32%, rgba(20, 184, 166, 0.55), transparent),
    radial-gradient(1.6px 1.6px at 38% 9%, rgba(139, 92, 246, 0.55), transparent),
    radial-gradient(1.4px 1.4px at 52% 28%, rgba(245, 158, 11, 0.5), transparent),
    radial-gradient(1.6px 1.6px at 68% 14%, rgba(14, 165, 233, 0.5), transparent),
    radial-gradient(1.4px 1.4px at 84% 36%, rgba(244, 63, 94, 0.55), transparent),
    radial-gradient(1.6px 1.6px at 94% 18%, rgba(20, 184, 166, 0.5), transparent),
    radial-gradient(1.4px 1.4px at 12% 52%, rgba(139, 92, 246, 0.5), transparent),
    radial-gradient(1.6px 1.6px at 28% 66%, rgba(245, 158, 11, 0.45), transparent),
    radial-gradient(1.4px 1.4px at 44% 48%, rgba(14, 165, 233, 0.45), transparent),
    radial-gradient(1.6px 1.6px at 58% 72%, rgba(244, 63, 94, 0.5), transparent),
    radial-gradient(1.4px 1.4px at 74% 58%, rgba(20, 184, 166, 0.45), transparent),
    radial-gradient(1.6px 1.6px at 88% 84%, rgba(139, 92, 246, 0.45), transparent),
    radial-gradient(1.4px 1.4px at 8% 88%, rgba(245, 158, 11, 0.4), transparent),
    radial-gradient(1.6px 1.6px at 32% 92%, rgba(14, 165, 233, 0.4), transparent),
    radial-gradient(1.4px 1.4px at 48% 86%, rgba(244, 63, 94, 0.42), transparent),
    radial-gradient(1.6px 1.6px at 64% 94%, rgba(20, 184, 166, 0.4), transparent),
    radial-gradient(1.4px 1.4px at 78% 78%, rgba(139, 92, 246, 0.4), transparent),
    radial-gradient(1.6px 1.6px at 92% 62%, rgba(245, 158, 11, 0.4), transparent),
    radial-gradient(1.4px 1.4px at 18% 74%, rgba(14, 165, 233, 0.38), transparent);
  background-repeat: no-repeat;
  animation: showcase-particles-float 18s ease-in-out infinite alternate;
}

@keyframes showcase-particles-float {
  from { transform: translateY(0); }
  to { transform: translateY(-24px); }
}

@media (prefers-reduced-motion: reduce) {
  .showcase-page :deep(*) {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  .showcase-page::before,
  .showcase-page::after,
  .showcase-glow-mid,
  .showcase-glow-amber,
  .showcase-glow-emerald,
  .showcase-aurora,
  .showcase-particles,
  .showcase-bg-mesh::before,
  .showcase-bg-mesh::after {
    animation: none !important;
  }
  .showcase-bg-grid,
  .showcase-bg-mesh,
  .showcase-constellation,
  .showcase-bg-dots,
  .showcase-aurora,
  .showcase-glow-amber,
  .showcase-glow-emerald,
  .showcase-particles {
    opacity: 0.55;
  }
  .showcase-card,
  .node-sweep,
  .showcase-featured::before {
    animation: none !important;
  }
}
</style>
