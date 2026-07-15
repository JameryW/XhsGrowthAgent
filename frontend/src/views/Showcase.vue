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
const failedDetailIds = ref<Set<string>>(new Set())
const listLoaded = ref(false)
const error = ref<string | null>(null)
const statsReady = ref(false)
const ambientReady = ref(false)

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
const DETAIL_IMMEDIATE_COUNT = 3
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
let deferredDetailTimer: number | null = null
let ambientTimer: number | null = null

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

function clearFilters() {
  statusFilter.value = 'all'
  modeFilter.value = 'all'
  sortKey.value = 'updated'
  visibleCount.value = ITEMS_PER_PAGE
}

// Fetch list first (fast), then lazy-load details for visible cards
async function fetchWorkflows() {
  error.value = null
  failedDetailIds.value = new Set()
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
  if (workflowDetails.value.has(threadId) || loadingDetailIds.value.has(threadId) || failedDetailIds.value.has(threadId)) return
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
        failedDetailIds.value.add(threadId)
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
  if (deferredDetailTimer !== null) {
    window.clearTimeout(deferredDetailTimer)
    deferredDetailTimer = null
  }

  const immediateIds = new Set<string>()
  if (featuredWorkflow.value) {
    immediateIds.add(featuredWorkflow.value.thread_id)
  }
  for (const wf of visibleWorkflows.value.slice(0, DETAIL_IMMEDIATE_COUNT)) {
    immediateIds.add(wf.thread_id)
  }
  for (const threadId of immediateIds) {
    queueDetail(threadId)
  }

  const deferredIds = visibleWorkflows.value
    .slice(DETAIL_IMMEDIATE_COUNT)
    .map(wf => wf.thread_id)
    .filter(threadId => !immediateIds.has(threadId))
  if (deferredIds.length > 0) {
    deferredDetailTimer = window.setTimeout(() => {
      deferredDetailTimer = null
      for (const threadId of deferredIds) queueDetail(threadId)
    }, 360)
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

const featuredDetailState = computed<'loading' | 'ready' | 'unavailable'>(() => {
  const threadId = featuredWorkflow.value?.thread_id
  if (!threadId || featuredDetail.value) return featuredDetail.value ? 'ready' : 'unavailable'
  return failedDetailIds.value.has(threadId) ? 'unavailable' : 'loading'
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
const LOOP_HEIGHT = 300
const ellipseRxPct = 36
const ellipseRyPct = 28
const nodeSize = 82
const containerW = ref(1200)
const loopContainer = ref<HTMLElement | null>(null)
const stepsVisible = ref(false)

function stepStyle(i: number, containerWidth: number): Record<string, string> {
  const rx = containerWidth * ellipseRxPct / 100
  const ry = LOOP_HEIGHT * ellipseRyPct / 100
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
  ambientTimer = window.setTimeout(() => {
    ambientTimer = null
    ambientReady.value = true
  }, 260)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateLoopWidth)
  if (detailPumpTimer !== null) window.clearTimeout(detailPumpTimer)
  if (deferredDetailTimer !== null) window.clearTimeout(deferredDetailTimer)
  if (ambientTimer !== null) window.clearTimeout(ambientTimer)
})

const svgCx = computed(() => containerW.value / 2)
const svgCy = LOOP_HEIGHT / 2
const svgRx = computed(() => containerW.value * ellipseRxPct / 100)
const svgRy = computed(() => LOOP_HEIGHT * ellipseRyPct / 100)

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

// Evolution trees: organic branching — smoother curves, natural canopy shape
type TreeBranch = { d: string; depth: number }
type EvoTree = { branches: TreeBranch[]; tips: { x: number; y: number; depth: number }[]; color: string }

const EVO_COLORS = ['244,63,94', '20,184,166']

function buildTree(rng: () => number, ox: number, oy: number, angle: number, len: number, depth: number, maxDepth: number, acc: TreeBranch[], tips: { x: number; y: number; depth: number }[]) {
  if (depth > maxDepth || len < 8) return
  const ex = ox + Math.cos(angle) * len
  const ey = oy + Math.sin(angle) * len
  // organic curve: gentle perpendicular offset
  const perp = angle + Math.PI / 2
  const curve = len * 0.25 * (rng() - 0.5)
  const cx = (ox + ex) / 2 + Math.cos(perp) * curve
  const cy = (oy + ey) / 2 + Math.sin(perp) * curve
  acc.push({ d: `M${ox.toFixed(1)},${oy.toFixed(1)}Q${cx.toFixed(1)},${cy.toFixed(1)} ${ex.toFixed(1)},${ey.toFixed(1)}`, depth })
  if (depth === maxDepth) {
    tips.push({ x: ex, y: ey, depth })
    return
  }
  // always 2 children for balanced canopy; wider spread
  const spread = 0.7 + rng() * 0.35
  const nextLen = len * (0.68 + rng() * 0.1)
  for (let i = 0; i < 2; i++) {
    const t = i === 0 ? -1 : 1
    const childAngle = angle + t * spread * 0.5 + (rng() - 0.5) * 0.2
    buildTree(rng, ex, ey, childAngle, nextLen, depth + 1, maxDepth, acc, tips)
  }
}

// ponytail: 2 trees instead of 4 — fewer DOM nodes, less visual noise
const TREE_DEFS = [
  { x: 60, y: 680, angle: -1.1, len: 130, depth: 5, color: 0 },   // bottom-left, grows up-right
  { x: 1140, y: 680, angle: -2.05, len: 115, depth: 5, color: 1 }, // bottom-right, grows up-left
]

const evolutionTrees = computed<EvoTree[]>(() => {
  return TREE_DEFS.map((def, idx) => {
    const rng = mulberry32(70000 + idx * 101)
    const branches: TreeBranch[] = []
    const tips: { x: number; y: number; depth: number }[] = []
    buildTree(rng, def.x, def.y, def.angle, def.len, 0, def.depth, branches, tips)
    return { branches, tips, color: EVO_COLORS[def.color] }
  })
})

// ponytail: precompute path lengths once per computed change (not per render), 4-point sampling
const evolutionTreeData = computed(() => {
  return evolutionTrees.value.map(tree => {
    const lens = tree.branches.map(b => {
      const m = b.d.match(/M([\d.]+),([\d.]+)Q([\d.]+),([\d.]+) ([\d.]+),([\d.]+)/)
      if (!m) return 40
      const [ox, oy, cx, cy, ex, ey] = [m[1], m[2], m[3], m[4], m[5], m[6]].map(Number)
      let len = 0, px = ox, py = oy
      for (let i = 1; i <= 4; i++) {
        const t = i / 4
        const x = (1 - t) ** 2 * ox + 2 * (1 - t) * t * cx + t ** 2 * ex
        const y = (1 - t) ** 2 * oy + 2 * (1 - t) * t * cy + t ** 2 * ey
        len += Math.hypot(x - px, y - py)
        px = x; py = y
      }
      return len
    })
    return { tree, lens }
  })
})

</script>

<template>
  <div class="showcase-page min-h-screen text-slate-800 relative overflow-hidden">
    <!-- Ambient background layers -->
    <div class="showcase-bg-grid" aria-hidden="true" />
    <div class="showcase-bg-mesh" aria-hidden="true" />
    <div v-if="ambientReady" class="showcase-aurora" aria-hidden="true" />
    <svg v-if="ambientReady" class="showcase-constellation" aria-hidden="true" preserveAspectRatio="none" viewBox="0 0 1200 800">
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
    <svg v-if="ambientReady" class="showcase-evolution" aria-hidden="true" preserveAspectRatio="xMidYMid slice" viewBox="0 0 1200 800">
      <g v-for="(td, ti) in evolutionTreeData" :key="'evo-'+ti">
        <path
          v-for="(b, bi) in td.tree.branches"
          :key="'b-'+ti+'-'+bi"
          :d="b.d"
          fill="none"
          :stroke="`rgba(${td.tree.color},${0.06 + b.depth * 0.03})`"
          :stroke-width="1.8 - b.depth * 0.25"
          stroke-linecap="round"
          class="evo-branch"
          :style="{ animationDelay: `${ti * 1.6 + b.depth * 0.5}s`, strokeDasharray: td.lens[bi].toFixed(1), strokeDashoffset: td.lens[bi].toFixed(1) }"
        />
        <circle
          v-for="(tip, ii) in td.tree.tips"
          :key="'t-'+ti+'-'+ii"
          :cx="tip.x"
          :cy="tip.y"
          :r="1.8"
          :fill="`rgba(${td.tree.color},0.3)`"
          class="evo-tip"
          :style="{ animationDelay: `${ti * 1.6 + 2.5 + ii * 0.2}s` }"
        />
      </g>
    </svg>
    <!-- Nav -->
    <nav class="relative z-20 liquid-glass-nav showcase-nav">
      <div class="mx-auto flex min-h-16 max-w-[1200px] items-center justify-between px-3 py-2 md:px-6">
        <div class="flex items-center gap-3">
          <div class="showcase-logo w-8 h-8 rounded-lg bg-gradient-to-br from-rose-500 to-amber-400 flex items-center justify-center shadow-md shadow-rose-500/20">
            <AppIcon name="Rocket" size="sm" variant="white" />
          </div>
          <div>
            <h1 class="text-base font-bold tracking-tight text-slate-800">{{ t('showcase.title') }}</h1>
            <p class="text-[11px] text-slate-400 -mt-0.5">{{ t('showcase.subtitle') }}</p>
          </div>
        </div>
      </div>
    </nav>

    <main class="w-full min-w-0 max-w-[1200px] mx-auto px-3 md:px-6 py-4 md:py-6 relative z-10">
      <!-- Public entry orientation: explain the value before the live workflow data. -->
      <section class="showcase-intro liquid-glass-liquid mb-5 flex flex-col gap-5 rounded-2xl p-4 shadow-sm md:mb-6 md:flex-row md:items-center md:justify-between md:rounded-3xl md:p-6" aria-labelledby="showcase-intro-title">
        <div class="showcase-intro-orbit" aria-hidden="true">
          <span class="showcase-orbit-ring showcase-orbit-ring-a" />
          <span class="showcase-orbit-ring showcase-orbit-ring-b" />
          <span class="showcase-orbit-dot showcase-orbit-dot-a" />
          <span class="showcase-orbit-dot showcase-orbit-dot-b" />
        </div>
        <div class="max-w-2xl">
          <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-rose-500">{{ t('showcase.heroTagline') }}</p>
          <h2 id="showcase-intro-title" class="mt-2 text-2xl font-bold tracking-tight text-slate-800 md:text-4xl">{{ t('showcase.sectionTitle') }}</h2>
          <p class="mt-2 text-sm leading-6 text-slate-500">{{ t('showcase.heroDesc') }}</p>
        </div>
        <div class="flex w-full shrink-0 flex-col gap-3 sm:flex-row md:w-auto md:flex-col md:items-stretch">
          <div class="showcase-intro-signal rounded-2xl border border-white/80 bg-white/65 px-4 py-3 shadow-sm" aria-hidden="true">
            <div class="flex items-center justify-between gap-4">
              <span class="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{{ t('showcase.closedLoop') }}</span>
              <span class="showcase-signal-dot h-2 w-2 rounded-full bg-teal-400" />
            </div>
            <div class="showcase-signal-steps mt-3 flex gap-1.5">
              <span v-for="step in howItWorksSteps" :key="`signal-${step.key}`" class="h-1.5 flex-1 rounded-full" :class="step.color" />
            </div>
            <div class="mt-2 flex items-end gap-2">
              <span class="text-3xl font-bold leading-none text-slate-800">6</span>
              <span class="max-w-[150px] text-[10px] leading-4 text-slate-500">{{ t('showcase.heroTagline') }}</span>
            </div>
          </div>
          <button type="button" @click="goDashboard" class="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-xl bg-slate-800 px-4 text-xs font-semibold text-white shadow-sm transition hover:bg-slate-700">
            <AppIcon name="Rocket" size="sm" variant="white" aria-hidden="true" />
            {{ t('showcase.dashboard') }}
          </button>
        </div>
      </section>

      <!-- Error -->
      <div v-if="error" class="rounded-xl p-8 liquid-glass-rose liquid-glass-hover text-center max-w-md w-full mx-auto">
        <div class="w-12 h-12 rounded-xl bg-rose-100 flex items-center justify-center mx-auto mb-4">
          <AppIcon name="AlertCircle" size="lg" variant="pink" />
        </div>
        <p class="text-sm text-rose-700 font-medium">{{ t('common.apiError') }}</p>
        <p class="text-xs text-rose-500/70 mt-2">{{ error }}</p>
        <button type="button" @click="fetchWorkflows" class="mt-4 min-h-11 rounded-xl bg-rose-600 px-5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-rose-700">{{ t('common.retry') }}</button>
      </div>

      <!-- Loading keeps the public entry stable while the workflow list arrives. -->
      <div v-else-if="!listLoaded" class="showcase-loading-shell grid grid-cols-1 gap-4 md:grid-cols-2" aria-live="polite">
        <div v-for="i in 2" :key="i" class="rounded-2xl border border-white/70 bg-white/60 p-5 shadow-sm">
          <div class="h-3 w-1/3 animate-pulse rounded bg-slate-200" />
          <div class="mt-5 h-4 w-4/5 animate-pulse rounded bg-slate-200" />
          <div class="mt-3 h-3 w-2/3 animate-pulse rounded bg-slate-100" />
          <div class="mt-6 h-2 w-full animate-pulse rounded bg-slate-100" />
        </div>
        <p class="col-span-full text-center text-xs text-slate-400">{{ t('common.loading') }}</p>
      </div>

      <!-- Content -->
      <template v-else>
        <div class="showcase-workspace-shell liquid-glass-liquid">
        <div class="showcase-live-heading mb-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p class="text-[10px] font-bold uppercase tracking-[0.18em] text-teal-600">{{ t('showcase.liveWorkspace') }}</p>
            <h2 class="mt-1 text-lg font-bold tracking-tight text-slate-800">{{ t('showcase.workspaceOverview') }}</h2>
          </div>
          <p class="max-w-md text-xs leading-5 text-slate-400 sm:text-right">{{ t('showcase.liveWorkspaceDesc') }}</p>
        </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 1: Closed-loop pipeline — elliptical loop animation
             ══════════════════════════════════════════════════════════════ -->
        <section class="showcase-loop-section mb-4 w-full min-w-0 rounded-3xl border border-white/75 bg-white/35 p-3 shadow-sm backdrop-blur-sm md:mb-6 md:p-5" aria-labelledby="showcase-loop-title">
          <div class="mb-2 flex items-end justify-between gap-3 px-1 md:mb-0 md:px-3">
            <div>
              <p class="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{{ t('showcase.howItWorks') }}</p>
              <h2 id="showcase-loop-title" class="mt-1 text-base font-bold text-slate-700 md:text-lg">{{ t('showcase.closedLoop') }}</h2>
            </div>
            <span class="hidden max-w-[220px] text-right text-[11px] leading-4 text-slate-400 sm:block">{{ t('showcase.closedLoopDesc') }}</span>
          </div>
          <!-- Desktop: elliptical loop with SVG path + circular nodes -->
          <div ref="loopContainer" class="relative hidden md:block" :style="{ height: `${LOOP_HEIGHT}px` }">
            <svg class="pointer-events-none absolute inset-0 h-full w-full" :viewBox="`0 0 ${containerW} ${LOOP_HEIGHT}`" preserveAspectRatio="xMidYMid meet" fill="none" xmlns="http://www.w3.org/2000/svg">
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
              <div class="relative z-10 flex h-[82px] w-[82px] items-center justify-center rounded-full border-2 bg-white/90 shadow-md transition-all duration-300 group-hover:scale-105 group-hover:shadow-lg" :class="[step.borderColor, step.iconColor]">
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
            <div class="showcase-mobile-grid grid w-full min-w-0 grid-cols-[repeat(3,minmax(0,1fr))] gap-2 mb-3 sm:gap-3">
              <div
                v-for="(step, i) in howItWorksSteps"
                :key="step.key"
                class="group flex min-w-0 flex-col items-center text-center transition-all duration-500 ease-out"
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
                <div class="mt-1 min-w-0 max-w-full break-words text-[11px] font-bold text-slate-600">{{ phaseLabel(step.key as WorkflowPhase) }}</div>
                <div class="mt-0.5 min-w-0 max-w-full break-words text-[9px] leading-3 text-slate-400 line-clamp-2">{{ t(`showcase.steps.${step.key}`) }}</div>
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
        </section>

        <!-- Empty data is a valid public state: keep the product explanation visible,
             then give the user one clear next action. -->
        <div v-if="isEmpty" class="showcase-empty-state liquid-glass-inset mb-5 rounded-2xl px-5 py-8 text-center md:mb-6 md:py-10">
          <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-white/75 shadow-sm ring-1 ring-white/80">
            <AppIcon name="Inbox" size="lg" variant="cyan" />
          </div>
          <p class="mt-4 text-sm font-semibold text-slate-700">{{ t('showcase.empty') }}</p>
          <p class="mx-auto mt-1.5 max-w-sm text-xs leading-5 text-slate-400">{{ t('showcase.emptyDesc') }}</p>
          <button type="button" @click="goDashboard" class="mt-5 inline-flex min-h-11 items-center gap-2 rounded-xl bg-slate-800 px-4 text-xs font-semibold text-white shadow-sm transition hover:bg-slate-700">
            <AppIcon name="Rocket" size="sm" variant="white" aria-hidden="true" />
            {{ t('showcase.dashboard') }}
          </button>
        </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 2: Stats — compact horizontal strip
             ══════════════════════════════════════════════════════════════ -->
        <div v-if="!isEmpty" class="showcase-stats mb-5 grid grid-cols-2 gap-2 rounded-2xl border border-white/80 bg-white/45 px-2 py-2.5 shadow-sm backdrop-blur-sm sm:flex sm:items-center sm:justify-center sm:gap-5 sm:px-3 md:mb-6 md:gap-8">
          <div class="showcase-stat-item showcase-stat-total flex min-h-14 items-center justify-center gap-2 rounded-xl border border-white/70 bg-white/60 px-3 shadow-sm sm:min-h-0 sm:justify-start sm:border-0 sm:bg-transparent sm:px-0 sm:shadow-none">
            <div class="text-lg md:text-xl font-bold text-slate-700"><AnimatedCounter :value="statsReady ? stats.total : 0" :duration="800" /></div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.total') }}</div>
          </div>
          <div class="hidden h-5 w-px bg-slate-200/60 sm:block" />
          <div class="showcase-stat-item showcase-stat-running flex min-h-14 items-center justify-center gap-2 rounded-xl border border-white/70 bg-white/60 px-3 shadow-sm sm:min-h-0 sm:justify-start sm:border-0 sm:bg-transparent sm:px-0 sm:shadow-none">
            <div class="text-lg md:text-xl font-bold text-teal-600"><AnimatedCounter :value="statsReady ? stats.running : 0" :duration="800" /></div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.running') }}</div>
          </div>
          <div class="hidden h-5 w-px bg-slate-200/60 sm:block" />
          <div class="showcase-stat-item showcase-stat-completed flex min-h-14 items-center justify-center gap-2 rounded-xl border border-white/70 bg-white/60 px-3 shadow-sm sm:min-h-0 sm:justify-start sm:border-0 sm:bg-transparent sm:px-0 sm:shadow-none">
            <div class="text-lg md:text-xl font-bold text-emerald-600"><AnimatedCounter :value="statsReady ? stats.completed : 0" :duration="800" /></div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.completed') }}</div>
          </div>
          <template v-if="stats.needsAttention > 0">
            <div class="hidden h-5 w-px bg-slate-200/60 sm:block" />
            <div class="showcase-stat-item showcase-stat-attention flex min-h-14 items-center justify-center gap-2 rounded-xl border border-white/70 bg-white/60 px-3 shadow-sm sm:min-h-0 sm:justify-start sm:border-0 sm:bg-transparent sm:px-0 sm:shadow-none">
              <div class="text-lg md:text-xl font-bold text-rose-600"><AnimatedCounter :value="statsReady ? stats.needsAttention : 0" :duration="800" /></div>
              <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.needsAttention') }}</div>
            </div>
          </template>
          <div class="hidden h-5 w-px bg-slate-200/60 sm:block" />
          <div class="showcase-stat-item showcase-stat-progress flex min-h-14 items-center justify-center gap-2 rounded-xl border border-white/70 bg-white/60 px-3 shadow-sm sm:min-h-0 sm:justify-start sm:border-0 sm:bg-transparent sm:px-0 sm:shadow-none">
            <div class="text-lg md:text-xl font-bold text-violet-600"><AnimatedCounter :value="statsReady ? stats.avgProgress : 0" :duration="800" />%</div>
            <div class="text-[10px] text-slate-400 leading-tight">{{ t('showcase.stats.avgProgress') }}</div>
          </div>
        </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 3: Featured workflow
             ══════════════════════════════════════════════════════════════ -->
        <div v-if="!isEmpty && featuredWorkflow" role="button" tabindex="0" :aria-label="t('showcase.viewDetail')" @keydown.enter="goReplay(featuredWorkflow.thread_id)" class="showcase-featured mb-5 cursor-pointer overflow-hidden rounded-2xl transition-shadow hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/70 md:mb-6"
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
          <WorkflowCardBody v-if="featuredDetailState === 'ready' && featuredDetail" :detail="featuredDetail" />
          <div v-else-if="featuredDetailState === 'loading'" class="showcase-featured-loading space-y-3 px-4 py-5 md:px-5" aria-live="polite">
            <div class="h-3 w-1/4 animate-pulse rounded bg-white/70" />
            <div class="h-4 w-3/4 animate-pulse rounded bg-white/70" />
            <div class="h-3 w-1/2 animate-pulse rounded bg-white/60" />
          </div>
          <div v-else class="showcase-featured-unavailable flex items-center justify-between gap-3 px-4 py-4 md:px-5" aria-live="polite">
            <div class="min-w-0">
              <p class="text-xs font-medium text-slate-600">{{ phaseLabel(featuredWorkflow.phase) }}</p>
              <p class="mt-1 text-[10px] text-slate-400">{{ t('showcase.detailUnavailable') }}</p>
            </div>
            <AppIcon name="ArrowRight" size="sm" variant="cyan" aria-hidden="true" />
          </div>
        </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 4: Filter bar
             ══════════════════════════════════════════════════════════════ -->
        <section v-if="!isEmpty" id="showcase-records" class="showcase-workflows-section" aria-labelledby="showcase-workflows-title">
          <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p class="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{{ t('showcase.liveWorkspace') }}</p>
              <h2 id="showcase-workflows-title" class="mt-1 text-lg font-bold tracking-tight text-slate-800">{{ t('showcase.workflowRecords') }}</h2>
            </div>
            <div class="flex flex-col items-stretch gap-2 sm:items-end">
              <span class="showcase-record-count text-[10px] font-medium text-slate-400">{{ filteredWorkflows.length }} {{ t('showcase.workflowCount') }}</span>
              <div class="showcase-filter-toolbar flex flex-wrap items-center gap-2">
          <div class="flex items-center gap-1 rounded-xl border border-white/80 bg-white/65 p-1 shadow-sm">
            <button
              type="button"
              v-for="f in ([
                { key: 'all', label: t('showcase.filter.all') },
                { key: 'running', label: t('showcase.stats.running') },
                { key: 'completed', label: t('showcase.stats.completed') },
                { key: 'needs_attention', label: t('showcase.stats.needsAttention') },
              ] as const)"
              :key="f.key"
              @click="statusFilter = f.key"
              :aria-pressed="statusFilter === f.key"
              class="min-h-11 rounded-lg px-2.5 text-[11px] font-medium transition-colors"
              :class="statusFilter === f.key ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
            >{{ f.label }}</button>
          </div>
          <div class="flex items-center gap-1 rounded-xl border border-white/80 bg-white/65 p-1 shadow-sm">
            <button
              type="button"
              v-for="m in ([
                { key: 'all', label: t('showcase.filter.allMode') },
                { key: 'trend', label: t('showcase.filter.trend') },
                { key: 'brief', label: t('showcase.filter.brief') },
              ] as const)"
              :key="m.key"
              @click="modeFilter = m.key"
              :aria-pressed="modeFilter === m.key"
              class="min-h-11 rounded-lg px-2.5 text-[11px] font-medium transition-colors"
              :class="modeFilter === m.key ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
            >{{ m.label }}</button>
          </div>
          <select v-model="sortKey" class="min-h-11 rounded-xl border-0 bg-slate-100/80 px-3 text-[11px] font-medium text-slate-600 outline-none cursor-pointer focus:ring-2 focus:ring-rose-400/30">
            <option value="updated">{{ t('showcase.sort.updated') }}</option>
            <option value="progress">{{ t('showcase.sort.progress') }}</option>
            <option value="created">{{ t('showcase.sort.created') }}</option>
          </select>
              </div>
            </div>
          </div>

        <!-- ══════════════════════════════════════════════════════════════
             Layer 5: Card grid
             ══════════════════════════════════════════════════════════════ -->
        <div class="showcase-card-grid grid grid-cols-1 gap-4 md:grid-cols-2">
          <div
            v-for="(card, idx) in visibleCards"
            :key="card.wf.thread_id"
            v-memo="[card.wf.thread_id, card.wf.status, card.wf.progress_percent, card.detail, card.isLoading]"
            role="button"
            tabindex="0"
            :aria-label="`${card.title} · ${card.statusText}`"
            @keydown.enter="goReplay(card.wf.thread_id)"
            class="showcase-card cursor-pointer overflow-hidden rounded-2xl transition-shadow hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/70"
            :class="[card.statusClass]"
            :style="{ animationDelay: `${(idx % ITEMS_PER_PAGE) * 60}ms` }"
            @click="goReplay(card.wf.thread_id)"
          >
            <!-- Card header with integrated progress -->
            <div class="showcase-card-head px-4 md:px-5 py-2.5 flex items-center justify-between border-b border-white/10 liquid-glass-inset">
              <div class="flex items-center gap-1.5 min-w-0 flex-1">
                <span class="w-2 h-2 rounded-full shrink-0" :class="card.dotClass" />
                <span class="text-xs font-semibold text-slate-800 truncate">{{ card.title }}</span>
                <span class="text-[10px] px-1.5 py-0.5 rounded-full shrink-0" :class="card.badgeClass">{{ card.statusText }}</span>
                <span v-if="card.wf.workflow_mode" class="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600 shrink-0">{{ card.wf.workflow_mode }}</span>
                <!-- Inline progress bar + percent -->
                <div class="flex items-center gap-1.5 ml-1">
                  <div class="w-16 h-1 bg-slate-100 rounded-full overflow-hidden">
                    <div class="h-full rounded-full transition-all duration-500" :class="card.progressClass" :style="{ width: `${card.wf.progress_percent}%` }" />
                  </div>
                  <span class="text-[10px] text-slate-400 tabular-nums shrink-0">{{ card.wf.progress_percent }}%</span>
                </div>
              </div>
              <span class="text-[10px] text-slate-400 shrink-0 ml-2">{{ card.updatedLabel }}</span>
            </div>
            <!-- Card body -->
            <div class="showcase-card-body relative min-h-[60px]">
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
            <div class="showcase-card-footer px-4 pb-2.5 pt-1 flex items-center justify-between">
              <div class="flex items-center gap-0.5">
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
          <button type="button" @click="loadMore" class="min-h-11 rounded-xl px-6 liquid-glass text-xs font-medium text-slate-600 transition-shadow hover:shadow-md">
            {{ t('showcase.loadMore') }} ({{ filteredWorkflows.length - visibleCount }})
          </button>
        </div>

        <!-- No results after filter -->
        <div v-if="listLoaded && filteredWorkflows.length === 0 && workflows.length > 0" class="rounded-2xl border border-slate-200/60 bg-white/60 py-12 text-center">
          <AppIcon name="SearchX" size="lg" variant="cyan" aria-hidden="true" />
          <p class="mt-3 text-sm text-slate-400">{{ t('showcase.noResults') }}</p>
          <button type="button" @click="clearFilters" class="mt-4 min-h-11 rounded-xl border border-slate-200 bg-white/70 px-4 text-xs font-medium text-slate-600 transition hover:bg-white">
            {{ t('showcase.resetFilters') }}
          </button>
        </div>

        <!-- Footer -->
        <div class="mt-10 border-t border-slate-200/60 py-4 text-center text-xs text-slate-400">
          {{ t('showcase.footer') }}
        </div>
        </section>
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped>
/* ── Nav bar ── */
.showcase-nav {
  border-bottom: none;
  box-shadow:
    0 0 1px rgba(15, 23, 42, 0.06),
    0 4px 16px rgba(15, 23, 42, 0.04),
    inset 0 -1px 0 rgba(15, 23, 42, 0.04);
}

