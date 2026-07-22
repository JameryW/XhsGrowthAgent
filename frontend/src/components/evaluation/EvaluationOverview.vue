<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import TrendChart from '@/components/charts/TrendChart.vue'
import { getEvaluationTrend } from '@/api/evaluation'
import { getCreatorQuality, type CreatorQualityReport } from '@/api/analytics'
import type { Account } from '@/api/accounts'
import type { EvaluationTrendResponse } from '@/types/evaluation'
import { SCORE_THRESHOLDS, scoreTier as scoreTierOf } from '@/constants/evaluation'
import { formatShortDate } from '@/utils/format'

/**
 * EvaluationOverview — fused headline band for the quality hub.
 * One strip answering both "how is the account doing historically"
 * (deterministic creator-quality report) and "how are recent pieces scoring"
 * (RQGM workflow trend + evaluated count). Account selection lives here.
 */
const props = withDefaults(defineProps<{
  accountId: string
  accounts: Account[]
  activeAccountId?: string | null
  accountsLoading?: boolean
  evaluatedTotal?: number
}>(), {
  activeAccountId: null,
  accountsLoading: false,
  evaluatedTotal: 0,
})

const emit = defineEmits<{
  'update:accountId': [value: string]
  refreshAccounts: []
}>()

const { t, locale } = useI18n()

// ── 账户综合分（确定性历史报告，与下方诊断区块同源）──
const report = ref<CreatorQualityReport | null>(null)
const reportLoading = ref(false)
let reportRequest = 0

watch(
  () => [props.accountId, locale.value] as const,
  ([accountId, reportLocale]) => {
    void loadReport(accountId, reportLocale)
  },
  { immediate: true },
)

async function loadReport(accountId: string, reportLocale: string) {
  const request = ++reportRequest
  report.value = null
  if (!accountId) {
    reportLoading.value = false
    return
  }
  reportLoading.value = true
  try {
    const result = await getCreatorQuality(accountId, reportLocale)
    if (request === reportRequest) report.value = result
  } catch {
    // The diagnosis panel below owns the full error state; the band stays quiet.
  } finally {
    if (request === reportRequest) reportLoading.value = false
  }
}

const scoreText = computed(() => {
  const score = report.value?.overall_score
  return score == null ? '—' : `${Math.round(score)}`
})

function translateEnum(group: 'grade' | 'confidence', value: string | undefined): string {
  if (!value) return '—'
  const key = `creatorQuality.${group}.${value}`
  const translated = t(key)
  return translated === key ? value : translated
}

// ── RQGM 评估趋势（单篇视角）──
const trend = ref<EvaluationTrendResponse | null>(null)
const trendLoading = ref(false)
// EV-02: distinguish trend fetch failure from genuine no-data.
const trendError = ref<string | null>(null)

const trendData = computed(() =>
  (trend.value?.points || [])
    .filter((p) => p.overall_score != null && !p.degraded && !['degraded', 'failed', 'unavailable'].includes(p.status || 'ready'))
    .map((p) => ({
      date: formatShortDate(p.created_at, locale.value),
      value: p.overall_score as number,
    })),
)

const hasTrend = computed(() => trendData.value.length > 0)

async function loadTrend(accountId = props.accountId) {
  const request = ++trendRequest
  trendLoading.value = true
  trendError.value = null
  trend.value = null
  if (!accountId) {
    trendLoading.value = false
    return
  }
  try {
    const response = await getEvaluationTrend(accountId, 100, { suppressToast: true })
    if (request === trendRequest && accountId === props.accountId) trend.value = response
  } catch (e: any) {
    if (request === trendRequest) trendError.value = e?.message ?? 'error'
  } finally {
    if (request === trendRequest) trendLoading.value = false
  }
}

function retryTrend() {
  void loadTrend(props.accountId)
}

let trendRequest = 0
watch(
  () => [props.accountId, locale.value] as const,
  ([accountId]) => { void loadTrend(accountId) },
  { immediate: true },
)

function scoreTierClass(score: number | null | undefined): string {
  const thresholds = trend.value?.pass_threshold != null && trend.value?.warn_threshold != null
    ? { pass: trend.value.pass_threshold, warn: trend.value.warn_threshold }
    : SCORE_THRESHOLDS
  switch (scoreTierOf(score, thresholds)) {
    case 'pass': return 'score-pass'
    case 'warn': return 'score-warn'
    case 'fail': return 'score-fail'
    default: return ''
  }
}
</script>

