<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import type { PublicResult } from '@/types/publicShowcase'

const props = defineProps<{
  result: PublicResult
  compact?: boolean
}>()

const { t, locale } = useI18n()

function formatNumber(value?: number): string {
  if (value === undefined || value === null) return '—'
  return new Intl.NumberFormat(locale.value || undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function formatPercent(value?: number): string {
  if (value === undefined || value === null) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function hasResult(): boolean {
  return Object.keys(props.result).length > 0
}
</script>

<template>
  <section class="public-result space-y-4" :class="compact ? 'public-result-compact' : ''" :aria-label="t('replay.publicResultLabel')">
    <div v-if="!hasResult()" class="dark-explicit rounded-2xl border border-dashed border-slate-300/70 p-6 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
      {{ t('replay.publicNoResult') }}
    </div>

    <template v-else>
      <div v-if="result.error_category" class="dark-explicit rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-400/10 dark:text-amber-100" role="status">
        {{ t(`replay.publicErrorCategory.${result.error_category}`) }}
      </div>
      <div v-if="result.title || result.topic" class="space-y-1">
        <p v-if="result.topic" class="dark-explicit text-xs font-medium uppercase tracking-[0.12em] text-teal-700 dark:text-teal-300">{{ result.topic }}</p>
        <h2 v-if="result.title" class="dark-explicit text-xl font-bold leading-tight text-slate-900 dark:text-slate-50">{{ result.title }}</h2>
      </div>

      <p v-if="result.summary" class="dark-explicit text-sm leading-6 text-slate-600 dark:text-slate-300">{{ result.summary }}</p>

      <div v-if="result.key_points?.length" class="dark-explicit rounded-xl bg-slate-50/80 p-4 dark:bg-slate-800/70">
        <h3 class="dark-explicit text-sm font-semibold text-slate-800 dark:text-slate-100">{{ t('replay.publicKeyPoints') }}</h3>
        <ul class="dark-explicit mt-2 space-y-2 text-sm leading-5 text-slate-600 dark:text-slate-300">
          <li v-for="point in result.key_points" :key="point" class="flex gap-2">
            <AppIcon name="Check" size="xs" variant="cyan" class="mt-0.5 shrink-0" aria-hidden="true" />
            <span>{{ point }}</span>
          </li>
        </ul>
      </div>

      <div v-if="result.hashtags?.length" class="flex flex-wrap gap-2">
        <span v-for="tag in result.hashtags" :key="tag" class="dark-explicit rounded-full bg-teal-50 px-2.5 py-1 text-xs text-teal-700 dark:bg-teal-400/10 dark:text-teal-200">#{{ tag.replace(/^#/, '') }}</span>
      </div>

      <div v-if="result.visual" class="dark-explicit grid grid-cols-2 gap-3 rounded-xl border border-slate-200/70 p-4 dark:border-slate-700/70">
        <div v-if="result.visual.layout">
          <p class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('replay.publicLayout') }}</p>
          <p class="dark-explicit mt-1 text-sm font-medium text-slate-800 dark:text-slate-100">{{ result.visual.layout }}</p>
        </div>
        <div v-if="result.visual.image_count !== undefined">
          <p class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('replay.publicImageCount') }}</p>
          <p class="dark-explicit mt-1 text-sm font-medium text-slate-800 dark:text-slate-100">{{ result.visual.image_count }}</p>
        </div>
        <div v-if="result.visual.palette?.length" class="col-span-2 flex items-center gap-2">
          <span class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('replay.publicPalette') }}</span>
          <span v-for="color in result.visual.palette" :key="color" class="dark-explicit h-5 w-5 rounded-full border border-white shadow-sm dark:border-slate-600" :style="{ backgroundColor: color }" :title="color" />
        </div>
      </div>

      <div v-if="result.publish" class="flex flex-wrap items-center gap-3 rounded-xl bg-emerald-50/80 p-3 dark:bg-emerald-400/10">
        <span class="text-sm font-medium text-emerald-800 dark:text-emerald-200">{{ t(`replay.publicPublishStatus.${result.publish.status || 'draft'}`) }}</span>
        <a v-if="result.publish.post_url" :href="result.publish.post_url" target="_blank" rel="noopener" class="dark-explicit inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100 dark:text-emerald-200 dark:hover:bg-emerald-400/20">
          <AppIcon name="ExternalLink" size="xs" aria-hidden="true" />
          {{ t('replay.viewPost') }}
        </a>
      </div>

      <div v-if="result.metrics" class="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div v-if="result.metrics.views !== undefined" class="dark-explicit rounded-xl border border-slate-200/70 p-3 dark:border-slate-700/70">
          <p class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('replay.views') }}</p>
          <p class="dark-explicit mt-1 text-lg font-semibold text-slate-900 dark:text-slate-50">{{ formatNumber(result.metrics.views) }}</p>
        </div>
        <div v-if="result.metrics.likes !== undefined" class="dark-explicit rounded-xl border border-slate-200/70 p-3 dark:border-slate-700/70">
          <p class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('replay.likes') }}</p>
          <p class="dark-explicit mt-1 text-lg font-semibold text-slate-900 dark:text-slate-50">{{ formatNumber(result.metrics.likes) }}</p>
        </div>
        <div v-if="result.metrics.engagement_rate !== undefined" class="dark-explicit rounded-xl border border-slate-200/70 p-3 dark:border-slate-700/70">
          <p class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('replay.engagement') }}</p>
          <p class="dark-explicit mt-1 text-lg font-semibold text-slate-900 dark:text-slate-50">{{ formatPercent(result.metrics.engagement_rate) }}</p>
        </div>
      </div>

      <details v-if="result.prediction" class="dark-explicit rounded-xl border border-violet-200/70 p-4 dark:border-violet-400/20">
        <summary class="cursor-pointer text-sm font-medium text-violet-800 dark:text-violet-200">{{ t('replay.publicPrediction') }}</summary>
        <div class="dark-explicit mt-3 grid grid-cols-2 gap-3 text-sm text-slate-600 dark:text-slate-300">
          <span v-if="result.prediction.estimated_reach !== undefined">{{ t('replay.estReach') }}：{{ formatNumber(result.prediction.estimated_reach) }}</span>
          <span v-if="result.prediction.viral_probability !== undefined">{{ t('replay.viralProb') }}：{{ formatPercent(result.prediction.viral_probability) }}</span>
          <span v-if="result.prediction.confidence !== undefined">{{ t('replay.confidence') }}：{{ formatPercent(result.prediction.confidence) }}</span>
          <span v-if="result.prediction.pmf_score !== undefined">{{ t('replay.pmfScore') }}：{{ result.prediction.pmf_score }}</span>
        </div>
      </details>
    </template>
  </section>
</template>

<style scoped>
.public-result :deep(summary) {
  list-style: none;
}

.public-result :deep(summary::-webkit-details-marker) {
  display: none;
}

.public-result :deep(summary)::before {
  content: '＋';
  display: inline-block;
  margin-right: 0.45rem;
}

.public-result :deep(details[open] summary)::before {
  content: '−';
}
</style>
