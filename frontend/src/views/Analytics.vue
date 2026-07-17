<script setup lang="ts">
import { onMounted, computed, ref, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import MetricCard from '@/components/MetricCard.vue'
import DataTable from '@/components/DataTable.vue'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import PageHeader from '@/components/PageHeader.vue'
import CreatorStatsPanel from '@/components/settings/CreatorStatsPanel.vue'
import { AnalyticsSkeleton } from '@/components/skeletons'
import { useAnalyticsStore, useAccountsStore } from '@/stores'

const TrendChart = defineAsyncComponent(() => import('@/components/charts/TrendChart.vue'))
const EngagementChart = defineAsyncComponent(() => import('@/components/charts/EngagementChart.vue'))

const { t, locale } = useI18n()
const router = useRouter()
const analyticsStore = useAnalyticsStore()
const accountsStore = useAccountsStore()
const lastUpdatedAt = ref<Date | null>(null)

onMounted(async () => {
  // Refresh the shared account labels so a name imported from Creator Center
  // is visible even when this route stayed mounted across the import.
  await accountsStore.fetchAccounts()
  if (!analyticsStore.posts.length && !analyticsStore.isLoading && !analyticsStore.error) {
    await refreshData()
  }
})

const isLoading = computed(() => analyticsStore.isLoading && !analyticsStore.posts.length)
const hasError = computed(() => !!analyticsStore.error && !analyticsStore.posts.length)
const isEmpty = computed(() => !analyticsStore.isLoading && !analyticsStore.error && !analyticsStore.posts.length)

// ponytail: backend period cutoff — daily=24h, weekly=7d, monthly=30d.
// Map the selected period to its i18n label so cards/buttons reflect the
// actual data window (was hardcoded "thisWeek" for all three).
const periodLabel = computed(() => periodLabelFor(analyticsStore.period))
function periodLabelFor(p: 'daily' | 'weekly' | 'monthly') {
  if (p === 'daily') return t('analytics.today')
  if (p === 'monthly') return t('analytics.thisMonth')
  return t('analytics.thisWeek')
}

const totalViews = computed(() => analyticsStore.posts.reduce((sum, p) => sum + (p.views || 0), 0))

const metrics = computed(() => [
  { icon: 'Upload', title: t('analytics.postsPublished'), value: analyticsStore.posts.length, subtitle: periodLabel.value, variant: 'pink' as const },
  { icon: 'Eye', title: t('analytics.totalViews'), value: totalViews.value.toLocaleString(), subtitle: periodLabel.value, variant: 'cyan' as const },
  { icon: 'MessageCircle', title: t('analytics.totalEngagement'), value: analyticsStore.totalEngagement.toLocaleString(), subtitle: `${analyticsStore.posts.length} ` + t('analytics.postsPublished'), variant: 'purple' as const },
  { icon: 'TrendingUp', title: t('analytics.avgEngagementRate'), value: `${analyticsStore.avgEngagementRate.toFixed(1)}%`, subtitle: analyticsStore.posts.length > 0 ? `${analyticsStore.posts.length} ` + t('analytics.postsPublished') : periodLabel.value, variant: 'peach' as const },
  { icon: 'DollarSign', title: t('analytics.aiCost'), value: `$${analyticsStore.costData?.today_cost_usd?.toFixed(2) || '0.00'}`, subtitle: t('analytics.cost.today'), variant: 'pink' as const },
])

const trendData = computed(() => {
  const posts = analyticsStore.posts
  if (!posts.length) return []

  const hasPublishedPosts = posts.some(p => p.published_at)
  if (!hasPublishedPosts) return []

  const dayNames = [
    t('analytics.weekdays.sun'),
    t('analytics.weekdays.mon'),
    t('analytics.weekdays.tue'),
    t('analytics.weekdays.wed'),
    t('analytics.weekdays.thu'),
    t('analytics.weekdays.fri'),
    t('analytics.weekdays.sat'),
  ]
  const dayTotals = new Array(7).fill(0)
  const dayCounts = new Array(7).fill(0)

  posts.forEach(post => {
    if (post.published_at) {
      const d = new Date(post.published_at)
      const day = d.getDay()
      dayTotals[day] += post.likes + post.comments + post.collects
      dayCounts[day]++
    }
  })

  return [1, 2, 3, 4, 5, 6, 0].map(day => ({
    date: dayNames[day],
    value: dayCounts[day] > 0 ? Math.round(dayTotals[day] / dayCounts[day]) : 0,
  }))
})

const engagementData = computed(() => {
  const posts = analyticsStore.posts
  if (!posts.length) return []

  const totals = posts.reduce(
    (acc, post) => ({
      likes: acc.likes + post.likes,
      comments: acc.comments + post.comments,
      collects: acc.collects + post.collects,
      shares: acc.shares + (post.shares || 0),
    }),
    { likes: 0, comments: 0, collects: 0, shares: 0 }
  )

  return [
    { category: t('analytics.categories.likes'), value: totals.likes },
    { category: t('analytics.categories.comments'), value: totals.comments },
    { category: t('analytics.categories.collects'), value: totals.collects },
    { category: t('analytics.categories.shares'), value: totals.shares },
  ]
})

const formatDate = (isoDate: string | null | undefined) => {
  if (!isoDate) return '—'
  const d = new Date(isoDate)
  const month = d.toLocaleDateString(locale.value || undefined, { month: 'short' })
  const day = d.getDate()
  return `${month} ${day}`
}

const bestPostTitle = computed(() => analyticsStore.growthReport?.metrics?.best_post_title || '')

const tableColumns = computed(() => [
  { key: 'title', label: t('analytics.table.title'), align: 'left' as const },
  { key: 'views_display', label: t('analytics.table.views'), align: 'center' as const, sortable: true },
  { key: 'likes', label: t('analytics.table.likes'), align: 'center' as const, sortable: true },
  { key: 'comments', label: t('analytics.table.comments'), align: 'center' as const, sortable: true },
  { key: 'collects', label: t('analytics.table.collects'), align: 'center' as const, sortable: true },
  {
    key: 'engagement_rate_display',
    label: t('analytics.table.engagementRate'),
    align: 'center' as const,
    sortable: true,
    // ponytail: color-code rate inline — strong ≥5% green, 1–5% amber, <1% muted.
    cellClass: (row: Record<string, any>) => {
      const rate = Number(row.engagement_rate)
      if (!Number.isFinite(rate)) return 'font-semibold'
      if (rate >= 5) return 'font-semibold text-emerald-600 dark:text-emerald-400'
      if (rate >= 1) return 'font-semibold text-amber-600 dark:text-amber-400'
      return 'font-semibold text-slate-400'
    },
  },
  { key: 'published_at_display', label: t('analytics.table.publishedAt'), align: 'center' as const },
])

const tableData = computed(() => analyticsStore.posts.slice(0, 10).map(post => ({
  ...post,
  views_display: (post.views || 0).toLocaleString(),
  engagement_rate_display: `${post.engagement_rate.toFixed(1)}%`,
  published_at_display: formatDate(post.published_at),
})))

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
  analyticsStore.setPeriod(period)
}

