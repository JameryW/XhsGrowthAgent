<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getCreatorQuality,
  type CreatorQualityReport,
  type CreatorQualityRecommendation,
} from '@/api/analytics'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'

const props = withDefaults(defineProps<{
  accountId: string
  accountName?: string
  /** Increment after a real import to reload this read-only report. */
  refreshToken?: number
}>(), {
  accountName: '',
  refreshToken: 0,
})

const { t, locale } = useI18n()

const report = ref<CreatorQualityReport | null>(null)
const isLoading = ref(false)
const errorMessage = ref('')
let latestRequest = 0

const isLowData = computed(() => Boolean(
  report.value?.cold_start
  || report.value?.insufficient_data
  || report.value?.overall_score == null
))

const reportScore = computed(() => formatScore(report.value?.overall_score))
const scoreProgress = computed(() => {
  const score = report.value?.overall_score
  if (score == null) return '0%'
  return `${Math.min(100, Math.max(0, Math.round(score)))}%`
})
const sampleValue = computed(() => report.value
  ? t('creatorQuality.sampleValue', {
    analyzed: report.value.notes_analyzed,
    total: report.value.total_notes,
  })
  : '')

const visibleRecommendations = computed<CreatorQualityRecommendation[]>(() => {
  if (!report.value) return []
  // The backend may omit list fields (null) when nothing was analyzed yet.
  return [...(report.value.recommendations ?? [])]
    .sort((a, b) => a.priority - b.priority)
    .slice(0, 3)
})

const lowDataTitle = computed(() => report.value?.cold_start
  ? t('creatorQuality.empty.title')
  : t('creatorQuality.lowData.title'))

const lowDataDescription = computed(() => report.value?.cold_start
  ? t('creatorQuality.empty.description')
  : t('creatorQuality.lowData.description'))

watch(
  () => [props.accountId, props.refreshToken, locale.value] as const,
  ([accountId, , reportLocale]) => {
    void loadReport(accountId, reportLocale)
  },
  { immediate: true }
)

async function loadReport(accountId = props.accountId, reportLocale = locale.value) {
  const request = ++latestRequest
  if (!accountId) {
    report.value = null
    errorMessage.value = ''
    isLoading.value = false
    return
  }

  isLoading.value = true
  errorMessage.value = ''
  report.value = null
  try {
    const result = await getCreatorQuality(accountId, reportLocale)
    if (request !== latestRequest) return
    report.value = result
  } catch (error: unknown) {
    if (request !== latestRequest) return
    errorMessage.value = error instanceof Error
      ? error.message
      : t('creatorQuality.error.description')
  } finally {
    if (request === latestRequest) isLoading.value = false
  }
}

function formatScore(score: number | null | undefined): string {
  if (score == null) return '—'
  return `${Math.round(score)}`
}

function translateEnum(group: 'grade' | 'confidence' | 'scope', value: string): string {
  const key = `creatorQuality.${group}.${value}`
  const translated = t(key)
  return translated === key ? value : translated
}

function dimensionLabel(key: string): string {
  const translationKey = `creatorQuality.dimension.${key}`
  const translated = t(translationKey)
  return translated === translationKey ? key : translated
}
</script>