.showcase-logo {
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.showcase-logo:hover {
  transform: scale(1.08) rotate(-4deg);
  box-shadow: 0 4px 14px rgba(244, 63, 94, 0.3);
}

.showcase-intro,
.showcase-loop-section {
  position: relative;
  isolation: isolate;
  overflow: hidden;
}

.showcase-intro > * {
  position: relative;
  z-index: 1;
}

.showcase-intro::before {
  content: '';
  position: absolute;
  width: 22rem;
  height: 22rem;
  right: -8rem;
  top: -12rem;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(244, 63, 94, 0.16), transparent 68%);
  pointer-events: none;
}

.showcase-intro::after {
  content: '';
  position: absolute;
  width: 34rem;
  height: 18rem;
  right: -8rem;
  bottom: -12rem;
  border-radius: 50%;
  background: repeating-radial-gradient(ellipse at center, rgba(20, 184, 166, 0.12) 0 1px, transparent 1px 18px);
  opacity: 0.46;
  transform: rotate(-10deg);
  pointer-events: none;
  animation: showcase-radar-drift 12s ease-in-out infinite alternate;
}

.showcase-intro-orbit {
  position: absolute;
  z-index: 0;
  top: 50%;
  right: 16rem;
  width: 13rem;
  height: 7rem;
  transform: translateY(-50%) rotate(-12deg);
  opacity: 0.72;
  pointer-events: none;
}

