<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { CheckpointSnapshot } from '@/types/workflow'

const { t } = useI18n()
defineProps<{ cp: CheckpointSnapshot }>()

function formatNum(n?: number): string {
  if (n === undefined || n === null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}
</script>

<template>
  <div v-if="cp.trend_data">
    <div v-if="cp.trend_data.hot_topics?.length">
      <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('showcase.detail.hotTopics') }}</div>
      <div class="space-y-1.5">
        <div v-for="ht in cp.trend_data.hot_topics" :key="ht.topic" class="flex items-center justify-between p-2 rounded-lg liquid-glass-inset">
          <span class="text-xs font-medium text-slate-700">{{ ht.topic }}</span>
          <div class="flex items-center gap-2">
            <span class="text-[11px] px-1.5 py-0.5 rounded" :class="ht.heat_score >= 80 ? 'bg-rose-50 text-rose-600' : ht.heat_score >= 60 ? 'bg-amber-50 text-amber-600' : 'bg-slate-100 text-slate-500'">{{ ht.heat_score }}</span>
            <span v-if="ht.growth_rate != null" class="text-[11px]" :class="ht.growth_rate > 0 ? 'text-emerald-500' : 'text-rose-500'">{{ ht.growth_rate > 0 ? '+' : '' }}{{ (ht.growth_rate * 100).toFixed(0) }}%</span>
          </div>
        </div>
      </div>
    </div>
    <div v-if="cp.trend_data.trending_keywords?.length">
      <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.trendingKeywords') }}</div>
      <div class="flex flex-wrap gap-1.5">
        <span v-for="kw in cp.trend_data.trending_keywords" :key="kw" class="text-[11px] px-2 py-0.5 rounded-md bg-pink-50 text-pink-600 border border-pink-100">{{ kw }}</span>
      </div>
    </div>
    <div v-if="cp.trend_data.competitor_posts?.length">
      <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('showcase.detail.topCompetitor') }}</div>
      <div class="space-y-1.5">
        <div v-for="post in cp.trend_data.competitor_posts" :key="post.title" class="p-2.5 rounded-lg liquid-glass-inset">
          <div class="text-xs text-slate-700 font-medium">{{ post.title }}</div>
          <div class="text-[11px] text-slate-400 mt-0.5 flex gap-3">
            <span>{{ formatNum(post.likes) }} {{ t('replay.likes') }}</span>
            <span>{{ post.comments }} {{ t('replay.comments') }}</span>
            <span>{{ post.author }}</span>
          </div>
        </div>
      </div>
    </div>
    <div v-if="cp.trend_data.niche_opportunities?.length">
      <div class="text-xs text-slate-400 font-medium mb-1.5 uppercase tracking-wide">{{ t('replay.nicheOpportunities') }}</div>
      <div class="space-y-1.5">
        <div v-for="opp in cp.trend_data.niche_opportunities" :key="opp.topic" class="flex items-center justify-between p-2 rounded-lg bg-violet-50 border border-violet-100">
          <span class="text-xs text-slate-700">{{ opp.topic }}</span>
          <div class="flex items-center gap-2 text-[11px]">
            <span class="text-violet-600 font-medium">{{ t('replay.potential') }} {{ opp.potential_score }}</span>
            <span class="text-slate-400">{{ opp.entry_barrier }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
