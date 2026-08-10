<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import * as analyticsApi from '@/api/analytics'
import type { CreatorNoteStats, CreatorQualityReport, CreatorNotesPayload } from '@/api/analytics'
import * as evaluationApi from '@/api/evaluation'
import type { EvaluationResult } from '@/types/evaluation'
import type { EvaluationCoverage, EvaluationStatus } from '@/types/evaluation'
import AppIcon from '@/components/AppIcon.vue'
import EvaluationRadar from '@/components/charts/EvaluationRadar.vue'
import NeonButton from '@/components/NeonButton.vue'
import { SCORE_THRESHOLDS, scoreTier as scoreTierOf } from '@/constants/evaluation'
import { trackInteraction } from '@/utils/interactionTelemetry'

const props = withDefaults(defineProps<{
  accountId: string
  accountName?: string
  refreshToken?: number
  // AN-08: preselect a specific note for drill-down. When set, overrides the
  // default "first note" selection after notes load.
  noteId?: string
  /** Drawer mode: hides the chrome a host drawer already provides — the
      panel header, the account suffix, and the notes list sidebar (the host
      fixes the note being viewed). Without this the drawer rendered the full
      panel, duplicating the note title and cramming a two-column list into a
      narrow overlay. */
  compact?: boolean
}>(), {
  accountName: '',
  refreshToken: 0,
  noteId: '',
  compact: false,
})

const { t, locale } = useI18n()

const notes = ref<CreatorNoteStats[]>([])
const selectedNoteId = ref('')
const selectedNote = ref<CreatorNoteStats | null>(null)
const quality = ref<CreatorQualityReport | null>(null)
const isLoadingNotes = ref(false)
const isLoadingDetail = ref(false)
const errorMessage = ref('')
let requestGeneration = 0

// RQGM evaluation (thread-less, manual trigger — runs an LLM call per note)
const rqgmResult = ref<EvaluationResult | null>(null)
const rqgmStatus = ref<EvaluationStatus>('unavailable')
const rqgmCoverage = ref<EvaluationCoverage | null>(null)
const rqgmEvaluationId = ref<string | null>(null)
const rqgmDataAsOf = ref<string | null>(null)
const rqgmEvaluatorFingerprint = ref<string | null>(null)
const rqgmSnapshotId = ref<string | null>(null)
const rqgmThresholds = ref(SCORE_THRESHOLDS)
const rqgmRunning = ref(false)
const rqgmError = ref('')
let rqgmGeneration = 0

// EV-15: keep successful manual evaluations in this mounted panel session so
// switching between notes does not throw away a result the user may want to
// compare. The account+note key prevents a result from leaking across scopes;
// the persisted endpoint remains the source of truth after a full reload.
interface RqgmSessionSnapshot {
  result: EvaluationResult | null
  status: EvaluationStatus
  coverage: EvaluationCoverage | null
  evaluationId: string | null
  dataAsOf: string | null
  evaluatorFingerprint: string | null
  snapshotId: string | null
  thresholds: typeof SCORE_THRESHOLDS
}

const rqgmSession = new Map<string, RqgmSessionSnapshot>()

function rqgmSessionKey(noteId: string): string {
  return `${props.accountId}:${noteId}`
}

function applyRqgmSnapshot(snapshot: RqgmSessionSnapshot): void {
  rqgmResult.value = snapshot.result
    ? { ...snapshot.result, dimensions: [...snapshot.result.dimensions] }
    : null
  rqgmStatus.value = snapshot.status
  rqgmCoverage.value = snapshot.coverage
  rqgmEvaluationId.value = snapshot.evaluationId
  rqgmDataAsOf.value = snapshot.dataAsOf
  rqgmEvaluatorFingerprint.value = snapshot.evaluatorFingerprint
  rqgmSnapshotId.value = snapshot.snapshotId
  rqgmThresholds.value = snapshot.thresholds
}

function rememberRqgmSnapshot(noteId: string): void {
  if (!noteId || !rqgmResult.value) return
  rqgmSession.set(rqgmSessionKey(noteId), {
    result: { ...rqgmResult.value, dimensions: [...rqgmResult.value.dimensions] },
    status: rqgmStatus.value,
    coverage: rqgmCoverage.value,
    evaluationId: rqgmEvaluationId.value,
    dataAsOf: rqgmDataAsOf.value,
    evaluatorFingerprint: rqgmEvaluatorFingerprint.value,
    snapshotId: rqgmSnapshotId.value,
    thresholds: rqgmThresholds.value,
  })
}

function restoreRqgmSnapshot(noteId: string): boolean {
  const snapshot = rqgmSession.get(rqgmSessionKey(noteId))
  if (!snapshot) return false
  applyRqgmSnapshot(snapshot)
  return true
}

const rqgmScoreLabel = computed(() => {
  const score = rqgmResult.value?.overall_score
  return score == null ? '—' : score.toFixed(1)
})

const rqgmDecisionClass = computed(() => {
  const d = rqgmResult.value?.decision
  if (d === 'approved') return 'bg-emerald-50 text-emerald-700'
  if (d === 'needs_revision') return 'bg-amber-50 text-amber-700'
  return 'bg-rose-50 text-rose-700'
})

const RQGM_DECISION_KEYS: Record<string, string> = {
  approved: 'creatorNoteQuality.rqgm.decision.approved',
  needs_revision: 'creatorNoteQuality.rqgm.decision.needs_revision',
  rejected: 'creatorNoteQuality.rqgm.decision.rejected',
}

function rqgmDecisionLabel(decision: string): string {
  return t(RQGM_DECISION_KEYS[decision] ?? 'creatorNoteQuality.rqgm.decision.unknown')
}