.showcase-orbit-ring {
  position: absolute;
  inset: 0;
  border: 1px solid rgba(14, 165, 233, 0.2);
  border-radius: 50%;
  transform: rotate(18deg);
  box-shadow: 0 0 22px rgba(14, 165, 233, 0.08);
}

.showcase-orbit-ring-b {
  inset: 0.8rem -0.5rem;
  border-color: rgba(244, 63, 94, 0.17);
  transform: rotate(-34deg);
}

.showcase-orbit-dot {
  position: absolute;
  width: 0.42rem;
  height: 0.42rem;
  border-radius: 50%;
  box-shadow: 0 0 0 5px rgba(255, 255, 255, 0.45), 0 0 14px currentColor;
  animation: showcase-orbit-blink 3.6s ease-in-out infinite;
}

.showcase-orbit-dot-a {
  top: 0.2rem;
  right: 2.2rem;
  color: #14b8a6;
  background: currentColor;
}

.showcase-orbit-dot-b {
  bottom: 0.3rem;
  left: 2.1rem;
  color: #f43f5e;
  background: currentColor;
  animation-delay: 1.4s;
}

.showcase-intro-signal {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  min-width: 210px;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.78), rgba(240, 253, 250, 0.64)),
    rgba(255, 255, 255, 0.58);
}

