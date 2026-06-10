<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { WorkflowStateResponse } from '@/types/workflow'

const { t } = useI18n()

defineProps<{
  detail: WorkflowStateResponse | undefined
}>()

function formatNum(n?: number): string {
  if (n === undefined || n === null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

const has = (v: unknown) => !!v && typeof v === 'object' && Object.keys(v as Record<string, unknown>).length > 0
</script>

<template>
  <div v-if="detail" class="px-4 md:px-5 py-4">
    <div class="md:grid md:grid-cols-5 md:gap-4 space-y-3 md:space-y-0">
      <!-- Left: main content -->
      <div class="md:col-span-3 space-y-2">
        <div v-if="detail.content_plan?.selected_topic" class="mb-1">
          <div class="text-base font-bold text-slate-800 leading-snug">{{ detail.content_plan.selected_topic }}</div>
          <div v-if="detail.content_plan.content_angle" class="text-xs text-slate-500 mt-1 line-clamp-2">{{ detail.content_plan.content_angle }}</div>
        </div>
        <div v-if="detail.copy_content?.selected_title">
          <div class="text-sm font-semibold text-rose-600 leading-snug">{{ detail.copy_content.selected_title }}</div>
          <div v-if="detail.copy_content.body_text" class="text-xs text-slate-500 mt-1.5 line-clamp-5 whitespace-pre-line">{{ detail.copy_content.body_text }}</div>
        </div>
        <div v-if="detail.copy_content?.hashtags?.length" class="flex flex-wrap gap-1">
          <span v-for="tag in detail.copy_content.hashtags" :key="tag" class="text-[11px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-700">#{{ tag }}</span>
        </div>
        <div v-if="detail.content_plan?.key_points?.length" class="space-y-0.5">
          <div v-for="(point, i) in detail.content_plan.key_points.slice(0, 3)" :key="i" class="text-xs text-slate-500 flex gap-1">
            <span class="text-cyan-400">▸</span>
            <span class="line-clamp-1">{{ point }}</span>
          </div>
        </div>
        <!-- Publish result -->
        <div v-if="has(detail.publish_result)" class="p-2.5 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-emerald-500 font-medium mb-1">{{ t('replay.status') }}</div>
          <div class="grid grid-cols-2 gap-2">
            <div v-if="(detail.publish_result as any).post_id" class="text-xs">
              <span class="text-slate-400">Post ID:</span>
              <span class="text-emerald-700 font-mono ml-1">{{ (detail.publish_result as any).post_id }}</span>
            </div>
            <div v-if="(detail.publish_result as any).status" class="text-xs">
              <span class="text-slate-400">Status:</span>
              <span class="ml-1 font-medium" :class="(detail.publish_result as any).status === 'published' ? 'text-emerald-600' : 'text-amber-600'">{{ (detail.publish_result as any).status }}</span>
            </div>
            <div v-if="(detail.publish_result as any).published_at" class="text-xs col-span-2">
              <span class="text-slate-400">Published:</span>
              <span class="text-slate-600 ml-1">{{ new Date((detail.publish_result as any).published_at).toLocaleString() }}</span>
            </div>
          </div>
          <div v-if="(detail.publish_result as any).post_url" class="mt-1.5">
            <a :href="(detail.publish_result as any).post_url" target="_blank" rel="noopener" class="inline-flex items-center gap-1 text-xs text-emerald-600 hover:text-emerald-700 font-medium">
              <AppIcon name="ExternalLink" size="sm" />
              {{ t('replay.viewPost') }}
            </a>
          </div>
        </div>
      </div>

      <!-- Right: metadata -->
      <div class="md:col-span-2 space-y-2">
        <div v-if="detail.trend_data?.hot_topics?.length">
          <div class="text-[10px] text-slate-400 font-medium mb-1 uppercase tracking-wide">{{ t('showcase.detail.hotTopics') }}</div>
          <div class="flex flex-wrap gap-1">
            <span v-for="ht in detail.trend_data.hot_topics.slice(0, 5)" :key="ht.topic" class="text-[11px] px-1.5 py-0.5 rounded-full bg-rose-50 text-rose-600">{{ ht.topic }}</span>
          </div>
        </div>
        <div v-if="detail.trend_data?.trending_keywords?.length">
          <div class="text-[10px] text-slate-400 font-medium mb-1 uppercase tracking-wide">{{ t('replay.trendingKeywords') }}</div>
          <div class="flex flex-wrap gap-1">
            <span v-for="kw in detail.trend_data.trending_keywords" :key="kw" class="text-[11px] px-1.5 py-0.5 rounded-md bg-pink-50 text-pink-600 border border-pink-100">{{ kw }}</span>
          </div>
        </div>
        <div v-if="detail.trend_data?.competitor_posts?.[0]" class="p-2 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-slate-400 font-medium mb-0.5">{{ t('showcase.detail.topCompetitor') }}</div>
          <div class="text-xs text-slate-700">{{ detail.trend_data.competitor_posts[0].title }}</div>
          <div class="text-[11px] text-slate-400 mt-0.5">{{ (detail.trend_data.competitor_posts[0].likes / 1000).toFixed(1) }}k likes</div>
        </div>
        <div v-if="detail.visual_plan" class="p-2 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-slate-400 font-medium mb-0.5">{{ t('showcase.detail.visual') }}</div>
          <div class="text-xs text-slate-700">{{ detail.visual_plan.layout_style }}</div>
          <div class="text-[11px] text-slate-400">{{ t('showcase.detail.imageCount', { count: detail.visual_plan.image_count }) }}</div>
          <div v-if="detail.visual_plan.color_palette?.length" class="flex gap-1 mt-1">
            <div v-for="color in detail.visual_plan.color_palette.slice(0, 5)" :key="color" class="w-3.5 h-3.5 rounded-full border border-white shadow-sm" :style="{ backgroundColor: color }" />
          </div>
        </div>
        <!-- Analytics -->
        <div v-if="has(detail.analytics)" class="space-y-1.5">
          <div v-if="(detail.analytics as any).views !== undefined" class="grid grid-cols-2 gap-1.5">
            <div class="p-1.5 rounded liquid-glass-inset text-center">
              <div class="text-[10px] text-slate-400">Views</div>
              <div class="text-xs font-bold text-slate-700">{{ formatNum((detail.analytics as any).views) }}</div>
            </div>
            <div class="p-1.5 rounded bg-pink-50 text-center">
              <div class="text-[10px] text-slate-400">Likes</div>
              <div class="text-xs font-bold text-pink-600">{{ formatNum((detail.analytics as any).likes) }}</div>
            </div>
            <div v-if="(detail.analytics as any).collects !== undefined" class="p-1.5 rounded bg-amber-50 text-center">
              <div class="text-[10px] text-slate-400">{{ t('showcase.detail.collects') }}</div>
              <div class="text-xs font-bold text-amber-600">{{ formatNum((detail.analytics as any).collects) }}</div>
            </div>
            <div v-if="(detail.analytics as any).comments !== undefined" class="p-1.5 rounded bg-teal-50 text-center">
              <div class="text-[10px] text-slate-400">{{ t('showcase.detail.comments') }}</div>
              <div class="text-xs font-bold text-teal-600">{{ formatNum((detail.analytics as any).comments) }}</div>
            </div>
            <div v-if="(detail.analytics as any).engagement_rate !== undefined" class="p-1.5 rounded bg-violet-50 text-center col-span-2">
              <div class="text-[10px] text-slate-400">{{ t('showcase.detail.engagementRate') }}</div>
              <div class="text-xs font-bold text-violet-600">{{ ((detail.analytics as any).engagement_rate * 100).toFixed(1) }}%</div>
            </div>
          </div>
          <div v-if="(detail.analytics as any)?.insights?.length">
            <div class="text-[10px] text-emerald-500 font-medium mb-0.5">{{ t('showcase.detail.insights') }}</div>
            <ul class="space-y-0.5">
              <li v-for="(insight, i) in (detail.analytics as any).insights.slice(0, 3)" :key="i" class="text-xs text-slate-500 flex gap-1">
                <span class="text-emerald-500">+</span>
                <span class="line-clamp-1">{{ insight }}</span>
              </li>
            </ul>
          </div>
        </div>
        <!-- Ripple -->
        <div v-if="has(detail.ripple_prediction)" class="p-2 rounded-lg liquid-glass-inset">
          <div class="text-[10px] text-violet-500 font-medium mb-0.5">Ripple</div>
          <div class="grid grid-cols-2 gap-x-3 gap-y-0.5">
            <div class="text-xs text-violet-700" v-if="detail.ripple_prediction!.viral_probability != null">{{ t('replay.viralProb') }} {{ (detail.ripple_prediction!.viral_probability * 100).toFixed(1) }}%</div>
            <div class="text-xs text-violet-700" v-if="detail.ripple_prediction!.estimated_reach != null">{{ t('replay.estReach') }} {{ formatNum(detail.ripple_prediction!.estimated_reach) }}</div>
            <div class="text-xs text-violet-700" v-if="detail.ripple_prediction!.estimated_engagement != null">{{ t('replay.estEngagement') }} {{ formatNum(detail.ripple_prediction!.estimated_engagement) }}</div>
            <div class="text-xs text-violet-700" v-if="detail.ripple_prediction!.confidence != null">{{ t('replay.confidence') }} {{ (detail.ripple_prediction!.confidence * 100).toFixed(1) }}%</div>
            <div class="text-xs text-violet-700 col-span-2" v-if="detail.ripple_prediction!.verdict">{{ t('replay.verdict') }} {{ detail.ripple_prediction!.verdict }}</div>
          </div>
          <div v-if="detail.ripple_pmf?.pmf_score != null" class="mt-1 pt-1 border-t border-violet-100">
            <div class="text-xs text-violet-700">{{ t('dashboard.ripple.pmfScore') }} {{ (detail.ripple_pmf!.pmf_score * 100).toFixed(1) }}%</div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="px-4 md:px-5 py-4 text-xs text-slate-400">{{ t('common.loadingState') }}</div>
</template>