function rqgmScoreTier(score: number | null | undefined): string {
  const tier = scoreTierOf(score, rqgmThresholds.value)
  if (tier === 'pass') return 'text-emerald-600'
  if (tier === 'warn') return 'text-amber-600'
  if (tier === 'fail') return 'text-rose-600'
  return 'text-slate-400'
}

const rqgmUnavailable = computed(() =>
  ['unavailable', 'degraded', 'failed', 'running'].includes(rqgmStatus.value)
  || Boolean(rqgmResult.value?.degraded)
  || (rqgmStatus.value === 'partial' && rqgmResult.value?.overall_score == null)
)

async function readNotesPage(accountId: string): Promise<CreatorNotesPayload> {
  let reader: typeof analyticsApi.getCreatorNotes | undefined
  try { reader = analyticsApi.getCreatorNotes } catch { reader = undefined }
  if (typeof reader === 'function') {
    try {
      return await reader(accountId, { limit: 50, sort: 'published_at_desc' }, { suppressToast: true })
    } catch {
      // Compatibility with older backends that only expose the bounded
      // overview endpoint.
    }
  }
  const legacy = await analyticsApi.getCreatorStats(accountId, 50)
  return {
    account_id: accountId,
    items: legacy.notes || [],
    total: legacy.total ?? legacy.notes?.length ?? 0,
    limit: legacy.limit ?? 50,
    next_cursor: null,
    data_as_of: legacy.data_as_of ?? legacy.fetched_at ?? null,
    snapshot_id: legacy.snapshot_id ?? null,
  }
}

async function runRqgmEvaluation() {
  const noteId = selectedNoteId.value
  if (!props.accountId || !noteId || rqgmRunning.value) return
  const gen = ++rqgmGeneration
  rqgmRunning.value = true
  rqgmError.value = ''
  rqgmResult.value = null
  rqgmStatus.value = 'running'
  rqgmCoverage.value = null
  rqgmEvaluationId.value = null
  rqgmEvaluatorFingerprint.value = null
  rqgmSnapshotId.value = null
  try {
    const resp = await evaluationApi.evaluateNote(props.accountId, noteId, { suppressToast: true })
    if (gen !== rqgmGeneration) return
    rqgmStatus.value = resp.status || resp.evaluation_result?.status || (resp.degraded ? 'degraded' : 'ready')
    rqgmCoverage.value = resp.coverage || resp.evaluation_result?.coverage || null
    rqgmEvaluationId.value = resp.evaluation_id || null
    rqgmDataAsOf.value = resp.data_as_of || resp.source?.data_as_of || resp.evaluated_at || null
    rqgmEvaluatorFingerprint.value = resp.evaluator_fingerprint || resp.evaluation_result?.evaluator_fingerprint || null
    rqgmSnapshotId.value = resp.snapshot_id || resp.evaluation_result?.snapshot_id || resp.source?.snapshot_id || null
    rqgmThresholds.value = resp.thresholds || SCORE_THRESHOLDS
    if (resp.cache_hit) {
      trackInteraction('quality_evaluation_cache_hit', { source: 'quality', count: 1 })
    }
    if (['degraded', 'failed', 'unavailable'].includes(rqgmStatus.value) || resp.degraded) {
      trackInteraction('quality_evaluation_degraded', { source: 'quality', count: 1 })
    }
    const next = resp.evaluation_result || null
    // Compatibility guard for old timeout responses that incorrectly carry a
    // 100/approved fallback alongside degraded=true.
    rqgmResult.value = next
      ? {
          ...next,
          overall_score: (resp.degraded || ['degraded', 'failed', 'running', 'unavailable'].includes(rqgmStatus.value)) ? null : next.overall_score,
          decision: (resp.degraded || ['degraded', 'failed', 'running', 'unavailable'].includes(rqgmStatus.value)) ? null : next.decision,
        }
      : null
    rememberRqgmSnapshot(noteId)
  } catch (e: unknown) {
    if (gen !== rqgmGeneration) return
    rqgmError.value = e instanceof Error ? e.message : t('creatorNoteQuality.rqgm.error')
    rqgmStatus.value = 'failed'
  } finally {
    if (gen === rqgmGeneration) rqgmRunning.value = false
  }
}

const selectedSummary = computed(() =>
  notes.value.find(note => note.note_id === selectedNoteId.value) || null
)

const visibleRecommendations = computed(() => [...(quality.value?.recommendations || [])]
  .sort((a, b) => a.priority - b.priority)
  .slice(0, 3))

const metricCards = computed(() => {
  const note = selectedNote.value
  if (!note) return []
  return [
    { key: 'views', label: t('creatorNoteQuality.metrics.views'), value: formatNum(note.views) },
    { key: 'likes', label: t('creatorNoteQuality.metrics.likes'), value: formatNum(note.likes) },
    { key: 'comments', label: t('creatorNoteQuality.metrics.comments'), value: formatNum(note.comments) },
    { key: 'collects', label: t('creatorNoteQuality.metrics.collects'), value: formatNum(note.collects) },
    { key: 'shares', label: t('creatorNoteQuality.metrics.shares'), value: formatNum(note.shares) },
    { key: 'rate', label: t('creatorNoteQuality.metrics.rate'), value: formatRate(note.engagement_rate) },
  ]
})

const scoreLabel = computed(() => {
  const score = quality.value?.overall_score
  return score == null ? '—' : Math.round(score).toString()
})

watch(
  () => [props.accountId, props.refreshToken, locale.value] as const,
  ([accountId]) => {
    void loadNotes(accountId)
  },
  { immediate: true }
)

