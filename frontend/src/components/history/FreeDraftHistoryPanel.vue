<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import NeonButton from '@/components/NeonButton.vue'
import StatusFilterBar from '@/components/StatusFilterBar.vue'
import { deleteFreeDraft, listFreeDrafts, type FreeDraftStatus, type FreeDraftSummary } from '@/api/free'
import { useToastStore } from '@/stores'

const props = defineProps<{
  accountId: string | null
}>()

const { t, locale } = useI18n()
const router = useRouter()
const toastStore = useToastStore()
const emit = defineEmits<{
  (event: 'count-change', count: number): void
}>()

const drafts = ref<FreeDraftSummary[]>([])
const isLoading = ref(false)
const isRefreshing = ref(false)
const error = ref<string | null>(null)
const responseTruncated = ref(false)
const searchQuery = ref('')
const statusFilter = ref<FreeDraftStatus>('all')
const deleteTarget = ref<FreeDraftSummary | null>(null)
const isDeleting = ref(false)

let requestGeneration = 0
let listAbort: AbortController | null = null

const statusOptions = computed(() => {
  const countFor = (status: FreeDraftStatus) => drafts.value.filter(draftMatchesStatus(status)).length
  return [
    { value: 'all', label: t('history.freeDrafts.filterAll'), count: drafts.value.length },
    { value: 'unpublished', label: t('history.freeDrafts.filterUnpublished'), count: countFor('unpublished') },
    { value: 'published', label: t('history.freeDrafts.filterPublished'), count: countFor('published') },
    { value: 'publish_failed', label: t('history.freeDrafts.filterPublishFailed'), count: countFor('publish_failed') },
    { value: 'evaluated', label: t('history.freeDrafts.filterEvaluated'), count: countFor('evaluated') },
    { value: 'unevaluated', label: t('history.freeDrafts.filterUnevaluated'), count: countFor('unevaluated') },
  ]
})

const overviewStats = computed(() => [
  { label: t('history.freeDrafts.overviewShown'), value: drafts.value.length },
  { label: t('history.freeDrafts.overviewPublished'), value: drafts.value.filter(draft => Boolean(draft.published)).length },
  { label: t('history.freeDrafts.overviewAttention'), value: drafts.value.filter(needsAttention).length },
])

const filteredDrafts = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase(locale.value || 'en')
  return drafts.value.filter((draft) => {
    if (!draftMatchesStatus(statusFilter.value)(draft)) return false
    return !query || draft.title.toLocaleLowerCase(locale.value || 'en').includes(query)
  })
})

const hasActiveFilter = computed(() => Boolean(searchQuery.value.trim()) || statusFilter.value !== 'all')

function draftMatchesStatus(status: FreeDraftStatus) {
  return (draft: FreeDraftSummary) => {
    if (status === 'all') return true
    if (status === 'published') return Boolean(draft.published)
    if (status === 'unpublished') return !draft.published
    if (status === 'publish_failed') return publishFailed(draft)
    if (status === 'evaluated') return Boolean(draft.last_evaluation)
    if (status === 'unevaluated') return !draft.last_evaluation
    return true
  }
}

const PUBLISH_SUCCESS_STATUSES = new Set(['published', 'mock_published'])

function publishFailed(draft: FreeDraftSummary) {
  const status = draft.last_publish?.status?.trim()
  return Boolean(status && !PUBLISH_SUCCESS_STATUSES.has(status))
}

function needsAttention(draft: FreeDraftSummary) {
  if (publishFailed(draft)) return true
  if (draft.published) return false
  const evaluation = draft.last_evaluation
  if (!evaluation || evaluation.degraded) return true
  return evaluation.decision !== 'approved'
}

function publishFailureReason(draft: FreeDraftSummary) {
  return draft.last_publish?.error_type || draft.last_publish?.status || t('history.freeDrafts.publishFailed')
}

function actionLabel(draft: FreeDraftSummary) {
  if (publishFailed(draft)) return t('history.freeDrafts.retryPublish')
  if (draft.published) return t('history.freeDrafts.openDraft')
  if (draft.last_evaluation && !draft.last_evaluation.degraded && draft.last_evaluation.decision !== 'approved') {
    return t('history.freeDrafts.reviewDraft')
  }
  return t('history.freeDrafts.continueWriting')
}

