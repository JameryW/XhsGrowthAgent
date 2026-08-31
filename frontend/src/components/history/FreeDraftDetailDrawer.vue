<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getFreeDraft, type FreeDraftRecord, type FreeDraftTrend } from '@/api/free'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { useFocusTrap } from '@/composables/useFocusTrap'

const props = defineProps<{
  accountId: string | null
  draftId: string | null
  isOpen: boolean
  nextStepLabel?: string
}>()

const emit = defineEmits<{
  (event: 'close'): void
  (event: 'continue', detail: FreeDraftRecord): void
}>()

const { t, locale } = useI18n()
const focusTrap = useFocusTrap()
const drawerRef = ref<HTMLElement | null>(null)
const detail = ref<FreeDraftRecord | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)
const isUnavailable = ref(false)

let requestGeneration = 0
let detailAbort: AbortController | null = null

const dialogTitleId = 'free-draft-detail-title'

const evaluation = computed(() => detail.value?.last_evaluation ?? null)
const publishAttempt = computed(() => detail.value?.last_publish ?? null)
const analytics = computed(() => detail.value?.last_analytics ?? null)
const publishFailureDetail = computed(() => {
  const facts = [publishAttempt.value?.error_type, publishAttempt.value?.error]
    .map(value => value?.trim() || '')
    .filter(Boolean)
  return [...new Set(facts)].join(' · ')
})

const viewTrend = computed<FreeDraftTrend | null>(() => {
  const serverTrend = detail.value?.engagement_trend
  if (
    serverTrend
    && Number.isFinite(serverTrend.views)
    && Number.isFinite(serverTrend.delta_views)
  ) {
    return serverTrend
  }

  const snapshots = (detail.value?.analytics_snapshots ?? []).filter(
    snapshot => typeof snapshot.views === 'number' && Number.isFinite(snapshot.views),
  )
  if (snapshots.length < 2) return null
  const previous = snapshots[snapshots.length - 2]
  const latest = snapshots[snapshots.length - 1]
  return {
    views: latest.views as number,
    delta_views: (latest.views as number) - (previous.views as number),
    captured_at: latest.fetched_at ?? null,
  }
})

const realPostUrl = computed(() => {
  const record = detail.value
  const postId = record?.post_id?.trim() || ''
  const rawUrl = record?.post_url?.trim() || ''
  if (!record?.published || !postId || postId.startsWith('mock_') || !rawUrl) return ''
  try {
    const parsed = new URL(rawUrl)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.href : ''
  } catch {
    return ''
  }
})

function isAbortError(err: unknown) {
  if (!err || typeof err !== 'object') return false
  const candidate = err as { code?: string; name?: string }
  return candidate.code === 'ERR_CANCELED' || candidate.name === 'CanceledError' || candidate.name === 'AbortError'
}

function invalidateRequest() {
  requestGeneration += 1
  detailAbort?.abort()
  detailAbort = null
}

function resetDetailState() {
  detail.value = null
  error.value = null
  isUnavailable.value = false
  isLoading.value = false
}

async function loadDetail(accountId: string, draftId: string) {
  const generation = requestGeneration
  const abort = new AbortController()
  detailAbort = abort
  isLoading.value = true
  error.value = null
  isUnavailable.value = false

  try {
    const response = await getFreeDraft(accountId, draftId, {
      signal: abort.signal,
      suppressToast: true,
    })
    if (
      generation !== requestGeneration
      || props.accountId !== accountId
      || props.draftId !== draftId
      || !props.isOpen
    ) return

    const record = response?.draft
    const isEmptyRecord = !record || typeof record !== 'object' || Object.keys(record).length === 0
    const hasWrongIdentity = response?.draft_id !== draftId
      || (record?.draft_id != null && record.draft_id !== draftId)
      || (record?.account_id != null && record.account_id !== accountId)
    if (isEmptyRecord || hasWrongIdentity) {
      isUnavailable.value = true
      return
    }

    detail.value = {
      ...record,
      draft_id: record.draft_id || response.draft_id,
      hashtags: Array.isArray(record.hashtags) ? record.hashtags : [],
    }
  } catch (err: unknown) {
    if (generation !== requestGeneration || isAbortError(err)) return
    error.value = err instanceof Error ? err.message : t('history.freeDrafts.preview.loadError')
  } finally {
    if (generation === requestGeneration) {
      isLoading.value = false
      detailAbort = null
    }
  }
}

