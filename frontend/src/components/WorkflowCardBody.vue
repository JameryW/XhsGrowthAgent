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
  <div v-if="detail" class="px-4 md:px-5 py-3">
    <!-- Brief mode: brand + product + selling points (compact) -->
    <div v-if="has(detail.brief_content)" class="mb-1.5">
      <div class="flex items-baseline gap-2">
        <span v-if="(detail.brief_content as any).brand_name" class="text-sm font-semibold text-pink-600 leading-tight">{{ (detail.brief_content as any).brand_name }}</span>
        <span v-if="(detail.brief_content as any).product_name" class="text-xs text-slate-500 truncate">{{ (detail.brief_content as any).product_name }}</span>
      </div>
      <div v-if="(detail.brief_content as any).selling_points?.length" class="flex flex-wrap gap-1 mt-1">
        <span v-for="sp in (detail.brief_content as any).selling_points.slice(0, 3)" :key="sp" class="text-[10px] px-1.5 py-0.5 rounded bg-pink-50 text-pink-600">{{ sp }}</span>
      </div>
      <div v-if="(detail.brief_content as any).required_hashtags?.length" class="flex flex-wrap gap-1 mt-0.5">
        <span v-for="tag in (detail.brief_content as any).required_hashtags.slice(0, 4)" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
      </div>
    </div>

    <!-- Standard mode: content_plan title + copy title (2 lines max) -->
    <div v-if="!has(detail.brief_content) && detail.content_plan?.selected_topic" class="mb-1">
      <div class="text-sm font-bold text-slate-800 leading-tight line-clamp-1">{{ detail.content_plan.selected_topic }}</div>
      <div v-if="detail.copy_content?.selected_title" class="text-xs font-medium text-rose-600 mt-0.5 line-clamp-1">{{ detail.copy_content.selected_title }}</div>
    </div>
    <div v-if="!has(detail.brief_content) && detail.copy_content?.hashtags?.length" class="flex flex-wrap gap-1 mb-1">
      <span v-for="tag in detail.copy_content.hashtags.slice(0, 4)" :key="tag" class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 text-teal-700">#{{ tag }}</span>
    </div>

    <!-- Shooting plan (compact inline) -->
    <div v-if="has((detail as any).shooting_plan)" class="flex items-center gap-2 text-xs text-slate-500 mb-1">
      <span v-if="(detail as any).shooting_plan.creator_nickname" class="truncate">{{ (detail as any).shooting_plan.creator_nickname }}</span>
      <span v-if="(detail as any).shooting_plan.content_type_label" class="text-[10px] px-1.5 py-0.5 rounded bg-violet-50 text-violet-600">{{ (detail as any).shooting_plan.content_type_label }}</span>
    </div>

    <!-- Optimization: top suggestion only -->
    <div v-if="has((detail as any).optimization_analysis) && (detail as any).optimization_analysis.suggestions?.length" class="text-xs text-slate-500 mb-1 line-clamp-1">
      <span class="text-violet-500 font-medium">P{{ (detail as any).optimization_analysis.suggestions[0].priority }}</span> {{ (detail as any).optimization_analysis.suggestions[0].action }}
    </div>

    <!-- Content versions: show count badge only, not full list -->
    <div v-if="(detail as any).content_versions?.length" class="mb-1">
      <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600">{{ (detail as any).content_versions.length }} {{ t('replay.contentVersions') }}</span>
    </div>

    <!-- Publish result (compact) -->
    <div v-if="has(detail.publish_result)" class="flex items-center gap-2 text-xs">
      <span class="text-emerald-600 font-medium" v-if="(detail.publish_result as any).status === 'published'">{{ t('replay.status') }}</span>
      <a v-if="(detail.publish_result as any).post_url" :href="(detail.publish_result as any).post_url" target="_blank" rel="noopener" class="inline-flex items-center gap-0.5 text-emerald-600 hover:text-emerald-700 font-medium" @click.stop>
        <AppIcon name="ExternalLink" size="xs" />
        {{ t('replay.viewPost') }}
      </a>
    </div>

    <!-- Right-side metadata: hot topics + visual + analytics (compact row) -->
    <div class="flex flex-wrap items-center gap-1.5 mt-1.5 pt-1.5 border-t border-slate-100/60">
      <template v-if="detail.trend_data?.hot_topics?.length">
        <span v-for="ht in detail.trend_data.hot_topics.slice(0, 3)" :key="ht.topic" class="text-[10px] px-1.5 py-0.5 rounded-full bg-rose-50 text-rose-600">{{ ht.topic }}</span>
      </template>
      <div v-if="has(detail.visual_plan) && (detail.visual_plan as any)?.color_palette?.length" class="flex gap-0.5">
        <div v-for="color in (detail.visual_plan as any).color_palette.slice(0, 4)" :key="color" class="w-3 h-3 rounded-full border border-white shadow-sm" :style="{ backgroundColor: color }" />
      </div>
      <template v-if="has(detail.analytics)">
        <span v-if="(detail.analytics as any).views !== undefined" class="text-[10px] text-slate-400">{{ formatNum((detail.analytics as any).views) }} <span class="text-slate-300">views</span></span>
        <span v-if="(detail.analytics as any).likes !== undefined" class="text-[10px] text-pink-500">{{ formatNum((detail.analytics as any).likes) }} <span class="text-slate-300">likes</span></span>
        <span v-if="(detail.analytics as any).engagement_rate !== undefined" class="text-[10px] text-violet-500">{{ ((detail.analytics as any).engagement_rate * 100).toFixed(1) }}%</span>
      </template>
      <template v-if="has(detail.ripple_prediction)">
        <span v-if="detail.ripple_prediction!.viral_probability != null" class="text-[10px] text-violet-500">{{ (detail.ripple_prediction!.viral_probability * 100).toFixed(0) }}% viral</span>
      </template>
    </div>
  </div>
  <div v-else class="px-4 md:px-5 py-3 text-xs text-slate-400">{{ t('common.loadingState') }}</div>
</template>