.showcase-intro-signal::before {
  content: '';
  position: absolute;
  top: -30%;
  bottom: -30%;
  left: -42%;
  width: 26%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.82), transparent);
  transform: skewX(-18deg);
  opacity: 0;
  animation: showcase-signal-sheen 5.8s ease-in-out infinite;
  pointer-events: none;
}

.showcase-intro-signal > * {
  position: relative;
  z-index: 1;
}

.showcase-signal-steps span {
  opacity: 0.72;
  box-shadow: 0 0 8px rgba(255, 255, 255, 0.36);
}

.showcase-signal-dot {
  box-shadow: 0 0 0 5px rgba(45, 212, 191, 0.12), 0 0 18px rgba(20, 184, 166, 0.4);
  animation: showcase-signal-pulse 2.8s ease-in-out infinite;
}

@keyframes showcase-signal-pulse {
  0%, 100% { opacity: 0.65; transform: scale(0.9); }
  50% { opacity: 1; transform: scale(1.08); }
}

.showcase-loop-section {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.48), rgba(240, 253, 250, 0.22)),
    rgba(255, 255, 255, 0.18);
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.03),
    0 18px 42px rgba(15, 23, 42, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

.showcase-loop-section::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    radial-gradient(ellipse at center, rgba(255, 255, 255, 0.48), transparent 58%),
    repeating-linear-gradient(0deg, transparent 0 30px, rgba(14, 165, 233, 0.025) 31px 32px);
  opacity: 0.9;
}

