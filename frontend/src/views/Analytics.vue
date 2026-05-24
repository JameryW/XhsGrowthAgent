<script setup lang="ts">
import { onMounted, computed } from 'vue'
import MetricCard from '@/components/MetricCard.vue'
import DataTable from '@/components/DataTable.vue'
import { useAnalyticsStore } from '@/stores'

const analyticsStore = useAnalyticsStore()

onMounted(() => {
  analyticsStore.fetchAllData()
})

const metrics = computed(() => [
  { icon: '📤', title: 'POSTS_PUBLISHED', value: analyticsStore.posts.length, subtitle: '↑ +3 本周', variant: 'pink' as const },
  { icon: '💬', title: 'TOTAL_ENGAGEMENT', value: analyticsStore.totalEngagement, subtitle: '↑ +18%', variant: 'cyan' as const },
  { icon: '📈', title: 'AVG_ENGAGEMENT_RATE', value: `${analyticsStore.avgEngagementRate.toFixed(1)}%`, subtitle: '↑ +2.1%', variant: 'purple' as const },
  { icon: '💰', title: 'AI_COST_USD', value: analyticsStore.costData?.today_cost_usd?.toFixed(2) || '$0.00', subtitle: '本周累计', variant: 'peach' as const },
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
  <div class="relative overflow-hidden">
    <!-- 扫描线 -->
    <div class="absolute top-0 left-0 right-0 h-2 bg-gradient-to-r from-transparent via-neon-cyan/30 to-transparent animate-scan pointer-events-none" />

    <!-- 顶部标题栏 -->
    <div class="glass rounded-xl p-4 mb-6 border border-neon-cyan/30">
      <div class="flex items-center gap-4">
        <div class="w-14 h-14 rounded-xl bg-gradient-to-br from-neon-cyan to-emerald-600 flex items-center justify-center shadow-neon-cyan text-3xl">
          📊
        </div>
        <div class="flex-1">
          <div class="mono text-xs text-neon-cyan">ANALYTICS_MODULE</div>
          <div class="text-lg font-bold text-white mt-1">数据分析中心</div>
          <div class="mono text-xs text-white/50">
            Account: {{ analyticsStore.accountId }} | Period: {{ analyticsStore.period }}
          </div>
        </div>
        <div class="flex gap-3">
          <button
            v-for="p in ['daily', 'weekly', 'monthly']"
            :key="p"
            @click="setPeriod(p as any)"
            :class="[
              'px-4 py-2 rounded-lg mono text-xs border transition-all',
              analyticsStore.period === p
                ? 'bg-neon-cyan/20 border-neon-cyan text-neon-cyan'
                : 'bg-transparent border-white/20 text-white/50 hover:bg-white/10'
            ]"
          >
            📅 {{ p === 'daily' ? '本周' : p === 'weekly' ? '本月' : '全年' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 核心指标卡片 -->
    <div class="grid grid-cols-4 gap-4 mb-6">
      <MetricCard
        v-for="metric in metrics"
        :key="metric.title"
        v-bind="metric"
      />
    </div>

    <!-- 帖子表现列表 -->
    <div class="glass rounded-xl p-4 border border-neon-purple/30">
      <div class="flex items-center gap-3 mb-4">
        <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-neon-purple to-purple-700 flex items-center justify-center text-xl">
          📝
        </div>
        <div class="text-neon-purple mono font-bold">最近帖子表现</div>
        <div class="mono text-xs text-white/50">TOP 10</div>
      </div>

      <DataTable :columns="tableColumns" :data="tableData" />
    </div>
  </div>
</template>