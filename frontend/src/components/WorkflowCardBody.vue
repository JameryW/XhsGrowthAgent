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
  <div v-if="detail" class="min-h-[92px] px-4 py-3 space-y-1.5 md:px-5" aria-label="workflow-output">
    <!-- ═══ Level 1: Primary title — largest, boldest ═══ -->

    <!-- Brief mode: brand name (L1) -->
    <div v-if="has(detail.brief_content)">
      <div class="flex items-baseline gap-2">
        <span v-if="(detail.brief_content as any).brand_name" class="text-base font-bold text-slate-900 leading-tight">{{ (detail.brief_content as any).brand_name }}</span>
        <!-- L2: product name -->
        <span v-if="(detail.brief_content as any).product_name" class="text-sm font-semibold text-slate-500 truncate">{{ (detail.brief_content as any).product_name }}</span>
      </div>
    </div>

    <!-- Standard mode: selected topic (L1) -->
    <div v-if="!has(detail.brief_content) && detail.content_plan?.selected_topic">
      <div class="text-base font-bold text-slate-900 leading-tight line-clamp-1">{{ detail.content_plan.selected_topic }}</div>
      <!-- L2: copy title -->
      <div v-if="detail.copy_content?.selected_title" class="text-sm font-semibold text-rose-600 mt-0.5 line-clamp-1">{{ detail.copy_content.selected_title }}</div>
    </div>

    <!-- ═══ Level 3: Tags — hashtags, selling points, blogger, versions ═══ -->

    <div class="flex flex-wrap items-center gap-1">
      <!-- Brief: selling points (≤2) -->
      <template v-if="has(detail.brief_content) && (detail.brief_content as any).selling_points?.length">
        <span v-for="sp in (detail.brief_content as any).selling_points.slice(0, 2)" :key="sp" class="text-xs px-1.5 py-0.5 rounded bg-pink-50 text-pink-600">{{ sp }}</span>
      </template>
      <!-- Hashtags (≤3) -->
      <template v-if="!has(detail.brief_content) && detail.copy_content?.hashtags?.length">
        <span v-for="tag in detail.copy_content.hashtags.slice(0, 3)" :key="tag" class="text-xs px-1.5 py-0.5 rounded bg-teal-50 text-teal-700">#{{ tag }}</span>
      </template>
      <!-- Brief required hashtags -->
      <template v-if="has(detail.brief_content) && (detail.brief_content as any).required_hashtags?.length">
        <span v-for="tag in (detail.brief_content as any).required_hashtags.slice(0, 3)" :key="tag" class="text-xs px-1.5 py-0.5 rounded bg-teal-50 text-teal-600">#{{ tag }}</span>
      </template>
      <!-- Blogger nickname -->
      <span v-if="has((detail as any).shooting_plan) && (detail as any).shooting_plan.creator_nickname" class="text-xs text-slate-500">{{ (detail as any).shooting_plan.creator_nickname }}</span>
      <!-- Content type label -->
      <span v-if="has((detail as any).shooting_plan) && (detail as any).shooting_plan.content_type_label" class="text-xs px-1.5 py-0.5 rounded bg-violet-50 text-violet-600">{{ (detail as any).shooting_plan.content_type_label }}</span>
      <!-- Content versions count -->
      <span v-if="(detail as any).content_versions?.length" class="text-xs px-1.5 py-0.5 rounded-full bg-violet-50 text-violet-600">{{ (detail as any).content_versions.length }} {{ t('replay.contentVersions') }}</span>
    </div>

    <!-- Publish result (prominent for completed workflows) -->
    <div v-if="has(detail.publish_result)" class="flex items-center gap-2 text-xs">
      <span class="text-emerald-600 font-medium" v-if="(detail.publish_result as any).status === 'published'">{{ t('replay.status') }}</span>
      <a v-if="(detail.publish_result as any).post_url" :href="(detail.publish_result as any).post_url" target="_blank" rel="noopener" class="inline-flex items-center gap-0.5 text-emerald-600 hover:text-emerald-700 font-medium" @click.stop>
        <AppIcon name="ExternalLink" size="xs" />
        {{ t('replay.viewPost') }}
      </a>
    </div>

    <!-- Optimization: top suggestion (L3) -->
    <div v-if="has((detail as any).optimization_analysis) && (detail as any).optimization_analysis.suggestions?.length" class="text-xs text-slate-500 line-clamp-1">
      <span class="text-violet-500 font-medium">P{{ (detail as any).optimization_analysis.suggestions[0].priority }}</span> {{ (detail as any).optimization_analysis.suggestions[0].action }}
    </div>

    <!-- ═══ Level 4: Metadata — smallest, faintest ═══ -->

    <div class="flex flex-wrap items-center gap-1.5 pt-1 border-t border-slate-100/40">
      <template v-if="detail.trend_data?.hot_topics?.length">
        <span v-for="ht in detail.trend_data.hot_topics.slice(0, 2)" :key="ht.topic" class="text-[10px] px-1.5 py-0.5 rounded-full bg-rose-50/60 text-rose-400">{{ ht.topic }}</span>
      </template>
      <div v-if="has(detail.visual_plan) && (detail.visual_plan as any)?.color_palette?.length" class="flex gap-0.5">
        <div v-for="color in (detail.visual_plan as any).color_palette.slice(0, 4)" :key="color" class="w-2.5 h-2.5 rounded-full border border-white shadow-sm" :style="{ backgroundColor: color }" />
      </div>
      <template v-if="has(detail.analytics)">
        <span v-if="(detail.analytics as any).views !== undefined" class="text-[10px] text-slate-300">{{ formatNum((detail.analytics as any).views) }} <span class="text-slate-200">{{ t('replay.views') }}</span></span>
        <span v-if="(detail.analytics as any).likes !== undefined" class="text-[10px] text-pink-400">{{ formatNum((detail.analytics as any).likes) }} <span class="text-slate-200">{{ t('replay.likes') }}</span></span>
        <span v-if="(detail.analytics as any).engagement_rate !== undefined" class="text-[10px] text-violet-400">{{ ((detail.analytics as any).engagement_rate * 100).toFixed(1) }}%</span>
      </template>
      <template v-if="has(detail.ripple_prediction)">
        <span v-if="detail.ripple_prediction!.viral_probability != null" class="text-[10px] text-violet-400">{{ t('workflowCardBody.viralProbability', { pct: (detail.ripple_prediction!.viral_probability * 100).toFixed(0) }) }}</span>
      </template>
    </div>
  </div>
  <div v-else class="px-4 md:px-5 py-3 text-xs text-slate-400">{{ t('common.loadingState') }}</div>
</template>
