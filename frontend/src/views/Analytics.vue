<script setup lang="ts">
import { onMounted, computed, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import MetricCard from '@/components/MetricCard.vue'
import DataTable from '@/components/DataTable.vue'
import AppIcon from '@/components/AppIcon.vue'
import { AnalyticsSkeleton } from '@/components/skeletons'
import { useAnalyticsStore } from '@/stores'

const TrendChart = defineAsyncComponent(() => import('@/components/charts/TrendChart.vue'))
const EngagementChart = defineAsyncComponent(() => import('@/components/charts/EngagementChart.vue'))

const { t } = useI18n()
const router = useRouter()
const analyticsStore = useAnalyticsStore()

onMounted(() => {
  if (!analyticsStore.posts.length && !analyticsStore.isLoading && !analyticsStore.error) {
    analyticsStore.fetchAllData()
  }
})

const isLoading = computed(() => analyticsStore.isLoading && !analyticsStore.posts.length)
const hasError = computed(() => !!analyticsStore.error && !analyticsStore.posts.length)
const isEmpty = computed(() => !analyticsStore.isLoading && !analyticsStore.error && !analyticsStore.posts.length)

const metrics = computed(() => [
  { icon: 'Upload', title: t('analytics.postsPublished'), value: analyticsStore.posts.length, subtitle: t('analytics.thisWeek'), variant: 'pink' as const },
  { icon: 'MessageCircle', title: t('analytics.totalEngagement'), value: analyticsStore.totalEngagement.toLocaleString(), subtitle: `${analyticsStore.posts.length} ` + t('analytics.postsPublished'), variant: 'cyan' as const },
  { icon: 'TrendingUp', title: t('analytics.avgEngagementRate'), value: `${analyticsStore.avgEngagementRate.toFixed(1)}%`, subtitle: analyticsStore.posts.length > 0 ? `${analyticsStore.posts.length} ` + t('analytics.postsPublished') : t('analytics.thisWeek'), variant: 'purple' as const },
  { icon: 'DollarSign', title: t('analytics.aiCost'), value: `$${analyticsStore.costData?.today_cost_usd?.toFixed(2) || '0.00'}`, subtitle: t('analytics.cost.today'), variant: 'peach' as const },
])

// Derive trend data from actual posts
const trendData = computed(() => {
  const posts = analyticsStore.posts
  if (!posts.length) return []

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

// Derive engagement breakdown from actual posts
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

// Format date for display
const formatDate = (isoDate: string | null | undefined) => {
  if (!isoDate) return '—'
  const d = new Date(isoDate)
  const month = d.toLocaleDateString('en', { month: 'short' })
  const day = d.getDate()
  return `${month} ${day}`
}

const tableColumns = computed(() => [
  { key: 'title', label: t('analytics.table.title'), align: 'left' as const },
  { key: 'likes', label: t('analytics.table.likes'), align: 'center' as const },
  { key: 'comments', label: t('analytics.table.comments'), align: 'center' as const },
  { key: 'collects', label: t('analytics.table.collects'), align: 'center' as const },
  { key: 'engagement_rate_display', label: t('analytics.table.engagementRate'), align: 'center' as const },
  { key: 'published_at_display', label: t('analytics.table.publishedAt'), align: 'center' as const },
])

const tableData = computed(() => analyticsStore.posts.slice(0, 10).map(post => ({
  ...post,
  engagement_rate_display: `${post.engagement_rate.toFixed(1)}%`,
  published_at_display: formatDate(post.published_at),
})))

const setPeriod = (period: 'daily' | 'weekly' | 'monthly') => {
  analyticsStore.setPeriod(period)
}

function refreshData() {
  analyticsStore.fetchAllData()
}

const budgetUsedPercent = computed(() => {
  const total = analyticsStore.costData?.total_cost_usd || 0
  const remaining = analyticsStore.costData?.budget_remaining_usd || 0
  const budget = total + remaining
  if (budget <= 0) return 0
  return Math.round((total / budget) * 100)
})

function goHome() {
  router.push('/')
}

// Insights from growth report
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
    default: return 'bg-slate-50 border-slate-100'
  }
}

function startWithTopic(topic: string, niche?: string) {
  const query: Record<string, string> = { topic }
  if (niche) query.niche = niche
  router.push({ path: '/', query })
}
</script>

<template>
  <AnalyticsSkeleton v-if="isLoading" />

  <!-- Error state -->
  <div v-else-if="hasError" class="relative space-y-6 md:space-y-8">
    <div class="card">
      <div class="flex flex-col items-center gap-4 py-8">
        <div class="w-14 h-14 rounded-xl bg-rose-50 flex items-center justify-center">
          <AppIcon name="AlertTriangle" size="xl" variant="pink" />
        </div>
        <div class="text-lg font-semibold text-slate-800">{{ t('analytics.error.title') }}</div>
        <div class="text-sm text-slate-500 text-center max-w-md">{{ t('analytics.error.description') }}</div>
        <button
          @click="refreshData"
          :disabled="analyticsStore.isLoading"
          class="px-4 py-2 rounded-lg bg-rose-500 text-white text-sm font-medium hover:bg-rose-600 transition-all duration-200 flex items-center gap-2 disabled:opacity-50"
        >
          <AppIcon name="RefreshCw" size="sm" variant="white" />
          {{ analyticsStore.isLoading ? t('analytics.refreshing') : t('analytics.error.retry') }}
        </button>
      </div>
    </div>
  </div>

  <!-- Empty state -->
  <div v-else-if="isEmpty" class="relative space-y-6 md:space-y-8">
    <div class="card">
      <div class="flex flex-col items-center gap-4 py-8">
        <div class="w-14 h-14 rounded-xl bg-teal-50 flex items-center justify-center">
          <AppIcon name="BarChart3" size="xl" variant="cyan" />
        </div>
        <div class="text-lg font-semibold text-slate-800">{{ t('analytics.empty.title') }}</div>
        <div class="text-sm text-slate-500 text-center max-w-md">{{ t('analytics.empty.description') }}</div>
        <button
          @click="goHome"
          class="px-4 py-2 rounded-lg bg-teal-500 text-white text-sm font-medium hover:bg-teal-600 transition-all duration-200 flex items-center gap-2"
        >
          <AppIcon name="Plus" size="sm" variant="white" />
          {{ t('analytics.empty.startWorkflow') }}
        </button>
      </div>
    </div>
  </div>

  <!-- Data view -->
  <div v-else class="relative space-y-6 md:space-y-8">
    <!-- Header -->
    <div class="card">
      <div class="flex flex-col sm:flex-row items-start sm:items-center gap-4 sm:gap-5">
        <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-teal-400 to-teal-500 flex items-center justify-center shadow-sm flex-shrink-0">
          <AppIcon name="BarChart3" size="xl" variant="white" :aria-label="t('analytics.title')" />
        </div>
        <div class="flex-1">
          <div class="flex items-center gap-2 mb-1">
            <span class="px-2 py-1 rounded bg-teal-50 text-teal-600 text-xs uppercase tracking-wide font-medium">{{ t('analytics.analyticsLabel') }}</span>
          </div>
          <div class="text-xl font-semibold text-slate-800">{{ t('analytics.title') }}</div>
          <div class="text-xs text-slate-400 mt-1">
            {{ t('analytics.account') }}: {{ analyticsStore.accountId }} | {{ t('analytics.period') }}: {{ analyticsStore.period }}
          </div>
        </div>

        <div class="flex items-center gap-2 flex-wrap">
          <!-- Refresh button -->
          <button
            @click="refreshData"
            :disabled="analyticsStore.isLoading"
            class="px-3 py-2 rounded-lg text-xs border transition-all duration-200 flex items-center gap-1.5 font-medium bg-white border-slate-200 text-slate-500 hover:bg-slate-50 hover:border-slate-300 disabled:opacity-50"
            :aria-label="t('analytics.refresh')"
          >
            <AppIcon name="RefreshCw" size="sm" variant="cyan" :class="{ 'animate-spin': analyticsStore.isLoading }" />
            {{ analyticsStore.isLoading ? t('analytics.refreshing') : t('analytics.refresh') }}
          </button>

          <!-- Period selector -->
          <button
            v-for="p in ['daily', 'weekly', 'monthly']"
            :key="p"
            @click="setPeriod(p as any)"
            :aria-pressed="analyticsStore.period === p"
            :aria-label="`${p === 'daily' ? t('analytics.thisWeek') : p === 'weekly' ? t('analytics.thisMonth') : t('analytics.thisYear')}`"
            :class="[
              'px-3 py-2 rounded-lg text-xs border transition-all duration-200 flex items-center gap-1.5 font-medium',
              analyticsStore.period === p
                ? 'bg-teal-50 border-teal-200 text-teal-600'
                : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50 hover:border-slate-300'
            ]"
          >
            <AppIcon name="Calendar" size="sm" variant="cyan" />
            {{ p === 'daily' ? t('analytics.thisWeek') : p === 'weekly' ? t('analytics.thisMonth') : t('analytics.thisYear') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Metric cards -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
      <MetricCard
        v-for="metric in metrics"
        :key="metric.title"
        v-bind="metric"
      />
    </div>

    <!-- Charts -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
      <Suspense>
        <TrendChart
          :data="trendData"
          :title="t('analytics.interactionTrend')"
          variant="cyan"
          :height="280"
        />
        <template #fallback>
          <div class="rounded-2xl p-6 bg-white/98 backdrop-blur-sm border border-slate-200/50">
            <div class="h-[280px] rounded-lg bg-slate-100 animate-pulse" />
          </div>
        </template>
      </Suspense>
      <Suspense>
        <EngagementChart
          :data="engagementData"
          :title="t('analytics.engagementBreakdown')"
          variant="pink"
          :height="280"
        />
        <template #fallback>
          <div class="rounded-2xl p-6 bg-white/98 backdrop-blur-sm border border-slate-200/50">
            <div class="h-[280px] rounded-lg bg-slate-100 animate-pulse" />
          </div>
        </template>
      </Suspense>
    </div>

    <!-- Cost breakdown -->
    <div v-if="analyticsStore.costData" class="card">
      <div class="flex items-center gap-3 mb-5">
        <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-rose-400 to-rose-500 flex items-center justify-center shadow-sm">
          <AppIcon name="DollarSign" size="md" variant="white" :aria-label="t('analytics.cost.title')" />
        </div>
        <div class="flex-1">
          <div class="text-rose-500 font-semibold text-sm">{{ t('analytics.cost.title') }}</div>
          <div class="text-xs text-slate-400">{{ t('analytics.cost.subtitle') }}</div>
        </div>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-5">
        <div class="rounded-lg p-4 bg-rose-50 border border-rose-100">
          <div class="text-xs text-rose-500 font-medium">{{ t('analytics.cost.total') }}</div>
          <div class="text-xl font-bold text-rose-700">${{ analyticsStore.costData.total_cost_usd?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-4 bg-amber-50 border border-amber-100">
          <div class="text-xs text-amber-500 font-medium">{{ t('analytics.cost.today') }}</div>
          <div class="text-xl font-bold text-amber-700">${{ analyticsStore.costData.today_cost_usd?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-4 bg-emerald-50 border border-emerald-100">
          <div class="text-xs text-emerald-500 font-medium">{{ t('analytics.cost.remaining') }}</div>
          <div class="text-xl font-bold text-emerald-700">${{ analyticsStore.costData.budget_remaining_usd?.toFixed(2) || '0.00' }}</div>
        </div>
      </div>

      <!-- Budget progress bar -->
      <div v-if="analyticsStore.costData.total_cost_usd" class="mb-5">
        <div class="flex items-center justify-between text-xs text-slate-500 mb-2">
          <span>{{ t('analytics.cost.budgetUsed') }}</span>
          <span>{{ budgetUsedPercent }}%</span>
        </div>
        <div class="h-2 rounded-full bg-slate-100 overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-500"
            :class="budgetUsedPercent > 90 ? 'bg-rose-500' : budgetUsedPercent > 70 ? 'bg-amber-500' : 'bg-emerald-500'"
            :style="{ width: `${Math.min(budgetUsedPercent, 100)}%` }"
          />
        </div>
      </div>

      <!-- By model breakdown -->
      <div v-if="analyticsStore.costData.by_model && Object.keys(analyticsStore.costData.by_model).length > 0">
        <div class="text-xs text-slate-500 uppercase tracking-wide font-medium mb-3">{{ t('analytics.cost.byModel') }}</div>
        <div class="space-y-2">
          <div
            v-for="(cost, model) in analyticsStore.costData.by_model"
            :key="model"
            class="flex items-center justify-between py-2 px-4 rounded-lg bg-slate-50 border border-slate-100"
          >
            <span class="text-sm text-slate-700 font-medium">{{ model }}</span>
            <span class="text-sm text-slate-600">${{ (cost as number).toFixed(2) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Growth insights -->
    <div v-if="insights.length > 0 || trendTopics.length > 0" class="card">
      <div class="flex items-center gap-3 mb-5">
        <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-amber-400 to-amber-500 flex items-center justify-center shadow-sm">
          <AppIcon name="Lightbulb" size="md" variant="white" :aria-label="t('analytics.insights.title')" />
        </div>
        <div class="flex-1">
          <div class="text-amber-600 font-semibold text-sm">{{ t('analytics.insights.title') }}</div>
          <div class="text-xs text-slate-400">{{ t('analytics.insights.subtitle') }}</div>
        </div>
      </div>

      <!-- Insight cards -->
      <div class="space-y-3 mb-5">
        <div
          v-for="(insight, idx) in insights"
          :key="idx"
          class="flex items-start gap-3 p-4 rounded-lg border"
          :class="insightBg(insight.type)"
        >
          <div class="w-6 h-6 rounded flex items-center justify-center flex-shrink-0 mt-0.5" :class="{
            'bg-teal-100': insight.type === 'trend',
            'bg-violet-100': insight.type === 'opportunity',
            'bg-amber-100': insight.type === 'warning',
            'bg-slate-100': insight.type === 'info',
          }">
            <AppIcon :name="insightIcon(insight.type)" size="sm" :variant="insightVariant(insight.type) as any" />
          </div>
          <p class="text-sm text-slate-700">{{ insight.message }}</p>
        </div>
      </div>

      <!-- Trending topics with workflow trigger -->
      <div v-if="trendTopics.length > 0" class="border-t border-slate-100 pt-5">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs text-slate-500 uppercase tracking-wide font-medium">{{ t('analytics.hotTopics') }}</span>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="topic in trendTopics"
            :key="topic"
            @click="startWithTopic(topic)"
            class="px-3 py-1.5 rounded-lg bg-teal-50 border border-teal-100 text-teal-700 text-xs font-medium hover:bg-teal-100 hover:border-teal-200 transition-all duration-200 flex items-center gap-1.5"
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
      <div class="flex items-center gap-3 mb-5">
        <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
          <AppIcon name="FileText" size="md" variant="white" :aria-label="t('analytics.recentPosts')" />
        </div>
        <div>
          <div class="text-violet-600 font-semibold text-sm">{{ t('analytics.recentPosts') }}</div>
          <div class="text-xs text-slate-400">{{ t('analytics.top10') }}</div>
        </div>
      </div>

      <DataTable :columns="tableColumns" :data="tableData" />
    </div>
  </div>
</template>