function retry() {
  const accountId = props.accountId
  const draftId = props.draftId
  if (!props.isOpen || !accountId || !draftId) return
  invalidateRequest()
  detail.value = null
  void loadDetail(accountId, draftId)
}

function close() {
  emit('close')
}

function continueDraft() {
  if (detail.value) emit('continue', detail.value)
}

function formatDate(iso?: string | null) {
  if (!iso) return t('history.freeDrafts.unavailable')
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return t('history.freeDrafts.unavailable')
  return date.toLocaleString(locale.value || 'en', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatMetric(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return t('history.freeDrafts.unavailable')
  return new Intl.NumberFormat(locale.value || 'en').format(value)
}

function decisionLabel(decision?: string | null) {
  if (!decision) return t('history.freeDrafts.evaluationUnavailable')
  const key = `history.freeDrafts.decision.${decision}`
  const translated = t(key)
  return translated === key ? decision : translated
}

function publishStatusLabel(status?: string | null) {
  if (!status) return t('history.freeDrafts.unavailable')
  const key = `history.freeDrafts.preview.publishStatuses.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

function publishedStateLabel(published?: boolean | null) {
  if (published === true) return t('history.freeDrafts.published')
  if (published === false) return t('history.freeDrafts.unpublished')
  return t('history.freeDrafts.unavailable')
}

function publishedStateClass(published?: boolean | null) {
  if (published === true) {
    return 'border-teal-200 bg-teal-50 text-teal-700 dark:border-teal-500/30 dark:bg-teal-950/40 dark:text-teal-200'
  }
  if (published === false) {
    return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300'
  }
  return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-950/40 dark:text-amber-200'
}

watch(
  [() => props.isOpen, () => props.accountId, () => props.draftId],
  ([isOpen, accountId, draftId], previous) => {
    const previousAccountId = previous[1]
    invalidateRequest()
    resetDetailState()

    // An account switch invalidates the identity of the whole dialog. The
    // parent also clears its selected row, while this guard keeps the drawer
    // safe when it is mounted independently.
    if (isOpen && previousAccountId && previousAccountId !== accountId) {
      emit('close')
      return
    }
    if (!isOpen) return
    if (!accountId || !draftId) {
      isUnavailable.value = true
      return
    }
    void loadDetail(accountId, draftId)
  },
  { immediate: true },
)

watch(
  () => props.isOpen,
  async (isOpen) => {
    if (isOpen) {
      await nextTick()
      await focusTrap.activate(drawerRef.value)
    } else {
      focusTrap.deactivate()
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  invalidateRequest()
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      ref="drawerRef"
      class="fixed inset-0 z-modal flex min-w-0 justify-end"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="dialogTitleId"
      data-testid="free-draft-detail-drawer"
      @keydown.esc.stop.prevent="close"
    >
      <div
        class="absolute inset-0 bg-black/45"
        data-testid="free-draft-detail-backdrop"
        aria-hidden="true"
        @click="close"
      />

      <section class="dark-explicit relative flex h-full w-full min-w-0 flex-col overflow-hidden bg-white shadow-2xl md:max-w-3xl dark:bg-slate-950">
        <header class="dark-explicit shrink-0 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur md:px-6 md:py-4 dark:border-slate-700 dark:bg-slate-950/95">
          <div class="flex min-w-0 items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="dark-explicit text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-600 dark:text-violet-300">{{ t('history.freeDrafts.preview.eyebrow') }}</p>
              <h2 :id="dialogTitleId" class="dark-explicit mt-1 text-base font-semibold text-slate-800 md:text-lg dark:text-slate-100">{{ t('history.freeDrafts.preview.title') }}</h2>
              <p class="dark-explicit mt-1 break-words text-xs text-slate-500 dark:text-slate-400">
                {{ detail
                  ? detail.title || t('history.freeDrafts.untitled')
                  : isLoading
                    ? t('common.loadingState')
                    : t('history.freeDrafts.unavailable') }}
              </p>
            </div>
            <button
              type="button"
              class="dark-explicit min-h-11 min-w-11 shrink-0 rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/50 dark:hover:bg-slate-800 dark:hover:text-slate-200"
              :aria-label="t('common.close')"
              @click="close"
            >
              <AppIcon name="X" size="sm" variant="muted" aria-hidden="true" />
            </button>
          </div>
        </header>

        <main class="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 md:px-6 md:py-5">
          <div v-if="isLoading" class="space-y-4" data-testid="free-draft-detail-loading" aria-busy="true">
            <div class="dark-explicit h-28 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800" />
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div v-for="index in 4" :key="index" class="dark-explicit h-20 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-800" />
            </div>
            <div class="dark-explicit h-40 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800" />
          </div>

          <div
            v-else-if="error"
            class="dark-explicit rounded-2xl border border-rose-200 bg-rose-50/80 p-6 text-center dark:border-rose-500/30 dark:bg-rose-950/30"
            data-testid="free-draft-detail-error"
            role="alert"
          >
            <AppIcon name="AlertTriangle" size="lg" variant="pink" aria-hidden="true" />
            <h3 class="dark-explicit mt-3 text-sm font-semibold text-rose-800 dark:text-rose-100">{{ t('history.freeDrafts.preview.loadErrorTitle') }}</h3>
            <p class="dark-explicit mt-1 break-words text-sm text-rose-700 dark:text-rose-200">{{ error }}</p>
            <NeonButton variant="ghost" size="sm" class="mt-4 min-h-11" @click="retry">{{ t('common.retry') }}</NeonButton>
          </div>

          <div
            v-else-if="isUnavailable || !detail"
            class="dark-explicit rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 p-6 text-center dark:border-slate-700 dark:bg-slate-900/60"
            data-testid="free-draft-detail-unavailable"
            role="status"
          >
            <AppIcon name="FileText" size="lg" variant="muted" aria-hidden="true" />
            <h3 class="dark-explicit mt-3 text-sm font-semibold text-slate-700 dark:text-slate-200">{{ t('history.freeDrafts.preview.unavailableTitle') }}</h3>
            <p class="dark-explicit mt-1 text-sm text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.unavailableDescription') }}</p>
          </div>

          <div v-else class="min-w-0 space-y-4" data-testid="free-draft-detail-content">
            <section class="dark-explicit min-w-0 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0">
                  <h3 class="dark-explicit break-words text-lg font-semibold text-slate-800 dark:text-slate-100">{{ detail.title || t('history.freeDrafts.untitled') }}</h3>
                  <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
                    <span>{{ t('history.freeDrafts.createdAt', { date: formatDate(detail.created_at) }) }}</span>
                    <span>{{ t('history.freeDrafts.updatedAt', { date: formatDate(detail.updated_at) }) }}</span>
                  </div>
                </div>
                <span class="dark-explicit shrink-0 rounded-full border px-2.5 py-1 text-xs font-semibold" :class="publishedStateClass(detail.published)">
                  {{ publishedStateLabel(detail.published) }}
                </span>
              </div>

              <div class="mt-4">
                <h4 class="dark-explicit text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.body') }}</h4>
                <p v-if="detail.body" class="dark-explicit mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-slate-700 dark:text-slate-200">{{ detail.body }}</p>
                <p v-else class="dark-explicit mt-2 text-sm text-slate-400 dark:text-slate-500">{{ t('history.freeDrafts.preview.bodyUnavailable') }}</p>
              </div>

              <div v-if="detail.hashtags.length" class="mt-4 flex flex-wrap gap-2" :aria-label="t('history.freeDrafts.preview.hashtags')">
                <span v-for="tag in detail.hashtags" :key="tag" class="dark-explicit max-w-full break-words rounded-lg bg-violet-50 px-2.5 py-1 text-xs text-violet-700 dark:bg-violet-950/40 dark:text-violet-200">{{ tag }}</span>
              </div>
            </section>

            <section class="dark-explicit min-w-0 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
              <h3 class="dark-explicit text-sm font-semibold text-slate-800 dark:text-slate-100">{{ t('history.freeDrafts.preview.creativeContext') }}</h3>
              <dl class="mt-3 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
                <div class="dark-explicit min-w-0 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
                  <dt class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.niche') }}</dt>
                  <dd class="dark-explicit mt-1 break-words text-sm font-medium text-slate-800 dark:text-slate-100">{{ detail.niche || t('history.freeDrafts.unavailable') }}</dd>
                </div>
                <div class="dark-explicit min-w-0 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
                  <dt class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.contentAngle') }}</dt>
                  <dd class="dark-explicit mt-1 break-words text-sm font-medium text-slate-800 dark:text-slate-100">{{ detail.content_angle || t('history.freeDrafts.unavailable') }}</dd>
                </div>
                <div class="dark-explicit min-w-0 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
                  <dt class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.targetAudience') }}</dt>
                  <dd class="dark-explicit mt-1 break-words text-sm font-medium text-slate-800 dark:text-slate-100">{{ detail.target_audience || t('history.freeDrafts.unavailable') }}</dd>
                </div>
                <div class="dark-explicit min-w-0 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
                  <dt class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.imageCount') }}</dt>
                  <dd class="dark-explicit mt-1 text-sm font-medium text-slate-800 dark:text-slate-100">{{ Array.isArray(detail.image_paths) ? detail.image_paths.length : t('history.freeDrafts.unavailable') }}</dd>
                </div>
              </dl>
            </section>

            <section class="dark-explicit min-w-0 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900" data-testid="free-draft-detail-evaluation">
              <h3 class="dark-explicit text-sm font-semibold text-slate-800 dark:text-slate-100">{{ t('history.freeDrafts.preview.evaluationTitle') }}</h3>
              <div v-if="evaluation" class="mt-3 min-w-0 space-y-3">
                <div v-if="evaluation.degraded" class="dark-explicit rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-950/35 dark:text-amber-100" role="status">
                  <p class="font-semibold">{{ t('history.freeDrafts.evaluationDegraded') }}</p>
                  <p v-if="evaluation.summary" class="mt-1 break-words">{{ evaluation.summary }}</p>
                </div>
                <dl v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div class="dark-explicit rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
                    <dt class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.score') }}</dt>
                    <dd class="dark-explicit mt-1 text-lg font-semibold text-slate-800 dark:text-slate-100">{{ formatMetric(evaluation.overall_score) }}</dd>
                  </div>
                  <div class="dark-explicit rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
                    <dt class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.decision') }}</dt>
                    <dd class="dark-explicit mt-1 break-words text-sm font-semibold text-slate-800 dark:text-slate-100">{{ decisionLabel(evaluation.decision) }}</dd>
                  </div>
                </dl>
                <div v-if="!evaluation.degraded && evaluation.summary" class="min-w-0">
                  <h4 class="dark-explicit text-xs font-semibold text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.summary') }}</h4>
                  <p class="dark-explicit mt-1 break-words text-sm leading-6 text-slate-700 dark:text-slate-200">{{ evaluation.summary }}</p>
                </div>
                <div v-if="evaluation.revision_hints?.length" class="min-w-0">
                  <h4 class="dark-explicit text-xs font-semibold text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.revisionHints') }}</h4>
                  <ul class="mt-2 space-y-2">
                    <li v-for="hint in evaluation.revision_hints" :key="hint" class="dark-explicit break-words rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/30 dark:text-amber-100">{{ hint }}</li>
                  </ul>
                </div>
              </div>
              <p v-else class="dark-explicit mt-3 text-sm text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.noEvaluation') }}</p>
            </section>

            <section class="dark-explicit min-w-0 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900" data-testid="free-draft-detail-anchors">
              <h3 class="dark-explicit text-sm font-semibold text-slate-800 dark:text-slate-100">{{ t('history.freeDrafts.preview.anchorsTitle') }}</h3>
              <dl v-if="detail.style_id || detail.play_id || detail.material_ids?.length" class="mt-3 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
                <div v-if="detail.style_id" class="dark-explicit min-w-0 rounded-xl bg-violet-50 p-3 dark:bg-violet-950/30">
                  <dt class="dark-explicit text-xs text-violet-600 dark:text-violet-300">{{ t('history.freeDrafts.preview.styleAnchor') }}</dt>
                  <dd class="dark-explicit mt-1 break-words text-sm font-medium text-violet-800 dark:text-violet-100">{{ detail.style_id }}</dd>
                </div>
                <div v-if="detail.play_id" class="dark-explicit min-w-0 rounded-xl bg-violet-50 p-3 dark:bg-violet-950/30">
                  <dt class="dark-explicit text-xs text-violet-600 dark:text-violet-300">{{ t('history.freeDrafts.preview.playAnchor') }}</dt>
                  <dd class="dark-explicit mt-1 break-words text-sm font-medium text-violet-800 dark:text-violet-100">{{ detail.play_id }}</dd>
                </div>
                <div v-if="detail.material_ids?.length" class="dark-explicit min-w-0 rounded-xl bg-violet-50 p-3 sm:col-span-2 dark:bg-violet-950/30">
                  <dt class="dark-explicit text-xs text-violet-600 dark:text-violet-300">{{ t('history.freeDrafts.preview.materialAnchors') }}</dt>
                  <dd class="mt-2 flex min-w-0 flex-wrap gap-2">
                    <span v-for="materialId in detail.material_ids" :key="materialId" class="dark-explicit max-w-full break-words rounded-md bg-white/80 px-2 py-1 text-xs text-violet-800 dark:bg-slate-900/70 dark:text-violet-100">{{ materialId }}</span>
                  </dd>
                </div>
              </dl>
              <p v-else class="dark-explicit mt-3 text-sm text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.noAnchors') }}</p>
            </section>

            <section class="dark-explicit min-w-0 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900" data-testid="free-draft-detail-publish">
              <h3 class="dark-explicit text-sm font-semibold text-slate-800 dark:text-slate-100">{{ t('history.freeDrafts.preview.publishTitle') }}</h3>
              <dl class="mt-3 grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
                <div class="dark-explicit min-w-0 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
                  <dt class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.publishState') }}</dt>
                  <dd class="dark-explicit mt-1 break-words text-sm font-medium text-slate-800 dark:text-slate-100">{{ publishedStateLabel(detail.published) }}</dd>
                </div>
                <div class="dark-explicit min-w-0 rounded-xl bg-slate-50 p-3 dark:bg-slate-800/70">
                  <dt class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.lastAttempt') }}</dt>
                  <dd class="dark-explicit mt-1 break-words text-sm font-medium text-slate-800 dark:text-slate-100">{{ publishStatusLabel(publishAttempt?.status) }}</dd>
                  <p v-if="publishAttempt?.at" class="dark-explicit mt-1 text-xs text-slate-500 dark:text-slate-400">{{ formatDate(publishAttempt.at) }}</p>
                </div>
                <div v-if="publishFailureDetail" class="dark-explicit min-w-0 rounded-xl border border-rose-200 bg-rose-50 p-3 sm:col-span-2 dark:border-rose-500/30 dark:bg-rose-950/30">
                  <dt class="dark-explicit text-xs text-rose-600 dark:text-rose-300">{{ t('history.freeDrafts.preview.failureReason') }}</dt>
                  <dd class="dark-explicit mt-1 break-words text-sm text-rose-800 dark:text-rose-100">{{ publishFailureDetail }}</dd>
                </div>
              </dl>
              <a
                v-if="realPostUrl"
                class="dark-explicit mt-3 inline-flex min-h-11 max-w-full items-center gap-2 break-all rounded-xl border border-cyan-200 bg-cyan-50 px-3 py-2 text-sm font-semibold text-cyan-700 transition hover:bg-cyan-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50 dark:border-cyan-500/30 dark:bg-cyan-950/30 dark:text-cyan-200 dark:hover:bg-cyan-950/50"
                :href="realPostUrl"
                target="_blank"
                rel="noopener noreferrer"
              >
                <AppIcon name="ExternalLink" size="sm" variant="cyan" aria-hidden="true" />
                <span>{{ t('history.freeDrafts.preview.openPost') }}</span>
              </a>
            </section>

            <section class="dark-explicit min-w-0 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900" data-testid="free-draft-detail-analytics">
              <h3 class="dark-explicit text-sm font-semibold text-slate-800 dark:text-slate-100">{{ t('history.freeDrafts.preview.analyticsTitle') }}</h3>
              <template v-if="analytics">
                <dl class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                  <div v-for="metric in [
                    { label: t('history.freeDrafts.preview.views'), value: analytics.views },
                    { label: t('history.freeDrafts.preview.likes'), value: analytics.likes },
                    { label: t('history.freeDrafts.preview.collects'), value: analytics.collects },
                    { label: t('history.freeDrafts.preview.comments'), value: analytics.comments },
                    { label: t('history.freeDrafts.preview.shares'), value: analytics.shares },
                  ]" :key="metric.label" class="dark-explicit min-w-0 rounded-xl bg-cyan-50 p-3 dark:bg-cyan-950/25">
                    <dt class="dark-explicit break-words text-xs text-cyan-700 dark:text-cyan-300">{{ metric.label }}</dt>
                    <dd class="dark-explicit mt-1 text-base font-semibold tabular-nums text-cyan-900 dark:text-cyan-100">{{ formatMetric(metric.value) }}</dd>
                  </div>
                </dl>
                <p class="dark-explicit mt-3 text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.capturedAt', { date: formatDate(analytics.fetched_at) }) }}</p>
                <div v-if="viewTrend" class="dark-explicit mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-800/70" data-testid="free-draft-detail-trend">
                  <p class="dark-explicit text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.viewsTrend') }}</p>
                  <p class="dark-explicit mt-1 text-sm font-semibold" :class="viewTrend.delta_views > 0 ? 'text-emerald-700 dark:text-emerald-300' : viewTrend.delta_views < 0 ? 'text-rose-700 dark:text-rose-300' : 'text-slate-700 dark:text-slate-200'">
                    {{ viewTrend.delta_views > 0
                      ? t('history.freeDrafts.trendUp', { value: viewTrend.delta_views })
                      : viewTrend.delta_views < 0
                        ? t('history.freeDrafts.trendDown', { value: Math.abs(viewTrend.delta_views) })
                        : t('history.freeDrafts.preview.trendFlat') }}
                  </p>
                </div>
                <p v-else class="dark-explicit mt-3 text-xs text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.trendUnavailable') }}</p>
              </template>
              <p v-else class="dark-explicit mt-3 text-sm text-slate-500 dark:text-slate-400">{{ t('history.freeDrafts.preview.noAnalytics') }}</p>
            </section>
          </div>
        </main>

        <footer class="dark-explicit shrink-0 border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur md:px-6 md:py-4 dark:border-slate-700 dark:bg-slate-950/95">
          <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <NeonButton variant="ghost" size="sm" class="min-h-11 sm:min-w-28" @click="close">{{ t('common.close') }}</NeonButton>
            <NeonButton variant="cyan" size="sm" class="min-h-11 sm:min-w-36" :disabled="!detail || isLoading || Boolean(error) || isUnavailable" @click="continueDraft">
              {{ nextStepLabel || t('history.freeDrafts.continue') }}
            </NeonButton>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