<template>
  <section class="eval-overview" :aria-label="t('evaluation.overview.title')">
    <div class="ov-blob ov-blob-a" aria-hidden="true" />
    <div class="ov-blob ov-blob-b" aria-hidden="true" />

    <div class="relative">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div class="min-w-0">
          <div class="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-violet-700 dark:text-violet-300">
            <span class="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-rose-500 shadow-sm">
              <AppIcon name="ClipboardCheck" size="sm" variant="white" />
            </span>
            {{ t('evaluation.overview.eyebrow') }}
          </div>
          <h2 class="mt-3 text-xl font-semibold tracking-tight text-slate-800 md:text-2xl dark:text-slate-100">
            {{ t('evaluation.overview.title') }}
          </h2>
        </div>

        <div v-if="accounts.length" class="flex w-full flex-col gap-2 sm:flex-row lg:w-auto">
          <label class="min-w-0 flex-1 lg:w-64">
            <span class="mb-1.5 block text-xs font-semibold text-slate-500 dark:text-slate-400">
              {{ t('creatorQuality.page.accountLabel') }}
            </span>
            <span class="relative block">
              <select
                :value="accountId"
                class="w-full appearance-none rounded-xl border border-slate-200 bg-white/90 py-2.5 pl-3 pr-9 text-sm font-medium text-slate-700 shadow-sm outline-none transition focus:border-violet-400 focus:ring-4 focus:ring-violet-100 dark:border-slate-600/60 dark:bg-slate-900/80 dark:text-slate-200 dark:focus:border-violet-400/50 dark:focus:ring-violet-900/40"
                :aria-label="t('creatorQuality.page.accountLabel')"
                @change="emit('update:accountId', ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="account in accounts" :key="account.id" :value="account.id">
                  {{ account.name }}{{ account.is_active ? ` (${t('settings.active')})` : '' }}
                </option>
              </select>
              <AppIcon name="ChevronDown" size="sm" variant="purple" class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2" />
            </span>
          </label>
          <button
            type="button"
            class="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white/80 px-3 py-2.5 text-xs font-semibold text-slate-600 shadow-sm transition hover:border-violet-200 hover:bg-violet-50 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-60 sm:self-end dark:border-slate-600/60 dark:bg-slate-900/70 dark:text-slate-300 dark:hover:border-violet-400/40 dark:hover:bg-violet-950/35 dark:hover:text-violet-200"
            :disabled="accountsLoading"
            :aria-label="t('creatorQuality.page.refreshAccounts')"
            :title="t('creatorQuality.page.refreshAccounts')"
            @click="emit('refreshAccounts')"
          >
            <AppIcon name="RefreshCw" size="xs" variant="purple" :animate="accountsLoading" />
            <span>{{ t('creatorQuality.page.refresh') }}</span>
          </button>
        </div>
      </div>

      <div class="mt-5 grid gap-3 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.45fr)_minmax(0,0.7fr)]">
        <!-- 账户综合分（历史视角） -->
        <div class="ov-card">
          <p class="ov-label">{{ t('evaluation.performanceScoreLabel') }}</p>
          <p v-if="!accountId" class="ov-hint">{{ t('evaluation.overview.noAccount') }}</p>
          <div v-else-if="reportLoading" class="mt-2 h-10 w-24 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" aria-busy="true" />
          <template v-else>
            <div class="mt-1 flex items-end gap-2">
              <span class="ov-score-value">{{ scoreText }}</span>
              <span v-if="report?.grade" class="ov-grade">{{ translateEnum('grade', report.grade) }}</span>
            </div>
            <p class="ov-sub">
              {{ t('creatorQuality.confidenceLabel') }}：{{ translateEnum('confidence', report?.confidence) }}
            </p>
          </template>
        </div>

        <!-- RQGM 评估趋势（单篇视角） -->
        <div class="ov-card">
          <p class="ov-label">{{ t('evaluation.rqgmTrendLabel') }}</p>
          <p v-if="trendLoading" class="ov-hint">{{ t('evaluation.trend.loading') }}</p>
          <template v-else-if="hasTrend">
            <TrendChart :data="trendData" :height="110" />
            <div
              v-if="trend?.dim_averages && Object.keys(trend.dim_averages).length"
              class="dim-averages"
            >
              <span class="dim-avg-label">{{ t('evaluation.trend.dimAverages') }}</span>
              <span
                v-for="(v, k) in trend.dim_averages"
                :key="k"
                class="dim-avg-chip"
                :class="scoreTierClass(v)"
              >
                {{ k }}: {{ v.toFixed(1) }}
              </span>
            </div>
          </template>
          <div v-else-if="trendError" class="trend-error">
            <span>{{ t('evaluation.trend.failed') }}</span>
            <button type="button" class="retry-btn min-h-[36px]" @click="retryTrend">{{ t('evaluation.trend.retry') }}</button>
          </div>
          <p v-else class="ov-hint">{{ t('evaluation.trend.empty') }}</p>
          <p v-if="trend?.data_as_of" class="ov-meta">{{ t('evaluation.dataAsOf') }} {{ trend.data_as_of }}</p>
        </div>

        <!-- 融合 KPI -->
        <div class="ov-card ov-kpis">
          <div>
            <p class="ov-label">{{ t('evaluation.overview.evaluated') }}</p>
            <p class="ov-kpi-value">{{ evaluatedTotal }}</p>
          </div>
          <div>
            <p class="ov-label">{{ t('evaluation.overview.samples') }}</p>
            <p class="ov-kpi-value">{{ accountId ? (report?.notes_analyzed ?? '—') : '—' }}</p>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.eval-overview {
  position: relative;
  overflow: hidden;
  border-radius: 1rem;
  border: 1px solid rgb(196 181 253 / 0.5);
  background: linear-gradient(135deg, rgb(245 243 255 / 0.95), rgb(255 255 255 / 0.98) 45%, rgb(255 241 242 / 0.9));
  padding: 1rem;
  box-shadow: 0 1px 3px rgb(15 23 42 / 0.06);
}

