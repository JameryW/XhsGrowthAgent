<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { getPublicTelemetrySummary } from '@/api/publicShowcase'
import type { PublicTelemetrySummaryRow } from '@/types/publicShowcase'

const { t, locale } = useI18n()

const days = ref(7)
const rows = ref<PublicTelemetrySummaryRow[]>([])
const loading = ref(true)
const loadError = ref(false)
let requestToken = 0
let abortController: AbortController | null = null

const totalEvents = computed(() => rows.value.reduce((sum, row) => sum + row.event_count, 0))
const measuredEvents = computed(() => rows.value.reduce((sum, row) => sum + row.measured_count, 0))
const visibleRows = computed(() => rows.value.slice(0, 24))
const FIRST_RESULT_BUDGET_MS = 2500
const CACHED_SELECT_BUDGET_MS = 100

type MetricStatus = 'passing' | 'overBudget' | 'noData'

function metricForEvent(
  eventName: string,
  field: 'p50_duration_ms' | 'p75_duration_ms',
  matches: (row: PublicTelemetrySummaryRow) => boolean = () => true,
): number | null {
  const values = rows.value
    .filter(row => row.event_name === eventName && matches(row))
    .map(row => row[field])
    .filter((value): value is number => typeof value === 'number')
  return values.length ? Math.max(...values) : null
}

const firstResultP75 = computed(() => metricForEvent('replay_first_result_visible', 'p75_duration_ms'))
const cachedSelectP75 = computed(() => metricForEvent(
  'replay_select_to_render',
  'p75_duration_ms',
  row => row.cached === true,
))

function metricStatus(value: number | null, budget: number): MetricStatus {
  if (value === null) return 'noData'
  return value <= budget ? 'passing' : 'overBudget'
}

const firstResultStatus = computed(() => metricStatus(firstResultP75.value, FIRST_RESULT_BUDGET_MS))
const cachedSelectStatus = computed(() => metricStatus(cachedSelectP75.value, CACHED_SELECT_BUDGET_MS))

function formatNumber(value: number): string {
  return new Intl.NumberFormat(locale.value || undefined).format(value)
}

function formatDuration(value: number | null): string {
  if (value === null) return '—'
  return formatNumber(Math.round(value)) + ' ms'
}

function statusLabel(status: MetricStatus): string {
  return t('settings.publicTelemetry.status.' + status)
}

function statusClasses(status: MetricStatus): string {
  if (status === 'passing') return 'dark-explicit bg-emerald-100 text-emerald-800 dark:bg-emerald-400/15 dark:text-emerald-200'
  if (status === 'overBudget') return 'dark-explicit bg-amber-100 text-amber-800 dark:bg-amber-400/15 dark:text-amber-200'
  return 'dark-explicit bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
}

function eventLabel(eventName: string): string {
  const key = 'settings.publicTelemetry.events.' + eventName
  const translated = t(key)
  return translated === key ? eventName : translated
}

function dimensions(row: PublicTelemetrySummaryRow): string {
  return [
    row.cached === true ? t('settings.publicTelemetry.cached') : row.cached === false ? t('settings.publicTelemetry.network') : null,
    row.viewport,
    row.source,
    row.status,
    row.mode,
    row.phase,
    row.view_mode,
    row.error_type,
  ].filter(Boolean).join(' · ') || t('settings.publicTelemetry.allDimensions')
}

async function load() {
  abortController?.abort()
  const controller = new AbortController()
  abortController = controller
  const token = ++requestToken
  loading.value = true
  loadError.value = false
  try {
    const response = await getPublicTelemetrySummary(days.value, {
      suppressToast: true,
      signal: controller.signal,
    })
    if (controller.signal.aborted || token !== requestToken) return
    rows.value = [...(response.events || [])].sort((a, b) => b.event_count - a.event_count)
  } catch {
    if (!controller.signal.aborted && token === requestToken) loadError.value = true
  } finally {
    if (abortController === controller) {
      abortController = null
      loading.value = false
    }
  }
}