// A drill-down supplies a stable note id. When that id changes while the
// drawer stays mounted, select the corresponding note or show an unavailable
// state; never retain or fall back to the first note from the account.
watch(
  () => props.noteId,
  (noteId) => {
    if (!notes.value.length) return
    const requested = noteId.trim()
    if (!requested) {
      if (!selectedNoteId.value) {
        const first = notes.value[0]?.note_id || ''
        if (first) void selectNote(first)
      }
      return
    }
    if (!notes.value.some(note => note.note_id === requested)) {
      requestGeneration += 1
      selectedNoteId.value = ''
      selectedNote.value = null
      quality.value = null
      isLoadingDetail.value = false
      errorMessage.value = ''
      rqgmGeneration += 1
      rqgmResult.value = null
      rqgmError.value = ''
      rqgmStatus.value = 'unavailable'
      rqgmCoverage.value = null
      rqgmEvaluationId.value = null
      rqgmEvaluatorFingerprint.value = null
      rqgmSnapshotId.value = null
      return
    }
    if (requested !== selectedNoteId.value) void selectNote(requested)
  },
)

async function loadNotes(accountId = props.accountId) {
  const generation = ++requestGeneration
  notes.value = []
  selectedNoteId.value = ''
  selectedNote.value = null
  quality.value = null
  rqgmGeneration += 1
  rqgmResult.value = null
  rqgmError.value = ''
  rqgmStatus.value = 'unavailable'
  rqgmCoverage.value = null
  rqgmEvaluationId.value = null
  rqgmDataAsOf.value = null
  rqgmEvaluatorFingerprint.value = null
  rqgmSnapshotId.value = null
  errorMessage.value = ''
  if (!accountId) return

  isLoadingNotes.value = true
  try {
    const stats = await readNotesPage(accountId)
    if (generation !== requestGeneration) return
    notes.value = (stats.items || []).filter(note => Boolean(note.note_id))
    const requested = props.noteId.trim()
    let preselect = requested
      ? (notes.value.some(n => n.note_id === requested) ? requested : '')
      : (notes.value[0]?.note_id || '')
    // The canonical reader is cursor-paged.  A drill-down can therefore
    // target a note beyond the first page; fetch that stable subject directly
    // instead of silently showing the first note or an unrelated empty state.
    const pageMayOmitRequested =
      Boolean(stats.next_cursor) || Number(stats.total ?? 0) > notes.value.length
    if (requested && !preselect && pageMayOmitRequested) {
      try {
        const detail = await analyticsApi.getCreatorNote(accountId, requested)
        if (generation !== requestGeneration) return
        if (detail?.note?.note_id === requested) {
          notes.value = [detail.note, ...notes.value]
          preselect = requested
        }
      } catch {
        // The requested note may have been removed or an older backend may not
        // expose direct detail reads; keep the explicit unavailable state.
      }
    }
    selectedNoteId.value = preselect
    if (selectedNoteId.value) {
      await loadSelectedNote(generation)
    }
  } catch (error: unknown) {
    if (generation !== requestGeneration) return
    errorMessage.value = error instanceof Error
      ? error.message
      : t('creatorNoteQuality.error.description')
  } finally {
    if (generation === requestGeneration) isLoadingNotes.value = false
  }
}

async function selectNote(noteId: string) {
  if (!noteId || (noteId === selectedNoteId.value && selectedNote.value?.note_id === noteId)) return
  selectedNoteId.value = noteId
  const generation = ++requestGeneration
  await loadSelectedNote(generation)
}

async function loadSelectedNote(generation = requestGeneration) {
  const noteId = selectedNoteId.value
  if (!props.accountId || !noteId) return
  isLoadingDetail.value = true
  errorMessage.value = ''
  selectedNote.value = null
  quality.value = null
  // Bump generation so any in-flight RQGM eval from the previous note no-op.
  rqgmGeneration += 1
  rqgmError.value = ''
  if (!restoreRqgmSnapshot(noteId)) {
    rqgmResult.value = null
    rqgmStatus.value = 'unavailable'
    rqgmCoverage.value = null
    rqgmEvaluationId.value = null
    rqgmDataAsOf.value = null
    rqgmEvaluatorFingerprint.value = null
    rqgmSnapshotId.value = null
    rqgmThresholds.value = SCORE_THRESHOLDS
  }
  try {
    const [detail, report] = await Promise.all([
      analyticsApi.getCreatorNote(props.accountId, noteId),
      analyticsApi.getCreatorNoteQuality(props.accountId, noteId, locale.value),
    ])
    if (generation !== requestGeneration) return
    selectedNote.value = detail.note
    quality.value = report.quality
    // Restore persisted RQGM in the background so note facts/details are not
    // blocked by an optional legacy endpoint.
    void restoreLatestEvaluation(generation, noteId)
  } catch (error: unknown) {
    if (generation !== requestGeneration) return
    errorMessage.value = error instanceof Error
      ? error.message
      : t('creatorNoteQuality.error.description')
  } finally {
    if (generation === requestGeneration) isLoadingDetail.value = false
  }
}