function formatDate(iso?: string | null) {
  if (!iso) return t('history.freeDrafts.unavailable')
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return t('history.freeDrafts.unavailable')
  return date.toLocaleString(locale.value || 'en', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function excerpt(draft: FreeDraftSummary) {
  const summary = draft.last_evaluation?.summary?.trim()
  if (summary) return summary
  if (draft.hashtags.length) return draft.hashtags.join(' ')
  return t('history.freeDrafts.excerptUnavailable')
}

function decisionLabel(decision?: string | null) {
  if (!decision) return t('history.freeDrafts.evaluationUnavailable')
  const key = `history.freeDrafts.decision.${decision}`
  const translated = t(key)
  return translated === key ? decision : translated
}

function evaluationClass(decision?: string | null, degraded?: boolean) {
  if (degraded) return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-500/30'
  if (decision === 'approved') return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:border-emerald-500/30'
  if (decision === 'rejected') return 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:border-rose-500/30'
  return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-500/30'
}

function hasUsableEvaluation(evaluation?: FreeDraftSummary['last_evaluation'] | null) {
  return Boolean(
    evaluation
    && !evaluation.degraded
    && typeof evaluation.overall_score === 'number'
    && Number.isFinite(evaluation.overall_score),
  )
}

/** Number of creative-memory anchors on a draft (style/play/materials). */
function anchorCount(draft: FreeDraftSummary): number {
  return (draft.style_id ? 1 : 0)
    + (draft.play_id ? 1 : 0)
    + (draft.material_ids?.length ?? 0)
}

/** Tooltip listing the anchored ids (task 08-26-free-anchor-display). */
function anchorTooltip(draft: FreeDraftSummary): string {
  const parts: string[] = []
  if (draft.style_id) parts.push(t('history.freeDrafts.anchorStyle', { id: draft.style_id }))
  if (draft.play_id) parts.push(t('history.freeDrafts.anchorPlay', { id: draft.play_id }))
  for (const mid of draft.material_ids ?? []) parts.push(t('history.freeDrafts.anchorMaterial', { id: mid }))
  return parts.join(' · ')
}

function isAbortError(err: unknown) {
  if (!err || typeof err !== 'object') return false
  const candidate = err as { code?: string; name?: string }
  return candidate.code === 'ERR_CANCELED' || candidate.name === 'CanceledError' || candidate.name === 'AbortError'
}

async function refresh() {
  const generation = ++requestGeneration
  listAbort?.abort()
  listAbort = null

  const accountId = props.accountId
  if (!accountId) {
    drafts.value = []
    responseTruncated.value = false
    error.value = null
    isLoading.value = false
    isRefreshing.value = false
    emit('count-change', 0)
    return
  }

  const abort = new AbortController()
  listAbort = abort
  const soft = drafts.value.length > 0
  if (soft) isRefreshing.value = true
  else isLoading.value = true
  error.value = null

  try {
    const response = await listFreeDrafts(accountId, { status: 'all' }, {
      signal: abort.signal,
      suppressToast: true,
    })
    if (generation !== requestGeneration || props.accountId !== accountId) return
    drafts.value = response.drafts ?? []
    responseTruncated.value = Boolean(response.truncated)
    emit('count-change', response.count ?? drafts.value.length)
  } catch (err: unknown) {
    if (generation !== requestGeneration || isAbortError(err)) return
    error.value = err instanceof Error ? err.message : t('history.freeDrafts.loadError')
    responseTruncated.value = false
  } finally {
    if (generation === requestGeneration) {
      isLoading.value = false
      isRefreshing.value = false
    }
  }
}

function continueDraft(draftId: string) {
  if (!props.accountId) return
  void router.push({
    name: 'tui',
    query: {
      mode: 'free',
      account_id: props.accountId,
      draft_id: draftId,
    },
  })
}

function newDraft() {
  if (!props.accountId) return
  void router.push({
    name: 'tui',
    query: { mode: 'free', account_id: props.accountId },
  })
}

function requestDelete(draft: FreeDraftSummary) {
  deleteTarget.value = draft
}

async function confirmDelete() {
  const target = deleteTarget.value
  const accountId = props.accountId
  if (!target || !accountId || isDeleting.value) return

  const deletionGeneration = requestGeneration
  isDeleting.value = true
  try {
    await deleteFreeDraft(accountId, target.draft_id, { suppressToast: true })
    if (deletionGeneration !== requestGeneration || props.accountId !== accountId) return
    drafts.value = drafts.value.filter(draft => draft.draft_id !== target.draft_id)
    emit('count-change', Math.max(0, drafts.value.length))
    toastStore.success(t('history.freeDrafts.deleteSuccess'), target.title || target.draft_id)
  } catch (err: unknown) {
    toastStore.error(t('history.freeDrafts.deleteError'), err instanceof Error ? err.message : undefined)
  } finally {
    isDeleting.value = false
    deleteTarget.value = null
  }
}

watch(() => props.accountId, () => {
  statusFilter.value = 'all'
  searchQuery.value = ''
  void refresh()
}, { immediate: true })

onUnmounted(() => {
  requestGeneration++
  listAbort?.abort()
})

defineExpose({ refresh })
</script>

<template>
  <section class="space-y-4" data-testid="free-draft-history-panel" aria-labelledby="free-drafts-heading">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p class="dark-explicit text-xs font-semibold uppercase tracking-[0.16em] text-violet-600 dark:text-violet-300">{{ t('history.freeDrafts.eyebrow') }}</p>
        <h2 id="free-drafts-heading" class="dark-explicit mt-1 text-lg font-semibold text-slate-800 dark:text-slate-100">{{ t('history.freeDrafts.title') }}</h2>
        <p class="dark-explicit mt-1 text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.subtitle') }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <NeonButton v-if="accountId" variant="cyan" size="sm" class="min-h-11" @click="newDraft">
          <AppIcon name="Plus" size="sm" variant="cyan" />
          <span>{{ t('history.freeDrafts.newDraft') }}</span>
        </NeonButton>
        <NeonButton variant="ghost" size="sm" class="min-h-11" :loading="isLoading || isRefreshing" @click="refresh">
          <AppIcon name="RefreshCw" size="sm" variant="cyan" />
          <span>{{ t('history.freeDrafts.refresh') }}</span>
        </NeonButton>
      </div>
    </div>

    <div v-if="!accountId" class="dark-explicit rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 p-6 text-center dark:border-slate-700 dark:bg-slate-900/40" data-testid="free-drafts-no-account">
      <AppIcon name="Link" size="lg" variant="muted" />
      <h3 class="dark-explicit mt-3 text-base font-semibold text-slate-700 dark:text-slate-200">{{ t('history.freeDrafts.noAccountTitle') }}</h3>
      <p class="dark-explicit mt-1 text-sm text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.noAccountDescription') }}</p>
    </div>

    <template v-else>
      <div v-if="drafts.length" class="grid grid-cols-1 gap-2 sm:grid-cols-3" data-testid="free-draft-overview" :aria-label="t('history.freeDrafts.overviewLabel')">
        <div v-for="stat in overviewStats" :key="stat.label" class="dark-explicit rounded-xl border border-slate-200/80 bg-white/70 px-3 py-2.5 dark:border-slate-700 dark:bg-slate-900/60">
          <p class="dark-explicit text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">{{ stat.label }}</p>
          <p class="dark-explicit mt-1 text-lg font-semibold tabular-nums text-slate-800 dark:text-slate-100">{{ stat.value }}</p>
        </div>
        <p v-if="responseTruncated" class="dark-explicit col-span-full text-[11px] text-slate-400">{{ t('history.freeDrafts.overviewCapped') }}</p>
      </div>

      <div class="flex flex-col gap-3 md:flex-row md:items-center">
        <label class="relative min-w-0 flex-1">
          <span class="sr-only">{{ t('history.freeDrafts.searchLabel') }}</span>
          <AppIcon name="Search" size="sm" variant="muted" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" aria-hidden="true" />
          <input
            v-model="searchQuery"
            type="search"
            class="dark-explicit min-h-11 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm text-slate-700 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
            :placeholder="t('history.freeDrafts.searchPlaceholder')"
          />
        </label>
      </div>

      <StatusFilterBar
        :label="t('history.freeDrafts.filterLabel')"
        :options="statusOptions"
        :model-value="statusFilter"
        @update:model-value="statusFilter = $event as FreeDraftStatus"
      />

      <div v-if="isLoading" class="space-y-3" data-testid="free-drafts-loading" aria-busy="true">
        <div v-for="i in 3" :key="i" class="dark-explicit h-32 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800" />
      </div>

      <div v-else-if="error" class="dark-explicit rounded-2xl border border-rose-200 bg-rose-50/70 p-6 text-center dark:border-rose-500/30 dark:bg-rose-950/25" data-testid="free-drafts-error" role="alert">
        <AppIcon name="AlertTriangle" size="lg" variant="pink" />
        <p class="mt-2 text-sm text-rose-700 dark:text-rose-200">{{ error }}</p>
        <NeonButton variant="ghost" size="sm" class="mt-3 min-h-11" @click="refresh">{{ t('common.retry') }}</NeonButton>
      </div>

      <div v-else-if="drafts.length === 0" class="dark-explicit rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 p-8 text-center dark:border-slate-700 dark:bg-slate-900/40" data-testid="free-drafts-empty">
        <AppIcon name="FileText" size="xl" variant="cyan" />
        <h3 class="dark-explicit mt-3 text-base font-semibold text-slate-700 dark:text-slate-200">{{ t('history.freeDrafts.emptyTitle') }}</h3>
        <p class="dark-explicit mx-auto mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.emptyDescription') }}</p>
        <NeonButton variant="cyan" size="sm" class="mt-4 min-h-11" @click="newDraft">
          <AppIcon name="Plus" size="sm" variant="cyan" />
          <span>{{ t('history.freeDrafts.emptyAction') }}</span>
        </NeonButton>
      </div>

      <div v-else-if="filteredDrafts.length === 0" class="dark-explicit rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 p-8 text-center dark:border-slate-700 dark:bg-slate-900/40" data-testid="free-drafts-filter-empty">
        <AppIcon name="SearchX" size="lg" variant="muted" />
        <p class="dark-explicit mt-2 text-sm text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.filterEmpty') }}</p>
        <NeonButton v-if="hasActiveFilter" variant="ghost" size="sm" class="mt-3 min-h-11" @click="searchQuery = ''; statusFilter = 'all'">{{ t('history.freeDrafts.clearFilters') }}</NeonButton>
      </div>

      <div v-else class="space-y-3" data-testid="free-drafts-list" :class="isRefreshing ? 'opacity-75' : 'opacity-100'">
        <article
          v-for="draft in filteredDrafts"
          :key="draft.draft_id"
          class="dark-explicit rounded-2xl border border-slate-200/80 bg-white/75 p-4 shadow-sm transition hover:border-violet-300 hover:shadow-md dark:border-slate-700 dark:bg-slate-900/65 dark:hover:border-violet-500/50"
          :aria-labelledby="`free-draft-${draft.draft_id}`"
        >
          <div class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <h3 :id="`free-draft-${draft.draft_id}`" class="dark-explicit min-w-0 truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{{ draft.title || t('history.freeDrafts.untitled') }}</h3>
                <span class="dark-explicit rounded-full border px-2 py-0.5 text-[10px] font-medium" :class="draft.published ? 'border-teal-200 bg-teal-50 text-teal-700 dark:border-teal-500/30 dark:bg-teal-950/40 dark:text-teal-200' : 'border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300'">
                  {{ draft.published ? t('history.freeDrafts.published') : t('history.freeDrafts.unpublished') }}
                </span>
                <span v-if="publishFailed(draft)" class="dark-explicit rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-[10px] font-semibold text-rose-700 dark:border-rose-500/30 dark:bg-rose-950/40 dark:text-rose-200" data-testid="free-draft-publish-failure">
                  {{ t('history.freeDrafts.publishFailed') }}
                </span>
              </div>
              <p class="dark-explicit mt-2 line-clamp-2 text-sm text-slate-600 dark:text-slate-300">{{ excerpt(draft) }}</p>
              <div class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
                <span>{{ t('history.freeDrafts.createdAt', { date: formatDate(draft.created_at) }) }}</span>
                <span>{{ t('history.freeDrafts.updatedAt', { date: formatDate(draft.updated_at) }) }}</span>
              </div>
              <div v-if="draft.hashtags.length" class="mt-2 flex flex-wrap gap-1.5">
                <span v-for="tag in draft.hashtags" :key="tag" class="dark-explicit rounded-md bg-violet-50 px-2 py-1 text-[11px] text-violet-700 dark:bg-violet-950/35 dark:text-violet-200">{{ tag }}</span>
              </div>
              <div v-if="hasUsableEvaluation(draft.last_evaluation)" class="mt-3 inline-flex flex-wrap items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs" :class="evaluationClass(draft.last_evaluation?.decision)">
                <span>{{ t('history.freeDrafts.evaluation') }}</span>
                <span class="font-semibold">{{ draft.last_evaluation?.overall_score }}</span>
                <span>{{ decisionLabel(draft.last_evaluation?.decision) }}</span>
              </div>
              <span v-else-if="draft.last_evaluation?.degraded" class="dark-explicit mt-3 inline-flex rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-200">
                {{ t('history.freeDrafts.evaluationDegraded') }}
              </span>
              <span v-else class="dark-explicit mt-3 inline-flex rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">{{ t('history.freeDrafts.evaluationUnavailable') }}</span>
              <div v-if="publishFailed(draft)" class="dark-explicit mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-xs text-rose-700 dark:border-rose-500/30 dark:bg-rose-950/40 dark:text-rose-200">
                <span class="font-semibold">{{ t('history.freeDrafts.publishFailedType', { reason: publishFailureReason(draft) }) }}</span>
                <span>{{ t('history.freeDrafts.publishFailedHint') }}</span>
              </div>
              <!-- Creative-memory anchors (task 08-26-free-anchor-display):
                   what the draft was built on; tooltip lists the ids. -->
              <span
                v-if="draft.style_id || draft.play_id || (draft.material_ids?.length ?? 0) > 0"
                class="dark-explicit mt-3 inline-flex rounded-lg border border-violet-200 bg-violet-50 px-2.5 py-1.5 text-xs text-violet-700 dark:border-violet-500/30 dark:bg-violet-950/40 dark:text-violet-200"
                data-testid="free-draft-anchors"
                :title="anchorTooltip(draft)"
              >{{ t('history.freeDrafts.anchorBadge', { count: anchorCount(draft) }) }}</span>
              <!-- Persisted engagement snapshot (server-set last_analytics):
                   offline-visible performance for published drafts. -->
              <div
                v-if="draft.published && draft.last_analytics"
                class="dark-explicit mt-3 inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-cyan-200 bg-cyan-50 px-2.5 py-1.5 text-xs text-cyan-700 dark:border-cyan-500/30 dark:bg-cyan-950/40 dark:text-cyan-200"
                data-testid="free-draft-engagement"
                :title="t('history.freeDrafts.engagementCapturedAt', { date: formatDate(draft.last_analytics?.fetched_at) })"
              >
                <span>{{ t('history.freeDrafts.engagementViews', { value: draft.last_analytics?.views ?? 0 }) }}</span>
                <span aria-hidden="true">·</span>
                <span>{{ t('history.freeDrafts.engagementLikes', { value: draft.last_analytics?.likes ?? 0 }) }}</span>
                <span aria-hidden="true">·</span>
                <span>{{ t('history.freeDrafts.engagementCollects', { value: draft.last_analytics?.collects ?? 0 }) }}</span>
                <!-- Views movement vs previous capture (server-computed trend,
                     null before two snapshots — task 08-26-free-snapshot-trend). -->
                <template v-if="draft.engagement_trend && draft.engagement_trend.delta_views !== 0">
                  <span aria-hidden="true">·</span>
                  <span
                    class="font-semibold"
                    :class="draft.engagement_trend.delta_views > 0 ? 'text-emerald-700 dark:text-emerald-300' : 'text-rose-700 dark:text-rose-300'"
                    data-testid="free-draft-trend"
                  >{{ t(draft.engagement_trend.delta_views > 0 ? 'history.freeDrafts.trendUp' : 'history.freeDrafts.trendDown', { value: Math.abs(draft.engagement_trend.delta_views) }) }}</span>
                </template>
              </div>
            </div>

            <div class="flex shrink-0 items-center gap-2">
              <NeonButton variant="cyan" size="sm" class="min-h-11" @click="continueDraft(draft.draft_id)">{{ actionLabel(draft) }}</NeonButton>
              <button type="button" class="dark-explicit min-h-11 min-w-11 rounded-lg text-slate-400 transition hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-950/30" :aria-label="t('history.freeDrafts.delete')" @click="requestDelete(draft)">
                <AppIcon name="Trash2" size="sm" variant="pink" aria-hidden="true" />
              </button>
            </div>
          </div>
        </article>
      </div>

      <p v-if="responseTruncated" class="dark-explicit text-center text-xs text-slate-400">{{ t('history.freeDrafts.truncated') }}</p>
    </template>

    <ConfirmModal
      :is-open="Boolean(deleteTarget)"
      :title="t('history.freeDrafts.deleteTitle')"
      :message="t('history.freeDrafts.deleteMessage', { title: deleteTarget?.title || t('history.freeDrafts.untitled') })"
      :confirm-action="t('history.freeDrafts.deleteConfirm')"
      variant="danger"
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />
  </section>
</template>