.showcase-loop-section::after {
  content: '';
  position: absolute;
  z-index: 0;
  top: 0;
  left: -24%;
  width: 24%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(20, 184, 166, 0.8), rgba(139, 92, 246, 0.5), transparent);
  box-shadow: 0 0 14px rgba(20, 184, 166, 0.35);
  animation: showcase-panel-scan 8s ease-in-out infinite;
  pointer-events: none;
}

.showcase-loop-section > * {
  position: relative;
  z-index: 1;
}

.showcase-mobile-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.showcase-mobile-grid > * {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.showcase-stat-item {
  position: relative;
  overflow: hidden;
  min-width: 0;
  max-width: 100%;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.showcase-stat-item::before {
  content: '';
  position: absolute;
  top: 0;
  left: 1rem;
  right: 1rem;
  height: 2px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.22;
}

.showcase-stat-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.06);
}

.showcase-stat-total { color: #64748b; }
.showcase-stat-running { color: #0d9488; }
.showcase-stat-completed { color: #059669; }
.showcase-stat-attention { color: #e11d48; }
.showcase-stat-progress { color: #7c3aed; }

.showcase-stat-item > div:last-child {
  min-width: 0;
  overflow-wrap: anywhere;
}

.showcase-workflows-section {
  scroll-margin-top: 5rem;
}

.showcase-workspace-shell {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  padding: 0.7rem;
  border-radius: 1.75rem;
  box-shadow:
    0 2px 4px rgba(15, 23, 42, 0.035),
    0 20px 48px rgba(15, 23, 42, 0.065),
    inset 0 1px 0 rgba(255, 255, 255, 0.78);
}

.showcase-workspace-shell::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background:
    linear-gradient(rgba(15, 23, 42, 0.018) 1px, transparent 1px),
    linear-gradient(90deg, rgba(15, 23, 42, 0.018) 1px, transparent 1px),
    radial-gradient(ellipse at 50% 0%, rgba(255, 255, 255, 0.56), transparent 62%);
  background-size: 34px 34px, 34px 34px, auto;
  opacity: 0.82;
}

.showcase-workspace-shell > * {
  position: relative;
  z-index: 1;
}

.showcase-live-heading {
  position: relative;
  padding: 0.15rem 0.25rem 0.5rem;
}

.showcase-live-heading::after {
  content: '';
  position: absolute;
  left: 0.25rem;
  right: 0.25rem;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, rgba(20, 184, 166, 0.3), rgba(148, 163, 184, 0.12), transparent);
}

.showcase-loading-shell {
  contain: content;
}

.showcase-empty-state {
  border: 1px dashed rgba(148, 163, 184, 0.32);
  background:
    radial-gradient(circle at 50% 0%, rgba(255, 255, 255, 0.78), transparent 66%),
    rgba(248, 250, 252, 0.44);
}

.showcase-featured-loading {
  min-height: 8rem;
}

.showcase-featured-unavailable {
  min-height: 5.5rem;
  background: rgba(248, 250, 252, 0.28);
}

@media (max-width: 767px) {
  .showcase-workspace-shell {
    width: 100%;
    max-width: 100%;
    padding: 0.45rem;
    border-radius: 1.35rem;
  }

  .showcase-intro,
  .showcase-loop-section,
  .showcase-stats,
  .showcase-featured,
  .showcase-workflows-section {
    width: calc(100vw - 1.5rem) !important;
    max-width: calc(100vw - 1.5rem);
    min-width: 0;
  }

  .showcase-mobile-grid {
    width: 100% !important;
    max-width: 100%;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .showcase-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    overflow: hidden;
  }

  .showcase-stat-item:hover,
  .showcase-card:hover {
    transform: none;
  }

  .showcase-constellation,
  .showcase-evolution {
    display: none;
  }

  .showcase-workspace-shell .showcase-loop-section,
  .showcase-workspace-shell .showcase-stats,
  .showcase-workspace-shell .showcase-featured,
  .showcase-workspace-shell .showcase-workflows-section {
    width: 100% !important;
    max-width: 100%;
  }

  .showcase-intro-orbit {
    right: 5rem;
    top: 38%;
    transform: translateY(-50%) rotate(-12deg) scale(0.72);
    opacity: 0.42;
  }

  .showcase-aurora {
    width: 720px;
    height: 480px;
    filter: blur(36px);
    opacity: 0.42;
    animation: none;
  }
}

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

.showcase-card {
  position: relative;
  content-visibility: auto;
  contain-intrinsic-size: 280px;
  animation: showcase-card-in 0.5s cubic-bezier(0.22, 1, 0.36, 1) backwards;
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 26px rgba(15, 23, 42, 0.05),
    inset 0 1px 0 rgba(255, 255, 255, 0.55);
  transition: transform 0.28s ease, box-shadow 0.28s ease;
}

.showcase-card:hover {
  transform: translateY(-2px);
  box-shadow:
    0 4px 8px rgba(15, 23, 42, 0.05),
    0 18px 34px rgba(15, 23, 42, 0.09),
    inset 0 1px 0 rgba(255, 255, 255, 0.68);
}

.showcase-card-head {
  background: linear-gradient(90deg, rgba(255, 255, 255, 0.32), rgba(255, 255, 255, 0.08));
}

.showcase-card-body {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.08), transparent 42%);
}

.showcase-card-footer {
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}

.showcase-filter-toolbar {
  padding: 0.25rem;
  border-radius: 1rem;
  background: rgba(255, 255, 255, 0.2);
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

.showcase-card::before {
  content: '';
  position: absolute;
  z-index: 2;
  top: -12%;
  bottom: -12%;
  left: 0;
  width: 26%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.42), transparent);
  transform: translateX(-180%) skewX(-18deg);
  opacity: 0;
  pointer-events: none;
}