<template>
  <section
    class="min-w-0 rounded-2xl border border-slate-200/70 bg-white/95 p-4 shadow-sm backdrop-blur-sm md:p-6 dark:bg-slate-900/90 dark:border-slate-700/55"
    :aria-label="t('creatorQuality.title')"
  >
    <div class="flex min-w-0 flex-col gap-3 border-b border-slate-100 pb-4 sm:flex-row sm:items-start sm:justify-between dark:border-slate-700/50">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-blue-500 shadow-sm">
            <AppIcon name="Brain" size="sm" variant="white" />
          </div>
          <h3 class="text-base font-semibold text-slate-800 dark:text-slate-100">
            {{ t('creatorQuality.title') }}
          </h3>
        </div>
        <p class="mt-1.5 break-words text-xs leading-relaxed text-slate-500 dark:text-slate-400">
          {{ t('creatorQuality.subtitle') }}
          <span v-if="accountName || accountId" class="text-slate-500 dark:text-slate-400">
            · {{ accountName || accountId }}
          </span>
        </p>
      </div>
      <NeonButton
        variant="ghost"
        size="sm"
        class="w-full shrink-0 sm:w-auto"
        :disabled="isLoading"
        :aria-label="t('creatorQuality.refresh')"
        :title="t('creatorQuality.refresh')"
        @click="loadReport()"
      >
        <AppIcon name="RefreshCw" size="xs" variant="cyan" :animate="isLoading" />
        <span>{{ t('creatorQuality.refresh') }}</span>
      </NeonButton>
    </div>

    <div
      v-if="isLoading"
      class="mt-4 space-y-3"
      aria-live="polite"
      :aria-label="t('creatorQuality.loading')"
    >
      <div class="h-20 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
      <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div v-for="index in 4" :key="index" class="h-24 animate-pulse rounded-lg bg-slate-50 dark:bg-slate-800" />
      </div>
      <p class="text-center text-xs text-slate-400">{{ t('creatorQuality.loading') }}</p>
    </div>

    <div
      v-else-if="errorMessage"
      class="mt-4 rounded-lg border border-rose-100 bg-rose-50/70 p-3 dark:border-rose-400/20 dark:bg-rose-400/10"
      aria-live="polite"
    >
      <div class="flex min-w-0 items-start gap-2">
        <AppIcon name="AlertTriangle" size="sm" variant="pink" class="mt-0.5 shrink-0" />
        <div class="min-w-0">
          <div class="text-xs font-semibold text-rose-700 dark:text-rose-200">{{ t('creatorQuality.error.title') }}</div>
          <p class="mt-1 break-words text-[11px] leading-relaxed text-rose-600 dark:text-rose-300">{{ errorMessage }}</p>
        </div>
      </div>
      <NeonButton variant="ghost" size="sm" class="mt-3 w-full sm:w-auto" @click="loadReport()">
        <AppIcon name="RefreshCw" size="xs" variant="cyan" />
        <span>{{ t('creatorQuality.error.retry') }}</span>
      </NeonButton>
    </div>

    <div v-else-if="report" class="mt-4 space-y-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div class="min-w-0 rounded-xl border border-cyan-100 bg-gradient-to-br from-cyan-50 to-blue-50/70 p-4 sm:col-span-1 dark:border-cyan-400/25 dark:from-cyan-400/15 dark:to-blue-400/10">
          <div class="text-[10px] font-semibold uppercase tracking-wider text-cyan-600 dark:text-cyan-300">
            {{ t('creatorQuality.score') }}
          </div>
          <div class="mt-1.5 flex items-end gap-1">
            <span class="text-4xl font-bold leading-none text-cyan-700 dark:text-cyan-200">{{ reportScore }}</span>
            <span v-if="report.overall_score != null" class="text-xs text-cyan-600 dark:text-cyan-300">{{ t('creatorQuality.scoreOutOf') }}</span>
          </div>
          <p v-if="report.overall_score == null" class="mt-1 text-[10px] text-cyan-600 dark:text-cyan-300">
            {{ t('creatorQuality.notScored') }}
          </p>
          <div v-else class="mt-3 h-1.5 overflow-hidden rounded-full bg-cyan-100 dark:bg-cyan-400/15">
            <div class="h-full rounded-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-500" :style="{ width: scoreProgress }" />
          </div>
        </div>
        <div class="min-w-0 rounded-xl border border-slate-100 bg-slate-50/70 p-4 dark:border-slate-700/50 dark:bg-slate-800/60">
          <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            {{ t('creatorQuality.gradeLabel') }}
          </div>
          <div class="mt-1 break-words text-sm font-semibold text-slate-700 dark:text-slate-100">
            {{ translateEnum('grade', report.grade) }}
          </div>
        </div>
        <div class="min-w-0 rounded-xl border border-slate-100 bg-slate-50/70 p-4 dark:border-slate-700/50 dark:bg-slate-800/60">
          <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            {{ t('creatorQuality.confidenceLabel') }}
          </div>
          <div class="mt-1 break-words text-sm font-semibold text-slate-700 dark:text-slate-100">
            {{ translateEnum('confidence', report.confidence) }}
          </div>
        </div>
      </div>

      <div class="rounded-xl border border-slate-100 bg-slate-50/60 p-4 dark:border-slate-700/50 dark:bg-slate-800/55">
        <div class="flex flex-wrap items-center justify-between gap-1.5">
          <div class="text-xs font-semibold text-slate-600 dark:text-slate-200">{{ t('creatorQuality.summary') }}</div>
          <span class="text-[10px] text-slate-400">{{ sampleValue }}</span>
        </div>
        <p class="mt-2 break-words text-sm leading-6 text-slate-600 dark:text-slate-300">{{ report.summary }}</p>
        <p class="mt-2 text-[10px] leading-relaxed text-slate-400">
          {{ t('creatorQuality.scopeLabel') }}: {{ translateEnum('scope', report.scope) }}
          <span v-if="report.data_as_of"> · {{ t('evaluation.dataAsOf') }} {{ report.data_as_of }}</span>
          <span v-if="report.algorithm_version"> · {{ report.algorithm_version }}</span>
        </p>
      </div>

      <div
        v-if="isLowData"
        class="rounded-xl border border-amber-100 bg-amber-50/70 p-4 dark:border-amber-400/20 dark:bg-amber-400/10"
        aria-live="polite"
      >
        <div class="flex min-w-0 items-start gap-2">
          <AppIcon name="HelpCircle" size="sm" variant="peach" class="mt-0.5 shrink-0" />
          <div class="min-w-0">
            <div class="text-xs font-semibold text-amber-700 dark:text-amber-200">{{ lowDataTitle }}</div>
            <p class="mt-1 break-words text-[11px] leading-relaxed text-amber-700 dark:text-amber-200">{{ lowDataDescription }}</p>
          </div>
        </div>
      </div>

      <section>
        <div class="mb-2 flex items-center gap-1.5">
          <AppIcon name="BarChart3" size="xs" variant="cyan" />
          <h4 class="text-xs font-semibold text-slate-600 dark:text-slate-200">{{ t('creatorQuality.dimensions') }}</h4>
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div
            v-for="dimension in report.dimensions"
            :key="dimension.key"
            class="min-w-0 rounded-xl border border-slate-100 bg-white p-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.03)] dark:bg-slate-900/80 dark:border-slate-700/50"
            :class="isLowData ? 'opacity-75' : ''"
          >
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0 text-xs font-semibold text-slate-700 dark:text-slate-100">
                {{ dimensionLabel(dimension.key) }}
              </div>
              <span v-if="!isLowData && dimension.score != null" class="shrink-0 text-sm font-bold text-cyan-700 dark:text-cyan-300">
                {{ formatScore(dimension.score) }}
              </span>
              <span v-else class="shrink-0 text-[10px] font-medium text-slate-400">
                {{ t('creatorQuality.notScored') }}
              </span>
            </div>
            <p class="mt-1.5 break-words text-xs leading-5 text-slate-500 dark:text-slate-400">
              {{ dimension.evidence }}
            </p>
          </div>
        </div>
      </section>

      <template v-if="!isLowData">

        <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <section class="min-w-0 rounded-xl border border-emerald-100 bg-emerald-50/50 p-4 dark:border-emerald-400/20 dark:bg-emerald-400/10">
            <div class="flex items-center gap-1.5">
              <AppIcon name="Star" size="xs" variant="cyan" />
              <h4 class="text-xs font-semibold text-emerald-700 dark:text-emerald-200">{{ t('creatorQuality.strengths') }}</h4>
            </div>
            <ul v-if="(report.strengths ?? []).length" class="mt-2 space-y-2">
              <li v-for="strength in report.strengths ?? []" :key="`${strength.dimension}-${strength.title}`" class="min-w-0">
                <div class="break-words text-xs font-medium text-slate-700 dark:text-slate-100">{{ strength.title }}</div>
                <p class="mt-0.5 break-words text-xs leading-5 text-slate-500 dark:text-slate-400">{{ strength.evidence }}</p>
              </li>
            </ul>
            <p v-else class="mt-2 text-[11px] text-slate-400">{{ t('creatorQuality.none') }}</p>
          </section>

          <section class="min-w-0 rounded-xl border border-rose-100 bg-rose-50/50 p-4 dark:border-rose-400/20 dark:bg-rose-400/10">
            <div class="flex items-center gap-1.5">
              <AppIcon name="AlertTriangle" size="xs" variant="pink" />
              <h4 class="text-xs font-semibold text-rose-700 dark:text-rose-200">{{ t('creatorQuality.weaknesses') }}</h4>
            </div>
            <ul v-if="(report.weaknesses ?? []).length" class="mt-2 space-y-2">
              <li v-for="weakness in report.weaknesses ?? []" :key="`${weakness.dimension}-${weakness.title}`" class="min-w-0">
                <div class="break-words text-xs font-medium text-slate-700 dark:text-slate-100">{{ weakness.title }}</div>
                <p class="mt-0.5 break-words text-xs leading-5 text-slate-500 dark:text-slate-400">{{ weakness.evidence }}</p>
              </li>
            </ul>
            <p v-else class="mt-2 text-[11px] text-slate-400">{{ t('creatorQuality.none') }}</p>
          </section>
        </div>
      </template>

      <section class="rounded-xl border border-violet-100 bg-violet-50/50 p-4 dark:border-violet-400/20 dark:bg-violet-400/10">
        <div class="flex items-center gap-1.5">
          <AppIcon name="Lightbulb" size="xs" variant="purple" />
          <h4 class="text-xs font-semibold text-violet-700 dark:text-violet-200">{{ t('creatorQuality.recommendations') }}</h4>
        </div>
        <ol v-if="visibleRecommendations.length" class="mt-2 space-y-2">
          <li
            v-for="recommendation in visibleRecommendations"
            :key="`${recommendation.priority}-${recommendation.dimension}-${recommendation.title}`"
            class="flex min-w-0 items-start gap-3 rounded-xl border border-violet-100/70 bg-white/80 p-3 dark:bg-slate-900/75 dark:border-violet-500/25"
          >
            <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-100 text-[10px] font-semibold text-violet-700 dark:bg-violet-400/20 dark:text-violet-200">
              {{ recommendation.priority }}
            </span>
            <div class="min-w-0">
              <div class="break-words text-xs font-semibold text-slate-700 dark:text-slate-100">{{ recommendation.title }}</div>
              <p class="mt-0.5 break-words text-xs leading-5 text-slate-600 dark:text-slate-300">{{ recommendation.advice }}</p>
              <p class="mt-1 break-words text-[10px] leading-relaxed text-slate-400">{{ recommendation.evidence }}</p>
            </div>
          </li>
        </ol>
        <p v-else class="mt-2 text-[11px] text-slate-400">{{ t('creatorQuality.none') }}</p>
      </section>

      <p class="border-t border-slate-100 pt-3 text-[10px] leading-relaxed text-slate-400 dark:border-slate-700/50">
        {{ t('creatorQuality.scopeLimit') }}
      </p>
    </div>

    <div v-else class="mt-4 rounded-lg border border-slate-100 bg-slate-50/60 p-3 text-center text-xs text-slate-400 dark:border-slate-700/50 dark:bg-slate-800/55">
      {{ t('creatorQuality.empty.description') }}
    </div>
  </section>
</template>
