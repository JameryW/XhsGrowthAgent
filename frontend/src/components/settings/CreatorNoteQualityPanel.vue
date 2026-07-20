<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getCreatorNote,
  getCreatorNoteQuality,
  getCreatorStats,
  type CreatorNoteStats,
  type CreatorQualityReport,
} from '@/api/analytics'
import { evaluateNote } from '@/api/evaluation'
import type { EvaluationResult } from '@/types/evaluation'
import AppIcon from '@/components/AppIcon.vue'
import EvaluationRadar from '@/components/charts/EvaluationRadar.vue'
import NeonButton from '@/components/NeonButton.vue'

const props = withDefaults(defineProps<{
  accountId: string
  accountName?: string
  refreshToken?: number
  // AN-08: preselect a specific note for drill-down. When set, overrides the
  // default "first note" selection after notes load.
  noteId?: string
}>(), {
  accountName: '',
  refreshToken: 0,
  noteId: '',
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
const rqgmRunning = ref(false)
const rqgmError = ref('')
let rqgmGeneration = 0

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

function rqgmScoreTier(score: number): string {
  if (score >= 70) return 'text-emerald-600'
  if (score >= 50) return 'text-amber-600'
  return 'text-rose-600'
}

async function runRqgmEvaluation() {
  const noteId = selectedNoteId.value
  if (!props.accountId || !noteId || rqgmRunning.value) return
  const gen = ++rqgmGeneration
  rqgmRunning.value = true
  rqgmError.value = ''
  rqgmResult.value = null
  try {
    const resp = await evaluateNote(props.accountId, noteId)
    if (gen !== rqgmGeneration) return
    rqgmResult.value = resp.evaluation_result || null
  } catch (e: unknown) {
    if (gen !== rqgmGeneration) return
    rqgmError.value = e instanceof Error ? e.message : t('creatorNoteQuality.rqgm.error')
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
  errorMessage.value = ''
  if (!accountId) return

  isLoadingNotes.value = true
  try {
    const stats = await getCreatorStats(accountId, 200)
    if (generation !== requestGeneration) return
    notes.value = (stats.notes || []).filter(note => Boolean(note.note_id))
    const requested = props.noteId.trim()
    const preselect = requested
      ? (notes.value.some(n => n.note_id === requested) ? requested : '')
      : (notes.value[0]?.note_id || '')
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
  rqgmResult.value = null
  rqgmError.value = ''
  try {
    const [detail, report] = await Promise.all([
      getCreatorNote(props.accountId, noteId),
      getCreatorNoteQuality(props.accountId, noteId, locale.value),
    ])
    if (generation !== requestGeneration) return
    selectedNote.value = detail.note
    quality.value = report.quality
  } catch (error: unknown) {
    if (generation !== requestGeneration) return
    errorMessage.value = error instanceof Error
      ? error.message
      : t('creatorNoteQuality.error.description')
  } finally {
    if (generation === requestGeneration) isLoadingDetail.value = false
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
    class="min-w-0 rounded-2xl border border-violet-200/70 bg-white/95 p-4 shadow-sm backdrop-blur-sm md:p-6 dark:bg-slate-900/90 dark:border-violet-500/30"
    :aria-label="t('creatorNoteQuality.title')"
  >
    <div class="flex min-w-0 flex-col gap-2 border-b border-slate-100 pb-4 sm:flex-row sm:items-start sm:justify-between dark:border-slate-700/50">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-400 to-fuchsia-500 shadow-sm">
            <AppIcon name="FileText" size="sm" variant="white" />
          </div>
          <h3 class="text-base font-semibold text-slate-800 dark:text-slate-100">{{ t('creatorNoteQuality.title') }}</h3>
        </div>
        <p class="mt-1.5 break-words text-xs leading-relaxed text-slate-500 dark:text-slate-400">
          {{ t('creatorNoteQuality.subtitle') }}
          <span v-if="accountName || accountId" class="text-slate-500 dark:text-slate-400"> · {{ accountName || accountId }}</span>
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
      <div class="h-12 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
      <div class="h-32 animate-pulse rounded-lg bg-slate-50 dark:bg-slate-800" />
      <p class="text-center text-xs text-slate-400">{{ t('creatorNoteQuality.loading') }}</p>
    </div>

    <div v-else-if="errorMessage" class="mt-4 rounded-xl border border-rose-100 bg-rose-50/70 p-3 dark:border-rose-400/20 dark:bg-rose-400/10" aria-live="polite">
      <div class="flex min-w-0 items-start gap-2">
        <AppIcon name="AlertTriangle" size="sm" variant="pink" class="mt-0.5 shrink-0" />
        <div class="min-w-0">
          <div class="text-xs font-semibold text-rose-700 dark:text-rose-200">{{ t('creatorNoteQuality.error.title') }}</div>
          <p class="mt-1 break-words text-[11px] leading-relaxed text-rose-600 dark:text-rose-300">{{ errorMessage }}</p>
        </div>
      </div>
      <NeonButton variant="ghost" size="sm" class="mt-3 w-full sm:w-auto" @click="loadNotes()">
        <AppIcon name="RefreshCw" size="xs" variant="cyan" />
        <span>{{ t('creatorNoteQuality.error.retry') }}</span>
      </NeonButton>
    </div>

    <div v-else-if="!notes.length" class="mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50/60 p-5 text-center dark:border-slate-600 dark:bg-slate-800/50">
      <AppIcon name="Database" size="md" variant="purple" />
      <p class="mt-2 text-xs font-medium text-slate-600 dark:text-slate-300">{{ t('creatorNoteQuality.empty.title') }}</p>
      <p class="mt-1 text-[11px] leading-relaxed text-slate-400">{{ t('creatorNoteQuality.empty.description') }}</p>
    </div>

    <div v-else class="mt-4 grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(11rem,0.8fr)_minmax(0,2fr)]">
      <div class="min-w-0 rounded-xl border border-slate-100 bg-slate-50/70 p-2 dark:border-slate-700/50 dark:bg-slate-800/60">
        <div class="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          {{ t('creatorNoteQuality.listTitle') }}
        </div>
        <div class="max-h-[30rem] space-y-1 overflow-y-auto">
          <button
            v-for="note in notes"
            :key="note.note_id"
            type="button"
            class="block min-h-11 w-full min-w-0 rounded-lg px-2.5 py-2 text-left transition"
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
          <div class="h-24 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" />
          <div class="h-32 animate-pulse rounded-xl bg-slate-50 dark:bg-slate-800" />
          <p class="text-center text-xs text-slate-400">{{ t('creatorNoteQuality.loadingDetail') }}</p>
        </div>

        <div v-else-if="selectedNote" class="min-w-0 space-y-4">
          <article class="min-w-0 rounded-xl border border-slate-100 bg-white p-4 dark:bg-slate-900/80 dark:border-slate-700/50">
            <div class="flex min-w-0 flex-col gap-3 sm:flex-row">
              <img
                v-if="selectedNote.cover_url"
                :src="selectedNote.cover_url"
                :alt="selectedNote.title || t('creatorNoteQuality.untitled')"
                class="h-28 w-full shrink-0 rounded-lg object-cover sm:h-24 sm:w-24"
              />
              <div class="min-w-0 flex-1">
                <h4 class="break-words text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {{ selectedNote.title || selectedNote.note_id }}
                </h4>
                <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-slate-400">
                  <span>{{ formatDate(selectedNote.published_at) }}</span>
                  <span>{{ selectedNote.content_type || t('creatorNoteQuality.noteType') }}</span>
                  <span>{{ selectedNote.note_id }}</span>
                </div>
                <div v-if="selectedNote.tags?.length" class="mt-2 flex flex-wrap gap-1">
                  <span v-for="tag in selectedNote.tags" :key="tag" class="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] text-violet-700 dark:bg-violet-400/15 dark:text-violet-200">
                    {{ tag }}
                  </span>
                </div>
              </div>
            </div>
            <p v-if="selectedNote.body_text" class="mt-3 whitespace-pre-wrap break-words text-xs leading-6 text-slate-600 dark:text-slate-300">
              {{ selectedNote.body_text }}
            </p>
            <p v-else class="mt-3 text-[11px] leading-relaxed text-slate-400">
              {{ t('creatorNoteQuality.noBody') }}
            </p>
          </article>

          <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <div v-for="metric in metricCards" :key="metric.key" class="min-w-0 rounded-xl border border-slate-100 bg-slate-50/70 p-2.5 text-center dark:border-slate-700/50 dark:bg-slate-800/60">
              <div class="truncate text-[10px] text-slate-400">{{ metric.label }}</div>
              <div class="mt-1 truncate text-sm font-semibold text-slate-700 dark:text-slate-100">{{ metric.value }}</div>
            </div>
          </div>

          <div class="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-3">
            <div class="min-w-0 rounded-xl border border-slate-100 bg-white p-3 dark:bg-slate-900/80 dark:border-slate-700/50">
              <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.viewSources') }}</div>
              <div v-if="selectedNote.view_sources?.length" class="mt-2 space-y-1">
                <div v-for="point in selectedNote.view_sources.slice(0, 5)" :key="pointLabel(point)" class="flex min-w-0 justify-between gap-2 text-[11px]">
                  <span class="truncate text-slate-600 dark:text-slate-300">{{ pointLabel(point) }}</span>
                  <span class="shrink-0 text-violet-700 dark:text-violet-300">{{ pointValue(point) }}</span>
                </div>
              </div>
              <p v-else class="mt-2 text-[11px] text-slate-400">{{ t('creatorNoteQuality.unavailable') }}</p>
            </div>
            <div class="min-w-0 rounded-xl border border-slate-100 bg-white p-3 dark:bg-slate-900/80 dark:border-slate-700/50">
              <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.audienceProfile') }}</div>
              <div v-if="selectedNote.audience_profile?.length" class="mt-2 flex flex-wrap gap-1">
                <span v-for="point in selectedNote.audience_profile.slice(0, 8)" :key="pointLabel(point)" class="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-700 dark:bg-amber-400/15 dark:text-amber-200">
                  {{ pointLabel(point) }}<span v-if="pointValue(point)"> · {{ pointValue(point) }}</span>
                </span>
              </div>
              <p v-else class="mt-2 text-[11px] text-slate-400">{{ t('creatorNoteQuality.unavailable') }}</p>
            </div>
            <div class="min-w-0 rounded-xl border border-slate-100 bg-white p-3 dark:bg-slate-900/80 dark:border-slate-700/50">
              <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.audienceTrend') }}</div>
              <div v-if="selectedNote.audience_trend?.length" class="mt-2 space-y-1">
                <div v-for="point in selectedNote.audience_trend.slice(0, 5)" :key="pointLabel(point)" class="flex min-w-0 justify-between gap-2 text-[11px]">
                  <span class="truncate text-slate-600 dark:text-slate-300">{{ pointLabel(point) }}</span>
                  <span class="shrink-0 text-cyan-700 dark:text-cyan-300">{{ pointValue(point) }}</span>
                </div>
              </div>
              <p v-else class="mt-2 text-[11px] text-slate-400">{{ t('creatorNoteQuality.unavailable') }}</p>
            </div>
          </div>

          <section v-if="quality" class="min-w-0 rounded-xl border border-cyan-100 bg-cyan-50/40 p-4 dark:border-cyan-400/25 dark:bg-cyan-400/10">
            <div class="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div class="min-w-0">
                <div class="text-[10px] font-semibold uppercase tracking-wider text-cyan-700 dark:text-cyan-200">{{ t('creatorNoteQuality.qualityTitle') }}</div>
                <p class="mt-1 break-words text-xs leading-5 text-slate-600 dark:text-slate-300">{{ quality.summary }}</p>
              </div>
              <div class="flex shrink-0 items-end gap-2">
                <span class="text-3xl font-bold leading-none text-cyan-700 dark:text-cyan-200">{{ scoreLabel }}</span>
                <span v-if="quality.overall_score != null" class="pb-0.5 text-[10px] text-cyan-600 dark:text-cyan-300">{{ t('creatorQuality.scoreOutOf') }}</span>
              </div>
            </div>
            <div class="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-500">
              <span class="rounded-full bg-white px-2 py-1 dark:bg-slate-900/80 dark:text-slate-200">{{ translateQualityEnum('grade', quality.grade) }}</span>
              <span class="rounded-full bg-white px-2 py-1 dark:bg-slate-900/80 dark:text-slate-200">{{ translateQualityEnum('confidence', quality.confidence) }}</span>
              <span class="rounded-full bg-white px-2 py-1 dark:bg-slate-900/80 dark:text-slate-200">{{ translateQualityEnum('scope', quality.scope) }}</span>
            </div>
            <div class="mt-3 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2">
              <div v-for="dimension in quality.dimensions" :key="dimension.key" class="min-w-0 rounded-lg border border-white/80 bg-white/80 p-2.5 dark:border-slate-700/50 dark:bg-slate-900/75">
                <div class="flex min-w-0 items-center justify-between gap-2">
                  <span class="truncate text-[11px] font-semibold text-slate-700 dark:text-slate-100">{{ dimensionLabel(dimension.key) }}</span>
                  <span v-if="dimension.available !== false && !quality.insufficient_data" class="shrink-0 text-xs font-bold text-cyan-700 dark:text-cyan-300">{{ Math.round(dimension.score ?? 0) }}</span>
                  <span v-else class="shrink-0 text-[10px] text-slate-400">{{ t('creatorQuality.notScored') }}</span>
                </div>
                <p class="mt-1 break-words text-[10px] leading-4 text-slate-500 dark:text-slate-400">{{ dimension.evidence }}</p>
              </div>
            </div>
            <div v-if="visibleRecommendations.length" class="mt-3">
              <div class="text-[10px] font-semibold uppercase tracking-wider text-violet-700 dark:text-violet-200">{{ t('creatorQuality.recommendations') }}</div>
              <ol class="mt-1.5 space-y-1.5">
                <li v-for="recommendation in visibleRecommendations" :key="recommendation.priority + '-' + recommendation.dimension" class="flex min-w-0 gap-2 rounded-lg bg-white/80 p-2.5 dark:bg-slate-900/75">
                  <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-100 text-[10px] font-semibold text-violet-700 dark:bg-violet-400/20 dark:text-violet-200">{{ recommendation.priority }}</span>
                  <div class="min-w-0">
                    <div class="break-words text-[11px] font-semibold text-slate-700 dark:text-slate-100">{{ recommendation.title }}</div>
                    <p class="mt-0.5 break-words text-[10px] leading-4 text-slate-500 dark:text-slate-400">{{ recommendation.advice }}</p>
                  </div>
                </li>
              </ol>
            </div>
          </section>

          <!-- RQGM judge-panel evaluation (thread-less, manual trigger) -->
          <section class="min-w-0 rounded-xl border border-rose-100 bg-rose-50/30 p-4 dark:border-rose-400/20 dark:bg-rose-400/10">
            <div class="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div class="min-w-0">
                <div class="text-[10px] font-semibold uppercase tracking-wider text-rose-700 dark:text-rose-200">{{ t('creatorNoteQuality.rqgm.sectionTitle') }}</div>
                <p class="mt-1 break-words text-[11px] leading-4 text-slate-500 dark:text-slate-400">{{ t('creatorNoteQuality.rqgm.sectionHint') }}</p>
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
              <!-- EV-15: set expectations for manual RQGM (runtime + LLM cost). -->
              <p class="text-[11px] text-slate-400 dark:text-slate-500">{{ t('creatorNoteQuality.rqgm.costHint') }}</p>
            </div>

            <p v-if="rqgmError" class="mt-3 break-words text-[11px] leading-4 text-rose-600 dark:text-rose-300">{{ rqgmError }}</p>

            <div v-else-if="!rqgmResult && !rqgmRunning" class="mt-3 text-[11px] text-slate-400">
              {{ t('creatorNoteQuality.rqgm.empty') }}
            </div>

            <div v-if="rqgmResult" class="mt-3 space-y-3">
              <div class="flex min-w-0 flex-wrap items-end gap-2">
                <span class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.rqgm.overall') }}</span>
                <span class="text-2xl font-bold leading-none" :class="rqgmScoreTier(rqgmResult.overall_score ?? 0)">{{ rqgmScoreLabel }}</span>
                <span class="rounded-full px-2 py-0.5 text-[10px] font-semibold" :class="rqgmDecisionClass">
                  {{ rqgmDecisionLabel(rqgmResult.decision) }}
                </span>
                <p v-if="rqgmResult.summary" class="min-w-0 basis-full break-words text-[11px] leading-4 text-slate-500 dark:text-slate-400">{{ rqgmResult.summary }}</p>
              </div>

              <div v-if="rqgmResult.bias_warning" class="rounded-lg border border-amber-200 bg-amber-50/70 p-2.5 dark:border-amber-400/25 dark:bg-amber-400/10">
                <div class="flex items-center gap-1.5 text-[10px] font-semibold text-amber-700 dark:text-amber-200">
                  <AppIcon name="AlertTriangle" size="xs" variant="pink" />
                  {{ t('creatorNoteQuality.rqgm.biasTitle') }}
                </div>
                <p class="mt-1 break-words text-[11px] leading-4 text-amber-700 dark:text-amber-200">{{ rqgmResult.bias_warning }}</p>
              </div>

              <EvaluationRadar :dimensions="rqgmResult.dimensions || []" :height="240" />

              <div>
                <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.rqgm.dimensionsTitle') }}</div>
                <div class="mt-1.5 space-y-1.5">
                  <div v-for="d in rqgmResult.dimensions || []" :key="d.dimension" class="rounded-lg bg-white/80 p-2.5 dark:bg-slate-900/75">
                    <div class="flex min-w-0 items-center justify-between gap-2">
                      <span class="truncate text-[11px] font-semibold text-slate-700 dark:text-slate-100">
                        {{ rqgmDimLabel(d.dimension) }}
                        <span v-if="d.is_blocking" class="ml-1 rounded bg-rose-100 px-1 text-[9px] font-bold text-rose-700 dark:bg-rose-400/20 dark:text-rose-200">{{ t('creatorNoteQuality.rqgm.blocking') }}</span>
                      </span>
                      <span class="shrink-0 text-xs font-bold" :class="rqgmScoreTier(d.score ?? 0)">{{ (d.score ?? 0).toFixed(1) }}</span>
                    </div>
                    <p v-if="d.rationale" class="mt-1 break-words text-[10px] leading-4 text-slate-500 dark:text-slate-400">{{ d.rationale }}</p>
                    <ul v-if="d.issues?.length" class="mt-1 list-disc space-y-0.5 pl-4">
                      <li v-for="(issue, i) in d.issues" :key="i" class="break-words text-[10px] leading-4 text-slate-500 dark:text-slate-400">{{ issue }}</li>
                    </ul>
                  </div>
                </div>
              </div>

              <div v-if="rqgmResult.revision_hints?.length">
                <div class="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{{ t('creatorNoteQuality.rqgm.hintsTitle') }}</div>
                <ul class="mt-1.5 list-disc space-y-0.5 pl-4">
                  <li v-for="(h, i) in rqgmResult.revision_hints" :key="i" class="break-words text-[11px] leading-4 text-slate-600 dark:text-slate-300">{{ h }}</li>
                </ul>
              </div>
            </div>
          </section>
        </div>

        <div v-else-if="props.noteId" class="rounded-xl border border-dashed border-slate-200 bg-slate-50/70 p-5 text-center text-xs text-slate-400 dark:border-slate-700/50 dark:bg-slate-800/60">
          {{ t('creatorNoteQuality.unavailableSpecific') }}
        </div>
        <div v-else-if="selectedSummary" class="rounded-xl border border-slate-100 bg-slate-50/70 p-5 text-center text-xs text-slate-400 dark:border-slate-700/50 dark:bg-slate-800/60">
          {{ t('creatorNoteQuality.loadingDetail') }}
        </div>
      </div>
    </div>
  </section>
</template>