async function restoreLatestEvaluation(generation: number, noteId: string) {
  let latestReader: typeof evaluationApi.getLatestNoteEvaluation | undefined
  try { latestReader = evaluationApi.getLatestNoteEvaluation } catch { latestReader = undefined }
  if (typeof latestReader !== 'function') return
  try {
    const latest = await latestReader(props.accountId, noteId, { suppressToast: true })
    if (generation !== requestGeneration || !latest?.evaluation_result) return
    if (latest.stale) {
      rqgmSession.delete(rqgmSessionKey(noteId))
      rqgmStatus.value = 'unavailable'
      rqgmResult.value = null
      rqgmCoverage.value = null
      rqgmEvaluationId.value = latest.evaluation_id || null
      rqgmDataAsOf.value = latest.data_as_of || latest.source?.data_as_of || latest.evaluated_at || null
      rqgmEvaluatorFingerprint.value = latest.evaluator_fingerprint || latest.evaluation_result?.evaluator_fingerprint || null
      rqgmSnapshotId.value = latest.snapshot_id || latest.evaluation_result?.snapshot_id || latest.source?.snapshot_id || null
      rqgmThresholds.value = latest.thresholds || SCORE_THRESHOLDS
      return
    }
    rqgmStatus.value = latest.status || latest.evaluation_result.status || (latest.degraded ? 'degraded' : 'ready')
    rqgmCoverage.value = latest.coverage || latest.evaluation_result.coverage || null
    rqgmEvaluationId.value = latest.evaluation_id || null
    rqgmDataAsOf.value = latest.data_as_of || latest.source?.data_as_of || latest.evaluated_at || null
    rqgmEvaluatorFingerprint.value = latest.evaluator_fingerprint || latest.evaluation_result?.evaluator_fingerprint || null
    rqgmSnapshotId.value = latest.snapshot_id || latest.evaluation_result?.snapshot_id || latest.source?.snapshot_id || null
    rqgmThresholds.value = latest.thresholds || SCORE_THRESHOLDS
    const latestResult = latest.evaluation_result
    const unusable = Boolean(latest.degraded) || ['degraded', 'failed', 'running', 'unavailable'].includes(rqgmStatus.value)
    rqgmResult.value = {
      ...latestResult,
      overall_score: unusable ? null : latestResult.overall_score,
      decision: unusable ? null : latestResult.decision,
    }
    rememberRqgmSnapshot(noteId)
  } catch {
    // Legacy backend has no persisted run; keep the explicit empty state.
  }
}

function formatNum(value: number | undefined): string {
  return value == null ? '0' : value.toLocaleString()
}

function formatRate(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  const percent = value > 1 ? value : value * 100
  return percent.toFixed(1) + '%'
}

function formatDate(value: string | undefined): string {
  if (!value) return t('creatorNoteQuality.unknown')
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(locale.value || undefined)
}

function pointLabel(point: Record<string, unknown>): string {
  return String(
    point.title
      || point.name
      || point.label
      || point.text
      || point.dimension
      || t('creatorNoteQuality.unnamed')
  )
}

function pointValue(point: Record<string, unknown>): string {
  const value = point.value ?? point.count ?? point.rate
  if (value == null) return ''
  const numeric = Number(value)
  return Number.isFinite(numeric) ? formatNum(numeric) : String(value)
}

// Audience-profile values are audience shares (0–1), not counts: render them
// as percentages so "0.78" reads as "78%". Larger values pass through as-is.
function pointShare(point: Record<string, unknown>): string {
  const value = point.value ?? point.count ?? point.rate
  const numeric = Number(value)
  if (value != null && Number.isFinite(numeric) && numeric > 0 && numeric <= 1) {
    return `${Math.round(numeric * 100)}%`
  }
  return pointValue(point)
}

function translateQualityEnum(group: 'grade' | 'confidence' | 'scope', value: string): string {
  const key = 'creatorQuality.' + group + '.' + value
  const translated = t(key)
  return translated === key ? value : translated
}

function dimensionLabel(key: string): string {
  const translationKey = 'creatorQuality.dimension.' + key
  const translated = t(translationKey)
  return translated === translationKey ? key : translated
}

import { DIMENSION_LABEL_KEYS as RQGM_DIM_KEYS } from '@/constants/evaluation'

function rqgmDimLabel(dim: string): string {
  return t(RQGM_DIM_KEYS[dim] ?? 'evaluation.dim.unknown', { dim })
}
</script>