.showcase-card:hover::before {
  opacity: 1;
  animation: showcase-card-shine 1.05s ease-out;
}

@keyframes showcase-card-shine {
  to { transform: translateX(560%) skewX(-18deg); }
}

@keyframes showcase-card-in {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes showcase-grid-sweep {
  0%, 14% { transform: translateX(0) skewX(-16deg); opacity: 0; }
  25% { opacity: 0.55; }
  68% { opacity: 0.55; }
  82%, 100% { transform: translateX(920%) skewX(-16deg); opacity: 0; }
}

@keyframes showcase-panel-scan {
  0%, 15% { transform: translateX(0); opacity: 0; }
  28% { opacity: 1; }
  72% { opacity: 1; }
  88%, 100% { transform: translateX(520%); opacity: 0; }
}

@keyframes showcase-signal-sheen {
  0%, 30% { transform: translateX(0) skewX(-18deg); opacity: 0; }
  42% { opacity: 0.85; }
  62%, 100% { transform: translateX(560%) skewX(-18deg); opacity: 0; }
}

@keyframes showcase-radar-drift {
  0% { transform: rotate(-10deg) scale(0.96); opacity: 0.28; }
  100% { transform: rotate(-4deg) scale(1.06); opacity: 0.58; }
}

@keyframes showcase-orbit-blink {
  0%, 100% { transform: scale(0.7); opacity: 0.45; }
  50% { transform: scale(1.1); opacity: 1; }
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

.showcase-bg-grid::after {
  content: '';
  position: absolute;
  top: -10%;
  bottom: -10%;
  left: -18%;
  width: 14%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.28), transparent);
  transform: skewX(-16deg);
  animation: showcase-grid-sweep 14s ease-in-out infinite;
  mix-blend-mode: screen;
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

/* Thematic: evolution trees — subtle background accent */
.showcase-evolution {
  position: absolute;
  inset: 0;
  z-index: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  opacity: 0.55;
}

.evo-branch {
  animation: evo-grow 3.6s ease-out forwards;
}

/* strokeDashoffset is set inline to the full path length; animate it to 0 to "draw" the branch */
@keyframes evo-grow {
  to { stroke-dashoffset: 0; }
}

.evo-tip {
  opacity: 0;
  transform-box: fill-box;
  transform-origin: center;
  animation: evo-tip-pulse 4.5s ease-in-out infinite;
}

@keyframes evo-tip-pulse {
  0%, 100% { opacity: 0; transform: scale(0.6); }
  40% { opacity: 0.9; transform: scale(1); }
  60% { opacity: 0.6; transform: scale(1.25); }
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

@media (prefers-reduced-motion: reduce) {
  .showcase-page :deep(*) {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  .showcase-page::before,
  .showcase-page::after,
  .showcase-aurora,
  .showcase-bg-mesh::before,
  .showcase-bg-mesh::after,
  .showcase-bg-grid::after,
  .showcase-intro::after,
  .showcase-intro-signal::before,
  .showcase-loop-section::after {
    animation: none !important;
  }
  .showcase-bg-grid,
  .showcase-bg-mesh,
  .showcase-constellation,
  .showcase-evolution,
  .showcase-aurora {
    opacity: 0.55;
  }
  .showcase-card,
  .showcase-card::before,
  .node-sweep,
  .showcase-featured::before,
  .showcase-orbit-dot,
  .showcase-signal-dot,
  .evo-branch,
  .evo-tip {
    animation: none !important;
  }
  /* Static evolution trees: cancel the grow dashoffset so branches render fully */
  .evo-branch {
    stroke-dashoffset: 0 !important;
  }
  .evo-tip {
    opacity: 0.7 !important;
  }
}
</style>