@media (min-width: 768px) {
  .eval-overview {
    padding: 1.5rem;
  }
}

.dark .eval-overview {
  border-color: rgb(139 92 246 / 0.25);
  background: linear-gradient(135deg, rgb(15 23 42 / 0.95), rgb(15 23 42 / 0.9) 50%, rgb(76 29 149 / 0.25));
}

.ov-blob {
  position: absolute;
  border-radius: 9999px;
  pointer-events: none;
  filter: blur(48px);
}

.ov-blob-a {
  top: -4rem;
  right: -3.5rem;
  width: 12rem;
  height: 12rem;
  background: rgb(196 181 253 / 0.4);
}

.ov-blob-b {
  bottom: -5rem;
  left: 30%;
  width: 10rem;
  height: 10rem;
  background: rgb(251 207 232 / 0.35);
}

.dark .ov-blob-a {
  background: rgb(139 92 246 / 0.18);
}

.dark .ov-blob-b {
  background: rgb(244 63 94 / 0.12);
}

.ov-card {
  border-radius: 0.875rem;
  border: 1px solid rgb(226 232 240 / 0.9);
  background: rgb(255 255 255 / 0.8);
  padding: 0.875rem 1rem;
  backdrop-filter: blur(8px);
}

.dark .ov-card {
  border-color: rgb(51 65 85 / 0.7);
  background: rgb(15 23 42 / 0.6);
}

.ov-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
}

.dark .ov-label {
  color: #94a3b8;
}

.ov-hint {
  margin-top: 0.5rem;
  font-size: 0.8125rem;
  line-height: 1.5;
  color: #94a3b8;
}

.ov-score-value {
  font-size: 2.25rem;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.02em;
  color: #1e293b;
}

.dark .ov-score-value {
  color: #f1f5f9;
}

.ov-grade {
  margin-bottom: 0.2rem;
  border-radius: 999px;
  background: linear-gradient(135deg, rgb(139 92 246 / 0.14), rgb(244 63 94 / 0.12));
  padding: 0.2rem 0.6rem;
  font-size: 0.7rem;
  font-weight: 700;
  color: #7c3aed;
}

.dark .ov-grade {
  color: #c4b5fd;
}

.ov-sub {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #94a3b8;
}

.ov-kpis {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 0.75rem;
}

.ov-kpi-value {
  margin-top: 0.15rem;
  font-size: 1.5rem;
  font-weight: 800;
  line-height: 1;
  color: #1e293b;
  font-variant-numeric: tabular-nums;
}

.dark .ov-kpi-value {
  color: #f1f5f9;
}

/* ── 趋势错误态 / 维度均值 chips（自原列表趋势卡迁入）── */
.trend-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem 0 0.5rem;
  font-size: 0.8125rem;
  color: #b91c1c;
}

.retry-btn {
  padding: 0.25rem 1rem;
  border-radius: 0.5rem;
  background: #0d9488;
  color: #fff;
  font-size: 0.75rem;
  font-weight: 600;
  border: 0;
  cursor: pointer;
}

.retry-btn:hover {
  background: #0f766e;
}

.dim-averages {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.6rem;
}

.dim-avg-label {
  font-size: 0.75rem;
  color: #64748b;
}

.dim-avg-chip {
  font-size: 0.7rem;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-weight: 600;
  background: #f1f5f9;
  color: #334155;
}

.dim-avg-chip.score-pass {
  background: #dcfce7;
  color: #15803d;
}

.dim-avg-chip.score-warn {
  background: #fef3c7;
  color: #b45309;
}

.dim-avg-chip.score-fail {
  background: #fee2e2;
  color: #b91c1c;
}

.dark .dim-avg-chip {
  background: #1e293b;
  color: #cbd5e1;
}
</style>