<template>
  <section
    class="dark-explicit min-w-0 rounded-2xl border border-violet-200/70 bg-white/95 p-4 shadow-sm backdrop-blur-sm md:p-6 dark:bg-slate-900/90 dark:border-violet-500/30"
    :aria-label="t('creatorNoteQuality.title')"
  >
    <!-- Panel chrome (title/subtitle/refresh) is omitted in compact mode:
         the host drawer supplies its own title and loading context. -->
    <div v-if="!compact" class="dark-explicit flex min-w-0 flex-col gap-2 border-b border-slate-100 pb-4 sm:flex-row sm:items-start sm:justify-between dark:border-slate-700/50">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-400 to-fuchsia-500 shadow-sm">
            <AppIcon name="FileText" size="sm" variant="white" />
          </div>
          <h3 class="dark-explicit text-base font-semibold text-slate-800 dark:text-slate-100">{{ t('creatorNoteQuality.title') }}</h3>
        </div>
        <p class="dark-explicit mt-1.5 break-words text-xs leading-relaxed text-slate-500 dark:text-slate-400">
          {{ t('creatorNoteQuality.subtitle') }}
          <span v-if="accountName || accountId" class="dark-explicit text-slate-500 dark:text-slate-400"> · {{ accountName || accountId }}</span>
        </p>
        <p class="dark-explicit mt-1 break-words text-[11px] leading-4 text-slate-400 dark:text-slate-400">
          {{ t('creatorNoteQuality.comparisonHint') }}
        </p>
      </div>
      <NeonButton
        variant="ghost"
        size="sm"
        class="w-full shrink-0 sm:w-auto"
        :disabled="isLoadingNotes || isLoadingDetail"
        :aria-label="t('creatorNoteQuality.refresh')"
        :title="t('creatorNoteQuality.refresh')"
        @click="loadNotes()"
      >
        <AppIcon name="RefreshCw" size="xs" variant="cyan" :animate="isLoadingNotes || isLoadingDetail" />
        <span>{{ t('creatorNoteQuality.refresh') }}</span>
      </NeonButton>
    </div>

    <div v-if="isLoadingNotes" class="mt-4 space-y-3" aria-live="polite">
      <div class="dark-explicit h-12 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
      <div class="dark-explicit h-32 animate-pulse rounded-lg bg-slate-50 dark:bg-slate-800" />
      <p class="text-center text-xs text-slate-400">{{ t('creatorNoteQuality.loading') }}</p>
    </div>

    <div v-else-if="errorMessage" class="dark-explicit mt-4 rounded-xl border border-rose-100 bg-rose-50/70 p-3 dark:border-rose-400/20 dark:bg-rose-400/10" aria-live="polite">
      <div class="flex min-w-0 items-start gap-2">
        <AppIcon name="AlertTriangle" size="sm" variant="pink" class="mt-0.5 shrink-0" />
        <div class="min-w-0">
          <div class="dark-explicit text-xs font-semibold text-rose-700 dark:text-rose-200">{{ t('creatorNoteQuality.error.title') }}</div>
          <p class="dark-explicit mt-1 break-words text-[11px] leading-relaxed text-rose-600 dark:text-rose-300">{{ errorMessage }}</p>
        </div>
      </div>
      <NeonButton variant="ghost" size="sm" class="mt-3 w-full sm:w-auto" @click="loadNotes()">
        <AppIcon name="RefreshCw" size="xs" variant="cyan" />
        <span>{{ t('creatorNoteQuality.error.retry') }}</span>
      </NeonButton>
    </div>

    <div v-else-if="!notes.length" class="dark-explicit mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50/60 p-5 text-center dark:border-slate-600 dark:bg-slate-800/50">
      <AppIcon name="Database" size="md" variant="purple" />
      <p class="dark-explicit mt-2 text-xs font-medium text-slate-600 dark:text-slate-300">{{ t('creatorNoteQuality.empty.title') }}</p>
      <p class="mt-1 text-[11px] leading-relaxed text-slate-400">{{ t('creatorNoteQuality.empty.description') }}</p>
    </div>

    <div v-else class="mt-4 grid min-w-0 grid-cols-1 gap-4" :class="compact ? '' : 'lg:grid-cols-[minmax(11rem,0.8fr)_minmax(0,2fr)]'">
      <!-- Note picker: hidden in compact mode, where the host drawer pins
           the note being viewed. -->
      <div v-if="!compact" class="dark-explicit min-w-0 rounded-xl border border-slate-100 bg-slate-50/70 p-2 dark:border-slate-700/50 dark:bg-slate-800/60">
        <div class="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          {{ t('creatorNoteQuality.listTitle') }}
        </div>
        <div class="max-h-[30rem] space-y-1 overflow-y-auto">
          <button
            v-for="note in notes"
            :key="note.note_id"
            type="button"
            class="dark-explicit block min-h-11 w-full min-w-0 rounded-lg px-2.5 py-2 text-left transition"
            :class="selectedNoteId === note.note_id
              ? 'bg-violet-100 text-violet-800 dark:bg-violet-400/20 dark:text-violet-100'
              : 'text-slate-600 hover:bg-white dark:text-slate-300 dark:hover:bg-slate-800'"
            :aria-pressed="selectedNoteId === note.note_id"
            @click="selectNote(note.note_id)"
          >
            <span class="block truncate text-xs font-medium">{{ note.title || note.note_id }}</span>
            <span class="mt-0.5 block text-[10px] text-slate-400">
              {{ formatRate(note.engagement_rate) }} · {{ formatDate(note.published_at) }}
            </span>
          </button>
        </div>
      </div>

      <div class="min-w-0">
        <div v-if="isLoadingDetail" class="space-y-3" aria-live="polite">
          <div class="dark-explicit h-24 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" />
          <div class="dark-explicit h-32 animate-pulse rounded-xl bg-slate-50 dark:bg-slate-800" />
          <p class="text-center text-xs text-slate-400">{{ t('creatorNoteQuality.loadingDetail') }}</p>
        </div>

        <div v-else-if="selectedNote" class="min-w-0 space-y-4">
          <article class="dark-explicit min-w-0 rounded-xl border border-slate-100 bg-white p-4 dark:bg-slate-900/80 dark:border-slate-700/50">
            <div class="flex min-w-0 flex-col gap-3 sm:flex-row">
              <img
                v-if="selectedNote.cover_url"
                :src="selectedNote.cover_url"
                :alt="selectedNote.title || t('creatorNoteQuality.untitled')"
                class="h-28 w-full shrink-0 rounded-lg object-cover sm:h-24 sm:w-24"
              />
              <div class="min-w-0 flex-1">
                <!-- Title omitted in compact mode: the host drawer header
                     already shows it. -->
                <h4 v-if="!compact" class="dark-explicit break-words text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {{ selectedNote.title || selectedNote.note_id }}
                </h4>
                <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-400">
                  <span>{{ formatDate(selectedNote.published_at) }}</span>
                  <span>{{ selectedNote.content_type || t('creatorNoteQuality.noteType') }}</span>
                  <span>{{ selectedNote.note_id }}</span>
                  <span v-if="selectedNote.synced_at">{{ t('evaluation.dataAsOf') }} {{ formatDate(selectedNote.synced_at) }}</span>
                </div>
                <div v-if="selectedNote.tags?.length" class="mt-2 flex flex-wrap gap-1">
                  <span v-for="tag in selectedNote.tags" :key="tag" class="dark-explicit rounded-full bg-violet-50 px-2 py-0.5 text-[10px] text-violet-700 dark:bg-violet-400/15 dark:text-violet-200">
                    {{ tag }}
                  </span>
                </div>
              </div>
            </div>
            <p v-if="selectedNote.body_text" class="dark-explicit mt-3 whitespace-pre-wrap break-words text-xs leading-6 text-slate-600 dark:text-slate-300">
              {{ selectedNote.body_text }}
            </p>
            <p v-else class="mt-3 text-[11px] leading-relaxed text-slate-400">
              {{ t('creatorNoteQuality.noBody') }}
            </p>
          </article>

          <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <div v-for="metric in metricCards" :key="metric.key" class="dark-explicit min-w-0 rounded-xl border border-slate-100 bg-slate-50/70 p-2.5 text-center dark:border-slate-700/50 dark:bg-slate-800/60">
              <div class="truncate text-[10px] text-slate-400">{{ metric.label }}</div>
              <div class="dark-explicit mt-1 truncate text-sm font-semibold text-slate-700 dark:text-slate-100">{{ metric.value }}</div>
            </div>
          </div>

          <div class="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-3">
            <div class="dark-explicit min-w-0 rounded-xl border border-slate-100 bg-white p-3 dark:bg-slate-900/80 dark:border-slate-700/50">
              <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.viewSources') }}</div>
              <div v-if="selectedNote.view_sources?.length" class="mt-2 space-y-1">
                <div v-for="point in selectedNote.view_sources.slice(0, 5)" :key="pointLabel(point)" class="flex min-w-0 justify-between gap-2 text-[11px]">
                  <span class="dark-explicit truncate text-slate-600 dark:text-slate-300">{{ pointLabel(point) }}</span>
                  <span class="dark-explicit shrink-0 text-violet-700 dark:text-violet-300">{{ pointValue(point) }}</span>
                </div>
              </div>
              <p v-else class="mt-2 text-[11px] text-slate-400">{{ t('creatorNoteQuality.unavailable') }}</p>
            </div>
            <div class="dark-explicit min-w-0 rounded-xl border border-slate-100 bg-white p-3 dark:bg-slate-900/80 dark:border-slate-700/50">
              <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.audienceProfile') }}</div>
              <div v-if="selectedNote.audience_profile?.length" class="mt-2 flex flex-wrap gap-1">
                <span v-for="point in selectedNote.audience_profile.slice(0, 8)" :key="pointLabel(point)" class="dark-explicit rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-700 dark:bg-amber-400/15 dark:text-amber-200">
                  {{ pointLabel(point) }}<span v-if="pointValue(point)"> · {{ pointShare(point) }}</span>
                </span>
              </div>
              <p v-else class="mt-2 text-[11px] text-slate-400">{{ t('creatorNoteQuality.unavailable') }}</p>
            </div>
            <div class="dark-explicit min-w-0 rounded-xl border border-slate-100 bg-white p-3 dark:bg-slate-900/80 dark:border-slate-700/50">
              <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.audienceTrend') }}</div>
              <div v-if="selectedNote.audience_trend?.length" class="mt-2 space-y-1">
                <div v-for="point in selectedNote.audience_trend.slice(0, 5)" :key="pointLabel(point)" class="flex min-w-0 justify-between gap-2 text-[11px]">
                  <span class="dark-explicit truncate text-slate-600 dark:text-slate-300">{{ pointLabel(point) }}</span>
                  <span class="dark-explicit shrink-0 text-cyan-700 dark:text-cyan-300">{{ pointValue(point) }}</span>
                </div>
              </div>
              <p v-else class="mt-2 text-[11px] text-slate-400">{{ t('creatorNoteQuality.unavailable') }}</p>
            </div>
          </div>

          <section v-if="quality" class="dark-explicit min-w-0 rounded-xl border border-cyan-100 bg-cyan-50/40 p-4 dark:border-cyan-400/25 dark:bg-cyan-400/10">
            <div class="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div class="min-w-0">
                <div class="dark-explicit text-[10px] font-semibold uppercase tracking-wider text-cyan-700 dark:text-cyan-200">{{ t('evaluation.performanceScoreLabel') }}</div>
                <p class="dark-explicit mt-1 break-words text-xs leading-5 text-slate-600 dark:text-slate-300">{{ quality.summary }}</p>
              </div>
              <div class="flex shrink-0 items-end gap-2">
                <span class="dark-explicit text-3xl font-bold leading-none text-cyan-700 dark:text-cyan-200">{{ scoreLabel }}</span>
                <span v-if="quality.overall_score != null" class="dark-explicit pb-0.5 text-[10px] text-cyan-600 dark:text-cyan-300">{{ t('creatorQuality.scoreOutOf') }}</span>
              </div>
            </div>
            <div class="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
              <span class="dark-explicit rounded-full bg-white px-2 py-1 dark:bg-slate-900/80 dark:text-slate-200">{{ translateQualityEnum('grade', quality.grade) }}</span>
              <span class="dark-explicit rounded-full bg-white px-2 py-1 dark:bg-slate-900/80 dark:text-slate-200">{{ translateQualityEnum('confidence', quality.confidence) }}</span>
              <span class="dark-explicit rounded-full bg-white px-2 py-1 dark:bg-slate-900/80 dark:text-slate-200">{{ translateQualityEnum('scope', quality.scope) }}</span>
              <span v-if="quality.status" class="dark-explicit rounded-full bg-white px-2 py-1 dark:bg-slate-900/80 dark:text-slate-200">{{ quality.status }}</span>
              <span v-if="quality.data_as_of" class="dark-explicit rounded-full bg-white px-2 py-1 dark:bg-slate-900/80 dark:text-slate-200">{{ t('evaluation.dataAsOf') }} {{ formatDate(quality.data_as_of) }}</span>
            </div>
            <div class="mt-3 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
              <div v-for="dimension in quality.dimensions" :key="dimension.key" class="dark-explicit min-w-0 rounded-lg border border-white/80 bg-white/80 p-2.5 dark:border-slate-700/50 dark:bg-slate-900/75">
                <div class="flex min-w-0 items-center justify-between gap-2">
                  <span class="dark-explicit truncate text-[11px] font-semibold text-slate-700 dark:text-slate-100">{{ dimensionLabel(dimension.key) }}</span>
                  <span v-if="dimension.available !== false && !quality.insufficient_data && dimension.score != null" class="dark-explicit shrink-0 text-xs font-bold text-cyan-700 dark:text-cyan-300">{{ Math.round(dimension.score) }}</span>
                  <span v-else class="shrink-0 text-[10px] text-slate-400">{{ t('creatorQuality.notScored') }}</span>
                </div>
                <p class="dark-explicit mt-1 break-words text-[10px] leading-4 text-slate-500 dark:text-slate-400">{{ dimension.evidence }}</p>
              </div>
            </div>
            <div v-if="visibleRecommendations.length" class="mt-3">
              <div class="dark-explicit text-[10px] font-semibold uppercase tracking-wider text-violet-700 dark:text-violet-200">{{ t('creatorQuality.recommendations') }}</div>
              <ol class="mt-1.5 space-y-1.5">
                <li v-for="recommendation in visibleRecommendations" :key="recommendation.priority + '-' + recommendation.dimension" class="dark-explicit flex min-w-0 gap-2 rounded-lg bg-white/80 p-2.5 dark:bg-slate-900/75">
                  <span class="dark-explicit flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-100 text-[10px] font-semibold text-violet-700 dark:bg-violet-400/20 dark:text-violet-200">{{ recommendation.priority }}</span>
                  <div class="min-w-0">
                    <div class="dark-explicit break-words text-[11px] font-semibold text-slate-700 dark:text-slate-100">{{ recommendation.title }}</div>
                    <p class="dark-explicit mt-0.5 break-words text-[10px] leading-4 text-slate-500 dark:text-slate-400">{{ recommendation.advice }}</p>
                  </div>
                </li>
              </ol>
            </div>
          </section>

          <!-- RQGM judge-panel evaluation (thread-less, manual trigger) -->
          <section class="dark-explicit min-w-0 rounded-xl border border-rose-100 bg-rose-50/30 p-4 dark:border-rose-400/20 dark:bg-rose-400/10">
            <div class="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div class="min-w-0">
                <div class="dark-explicit text-[10px] font-semibold uppercase tracking-wider text-rose-700 dark:text-rose-200">{{ t('evaluation.rqgmScoreLabel') }}</div>
                <p class="dark-explicit mt-1 break-words text-[11px] leading-4 text-slate-500 dark:text-slate-400">{{ t('creatorNoteQuality.rqgm.sectionHint') }}</p>
                <!-- EV-15: set expectations for manual RQGM (runtime + LLM
                     cost). Kept inside the text block: as a third flex item
                     it was squeezed into a vertical strip in narrow drawers. -->
                <p class="dark-explicit mt-1 break-words text-[11px] leading-4 text-slate-400 dark:text-slate-400">{{ t('creatorNoteQuality.rqgm.costHint') }}</p>
              </div>
              <NeonButton
                variant="ghost"
                size="sm"
                class="shrink-0"
                :loading="rqgmRunning"
                :disabled="!selectedNoteId"
                @click="runRqgmEvaluation"
              >
                <AppIcon name="Sparkles" size="xs" variant="cyan" />
                <span>{{ rqgmRunning ? t('creatorNoteQuality.rqgm.running') : t('creatorNoteQuality.rqgm.run') }}</span>
              </NeonButton>
            </div>

            <p v-if="rqgmError" class="dark-explicit mt-3 break-words text-[11px] leading-4 text-rose-600 dark:text-rose-300">{{ rqgmError }}</p>

            <div v-else-if="rqgmStatus === 'degraded' || rqgmStatus === 'failed' || rqgmStatus === 'unavailable' || rqgmStatus === 'running'" class="dark-explicit mt-3 rounded-lg border border-amber-200 bg-amber-50/70 p-3 text-[11px] leading-4 text-amber-700 dark:border-amber-400/25 dark:bg-amber-400/10 dark:text-amber-200" role="status">
              {{ t('creatorNoteQuality.rqgm.notReady') }}
              <button type="button" class="dark-explicit ml-2 min-h-9 rounded-md border border-amber-300 px-2 py-1 font-semibold hover:bg-amber-100 dark:border-amber-300/40 dark:hover:bg-amber-400/20" @click="runRqgmEvaluation">{{ t('creatorNoteQuality.rqgm.retry') }}</button>
            </div>
            <div v-else-if="rqgmStatus === 'partial'" class="dark-explicit mt-3 rounded-lg border border-sky-200 bg-sky-50/70 p-3 text-[11px] leading-4 text-sky-700 dark:border-sky-400/25 dark:bg-sky-400/10 dark:text-sky-200" role="status">
              {{ t('creatorNoteQuality.rqgm.partial') }}<span v-if="rqgmCoverage?.weighted_ratio != null"> ({{ Math.round(rqgmCoverage.weighted_ratio * 100) }}%)</span>
            </div>

            <div v-else-if="!rqgmResult && !rqgmRunning" class="mt-3 text-[11px] text-slate-400">
              {{ t('creatorNoteQuality.rqgm.empty') }}
            </div>

            <div v-if="rqgmResult" class="mt-3 space-y-3">
              <div class="flex min-w-0 flex-wrap items-end gap-2">
                <span class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('evaluation.rqgmScoreLabel') }}</span>
                <span class="text-2xl font-bold leading-none" :class="rqgmScoreTier(rqgmResult.overall_score ?? null)">{{ rqgmUnavailable ? '—' : rqgmScoreLabel }}</span>
                <span v-if="!rqgmUnavailable" class="rounded-full px-2 py-0.5 text-[10px] font-semibold" :class="rqgmDecisionClass">
                  {{ rqgmDecisionLabel(rqgmResult.decision || 'unknown') }}
                </span>
                <p v-if="rqgmResult.summary" class="dark-explicit min-w-0 basis-full break-words text-[11px] leading-4 text-slate-500 dark:text-slate-400">{{ rqgmResult.summary }}</p>
              </div>

              <div v-if="rqgmResult.bias_warning" class="dark-explicit rounded-lg border border-amber-200 bg-amber-50/70 p-2.5 dark:border-amber-400/25 dark:bg-amber-400/10">
                <div class="dark-explicit flex items-center gap-1.5 text-[10px] font-semibold text-amber-700 dark:text-amber-200">
                  <AppIcon name="AlertTriangle" size="xs" variant="pink" />
                  {{ t('creatorNoteQuality.rqgm.biasTitle') }}
                </div>
                <p class="dark-explicit mt-1 break-words text-[11px] leading-4 text-amber-700 dark:text-amber-200">{{ rqgmResult.bias_warning }}</p>
              </div>

              <EvaluationRadar :dimensions="rqgmResult.dimensions || []" :height="240" />

              <div>
                <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.rqgm.dimensionsTitle') }}</div>
                <div class="mt-1.5 space-y-1.5">
                  <div v-for="d in rqgmResult.dimensions || []" :key="d.dimension" class="dark-explicit rounded-lg bg-white/80 p-2.5 dark:bg-slate-900/75">
                    <div class="flex min-w-0 items-center justify-between gap-2">
                      <span class="dark-explicit truncate text-[11px] font-semibold text-slate-700 dark:text-slate-100">
                        {{ rqgmDimLabel(d.dimension) }}
                        <span v-if="d.is_blocking" class="dark-explicit ml-1 rounded bg-rose-100 px-1 text-[9px] font-bold text-rose-700 dark:bg-rose-400/20 dark:text-rose-200">{{ t('creatorNoteQuality.rqgm.blocking') }}</span>
                      </span>
                      <span class="shrink-0 text-xs font-bold" :class="rqgmScoreTier(d.score)" >{{ d.available === false || d.score == null ? '—' : d.score.toFixed(1) }}</span>
                    </div>
                    <p v-if="d.rationale" class="dark-explicit mt-1 break-words text-[10px] leading-4 text-slate-500 dark:text-slate-400">{{ d.rationale }}</p>
                    <ul v-if="d.issues?.length" class="mt-1 list-disc space-y-0.5 pl-4">
                      <li v-for="(issue, i) in d.issues" :key="i" class="dark-explicit break-words text-[10px] leading-4 text-slate-500 dark:text-slate-400">{{ issue }}</li>
                    </ul>
                  </div>
                </div>
              </div>

              <div v-if="rqgmEvaluationId || rqgmDataAsOf || rqgmEvaluatorFingerprint || rqgmSnapshotId" class="text-[10px] text-slate-400">
                <span v-if="rqgmEvaluationId">{{ t('evaluation.evaluationId') }}: {{ rqgmEvaluationId }}</span>
                <span v-if="rqgmDataAsOf"> · {{ t('evaluation.dataAsOf') }} {{ rqgmDataAsOf }}</span>
                <span v-if="rqgmEvaluatorFingerprint"> · {{ t('evaluation.evaluatorFingerprint') }} {{ rqgmEvaluatorFingerprint }}</span>
                <span v-if="rqgmSnapshotId"> · {{ t('evaluation.snapshotId') }} {{ rqgmSnapshotId }}</span>
              </div>

              <div v-if="rqgmResult.revision_hints?.length">
                <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.rqgm.hintsTitle') }}</div>
                <ul class="mt-1.5 list-disc space-y-0.5 pl-4">
                  <li v-for="(h, i) in rqgmResult.revision_hints" :key="i" class="dark-explicit break-words text-[11px] leading-4 text-slate-600 dark:text-slate-300">{{ h }}</li>
                </ul>
              </div>
            </div>
          </section>
        </div>

        <div v-else-if="props.noteId" class="dark-explicit rounded-xl border border-dashed border-slate-200 bg-slate-50/70 p-5 text-center text-xs text-slate-400 dark:border-slate-700/50 dark:bg-slate-800/60">
          {{ t('creatorNoteQuality.unavailableSpecific') }}
        </div>
        <div v-else-if="selectedSummary" class="dark-explicit rounded-xl border border-slate-100 bg-slate-50/70 p-5 text-center text-xs text-slate-400 dark:border-slate-700/50 dark:bg-slate-800/60">
          {{ t('creatorNoteQuality.loadingDetail') }}
        </div>
      </div>
    </div>
  </section>
</template>