async function refreshData() {
  await analyticsStore.fetchAllData()
  if (!analyticsStore.error) lastUpdatedAt.value = new Date()
}

function handleCreatorStatsUpdated() {
  refreshData()
}

function goHome() {
  router.push('/start')
}

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
  const query: Record<string, string> = { topic }
  if (niche) query.niche = niche
  router.push({ path: '/start', query })
}
</script>

<template>
  <div class="app-page-content space-y-4 md:space-y-6">
    <PageHeader
      :title="t('analytics.title')"
      :description="t('analytics.insights.subtitle')"
      :eyebrow="t('analytics.analyticsLabel')"
      icon="BarChart3"
      tone="cyan"
    >
      <template #meta>
        <span v-if="accountsStore.activeAccount?.name || analyticsStore.accountId">
          {{ t('analytics.account') }}: {{ accountsStore.activeAccount?.name || analyticsStore.accountId }}
        </span>
        <span>{{ t('analytics.period') }}: {{ analyticsStore.period }}</span>
        <span v-if="lastUpdatedAt" role="status">
          {{ t('analytics.lastUpdated', { time: lastUpdatedAt.toLocaleTimeString(locale || undefined) }) }}
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
    <!-- Import still available when dashboard fetch fails -->
    <CreatorStatsPanel
      v-if="accountsStore.activeAccountId || analyticsStore.accountId"
      :account-id="accountsStore.activeAccountId || analyticsStore.accountId"
      :account-name="accountsStore.activeAccount?.name"
      compact
      @updated="handleCreatorStatsUpdated"
    />
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
        <p class="text-[11px] text-slate-400 text-center max-w-md">
          {{ t('analytics.empty.importHint') }}
        </p>
      </div>
    </div>
    <!-- Still allow creator-center import when workflow posts are empty -->
    <CreatorStatsPanel
      v-if="accountsStore.activeAccountId || analyticsStore.accountId"
      :account-id="accountsStore.activeAccountId || analyticsStore.accountId"
      :account-name="accountsStore.activeAccount?.name"
      compact
      @updated="handleCreatorStatsUpdated"
    />
  </div>

  <!-- Data view -->
  <div v-else class="relative space-y-4 md:space-y-6">
    <!-- Creator-center import / niche bind for active account -->
    <section
      v-if="accountsStore.activeAccountId || analyticsStore.accountId"
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

    <!-- Metric cards (5 columns on xl) -->
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-5 gap-3 md:gap-5">
      <MetricCard
        v-for="metric in metrics"
        :key="metric.title"
        v-bind="metric"
      />
    </div>

    <!-- Charts -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-3 md:gap-5">
      <Suspense>
        <TrendChart
          :data="trendData"
          :title="t('analytics.interactionTrend')"
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

    <!-- Cost breakdown -->
    <div v-if="analyticsStore.costData" class="card">
      <div class="flex items-center gap-2 md:gap-3 mb-3 md:mb-5">
        <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-gradient-to-br from-rose-400 to-rose-500 flex items-center justify-center shadow-sm">
          <AppIcon name="DollarSign" size="sm" variant="white" class="md:hidden" :aria-label="t('analytics.cost.title')" />
          <AppIcon name="DollarSign" size="md" variant="white" class="hidden md:block" :aria-label="t('analytics.cost.title')" />
        </div>
        <div class="flex-1">
          <div class="text-rose-500 font-semibold text-xs md:text-sm">{{ t('analytics.cost.title') }}</div>
          <div class="text-[10px] md:text-xs text-slate-400">{{ t('analytics.cost.subtitle') }}</div>
        </div>
      </div>

      <div class="grid grid-cols-3 gap-2 md:gap-4 mb-3 md:mb-5">
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
    </div>

    <!-- Growth insights -->
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

    <!-- Post performance table -->
    <div class="card">
      <div class="flex items-center gap-2 md:gap-3 mb-3 md:mb-5">
        <div class="w-8 h-8 md:w-10 md:h-10 rounded-lg bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
          <AppIcon name="FileText" size="sm" variant="white" class="md:hidden" :aria-label="t('analytics.recentPosts')" />
          <AppIcon name="FileText" size="md" variant="white" class="hidden md:block" :aria-label="t('analytics.recentPosts')" />
        </div>
        <div>
          <div class="text-violet-600 font-semibold text-xs md:text-sm">{{ t('analytics.recentPosts') }}</div>
          <div class="text-[10px] md:text-xs text-slate-400">{{ t('analytics.top10') }}</div>
        </div>
      </div>

      <DataTable
        :columns="tableColumns"
        :data="tableData"
        highlight-row-key="title"
        :highlight-key-value="bestPostTitle"
      />
    </div>
  </div>
  </div>
</template>