watch(days, () => void load())
onMounted(() => void load())
onUnmounted(() => abortController?.abort())
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <h2 class="dark-explicit text-lg font-semibold text-slate-800 dark:text-slate-100">{{ t('settings.publicTelemetry.title') }}</h2>
        <p class="dark-explicit mt-1 text-xs leading-5 text-slate-400 dark:text-slate-500">{{ t('settings.publicTelemetry.subtitle') }}</p>
      </div>
      <div class="flex items-center gap-2">
        <label class="sr-only" for="public-telemetry-days">{{ t('settings.publicTelemetry.period') }}</label>
        <select id="public-telemetry-days" v-model.number="days" class="dark-explicit min-h-11 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
          <option :value="1">{{ t('settings.publicTelemetry.days', { count: 1 }) }}</option>
          <option :value="7">{{ t('settings.publicTelemetry.days', { count: 7 }) }}</option>
          <option :value="14">{{ t('settings.publicTelemetry.days', { count: 14 }) }}</option>
          <option :value="30">{{ t('settings.publicTelemetry.days', { count: 30 }) }}</option>
        </select>
        <button type="button" class="dark-explicit inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800" :aria-label="t('settings.publicTelemetry.refresh')" :title="t('settings.publicTelemetry.refresh')" :disabled="loading" @click="load">
          <AppIcon name="RefreshCw" size="xs" variant="muted" :class="loading ? 'animate-spin' : ''" aria-hidden="true" />
        </button>
      </div>
    </div>

    <div v-if="loading" class="grid gap-3 sm:grid-cols-3" aria-busy="true">
      <div v-for="index in 3" :key="index" class="dark-explicit h-24 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" />
    </div>
    <div v-else-if="loadError" class="dark-explicit rounded-xl border border-rose-200 bg-rose-50 p-6 text-center dark:border-rose-400/20 dark:bg-rose-400/10" role="alert">
      <p class="text-sm font-medium text-rose-800 dark:text-rose-100">{{ t('settings.publicTelemetry.loadFailed') }}</p>
      <button type="button" class="mt-4 min-h-11 rounded-lg bg-slate-900 px-4 text-sm font-semibold text-white dark:bg-white dark:text-slate-900" @click="load">{{ t('common.retry') }}</button>
    </div>
    <template v-else>
      <div class="grid gap-3 sm:grid-cols-3">
        <div class="dark-explicit rounded-xl border border-slate-200/70 bg-white/90 p-4 dark:border-slate-700/60 dark:bg-slate-900/80">
          <p class="dark-explicit text-xs font-medium text-slate-500 dark:text-slate-400">{{ t('settings.publicTelemetry.totalEvents') }}</p>
          <p class="dark-explicit mt-2 text-2xl font-bold text-slate-900 dark:text-slate-50">{{ formatNumber(totalEvents) }}</p>
          <p class="mt-1 text-xs text-slate-400">{{ t('settings.publicTelemetry.measured', { count: formatNumber(measuredEvents) }) }}</p>
        </div>
        <div data-testid="first-result-budget-card" class="dark-explicit rounded-xl border border-teal-200/70 bg-teal-50/70 p-4 dark:border-teal-400/20 dark:bg-teal-400/10">
          <div class="flex items-start justify-between gap-2">
            <p class="text-xs font-medium text-teal-800 dark:text-teal-200">{{ t('settings.publicTelemetry.firstResultP75') }}</p>
            <span class="rounded-full px-2 py-0.5 text-[11px] font-semibold" :class="statusClasses(firstResultStatus)" role="status">{{ statusLabel(firstResultStatus) }}</span>
          </div>
          <p class="mt-2 text-2xl font-bold text-teal-900 dark:text-teal-50">{{ formatDuration(firstResultP75) }}</p>
          <p class="mt-1 text-xs text-teal-700/70 dark:text-teal-200/70">{{ t('settings.publicTelemetry.budget', { value: formatDuration(FIRST_RESULT_BUDGET_MS) }) }}</p>
        </div>
        <div data-testid="cached-select-budget-card" class="dark-explicit rounded-xl border border-violet-200/70 bg-violet-50/70 p-4 dark:border-violet-400/20 dark:bg-violet-400/10">
          <div class="flex items-start justify-between gap-2">
            <p class="text-xs font-medium text-violet-800 dark:text-violet-200">{{ t('settings.publicTelemetry.cachedSelectP75') }}</p>
            <span class="rounded-full px-2 py-0.5 text-[11px] font-semibold" :class="statusClasses(cachedSelectStatus)" role="status">{{ statusLabel(cachedSelectStatus) }}</span>
          </div>
          <p class="mt-2 text-2xl font-bold text-violet-900 dark:text-violet-50">{{ formatDuration(cachedSelectP75) }}</p>
          <p class="mt-1 text-xs text-violet-700/70 dark:text-violet-200/70">{{ t('settings.publicTelemetry.cachedBudget', { value: formatDuration(CACHED_SELECT_BUDGET_MS) }) }}</p>
        </div>
      </div>

      <div class="dark-explicit overflow-hidden rounded-xl border border-slate-200/70 bg-white/90 dark:border-slate-700/60 dark:bg-slate-900/80">
        <div class="dark-explicit border-b border-slate-100 px-4 py-3 dark:border-slate-800">
          <h3 class="dark-explicit text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{{ t('settings.publicTelemetry.breakdown') }}</h3>
        </div>
        <div v-if="!visibleRows.length" class="px-4 py-10 text-center text-sm text-slate-400">{{ t('settings.publicTelemetry.empty') }}</div>
        <div v-else class="overflow-x-auto">
          <table class="min-w-full text-left text-sm">
            <thead class="dark-explicit bg-slate-50/80 text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
              <tr>
                <th class="px-4 py-3 font-medium">{{ t('settings.publicTelemetry.event') }}</th>
                <th class="px-4 py-3 font-medium">{{ t('settings.publicTelemetry.dimensions') }}</th>
                <th class="px-4 py-3 text-right font-medium">{{ t('settings.publicTelemetry.count') }}</th>
                <th class="px-4 py-3 text-right font-medium">p50</th>
                <th class="px-4 py-3 text-right font-medium">p75</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
              <tr v-for="row in visibleRows" :key="row.event_name + '-' + dimensions(row)" class="dark-explicit text-slate-700 dark:text-slate-200">
                <td class="whitespace-nowrap px-4 py-3 font-medium">{{ eventLabel(row.event_name) }}</td>
                <td class="dark-explicit whitespace-nowrap px-4 py-3 text-xs text-slate-500 dark:text-slate-400">{{ dimensions(row) }}</td>
                <td class="whitespace-nowrap px-4 py-3 text-right">{{ formatNumber(row.event_count) }}</td>
                <td class="dark-explicit whitespace-nowrap px-4 py-3 text-right text-xs text-slate-500 dark:text-slate-400">{{ formatDuration(row.p50_duration_ms) }}</td>
                <td class="dark-explicit whitespace-nowrap px-4 py-3 text-right text-xs text-slate-500 dark:text-slate-400">{{ formatDuration(row.p75_duration_ms) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="rows.length > visibleRows.length" class="dark-explicit border-t border-slate-100 px-4 py-3 text-xs text-slate-400 dark:border-slate-800">{{ t('settings.publicTelemetry.moreRows', { count: rows.length - visibleRows.length }) }}</p>
      </div>
    </template>
  </div>
</template>
