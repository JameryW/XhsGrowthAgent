<script setup lang="ts">
import { onMounted, computed, ref, defineAsyncComponent, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import MetricCard from '@/components/MetricCard.vue'
import DataTable from '@/components/DataTable.vue'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import PageHeader from '@/components/PageHeader.vue'
import CreatorStatsPanel from '@/components/settings/CreatorStatsPanel.vue'
import CreatorNoteQualityPanel from '@/components/settings/CreatorNoteQualityPanel.vue'
import { AnalyticsSkeleton } from '@/components/skeletons'
import { useAnalyticsStore, useAccountsStore } from '@/stores'
import * as analyticsApi from '@/api/analytics'
import type { CreatorAccountStats, CreatorNoteStats, CreatorNotesPayload } from '@/api/analytics'
import type { PostPerformance } from '@/types/analytics'

const TrendChart = defineAsyncComponent(() => import('@/components/charts/TrendChart.vue'))
const EngagementChart = defineAsyncComponent(() => import('@/components/charts/EngagementChart.vue'))
import { formatNumber, formatPercent, formatShortDate } from '@/utils/format'
import { trackInteraction } from '@/utils/interactionTelemetry'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { hasSnapshotMismatch } from '@/constants/qualityConsistency'

const { t, locale } = useI18n()
const router = useRouter()
const analyticsStore = useAnalyticsStore()
const accountsStore = useAccountsStore()
const lastUpdatedAt = ref<Date | null>(null)
// AN-05: creator fans for the first-screen metric card. Single snapshot only —
// the payload has no historical fans array, so the period growth delta falls
// back to '—' until a second snapshot exists.
const creatorAccount = ref<CreatorAccountStats | null>(null)
const fansValue = computed(() => creatorAccount.value?.fans ?? null)
const fansDisplay = computed(() => fansValue.value !== null ? formatNumber(fansValue.value, locale.value) : '—')

// Canonical historical-note reader shared with EvaluationView. Dashboard
// performance remains the period aggregate; this collection is the durable
// imported-note fact source and exposes cursor/total/data-as-of explicitly.
const historicalNotes = ref<CreatorNoteStats[]>([])
const historicalTotal = ref(0)
const historicalCursor = ref<string | null>(null)
const historicalDataAsOf = ref<string | null>(null)
const historicalSnapshotId = ref<string | null>(null)
const historicalSnapshotMismatch = ref(false)
const historicalLoading = ref(false)
const historicalError = ref<string | null>(null)
const showAllHistorical = ref(false)
let historicalRequest = 0

async function readHistoricalNotes(accountId: string, cursor: string | null = null): Promise<CreatorNotesPayload> {
  let reader: typeof analyticsApi.getCreatorNotes | undefined
  try { reader = analyticsApi.getCreatorNotes } catch { reader = undefined }
  if (typeof reader === 'function') {
    try {
      return await reader(accountId, { cursor, limit: 50, sort: 'published_at_desc' }, { suppressToast: true })
    } catch {
      // Compatibility with older backends that have not exposed the cursor
      // reader yet; fall back to the bounded legacy overview.
    }
  }
  const legacy = await analyticsApi.getCreatorStats(accountId, 50)
  return {
    account_id: accountId,
    items: legacy.notes || [],
    total: legacy.total ?? legacy.notes?.length ?? 0,
    limit: legacy.limit ?? 50,
    next_cursor: null,
    data_as_of: legacy.data_as_of ?? legacy.fetched_at ?? null,
    snapshot_id: legacy.snapshot_id ?? null,
    engagement_rate_unit: legacy.engagement_rate_unit,
  }
}

async function loadHistoricalNotes(accountId: string, reset = true) {
  const request = ++historicalRequest
  if (reset) {
    historicalNotes.value = []
    historicalTotal.value = 0
    historicalCursor.value = null
    historicalDataAsOf.value = null
    historicalSnapshotId.value = null
    historicalSnapshotMismatch.value = false
    showAllHistorical.value = false
  }
  historicalError.value = null
  if (!accountId) {
    historicalLoading.value = false
    return
  }
  historicalLoading.value = true
  try {
    const page = await readHistoricalNotes(accountId, reset ? null : historicalCursor.value)
    // The selected scope falls back to the first loaded account when there is
    // no explicit global active account. Compare against the same canonical
    // account resolver so a valid first-account response is not discarded.
    if (request !== historicalRequest || accountId !== selectedAnalyticsAccountId.value) return
    const items = (page.items || []).filter(note => Boolean(note.note_id))
    const dashboardSnapshot = analyticsStore.snapshotId
    if (hasSnapshotMismatch(dashboardSnapshot, page.snapshot_id)
      || (!reset && hasSnapshotMismatch(historicalSnapshotId.value, page.snapshot_id))) {
      historicalSnapshotMismatch.value = true
      trackInteraction('quality_note_set_mismatch', { source: 'quality', count: 1 })
      trackInteraction('quality_snapshot_lag', { source: 'quality', count: 1 })
      return
    }
    historicalNotes.value = reset ? items : [...historicalNotes.value, ...items]
    historicalTotal.value = Number.isFinite(page.total) ? page.total : historicalNotes.value.length
    historicalCursor.value = page.next_cursor ?? null
    historicalDataAsOf.value = page.data_as_of ?? null
    historicalSnapshotId.value = page.snapshot_id ?? historicalSnapshotId.value ?? dashboardSnapshot
  } catch (error: unknown) {
    if (request === historicalRequest) historicalError.value = error instanceof Error ? error.message : t('analytics.history.loadError')
  } finally {
    if (request === historicalRequest) historicalLoading.value = false
  }
}

const historicalHasMore = computed(() => Boolean(historicalCursor.value) && historicalNotes.value.length < historicalTotal.value)
// The page header already shows the dashboard snapshot's data-as-of; only
// surface the historical reader's own timestamp when it genuinely differs.
const showHistoricalDataAsOf = computed(() =>
  Boolean(historicalDataAsOf.value) && historicalDataAsOf.value !== analyticsStore.dataAsOf
)
const selectedAnalyticsAccountId = computed(() => accountsStore.activeAccountId || accountsStore.accounts[0]?.id || '')
function loadMoreHistorical() {
  if (!historicalLoading.value && historicalHasMore.value) void loadHistoricalNotes(selectedAnalyticsAccountId.value, false)
}

onMounted(async () => {
  // Refresh the shared account labels so a name imported from Creator Center
  // is visible even when this route stayed mounted across the import.
  await accountsStore.fetchAccounts()
  await loadHistoricalNotes(selectedAnalyticsAccountId.value)
  // AN-12: auto-retry once if the previous session ended in an error, instead
  // of leaving the error state showing on re-entry.
  if (analyticsStore.error || (!analyticsStore.posts.length && !analyticsStore.isLoading)) {
    await refreshData()
  }
})

watch(selectedAnalyticsAccountId, (accountId, previous) => {
  if (!accountId || accountId === previous) return
  // Analytics intentionally follows the global active account. Reload both
  // period aggregates and the canonical historical reader as one scope.
  selectedPost.value = null
  void analyticsStore.fetchAllData()
  void loadHistoricalNotes(accountId)
})

watch(() => analyticsStore.snapshotId, (snapshot) => {
  if (hasSnapshotMismatch(snapshot, historicalSnapshotId.value)) {
    historicalSnapshotMismatch.value = true
    trackInteraction('quality_note_set_mismatch', { source: 'quality', count: 1 })
    trackInteraction('quality_snapshot_lag', { source: 'quality', count: 1 })
  }
})

let rawMismatchSnapshot = ''
watch([() => analyticsStore.posts, historicalNotes], () => {
  if (!analyticsStore.posts.length || !historicalNotes.value.length) return
  const facts = new Map(historicalNotes.value.map((note) => [note.note_id, note]))
  let mismatches = 0
  for (const post of analyticsStore.posts) {
    const noteId = post.linked_note_id || (post.source === 'workflow' ? '' : post.id || '')
    const note = noteId ? facts.get(noteId) : undefined
    if (!note) continue
    const postRate = engagementRatePercent(post.engagement_rate, analyticsStore.performanceData?.engagement_rate_unit)
    const noteRate = engagementRatePercent(note.engagement_rate, 'fraction')
    const fieldsMatch = post.views === note.views
      && post.likes === note.likes
      && post.comments === note.comments
      && post.collects === note.collects
      && post.shares === note.shares
      && Math.abs(postRate - noteRate) < 0.001
    if (!fieldsMatch) mismatches += 1
  }
  const snapshotKey = analyticsStore.snapshotId || historicalSnapshotId.value || 'unknown'
  if (mismatches > 0 && rawMismatchSnapshot !== snapshotKey) {
    rawMismatchSnapshot = snapshotKey
    trackInteraction('quality_raw_metric_mismatch', { source: 'quality', count: mismatches })
  }
}, { deep: true })

const isLoading = computed(() => analyticsStore.isLoading && !analyticsStore.posts.length)
// AN-12: switching period keeps old data visible under a busy overlay rather
// than blanking to a skeleton.
const isRefreshing = computed(() => analyticsStore.isLoading && analyticsStore.posts.length > 0)
const hasError = computed(() => !!analyticsStore.error && !analyticsStore.posts.length)
const isEmpty = computed(() => !analyticsStore.isLoading && !analyticsStore.error && !analyticsStore.posts.length && !historicalLoading.value && !historicalNotes.value.length)
// AN-09: refresh failure with cached data must not be silent — surface an
// inline notice that the shown data is stale, with a retry.
const hasStaleError = computed(() => !!analyticsStore.error && analyticsStore.posts.length > 0)

// ponytail: backend period cutoff — daily=24h, weekly=7d, monthly=30d.
// Map the selected period to its i18n label so the switcher buttons reflect
// the actual data window (was hardcoded "thisWeek" for all three).
function periodLabelFor(p: 'daily' | 'weekly' | 'monthly') {
  if (p === 'daily') return t('analytics.today')
  if (p === 'monthly') return t('analytics.thisMonth')
  return t('analytics.thisWeek')
}

const currentPeriod = computed(() => analyticsStore.periodSummary?.current ?? null)
const totalViews = computed(() => currentPeriod.value?.views ?? 0)

// AN-07: period-over-period deltas come from the server-owned aggregate
// contract. The visible post table is intentionally limited to 20 rows and
// must never be used to infer a complete period or its previous window.
const periodBuckets = computed(() => {
  const summary = analyticsStore.periodSummary
  if (!summary) {
    return { curViews: 0, prevViews: 0, curEng: 0, prevEng: 0, curPosts: 0, prevPosts: 0 }
  }
  return {
    curViews: summary.current.views,
    prevViews: summary.previous.views,
    curEng: summary.current.engagement,
    prevEng: summary.previous.engagement,
    curPosts: summary.current.posts,
    prevPosts: summary.previous.posts,
  }
})

function deltaLabel(cur: number, prev: number): string {
  if (prev === 0) return '—'
  const pct = Math.round(((cur - prev) / prev) * 100)
  if (!Number.isFinite(pct)) return '—'
  const arrow = pct > 0 ? '↑' : pct < 0 ? '↓' : '→'
  return `${arrow} ${Math.abs(pct)}% ${t('analytics.vsPrevPeriod')}`
}

const viewsDelta = computed(() => deltaLabel(periodBuckets.value.curViews, periodBuckets.value.prevViews))
const engDelta = computed(() => deltaLabel(periodBuckets.value.curEng, periodBuckets.value.prevEng))
const postsDelta = computed(() => deltaLabel(periodBuckets.value.curPosts, periodBuckets.value.prevPosts))

const metrics = computed(() => [
  // No per-card subtitles: the data window is shown once by the active range
  // button above — repeating the same label on all five cards was noise.
  { icon: 'Upload', title: t('analytics.postsPublished'), value: currentPeriod.value?.posts ?? 0, variant: 'pink' as const, delta: postsDelta.value },
  { icon: 'Eye', title: t('analytics.totalViews'), value: formatNumber(totalViews.value, locale.value), variant: 'cyan' as const, delta: viewsDelta.value },
  { icon: 'MessageCircle', title: t('analytics.totalEngagement'), value: formatNumber(currentPeriod.value?.engagement ?? 0, locale.value), variant: 'purple' as const, delta: engDelta.value },
  { icon: 'TrendingUp', title: t('analytics.avgEngagementRate'), value: formatPercent(engagementRatePercent(currentPeriod.value?.avg_engagement_rate, analyticsStore.periodSummary?.engagement_rate_unit), locale.value), variant: 'peach' as const },
  // AN-05: fans card on the first screen (was buried in CreatorStatsPanel);
  // AI cost moved out to the demoted cost section. No delta: the payload has
  // no historical fans series, so a placeholder dash adds no information.
  { icon: 'Users', title: t('analytics.fans'), value: fansDisplay.value, variant: 'cyan' as const },
])

// AN-01: true daily time series from published_at (was weekday-bucketed avg
// with 0s on empty days). No-data days are omitted (connectNulls:false) so
// the chart never implies zero engagement on a day with no posts.
const trendData = computed(() => {
  const posts = analyticsStore.posts
  if (!posts.length) return []

  const published = posts
    .filter(p => p.published_at)
    .map(p => ({ date: new Date(p.published_at), value: (p.likes || 0) + (p.comments || 0) + (p.collects || 0) }))
    .filter(d => !Number.isNaN(d.date.getTime()))
  if (!published.length) return []

  published.sort((a, b) => a.date.getTime() - b.date.getTime())

  // Bucket by calendar day; sum engagement per day.
  const byDay = new Map<string, number>()
  for (const point of published) {
    const key = trendDateKey(point.date)
    byDay.set(key, (byDay.get(key) || 0) + point.value)
  }

  return Array.from(byDay.entries()).map(([key, value]) => {
    const [y, m, d] = key.split('-').map(Number)
    return { date: formatShortDate(new Date(y, m - 1, d).toISOString(), locale.value), value }
  })
})

function trendDateKey(d: Date): string {
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
}

const engagementData = computed(() => {
  const posts = analyticsStore.posts
  if (!posts.length) return []

  const summary = currentPeriod.value
  const totals = summary
    ? {
      likes: summary.likes,
      comments: summary.comments,
      collects: summary.collects,
      shares: summary.shares,
    }
    : { likes: 0, comments: 0, collects: 0, shares: 0 }

  return [
    { category: t('analytics.categories.likes'), value: totals.likes },
    { category: t('analytics.categories.comments'), value: totals.comments },
    { category: t('analytics.categories.collects'), value: totals.collects },
    { category: t('analytics.categories.shares'), value: totals.shares },
  ]
})

const formatDate = (isoDate: string | null | undefined) => formatShortDate(isoDate, locale.value)

const bestPostTitle = computed(() => analyticsStore.growthReport?.metrics?.best_post_title || '')

const tableColumns = computed(() => [
  { key: 'title', label: t('analytics.table.title'), align: 'left' as const },
  { key: 'views_display', label: t('analytics.table.views'), align: 'center' as const, sortable: true, sortKey: 'views' },
  { key: 'likes', label: t('analytics.table.likes'), align: 'center' as const, sortable: true },
  { key: 'comments', label: t('analytics.table.comments'), align: 'center' as const, sortable: true },
  { key: 'collects', label: t('analytics.table.collects'), align: 'center' as const, sortable: true },
  { key: 'shares', label: t('analytics.table.shares'), align: 'center' as const, sortable: true },
  {
    key: 'engagement_rate_display',
    label: t('analytics.table.engagementRate'),
    align: 'center' as const,
    sortable: true,
    sortKey: 'engagement_rate',
    // ponytail: color-code rate inline — strong ≥5% green, 1–5% amber, <1% muted.
    cellClass: (row: Record<string, unknown>) => {
      const rate = Number(row.engagement_rate)
      if (!Number.isFinite(rate)) return 'font-semibold'
      if (rate >= 5) return 'font-semibold text-emerald-600 dark:text-emerald-400'
      if (rate >= 1) return 'font-semibold text-amber-600 dark:text-amber-400'
      return 'font-semibold text-slate-400'
    },
  },
  { key: 'published_at_display', label: t('analytics.table.publishedAt'), align: 'center' as const },
])

// AN-11: show 10 by default, expand to all (max 20 from backend) on demand.
const showAllPosts = ref(false)
type AnalyticsTableRow = Record<string, unknown> & PostPerformance & {
  views_display: string
  engagement_rate_display: string
  published_at_display: string
}

const visibleTableData = computed<AnalyticsTableRow[]>(() => {
  const canonical = historicalNotes.value.map(note => ({
    id: note.note_id,
    title: note.title,
    likes: note.likes,
    comments: note.comments,
    collects: note.collects,
    shares: note.shares,
    views: note.views,
    // Canonical API stores a fraction; table presentation uses the shared
    // formatter's percent-like input (5 means 5%).
    engagement_rate: engagementRatePercent(note.engagement_rate, 'fraction'),
    published_at: note.published_at,
    source: note.source,
  }))
  const posts = canonical.length
    ? canonical
    : analyticsStore.posts.map(post => ({
      ...post,
      engagement_rate: engagementRatePercent(post.engagement_rate, analyticsStore.performanceData?.engagement_rate_unit),
    }))
  const sliced = canonical.length
    ? (showAllHistorical.value ? posts : posts.slice(0, 10))
    : (showAllPosts.value ? posts : posts.slice(0, 10))
  return sliced.map(post => ({
  ...post,
  views_display: formatNumber(post.views || 0, locale.value),
  engagement_rate_display: formatPercent(post.engagement_rate, locale.value),
  published_at_display: formatDate(post.published_at),
}))
})
const tableData = visibleTableData
const tableUsesCanonicalHistory = computed(() => historicalNotes.value.length > 0)
const tableLoadedCount = computed(() => tableUsesCanonicalHistory.value ? historicalNotes.value.length : analyticsStore.posts.length)
const tableTotalCount = computed(() => tableUsesCanonicalHistory.value ? historicalTotal.value : (analyticsStore.performanceData?.total ?? analyticsStore.posts.length))

function engagementRatePercent(value: number | undefined, unit?: string): number {
  if (value == null || Number.isNaN(value)) return 0
  if (unit === 'fraction') return value * 100
  if (unit === 'percent') return value
  return value <= 1 ? value * 100 : value
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function exportPostsCsv() {
  const headers = [
    t('analytics.table.title'),
    t('analytics.table.views'),
    t('analytics.table.likes'),
    t('analytics.table.comments'),
    t('analytics.table.collects'),
    t('analytics.table.shares'),
    t('analytics.table.engagementRate'),
    t('analytics.table.publishedAt'),
  ]
  const exportRows = tableUsesCanonicalHistory.value ? historicalNotes.value : analyticsStore.posts
  const rows = exportRows.map(post => [
    post.title,
    post.views,
    post.likes,
    post.comments,
    post.collects,
    post.shares,
    engagementRatePercent(
      post.engagement_rate,
      tableUsesCanonicalHistory.value ? 'fraction' : analyticsStore.performanceData?.engagement_rate_unit,
    ),
    post.published_at,
  ])
  const csv = [headers, ...rows].map(row => row.map(csvCell).join(',')).join('\n')
  const blob = new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `analytics-${analyticsStore.period}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

// Model cost bar data
const modelCostData = computed(() => {
  const byModel = analyticsStore.costData?.by_model
  if (!byModel || !Object.keys(byModel).length) return []

  const entries = Object.entries(byModel) as [string, number][]
  const maxCost = Math.max(...entries.map(([, cost]) => cost))

  return entries
    .map(([model, cost]) => ({
      model,
      cost,
      percent: maxCost > 0 ? (cost / maxCost) * 100 : 0,
    }))
    .sort((a, b) => b.cost - a.cost)
})

const setPeriod = (period: 'daily' | 'weekly' | 'monthly') => {
  trackInteraction('analytics_period_change', { period, old_period: analyticsStore.period })
  analyticsStore.setPeriod(period)
}

async function refreshData() {
  await analyticsStore.fetchAllData()
  if (!analyticsStore.error) lastUpdatedAt.value = new Date()
  const linkStats = analyticsStore.performanceData?.link_stats
  if (linkStats?.workflow_count) {
    trackInteraction('workflow_note_link_rate', {
      source: 'quality',
      count: linkStats.linked_count ?? 0,
    })
  }
  // AN-05: best-effort fetch of creator fans for the first-screen card; do not
  // block on failure (the rest of the page still renders).
  const accountId = accountsStore.activeAccountId || analyticsStore.accountId
  if (accountId) {
    try {
      const payload = await analyticsApi.getCreatorStats(accountId, 1)
      creatorAccount.value = payload.account
    } catch {
      // Fans card falls back to '—'; not a page-level failure.
    }
  }
}

function handleCreatorStatsUpdated() {
  refreshData()
}

function goHome() {
  router.push('/start')
}

// AN-08: single-post drill-down. The table row emits its data; we open a
// drawer with the post's metrics and the creator-note quality panel (which
// reuses the existing getCreatorNote/getCreatorNoteQuality APIs).
const selectedPost = ref<Record<string, unknown> | null>(null)
const detailNoteId = computed(() => {
  // The backend's id is the imported note_id when available. Never use title
  // matching: titles are not stable identifiers and a missing match must not
  // silently select another note in the quality panel.
  const source = selectedPost.value?.source
  const linkStatus = selectedPost.value?.link_status
  if (source === 'workflow' && linkStatus !== 'linked') return ''
  return typeof selectedPost.value?.id === 'string' ? selectedPost.value.id : ''
})
const detailAccountId = computed(() => accountsStore.activeAccountId || analyticsStore.accountId || '')
// The row-metric grid is the fallback for posts with no linked creator note.
// When the quality panel renders, its freshly fetched metric cards cover the
// same numbers — showing the grid as well duplicated them.
const showDetailMetrics = computed(() => !(detailAccountId.value && detailNoteId.value))

function openPostDetail(row: Record<string, unknown>) {
  trackInteraction('analytics_note_drilldown', { method: 'click' })
  selectedPost.value = row
}
function closePostDetail() {
  selectedPost.value = null
}

// INF-06: trap focus inside the drill-down drawer and restore on close.
const focusTrap = useFocusTrap()
const drawerRef = ref<HTMLElement | null>(null)
watch(selectedPost, async (post) => {
  if (post) {
    await nextTick()
    focusTrap.activate(drawerRef.value)
  } else {
    focusTrap.deactivate()
  }
})

const budgetUsedPercent = computed(() => {
  const total = analyticsStore.costData?.total_cost_usd || 0
  const remaining = analyticsStore.costData?.budget_remaining_usd || 0
  const budget = total + remaining
  if (budget <= 0) return 0
  return Math.round((total / budget) * 100)
})

const insights = computed(() => analyticsStore.growthReport?.insights || [])
const trendTopics = computed(() => analyticsStore.growthReport?.metrics?.trend_topics || [])

const insightIcon = (type: string) => {
  switch (type) {
    case 'trend': return 'TrendingUp'
    case 'opportunity': return 'Lightbulb'
    case 'warning': return 'AlertTriangle'
    default: return 'Info'
  }
}

const insightVariant = (type: string) => {
  switch (type) {
    case 'trend': return 'cyan'
    case 'opportunity': return 'purple'
    case 'warning': return 'peach'
    default: return 'cyan'
  }
}

const insightBg = (type: string) => {
  switch (type) {
    case 'trend': return 'bg-teal-50 border-teal-100'
    case 'opportunity': return 'bg-violet-50 border-violet-100'
    case 'warning': return 'bg-amber-50 border-amber-100'
    default: return 'bg-slate-50 border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50'
  }
}

function startWithTopic(topic: string, niche?: string) {
  // Topic text is user content; keep it in the navigation query only and send
  // a categorical telemetry event so browser listeners/beacons never receive
  // raw content.
  trackInteraction('analytics_topic_click', { method: 'click', source: 'direct' })
  const query: Record<string, string> = { topic }
  if (niche) query.niche = niche
  router.push({ path: '/start', query })
}
</script>

<template>
  <div class="app-page-content space-y-4 md:space-y-6">
    <PageHeader
      :title="t('analytics.title')"
      icon="BarChart3"
      tone="cyan"
    >
      <template #meta>
        <span v-if="accountsStore.activeAccount?.name || analyticsStore.accountId">
          {{ t('analytics.account') }}: {{ accountsStore.activeAccount?.name || analyticsStore.accountId }}
        </span>
        <!-- Period is already shown by the active range button below; the raw
             enum value here was redundant and unlocalized. -->
        <span v-if="lastUpdatedAt" role="status">
          {{ t('analytics.lastUpdated', { time: lastUpdatedAt.toLocaleTimeString(locale || undefined) }) }}
        </span>
        <span v-if="analyticsStore.dataAsOf" role="status">
          {{ t('evaluation.dataAsOf') }} {{ formatDate(analyticsStore.dataAsOf) }}
        </span>
      </template>
      <template #actions>
        <NeonButton
          variant="cyan"
          size="sm"
          class="min-h-11 w-full sm:w-auto"
          @click="refreshData"
          :disabled="analyticsStore.isLoading"
        >
          <span class="inline-flex items-center gap-1.5">
            <AppIcon name="RefreshCw" size="sm" variant="white" :class="{ 'animate-spin': analyticsStore.isLoading }" />
            {{ analyticsStore.isLoading ? t('analytics.refreshing') : t('analytics.refresh') }}
          </span>
        </NeonButton>
        <div v-if="!isLoading && !hasError && !isEmpty" class="grid w-full grid-cols-3 gap-1.5 sm:w-auto">
          <NeonButton
            v-for="p in ['daily', 'weekly', 'monthly']"
            :key="p"
            :variant="analyticsStore.period === p ? 'cyan' : 'ghost'"
            size="sm"
            class="min-h-11 min-w-0 justify-center px-2 sm:px-3"
            @click="setPeriod(p as any)"
            :aria-pressed="analyticsStore.period === p"
            :aria-label="periodLabelFor(p as any)"
          >
            <span class="inline-flex items-center justify-center gap-1 whitespace-nowrap">
              <AppIcon name="Calendar" size="sm" :variant="analyticsStore.period === p ? 'white' : 'cyan'" />
              {{ periodLabelFor(p as any) }}
            </span>
          </NeonButton>
        </div>
      </template>
    </PageHeader>

  <AnalyticsSkeleton v-if="isLoading" />

  <!-- Error state -->
  <div v-else-if="hasError" class="relative space-y-4 md:space-y-6">
    <div class="card">
      <div class="flex flex-col items-center gap-3 md:gap-4 py-6 md:py-8">
        <div class="w-10 h-10 md:w-14 md:h-14 rounded-lg md:rounded-xl bg-rose-50 flex items-center justify-center">
          <AppIcon name="AlertTriangle" size="md" variant="pink" class="md:hidden" />
          <AppIcon name="AlertTriangle" size="xl" variant="pink" class="hidden md:block" />
        </div>
        <div class="text-base md:text-lg font-semibold text-slate-800">{{ t('analytics.error.title') }}</div>
        <div class="text-xs md:text-sm text-slate-500 text-center max-w-md">{{ t('analytics.error.description') }}</div>
        <button
          type="button"
          @click="refreshData"
          :disabled="analyticsStore.isLoading"
          class="min-h-11 px-4 py-2 rounded-lg bg-rose-500 text-white text-sm font-medium hover:bg-rose-600 transition-all duration-200 flex items-center gap-2 disabled:opacity-50"
        >
          <AppIcon name="RefreshCw" size="sm" variant="white" />
          {{ analyticsStore.isLoading ? t('analytics.refreshing') : t('analytics.error.retry') }}
        </button>
      </div>
    </div>
  </div>

  <!-- Empty state -->
  <div v-else-if="isEmpty" class="relative space-y-4 md:space-y-6">
    <div class="card">
      <div class="flex flex-col items-center gap-3 md:gap-4 py-6 md:py-8">
        <div class="w-10 h-10 md:w-14 md:h-14 rounded-lg md:rounded-xl bg-teal-50 flex items-center justify-center">
          <AppIcon name="BarChart3" size="md" variant="cyan" class="md:hidden" />
          <AppIcon name="BarChart3" size="xl" variant="cyan" class="hidden md:block" />
        </div>
        <div class="text-base md:text-lg font-semibold text-slate-800">{{ t('analytics.empty.title') }}</div>
        <div class="text-xs md:text-sm text-slate-500 text-center max-w-md">{{ t('analytics.empty.description') }}</div>
        <div class="flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            @click="goHome"
            class="min-h-11 px-4 py-2 rounded-lg bg-teal-500 text-white text-sm font-medium hover:bg-teal-600 transition-all duration-200 flex items-center gap-2"
          >
            <AppIcon name="Plus" size="sm" variant="white" />
            {{ t('analytics.empty.startWorkflow') }}
          </button>
        </div>
        <!-- No separate import hint here: the creator panel directly below
             carries the import UI and its own instructions. -->
      </div>
    </div>
  </div>

  <!-- Data view -->
  <div v-else class="relative space-y-4 md:space-y-6">
    <!-- AN-12: busy overlay while switching period — keeps the old data visible. -->
    <div
      v-if="isRefreshing"
      class="absolute inset-0 z-20 flex items-center justify-center rounded-2xl bg-white/50 backdrop-blur-[1px] dark:bg-slate-900/50"
      role="status"
      aria-live="polite"
    >
      <AppIcon name="Loader2" size="md" variant="cyan" animate />
    </div>
    <!-- AN-09: refresh failed but cached data still shown — surface a stale
         notice so the failure isn't silent. -->
    <div
      v-if="hasStaleError"
      class="flex items-center gap-3 rounded-xl border border-amber-200/70 bg-amber-50/90 px-3 py-2 text-xs md:text-sm text-amber-700 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-200"
      role="alert"
    >
      <AppIcon name="AlertTriangle" size="sm" variant="peach" aria-hidden="true" />
      <span class="flex-1">{{ t('analytics.staleNotice') }}</span>
      <button
        type="button"
        class="rounded-lg px-2.5 py-1 text-xs font-medium bg-amber-600 text-white hover:bg-amber-700 active:scale-95 transition min-h-[36px]"
        @click="refreshData"
      >
        {{ t('analytics.error.retry') }}
      </button>
    </div>
    <!-- Metric cards (5 columns on xl) -->
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-5 gap-3 md:gap-5">
      <MetricCard
        v-for="metric in metrics"
        :key="metric.title"
        v-bind="metric"
      />
    </div>

    <!-- Growth insights (AN-06: conclusion-first — insights before charts) -->
    <div v-if="insights.length > 0 || trendTopics.length > 0" class="card">
      <div class="flex items-center gap-2 md:gap-3 mb-3 md:mb-5">
        <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-gradient-to-br from-amber-400 to-amber-500 flex items-center justify-center shadow-sm">
          <AppIcon name="Lightbulb" size="sm" variant="white" class="md:hidden" :aria-label="t('analytics.insights.title')" />
          <AppIcon name="Lightbulb" size="md" variant="white" class="hidden md:block" :aria-label="t('analytics.insights.title')" />
        </div>
        <div class="flex-1">
          <div class="text-amber-600 font-semibold text-xs md:text-sm">{{ t('analytics.insights.title') }}</div>
          <div class="text-[10px] md:text-xs text-slate-400">{{ t('analytics.insights.subtitle') }}</div>
        </div>
      </div>

      <!-- Insight cards -->
      <div class="space-y-2 md:space-y-3 mb-3 md:mb-5">
        <div
          v-for="(insight, idx) in insights"
          :key="idx"
          class="flex items-start gap-2 md:gap-3 p-2.5 md:p-4 rounded-lg border"
          :class="insightBg(insight.type)"
        >
          <div class="w-6 h-6 rounded flex items-center justify-center flex-shrink-0 mt-0.5" :class="{
            'bg-teal-100 dark:bg-teal-950/50': insight.type === 'trend',
            'bg-violet-100 dark:bg-violet-950/50': insight.type === 'opportunity',
            'bg-amber-100 dark:bg-amber-950/50': insight.type === 'warning',
            'bg-slate-100 dark:bg-slate-800': insight.type === 'info',
          }">
            <AppIcon :name="insightIcon(insight.type)" size="sm" :variant="insightVariant(insight.type) as any" />
          </div>
          <p class="text-xs md:text-sm text-slate-700">{{ insight.message }}</p>
        </div>
      </div>

      <!-- Trending topics with workflow trigger -->
      <div v-if="trendTopics.length > 0" class="border-t border-slate-100 pt-3 md:pt-5">
        <div class="flex items-center justify-between mb-2 md:mb-3">
          <span class="text-[10px] md:text-xs text-slate-500 uppercase tracking-wide font-medium">{{ t('analytics.hotTopics') }}</span>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="topic in trendTopics"
            :key="topic"
            type="button"
            @click="startWithTopic(topic)"
            class="min-h-11 px-3 py-1.5 rounded-lg bg-teal-50 border border-teal-100 text-teal-700 text-xs font-medium hover:bg-teal-100 hover:border-teal-200 transition-all duration-200 flex items-center gap-1.5"
          >
            <AppIcon name="Sparkles" size="sm" variant="cyan" />
            {{ topic }}
            <span class="text-teal-400 text-xs">{{ t('analytics.launch') }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Charts -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-3 md:gap-5">
      <Suspense>
        <TrendChart
          :data="trendData"
          :title="t('analytics.recentPerformanceTrend')"
          variant="cyan"
          :height="220"
        />
        <template #fallback>
          <div class="rounded-xl md:rounded-2xl p-3 md:p-6 liquid-glass">
            <div class="h-[220px] rounded-lg bg-slate-100 animate-pulse dark:bg-slate-800" />
          </div>
        </template>
      </Suspense>
      <Suspense>
        <EngagementChart
          :data="engagementData"
          :title="t('analytics.engagementBreakdown')"
          variant="pink"
          :height="220"
        />
        <template #fallback>
          <div class="rounded-xl md:rounded-2xl p-3 md:p-6 liquid-glass">
            <div class="h-[220px] rounded-lg bg-slate-100 animate-pulse dark:bg-slate-800" />
          </div>
        </template>
      </Suspense>
    </div>

    <!-- Post performance table -->
    <div class="card">
      <div class="flex items-center gap-2 md:gap-3 mb-3 md:mb-5">
        <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
          <AppIcon name="FileText" size="sm" variant="white" class="md:hidden" :aria-label="t('analytics.recentPosts')" />
          <AppIcon name="FileText" size="md" variant="white" class="hidden md:block" :aria-label="t('analytics.recentPosts')" />
        </div>
        <div class="flex-1">
          <div class="text-violet-600 font-semibold text-xs md:text-sm">{{ tableUsesCanonicalHistory ? t('analytics.history.title') : t('analytics.recentPosts') }}</div>
          <!-- Both modes are recency-sorted (backend sorts published_at desc),
               so the subtitle reports loaded/total counts — the old "TOP 10"
               label implied a performance ranking the data does not have. -->
          <div class="text-[10px] md:text-xs text-slate-400">{{ t('analytics.history.loadedCount', { loaded: Math.min(tableData.length, tableLoadedCount), total: tableTotalCount }) }}</div>
        </div>
        <button
          type="button"
          class="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          @click="exportPostsCsv"
        >
          <AppIcon name="Download" size="sm" variant="cyan" aria-hidden="true" />
          {{ t('analytics.exportCsv') }}
        </button>
      </div>

      <div v-if="historicalError" class="mb-3 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-950/30 dark:text-amber-200" role="alert">
        <AppIcon name="AlertTriangle" size="sm" variant="peach" />
        <span class="flex-1">{{ historicalError }}</span>
      <button type="button" class="min-h-[36px] rounded-md border border-amber-300 px-2 font-medium hover:bg-amber-100 dark:border-amber-400/40 dark:hover:bg-amber-900/40" @click="loadHistoricalNotes(selectedAnalyticsAccountId)">{{ t('analytics.history.retry') }}</button>
      </div>
      <div v-if="showHistoricalDataAsOf" class="mb-2 text-[11px] text-slate-400" role="status">{{ t('analytics.history.dataAsOf', { time: formatDate(historicalDataAsOf) }) }}</div>
      <div v-if="historicalSnapshotMismatch" class="mb-3 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2 text-xs text-amber-700 dark:border-amber-400/30 dark:bg-amber-950/30 dark:text-amber-200" role="alert">
        <AppIcon name="AlertTriangle" size="sm" variant="peach" />
        <span class="flex-1">{{ t('analytics.history.snapshotMismatch') }}</span>
        <button type="button" class="min-h-9 rounded-md border border-amber-300 px-2 font-medium hover:bg-amber-100 dark:border-amber-400/40 dark:hover:bg-amber-900/40" @click="loadHistoricalNotes(selectedAnalyticsAccountId)">{{ t('analytics.history.retry') }}</button>
      </div>

      <DataTable
        :columns="tableColumns"
        :data="tableData"
        highlight-row-key="title"
        :highlight-key-value="bestPostTitle"
        row-clickable
        @row-click="openPostDetail"
      />
      <!-- AN-11: legend explaining the best-post highlight, and an expand
           control so all 20 posts are reachable (was hard-capped at 10). -->
      <div v-if="bestPostTitle" class="mt-2 flex items-center gap-1.5 text-[11px] text-slate-500">
        <span class="inline-block w-2.5 h-2.5 rounded-sm bg-rose-200" aria-hidden="true" />
        <span>{{ t('analytics.bestPostLegend') }}</span>
      </div>
      <div v-if="tableUsesCanonicalHistory && historicalNotes.length > 10" class="mt-3 flex flex-wrap items-center justify-center gap-2">
        <button type="button" class="min-h-[44px] px-4 py-1.5 rounded-lg border border-slate-200 bg-white text-xs font-medium text-slate-600 hover:bg-slate-50 transition dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300" @click="showAllHistorical = !showAllHistorical">
          <!-- Counts live in the section subtitle above; the button stays an
               action label only. -->
          {{ showAllHistorical ? t('analytics.showLess') : t('analytics.history.showAll') }}
        </button>
        <button v-if="historicalHasMore" type="button" class="min-h-[44px] px-4 py-1.5 rounded-lg border border-violet-200 bg-violet-50 text-xs font-medium text-violet-700 hover:bg-violet-100 transition dark:border-violet-500/40 dark:bg-violet-950/30 dark:text-violet-200" :disabled="historicalLoading" @click="loadMoreHistorical">
          {{ historicalLoading ? t('analytics.refreshing') : t('analytics.history.loadMore') }}
        </button>
      </div>
      <div v-else-if="!tableUsesCanonicalHistory && analyticsStore.posts.length > 10" class="mt-3 flex justify-center">
        <button
          type="button"
          class="min-h-[44px] px-4 py-1.5 rounded-lg border border-slate-200 bg-white text-xs font-medium text-slate-600 hover:bg-slate-50 transition dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300"
          @click="showAllPosts = !showAllPosts"
        >
          {{ showAllPosts ? t('analytics.showLess') : t('analytics.showAll', { count: analyticsStore.posts.length }) }}
        </button>
      </div>
    </div>

    <!-- Cost breakdown (AN-06: demoted to secondary, after the post table) -->
    <details v-if="analyticsStore.costData" class="card">
      <summary class="flex cursor-pointer items-center gap-2 md:gap-3 list-none">
        <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-gradient-to-br from-rose-400 to-rose-500 flex items-center justify-center shadow-sm">
          <AppIcon name="DollarSign" size="sm" variant="white" class="md:hidden" :aria-label="t('analytics.cost.title')" />
          <AppIcon name="DollarSign" size="md" variant="white" class="hidden md:block" :aria-label="t('analytics.cost.title')" />
        </div>
        <div class="flex-1">
          <div class="text-rose-500 font-semibold text-xs md:text-sm">{{ t('analytics.cost.title') }}</div>
          <div class="text-[10px] md:text-xs text-slate-400">{{ t('analytics.cost.subtitle') }}</div>
        </div>
      </summary>

      <div class="grid grid-cols-3 gap-2 md:gap-4 mb-3 md:mb-5 mt-3 md:mt-5">
        <div class="rounded-lg p-2 md:p-4 liquid-glass-rose liquid-glass-hover">
          <div class="text-[10px] md:text-xs text-rose-500 font-medium">{{ t('analytics.cost.total') }}</div>
          <div class="text-base md:text-xl font-bold text-rose-700">${{ analyticsStore.costData.total_cost_usd?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-2 md:p-4 liquid-glass-amber liquid-glass-hover">
          <div class="text-[10px] md:text-xs text-amber-500 font-medium">{{ t('analytics.cost.today') }}</div>
          <div class="text-base md:text-xl font-bold text-amber-700">${{ analyticsStore.costData.today_cost_usd?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-2 md:p-4 liquid-glass-teal liquid-glass-hover">
          <div class="text-[10px] md:text-xs text-emerald-500 font-medium">{{ t('analytics.cost.remaining') }}</div>
          <div class="text-base md:text-xl font-bold text-emerald-700">${{ analyticsStore.costData.budget_remaining_usd?.toFixed(2) || '0.00' }}</div>
        </div>
      </div>

      <!-- Budget progress bar -->
      <div v-if="analyticsStore.costData.total_cost_usd" class="mb-3 md:mb-5">
        <div class="flex items-center justify-between text-[10px] md:text-xs text-slate-500 mb-1.5 md:mb-2">
          <span>{{ t('analytics.cost.budgetUsed') }}</span>
          <span>{{ budgetUsedPercent }}%</span>
        </div>
        <div class="h-2 rounded-full bg-slate-100 overflow-hidden dark:bg-slate-800">
          <div
            class="h-full rounded-full transition-all duration-500"
            :class="budgetUsedPercent > 90 ? 'bg-rose-500' : budgetUsedPercent > 70 ? 'bg-amber-500' : 'bg-emerald-500'"
            :style="{ width: `${Math.min(budgetUsedPercent, 100)}%` }"
          />
        </div>
      </div>

      <!-- By model breakdown (visual bars) -->
      <div v-if="modelCostData.length > 0">
        <div class="text-[10px] md:text-xs text-slate-500 uppercase tracking-wide font-medium mb-2 md:mb-3">{{ t('analytics.cost.byModel') }}</div>
        <div class="space-y-2 md:space-y-3">
          <div
            v-for="item in modelCostData"
            :key="item.model"
            class="group"
          >
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs md:text-sm text-slate-700 font-medium truncate">{{ item.model }}</span>
              <span class="text-xs md:text-sm text-slate-600 tabular-nums">${{ item.cost.toFixed(2) }}</span>
            </div>
            <div class="h-1.5 rounded-full bg-slate-100 overflow-hidden dark:bg-slate-800">
              <div
                class="h-full rounded-full bg-gradient-to-r from-rose-400 to-rose-500 transition-all duration-500 group-hover:from-rose-500 group-hover:to-rose-600"
                :style="{ width: `${item.percent}%` }"
              />
            </div>
          </div>
        </div>
      </div>
    </details>
  </div>

  <!-- Creator-center import / niche bind. A single instance shared by the
       error, empty and data states (was duplicated in each branch), demoted
       below the analytics content so results come first and tools last. -->
  <section
    v-if="!isLoading && (accountsStore.activeAccountId || analyticsStore.accountId)"
    class="min-w-0"
    :aria-label="t('creatorStats.title')"
  >
    <CreatorStatsPanel
      :account-id="accountsStore.activeAccountId || analyticsStore.accountId"
      :account-name="accountsStore.activeAccount?.name"
      compact
      @updated="handleCreatorStatsUpdated"
    />
  </section>
  </div>

  <!-- AN-08: single-post drill-down drawer -->
  <Teleport to="body">
    <div
      v-if="selectedPost"
      ref="drawerRef"
      class="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      :aria-label="t('analytics.detail.title')"
    >
      <div class="absolute inset-0 bg-black/40" @click="closePostDetail" />
      <div class="relative w-full max-w-md h-full overflow-y-auto bg-white dark:bg-slate-900 shadow-xl p-4 md:p-6 space-y-4">
        <div class="flex items-start justify-between gap-3">
          <h2 class="text-base md:text-lg font-semibold text-slate-800 dark:text-slate-100 truncate">{{ selectedPost.title || t('analytics.detail.untitled') }}</h2>
          <button type="button" class="shrink-0 rounded-lg p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 min-h-[44px] min-w-[44px]" :aria-label="t('common.close')" @click="closePostDetail">
            <AppIcon name="X" size="sm" />
          </button>
        </div>
        <dl v-if="showDetailMetrics" class="grid grid-cols-2 gap-3 text-sm">
          <div class="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
            <dt class="text-xs text-slate-500">{{ t('analytics.table.views') }}</dt>
            <dd class="font-semibold text-slate-800 dark:text-slate-100">{{ selectedPost.views_display }}</dd>
          </div>
          <div class="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
            <dt class="text-xs text-slate-500">{{ t('analytics.table.likes') }}</dt>
            <dd class="font-semibold text-slate-800 dark:text-slate-100">{{ selectedPost.likes }}</dd>
          </div>
          <div class="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
            <dt class="text-xs text-slate-500">{{ t('analytics.table.comments') }}</dt>
            <dd class="font-semibold text-slate-800 dark:text-slate-100">{{ selectedPost.comments }}</dd>
          </div>
          <div class="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
            <dt class="text-xs text-slate-500">{{ t('analytics.table.collects') }}</dt>
            <dd class="font-semibold text-slate-800 dark:text-slate-100">{{ selectedPost.collects }}</dd>
          </div>
          <div class="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
            <dt class="text-xs text-slate-500">{{ t('analytics.table.shares') }}</dt>
            <dd class="font-semibold text-slate-800 dark:text-slate-100">{{ selectedPost.shares }}</dd>
          </div>
          <div class="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
            <dt class="text-xs text-slate-500">{{ t('analytics.table.engagementRate') }}</dt>
            <dd class="font-semibold text-slate-800 dark:text-slate-100">{{ selectedPost.engagement_rate_display }}</dd>
          </div>
          <div class="rounded-lg bg-slate-50 p-3 dark:bg-slate-800">
            <dt class="text-xs text-slate-500">{{ t('analytics.table.publishedAt') }}</dt>
            <dd class="font-semibold text-slate-800 dark:text-slate-100">{{ selectedPost.published_at_display }}</dd>
          </div>
        </dl>
        <CreatorNoteQualityPanel
          v-if="detailAccountId && detailNoteId"
          :account-id="detailAccountId"
          :note-id="detailNoteId"
          compact
        />
        <div
          v-else-if="selectedPost?.source === 'workflow'"
          class="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-500 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-400"
          role="status"
        >
          {{ t('analytics.detail.noLinkedNote') }}
        </div>
      </div>
    </div>
  </Teleport>
</template>
