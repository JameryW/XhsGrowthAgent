<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import MetricCard from '@/components/MetricCard.vue'
import DataTable from '@/components/DataTable.vue'
import AppIcon from '@/components/AppIcon.vue'
import { TrendChart, EngagementChart } from '@/components/charts'
import { AnalyticsSkeleton } from '@/components/skeletons'
import { useAnalyticsStore } from '@/stores'

const analyticsStore = useAnalyticsStore()

onMounted(() => {
  // Only fetch if data hasn't been loaded yet
  if (!analyticsStore.posts.length && !analyticsStore.isLoading) {
    analyticsStore.fetchAllData()
  }
})

const isLoading = computed(() => analyticsStore.isLoading && !analyticsStore.posts.length)

const metrics = computed(() => [
  { icon: 'Upload', title: 'POSTS_PUBLISHED', value: analyticsStore.posts.length, subtitle: '↑ +3 本周', variant: 'pink' as const },
  { icon: 'MessageCircle', title: 'TOTAL_ENGAGEMENT', value: analyticsStore.totalEngagement, subtitle: '↑ +18%', variant: 'cyan' as const },
  { icon: 'TrendingUp', title: 'AVG_ENGAGEMENT_RATE', value: `${analyticsStore.avgEngagementRate.toFixed(1)}%`, subtitle: '↑ +2.1%', variant: 'purple' as const },
  { icon: 'DollarSign', title: 'AI_COST_USD', value: analyticsStore.costData?.today_cost_usd?.toFixed(2) || '$0.00', subtitle: '本周累计', variant: 'peach' as const },
])

// Mock trend data for chart visualization
const trendData = ref([
  { date: '周一', value: 120 },
  { date: '周二', value: 180 },
  { date: '周三', value: 250 },
  { date: '周四', value: 220 },
  { date: '周五', value: 310 },
  { date: '周六', value: 380 },
  { date: '周日', value: 420 },
])

const engagementData = ref([
  { category: '点赞', value: 1250 },
  { category: '评论', value: 320 },
  { category: '收藏', value: 180 },
  { category: '分享', value: 95 },
])

const tableColumns = [
  { key: 'title', label: '标题', align: 'left' as const },
  { key: 'likes', label: '点赞', align: 'center' as const },
  { key: 'comments', label: '评论', align: 'center' as const },
  { key: 'collects', label: '收藏', align: 'center' as const },
  { key: 'engagement_rate', label: '互动率', align: 'center' as const },
  { key: 'published_at', label: '发布时间', align: 'center' as const },
]

const tableData = computed(() => analyticsStore.posts.slice(0, 10))

const setPeriod = (period: 'daily' | 'weekly' | 'monthly') => {
  analyticsStore.setPeriod(period)
}
</script>

<template>
  <AnalyticsSkeleton v-if="isLoading" />
  <div v-else class="relative space-y-6">
    <!-- 顶部标题栏 -->
    <div class="rounded-2xl p-5 relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm">
      <div class="flex items-center gap-5">
        <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-teal-400 to-teal-500 flex items-center justify-center shadow-sm">
          <AppIcon name="BarChart3" size="xl" variant="white" aria-label="Analytics" />
        </div>
        <div class="flex-1">
          <div class="flex items-center gap-2 mb-1">
            <span class="px-2 py-1 rounded bg-teal-50 text-teal-600 text-xs uppercase tracking-wide font-medium">Analytics</span>
          </div>
          <div class="text-xl font-semibold text-slate-800">数据分析中心</div>
          <div class="text-xs text-slate-400 mt-1">
            Account: {{ analyticsStore.accountId }} | Period: {{ analyticsStore.period }}
          </div>
        </div>

        <!-- Period selector -->
        <div class="flex gap-2">
          <button
            v-for="p in ['daily', 'weekly', 'monthly']"
            :key="p"
            @click="setPeriod(p as any)"
            :aria-pressed="analyticsStore.period === p"
            :aria-label="`切换到${p === 'daily' ? '本周' : p === 'weekly' ? '本月' : '全年'}数据`"
            :class="[
              'px-3 py-2 rounded-lg text-xs border transition-all duration-200 flex items-center gap-1.5 font-medium',
              analyticsStore.period === p
                ? 'bg-teal-50 border-teal-200 text-teal-600'
                : 'bg-white border-slate-200 text-slate-500 hover:bg-slate-50 hover:border-slate-300'
            ]"
          >
            <AppIcon name="Calendar" size="sm" variant="cyan" />
            {{ p === 'daily' ? '本周' : p === 'weekly' ? '本月' : '全年' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 核心指标卡片 -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <MetricCard
        v-for="metric in metrics"
        :key="metric.title"
        v-bind="metric"
      />
    </div>

    <!-- 图表区域 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <TrendChart
        :data="trendData"
        title="互动趋势"
        variant="cyan"
        :height="280"
      />
      <EngagementChart
        :data="engagementData"
        variant="pink"
        :height="280"
      />
    </div>

    <!-- 帖子表现列表 -->
    <div class="rounded-2xl p-5 relative overflow-hidden bg-white/98 backdrop-blur-sm border border-slate-200/50 shadow-sm">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-400 to-violet-500 flex items-center justify-center shadow-sm">
          <AppIcon name="FileText" size="md" variant="white" aria-label="Posts" />
        </div>
        <div>
          <div class="text-violet-600 font-semibold text-sm">最近帖子表现</div>
          <div class="text-xs text-slate-400">TOP 10</div>
        </div>
      </div>

      <DataTable :columns="tableColumns" :data="tableData" />
    </div>
  </div>
</template>