<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import PageHeader from '@/components/PageHeader.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import AccountScopeBar from '@/components/AccountScopeBar.vue'
import AccountViewNotice from '@/components/AccountViewNotice.vue'
import StatusFilterBar from '@/components/StatusFilterBar.vue'
import { listWorkflows, deleteWorkflow, getWorkflowAccountTotals } from '@/api/workflow'
import {
  revokeShowcaseVisibility,
  updateShowcaseVisibility,
  type ShowcaseVisibilityUpdate,
} from '@/api/publicShowcase'
import type { WorkflowListItem, WorkflowStatus } from '@/types/workflow'
import { useWorkflowStore, useToastStore, useAccountsStore } from '@/stores'
import { useCrossAccountHintsStore } from '@/stores/crossAccountHints'
import { useHistoryAccountScope } from '@/composables/useHistoryAccountScope'
import { accountQuery } from '@/utils/accountViewSession'
import { navigateToStart, prefetchRouteChunk, prefetchStartWorkspace } from '@/utils/routePrefetch'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const workflowStore = useWorkflowStore()
const toastStore = useToastStore()
const accountsStore = useAccountsStore()
const crossAccountHints = useCrossAccountHintsStore()

const {
  historyAccountId,
  hasMultipleAccounts,
  isViewingNonWorkspace,
  accountChips,
  siblingHints,
  viewAccountName: viewAccountNameRaw,
  workspaceAccountName: workspaceAccountNameRaw,
  setAccountTotal,
  applyAccountTotals,
  bestSiblingWithHistory,
  getCachedList,
  setCachedList,
  invalidateCachedList,
  isCacheFresh,
  applyViewAccount,
  resolveOwned,
  pickPreferred,
  queryAccountId,
  isSuppressingQueryWatch,
  schedulePrefetch,
  cancelScheduledPrefetch,
} = useHistoryAccountScope({
  route,
  router,
  accountsStore,
  locale,
})

const viewAccountName = computed(
  () => viewAccountNameRaw.value || t('nav.accountSelect'),
)
const workspaceAccountName = computed(
  () => workspaceAccountNameRaw.value || t('nav.accountSelect'),
)

/** Other accounts with pending reviews — empty History can still point users there. */
const reviewSiblingHints = computed(() => {
  if (!hasMultipleAccounts.value) return [] as { id: string; name: string; total: number }[]
  const viewId = historyAccountId.value
  const loc = locale.value || 'zh-CN'
  return accountsStore.accounts
    .filter(a => a.id !== viewId)
    .map(a => ({
      id: a.id,
      name: a.name,
      total: crossAccountHints.reviewAwaitingTotals[a.id] ?? 0,
    }))
    .filter(h => h.total > 0)
    .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name, loc))
})

function openReviewForAccount(accountId: string) {
  void router.push({
    name: 'review',
    query: accountQuery(accountId, { omitIfEquals: accountsStore.activeAccountId }),
  })
}

const workflows = ref<WorkflowListItem[]>([])
/** First paint only — account switches use soft refresh / cache paint. */
const isLoading = ref(false)
const isRefreshing = ref(false)
const error = ref<string | null>(null)
const total = ref(0)
const isPromotingWorkspace = ref(false)
/** True while showing cached rows and a background revalidate is in flight. */
const isRevalidating = ref(false)

/** Client-side status filter for the currently viewed account list (also in ?status=). */
type StatusFilter = 'all' | WorkflowStatus
const VALID_STATUS_FILTERS = new Set<string>([
  'all',
  'running',
  'completed',
  'error',
  'cancelled',
  'awaiting_review',
  'awaiting_choice',
  'awaiting_draft',
  'awaiting_brief',
  'awaiting_ripple_decision',
  'awaiting_blogger_selection',
  'stale',
  'paused',
  'idle',
])

function statusFromQuery(): StatusFilter {
  const raw = route.query.status
  const value = typeof raw === 'string' ? raw.trim() : Array.isArray(raw) ? String(raw[0] || '').trim() : ''
  if (value && VALID_STATUS_FILTERS.has(value)) return value as StatusFilter
  return 'all'
}

const statusFilter = ref<StatusFilter>(statusFromQuery())
let suppressStatusQueryWatch = false

function syncStatusQuery(status: StatusFilter) {
  const current = typeof route.query.status === 'string' ? route.query.status : null
  const nextVal = status === 'all' ? null : status
  if ((nextVal || null) === (current || null)) return
  const nextQuery: Record<string, string | string[]> = {
    ...(route.query as Record<string, string | string[]>),
  }
  if (nextVal) nextQuery.status = nextVal
  else delete nextQuery.status
  suppressStatusQueryWatch = true
  void router.replace({ query: nextQuery }).finally(() => {
    suppressStatusQueryWatch = false
  })
}

function setStatusFilter(status: StatusFilter) {
  if (statusFilter.value === status) return
  statusFilter.value = status
  syncStatusQuery(status)
}

/** Prevent double-probing totals for the same account set while mounted. */
let totalsProbeKey = ''
let fetchGeneration = 0
let listAbort: AbortController | null = null
// Soft auto-browse when the preferred account is empty but a sibling has history.
// Once per mount so the user can still manually open an empty account afterwards.
let didAutoBrowseEmpty = false
/** Shown after empty-account auto-browse so the user understands the jump. */
const autoBrowseNotice = ref<{ fromName: string; toName: string; count: number } | null>(null)
// While promoting workspace account, skip the active-account watch reload.
let suppressActiveWatch = false

// Delete confirmation
const showDeleteModal = ref(false)
const deleteTarget = ref<string | null>(null)
const isDeleting = ref(false)

const deleteTargetIsShared = computed(() => {
  const wf = workflows.value.find(w => w.thread_id === deleteTarget.value)
  return !!wf?.showcase_visibility && wf.showcase_visibility !== 'private'
})

const deleteMessage = computed(() =>
  deleteTargetIsShared.value ? t('history.deleteMessageShared') : t('history.deleteMessage')
)

const isBusy = computed(
  () => isLoading.value || isRefreshing.value || isPromotingWorkspace.value || isRevalidating.value,
)

type ShowcaseVisibility = 'private' | 'unlisted' | 'public'

const showcaseTarget = ref<WorkflowListItem | null>(null)
const showcaseVisibility = ref<ShowcaseVisibility>('public')
const showcaseTitle = ref('')
const showcaseSummary = ref('')
const showcaseFeatured = ref(false)
const showcaseFeaturedRank = ref(1)
const isUpdatingShowcase = ref(false)

async function ensureAccountsLoaded() {
  if (accountsStore.accounts.length > 0 && accountsStore.activeAccount) return
  await accountsStore.fetchAccounts()
}

function resolveHistoryAccountId(): string | null {
  return historyAccountId.value || accountsStore.activeAccountId
}

function paintFromCache(accountId: string): boolean {
  const cached = getCachedList(accountId)
  if (!cached) return false
  workflows.value = cached.workflows
  total.value = cached.total
  setAccountTotal(accountId, cached.total)
  error.value = null
  return true
}

/** Coalesce concurrent History mounts / auto-browse probes. */
let totalsProbeInFlight: Promise<void> | null = null

/**
 * Fill chip badges for all owned accounts.
 * Prefers one-shot /account-totals; falls back to N× limit=1 if unavailable.
 */
async function probeAccountTotals(exceptAccountId: string | null) {
  if (accountsStore.accounts.length <= 1) return
  if (totalsProbeInFlight) return totalsProbeInFlight

  const key = accountsStore.accounts.map(a => a.id).sort().join(',')
  const needProbe = accountsStore.accounts.some((a) => {
    if (a.id === exceptAccountId) return false
    const chip = accountChips.value.find(c => c.id === a.id)
    return typeof chip?.total !== 'number'
  })
  // Re-fetch bulk totals when owned set changes even if numbers exist.
  if (!needProbe && totalsProbeKey === key) return
  totalsProbeKey = key

  totalsProbeInFlight = (async () => {
    try {
      const res = await getWorkflowAccountTotals(undefined, { suppressToast: true })
      if (res?.totals && typeof res.totals === 'object') {
        applyAccountTotals(res.totals)
        return
      }
    } catch {
      // fall through to legacy per-account probes
    }

    const targets = accountsStore.accounts.filter((a) => {
      if (a.id === exceptAccountId) return false
      const chip = accountChips.value.find(c => c.id === a.id)
      return typeof chip?.total !== 'number'
    })
    if (!targets.length) return

    await Promise.all(
      targets.map(async (acc) => {
        try {
          const res = await listWorkflows(
            { account_id: acc.id, limit: 1 },
            { suppressToast: true },
          )
          setAccountTotal(acc.id, res.total ?? 0)
        } catch {
          // Leave undefined so a later refresh can retry.
        }
      }),
    )
  })().finally(() => {
    totalsProbeInFlight = null
  })

  return totalsProbeInFlight
}

type FetchOpts = {
  soft?: boolean
  accountId?: string
  /** When true, keep painted rows while revalidating (cache hit path). */
  revalidate?: boolean
}

function isAbortError(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false
  const e = err as { code?: string; name?: string; message?: string }
  return e.code === 'ERR_CANCELED' || e.name === 'CanceledError' || e.name === 'AbortError'
}

/**
 * When the preferred/workspace account has zero history but another owned
 * account does, jump the *view* (not workspace) once so the original
 * "刚发布的工作流在历史里看不到" case resolves without an extra click.
 * Skips when the user explicitly opened ?account= for this empty account.
 */
async function maybeAutoBrowseFromEmpty(
  accountId: string | null,
  listTotal: number,
  gen: number,
): Promise<boolean> {
  if (didAutoBrowseEmpty || listTotal > 0 || !hasMultipleAccounts.value || !accountId) {
    return false
  }
  // Respect intentional deep-link to this empty account.
  if (queryAccountId() === accountId) return false

  await probeAccountTotals(accountId)
  if (gen !== fetchGeneration) return false

  const best = bestSiblingWithHistory(accountId)
  if (!best) return false

  didAutoBrowseEmpty = true
  const fromName =
    accountsStore.accounts.find(a => a.id === accountId)?.name?.trim()
    || workspaceAccountName.value
  autoBrowseNotice.value = {
    fromName,
    toName: best.name,
    count: best.total,
  }
  // selectHistoryAccount owns the follow-up fetch.
  selectHistoryAccount(best.id)
  return true
}

async function fetchWorkflows(opts: FetchOpts = {}) {
  const gen = ++fetchGeneration
  // Cancel any in-flight list request so rapid account switches don't thrash.
  if (listAbort) {
    listAbort.abort()
    listAbort = null
  }
  const abort = new AbortController()
  listAbort = abort

  const soft = opts.soft ?? workflows.value.length > 0
  const revalidate = opts.revalidate === true

  if (revalidate) {
    isRevalidating.value = true
  } else if (soft) {
    isRefreshing.value = true
  } else {
    isLoading.value = true
  }
  error.value = null
  try {
    await ensureAccountsLoaded()

    if (opts.accountId && resolveOwned(opts.accountId)) {
      applyViewAccount(opts.accountId)
    } else if (!historyAccountId.value || !resolveOwned(historyAccountId.value)) {
      const preferred = pickPreferred()
      if (preferred) applyViewAccount(preferred)
    } else {
      applyViewAccount(historyAccountId.value)
    }

    const accountId = resolveHistoryAccountId()

    const result = await listWorkflows(
      {
        limit: 50,
        ...(accountId ? { account_id: accountId } : {}),
      },
      { signal: abort.signal },
    )
    if (gen !== fetchGeneration) return

    workflows.value = result.workflows
    total.value = result.total
    if (accountId) {
      setAccountTotal(accountId, result.total)
      setCachedList(accountId, result.workflows, result.total)
    }

    if (hasMultipleAccounts.value) {
      // Await bulk totals so empty auto-browse can see sibling counts.
      await probeAccountTotals(accountId)
      if (gen !== fetchGeneration) return
      if (await maybeAutoBrowseFromEmpty(accountId, result.total, gen)) {
        return
      }
      // Warm the next-most-active sibling so the first manual switch is instant.
      const nextHot = bestSiblingWithHistory(accountId)
      if (nextHot) schedulePrefetch(nextHot.id)
    }
  } catch (e: any) {
    if (gen !== fetchGeneration || isAbortError(e)) return
    // Keep cached rows visible on revalidate failure; only hard-fail empty views.
    if (!revalidate || workflows.value.length === 0) {
      error.value = e.message
    }
  } finally {
    if (listAbort === abort) listAbort = null
    if (gen === fetchGeneration) {
      isLoading.value = false
      isRefreshing.value = false
      isRevalidating.value = false
    }
  }
}

/** Browse another account's history without changing the workspace active account. */
function selectHistoryAccount(accountId: string) {
  if (!accountId || accountId === historyAccountId.value || isPromotingWorkspace.value) return
  if (!resolveOwned(accountId) && accountsStore.accounts.length > 0) return

  applyViewAccount(accountId)

  const cached = getCachedList(accountId)
  if (cached) {
    // Instant paint from memory; skip network when still within TTL.
    workflows.value = cached.workflows
    total.value = cached.total
    setAccountTotal(accountId, cached.total)
    error.value = null
    setStatusFilter('all')
    if (!isCacheFresh(cached)) {
      void fetchWorkflows({ soft: true, accountId, revalidate: true })
    }
    return
  }

  // No cache: clear foreign rows so we never flash another account's items.
  if (workflows.value.length && workflows.value[0]?.account_id !== accountId) {
    workflows.value = []
    total.value = accountChips.value.find(c => c.id === accountId)?.total ?? 0
  }
  setStatusFilter('all')
  void fetchWorkflows({ soft: true, accountId })
}

function backToWorkspaceHistory() {
  autoBrowseNotice.value = null
  const id = accountsStore.activeAccountId
  if (id) selectHistoryAccount(id)
}

function dismissAutoBrowseNotice() {
  autoBrowseNotice.value = null
}

/** Make the currently viewed history account the workspace active account. */
async function promoteToWorkspaceAccount() {
  const accountId = historyAccountId.value
  if (!accountId || accountId === accountsStore.activeAccountId || isPromotingWorkspace.value) return
  isPromotingWorkspace.value = true
  suppressActiveWatch = true
  try {
    await accountsStore.setActiveAccount(accountId)
    applyViewAccount(accountId)
    toastStore.success(
      t('history.workspaceSwitched'),
      t('history.workspaceSwitchedDetail', { name: viewAccountName.value }),
    )
  } catch (e: any) {
    toastStore.error(t('history.switchAccountFailed'), e?.message)
  } finally {
    suppressActiveWatch = false
    isPromotingWorkspace.value = false
  }
}

function onRefreshClick() {
  totalsProbeKey = ''
  const id = resolveHistoryAccountId()
  if (id) invalidateCachedList(id)
  void fetchWorkflows({ soft: workflows.value.length > 0 })
}

onMounted(() => {
  crossAccountHints.hydrateFromSession()
  void crossAccountHints.refreshReviewAwaitingTotals()
  void fetchWorkflows({ soft: false })
})

onUnmounted(() => {
  cancelScheduledPrefetch()
  if (listAbort) {
    listAbort.abort()
    listAbort = null
  }
})

// Navbar / other pages changed the workspace account.
watch(() => accountsStore.activeAccountId, (nextId, prevId) => {
  if (suppressActiveWatch) return
  if (!nextId || nextId === prevId) return
  if (nextId === historyAccountId.value) return
  // Initial workspace hydration: mount fetch owns URL/session/workspace priority.
  if (!prevId) return

  const wasViewingPreviousWorkspace =
    !historyAccountId.value || historyAccountId.value === prevId
  if (!wasViewingPreviousWorkspace) return

  applyViewAccount(nextId)
  if (paintFromCache(nextId)) {
    void fetchWorkflows({ soft: true, accountId: nextId, revalidate: true })
  } else {
    void fetchWorkflows({ soft: true, accountId: nextId })
  }
})

// Browser back/forward or shared ?account= links.
watch(
  () => queryAccountId(),
  (next) => {
    if (isSuppressingQueryWatch()) return
    if (!next || next === historyAccountId.value) return
    if (accountsStore.accounts.length && !resolveOwned(next)) return
    applyViewAccount(next, { syncUrl: false })
    if (paintFromCache(next)) {
      void fetchWorkflows({ soft: true, accountId: next, revalidate: true })
    } else {
      void fetchWorkflows({ soft: true, accountId: next })
    }
  },
)

// Browser back/forward for ?status= filter.
watch(
  () => route.query.status,
  () => {
    if (suppressStatusQueryWatch) return
    const next = statusFromQuery()
    if (next !== statusFilter.value) statusFilter.value = next
  },
)

const statusColor = (status: string) => {
  switch (status) {
    case 'running': return 'bg-teal-500'
    case 'completed': return 'bg-emerald-500'
    case 'error': return 'bg-rose-500'
    case 'cancelled': return 'bg-slate-400'
    default: return 'bg-slate-400'
  }
}

function statusLabel(status: string) {
  const key = `history.status.${status}`
  const translated = t(key)
  // vue-i18n returns the key path when missing; fall back to raw status.
  return translated === key ? status : translated
}

const statusFilterOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const wf of workflows.value) {
    counts.set(wf.status, (counts.get(wf.status) || 0) + 1)
  }
  const options: { value: StatusFilter; label: string; count: number }[] = [
    { value: 'all', label: t('history.filterAll'), count: workflows.value.length },
  ]
  for (const [status, count] of [...counts.entries()].sort((a, b) => b[1] - a[1])) {
    options.push({
      value: status as WorkflowStatus,
      label: statusLabel(status),
      count,
    })
  }
  return options
})

const displayedWorkflows = computed(() => {
  if (statusFilter.value === 'all') return workflows.value
  return workflows.value.filter(w => w.status === statusFilter.value)
})

const phaseLabel = (phase: string) => {
  const map: Record<string, string> = {
    idle: 'review.emptyState.phaseIdle',
    scouting: 'dashboard.timeline.scouting',
    planning: 'dashboard.timeline.planning',
    creating: 'dashboard.timeline.creating',
    reviewing: 'dashboard.timeline.reviewing',
    publishing: 'dashboard.timeline.publishing',
    analyzing: 'dashboard.timeline.analyzing',
    engaging: 'dashboard.timeline.engaging',
    completed: 'dashboard.timeline.completed',
    error: 'dashboard.timeline.error',
    cancelled: 'review.emptyState.phaseCancelled',
  }
  return t(map[phase] || `dashboard.timeline.${phase}`)
}

function formatDate(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString(locale.value, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Carry the local history view account into dashboard deep links. */
function dashboardQuery(extra?: Record<string, string>) {
  return {
    ...accountQuery(historyAccountId.value, {
      omitIfEquals: accountsStore.activeAccountId,
    }),
    ...extra,
  }
}

async function resumeWorkflow(threadId: string) {
  workflowStore.setThreadId(threadId)
  await workflowStore.refreshStatus()
  router.push({ name: 'dashboard', params: { threadId }, query: dashboardQuery() })
}

async function viewWorkflow(threadId: string) {
  workflowStore.setThreadId(threadId)
  await workflowStore.refreshStatus()
  router.push({ name: 'dashboard', params: { threadId }, query: dashboardQuery() })
}

async function replayWorkflow(threadId: string) {
  workflowStore.setThreadId(threadId)
  await workflowStore.refreshStatus()
  router.push({
    name: 'dashboard',
    params: { threadId },
    query: dashboardQuery({ replay: 'true' }),
  })
}

function requestDelete(threadId: string) {
  deleteTarget.value = threadId
  showDeleteModal.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  isDeleting.value = true
  try {
    await deleteWorkflow(deleteTarget.value)
    workflowStore.closeTab(deleteTarget.value)
    workflows.value = workflows.value.filter(w => w.thread_id !== deleteTarget.value)
    total.value = Math.max(0, total.value - 1)
    const viewId = historyAccountId.value
    if (viewId) {
      setAccountTotal(viewId, total.value)
      setCachedList(viewId, workflows.value, total.value)
    }
    toastStore.success(t('history.deleteSuccess'), deleteTarget.value)
  } catch (e: any) {
    toastStore.error(t('history.deleteFailed'), e.message)
  } finally {
    isDeleting.value = false
    showDeleteModal.value = false
    deleteTarget.value = null
  }
}

function openShowcaseSettings(workflow: WorkflowListItem) {
  showcaseTarget.value = workflow
  showcaseVisibility.value = workflow.showcase_visibility && workflow.showcase_visibility !== 'private'
    ? workflow.showcase_visibility
    : 'public'
  showcaseTitle.value = workflow.public_title || workflow.label || ''
  showcaseSummary.value = workflow.public_summary || ''
  showcaseFeatured.value = Boolean(workflow.showcase_featured)
  showcaseFeaturedRank.value = workflow.featured_rank ?? 1
}

function closeShowcaseSettings() {
  if (isUpdatingShowcase.value) return
  showcaseTarget.value = null
}

function showcaseVisibilityLabel(workflow: WorkflowListItem): string {
  if (workflow.showcase_visibility === 'public') return t('history.showcasePublic')
  if (workflow.showcase_visibility === 'unlisted') return t('history.showcaseUnlisted')
  return t('history.showcasePrivate')
}

function isShowcaseLinkable(workflow: WorkflowListItem): boolean {
  return (
    !!workflow.showcase_public_id
    && (workflow.showcase_visibility === 'public' || workflow.showcase_visibility === 'unlisted')
  )
}

function openPublicShowcase(workflow: WorkflowListItem) {
  if (!isShowcaseLinkable(workflow) || !workflow.showcase_public_id) return
  void router.push({
    name: 'replay',
    params: { publicId: workflow.showcase_public_id },
    query: { from: 'history' },
  })
}

async function saveShowcaseSettings() {
  const workflow = showcaseTarget.value
  if (!workflow || isUpdatingShowcase.value) return
  if (!workflow.showcase_public_id) {
    toastStore.error(t('history.showcaseUpdateFailed'), t('common.retry'))
    return
  }

  isUpdatingShowcase.value = true
  try {
    if (showcaseVisibility.value === 'private') {
      await revokeShowcaseVisibility(workflow.showcase_public_id)
      workflow.showcase_visibility = 'private'
      workflow.showcase_featured = false
      workflow.featured_rank = null
      toastStore.success(t('history.showcaseUpdateSuccess'), workflow.label)
      showcaseTarget.value = null
    } else {
      const requestedSummary = showcaseSummary.value.trim() || null
      const payload: ShowcaseVisibilityUpdate = {
        visibility: showcaseVisibility.value,
        public_title: showcaseTitle.value.trim() || null,
        public_summary: requestedSummary,
        featured: showcaseVisibility.value === 'public' && showcaseFeatured.value,
        featured_rank: showcaseVisibility.value === 'public' && showcaseFeatured.value
          ? Math.max(0, Math.min(1000, Math.round(showcaseFeaturedRank.value || 1)))
          : null,
      }
      // LLM summary generation can exceed the default 30s client timeout.
      const response = await updateShowcaseVisibility(workflow.showcase_public_id, payload, {
        timeout: 90_000,
      })
      const autoSummary =
        !requestedSummary && response.summary_auto_generated
          ? (response.case?.summary || response.public_summary || null)
          : null
      const finalSummary = autoSummary || requestedSummary || response.case?.summary || null

      workflow.showcase_visibility = payload.visibility
      workflow.public_title = payload.public_title || response.case?.title || workflow.public_title
      workflow.public_summary = finalSummary
      workflow.showcase_featured = Boolean(payload.featured)
      workflow.featured_rank = payload.featured_rank
      if (response.public_id) workflow.showcase_public_id = response.public_id

      // Keep list cache in sync so soft refresh / account switch doesn't wipe summary.
      const viewId = historyAccountId.value
      if (viewId) setCachedList(viewId, workflows.value, total.value)

      if (autoSummary) {
        // Keep modal open with the filled summary so the operator can review/edit.
        showcaseSummary.value = autoSummary
        if (response.case?.title && !showcaseTitle.value.trim()) {
          showcaseTitle.value = response.case.title
        }
        toastStore.success(
          t('history.showcaseUpdateSuccess'),
          t('history.showcaseSummaryAutoGenerated'),
        )
      } else if (!requestedSummary) {
        toastStore.warning(
          t('history.showcaseUpdateSuccess'),
          t('history.showcaseSummaryAutoFailed'),
        )
        showcaseTarget.value = null
      } else {
        toastStore.success(t('history.showcaseUpdateSuccess'), workflow.label)
        showcaseTarget.value = null
      }
    }
  } catch (e: any) {
    toastStore.error(t('history.showcaseUpdateFailed'), e?.message)
  } finally {
    isUpdatingShowcase.value = false
  }
}

/** Skeleton on first paint, or when soft-switching away from an empty list. */
const showListSkeleton = computed(
  () => isLoading.value || (isRefreshing.value && workflows.value.length === 0 && !error.value),
)
const isEmpty = computed(
  () => !showListSkeleton.value && !error.value && workflows.value.length === 0,
)

const modeLabel = (mode: string) => mode === 'brief' ? t('home.briefMode') : t('home.trendMode')
const modeColor = (mode: string) => mode === 'brief' ? 'bg-pink-50 text-pink-600 border-pink-100' : 'bg-cyan-50 text-cyan-600 border-cyan-100'
</script>

<template>
  <div class="app-page-content space-y-4 md:space-y-6">
    <PageHeader
      :title="t('history.title')"
      :description="t('history.subtitle')"
      :eyebrow="t('nav.sections.insights')"
      icon="History"
      tone="purple"
    >
      <template #meta>
        <span>{{ t('history.scopedTo', { name: viewAccountName }) }}</span>
        <span class="text-slate-300 dark:text-slate-600" aria-hidden="true">·</span>
        <span>{{ t('history.records', { count: total }) }}</span>
      </template>
      <template #actions>
        <NeonButton variant="ghost" size="sm" class="min-h-11" @click="onRefreshClick" :loading="isBusy">
          <AppIcon name="RefreshCw" size="sm" variant="cyan" />
          <span class="hidden sm:inline">{{ t('history.refresh') }}</span>
        </NeonButton>
      </template>
    </PageHeader>

    <AccountScopeBar
      v-if="hasMultipleAccounts"
      :chips="accountChips"
      :label="t('history.accountFilter')"
      tone="violet"
      id-prefix="history-account-chip"
      :disabled="isPromotingWorkspace"
      :workspace-badge-label="t('history.workspaceBadge')"
      :title-for-workspace="t('history.chipTitleWorkspace')"
      :title-for-browse="t('history.chipTitleBrowse')"
      :announce-template="t('history.announceViewing')"
      @select="selectHistoryAccount"
      @prefetch="schedulePrefetch"
    />

    <AccountViewNotice
      v-if="autoBrowseNotice"
      variant="auto"
      :message="t('history.autoBrowseNotice', {
        from: autoBrowseNotice.fromName,
        to: autoBrowseNotice.toName,
        count: autoBrowseNotice.count,
      })"
    >
      <template #actions>
        <NeonButton variant="ghost" size="sm" class="min-h-11" @click="backToWorkspaceHistory">
          {{ t('history.backToWorkspaceHistory', { name: autoBrowseNotice.fromName }) }}
        </NeonButton>
        <NeonButton variant="ghost" size="sm" class="min-h-11" @click="dismissAutoBrowseNotice">
          {{ t('common.close') }}
        </NeonButton>
      </template>
    </AccountViewNotice>

    <AccountViewNotice
      v-if="isViewingNonWorkspace"
      variant="viewOnly"
      :message="t('history.viewOnlyBanner', { view: viewAccountName, workspace: workspaceAccountName })"
    >
      <template #actions>
        <NeonButton variant="ghost" size="sm" class="min-h-11" @click="backToWorkspaceHistory">
          {{ t('history.backToWorkspaceHistory', { name: workspaceAccountName }) }}
        </NeonButton>
        <NeonButton
          variant="cyan"
          size="sm"
          class="min-h-11"
          :loading="isPromotingWorkspace"
          @click="promoteToWorkspaceAccount"
        >
          {{ t('history.useAsWorkspace', { name: viewAccountName }) }}
        </NeonButton>
      </template>
    </AccountViewNotice>

    <!-- Soft refresh / revalidate indicator -->
    <div
      v-if="(isRefreshing || isRevalidating) && workflows.length > 0"
      class="text-[10px] font-medium text-slate-400 md:text-xs"
      role="status"
      aria-live="polite"
    >
      {{ isRevalidating ? t('history.revalidating') : t('history.switchingAccount') }}
    </div>

    <StatusFilterBar
      v-if="!showListSkeleton && !error && workflows.length > 1"
      :label="t('history.statusFilter')"
      :options="statusFilterOptions"
      :model-value="statusFilter"
      @update:model-value="setStatusFilter($event as StatusFilter)"
    />

    <!-- Loading skeleton (first paint or soft switch from empty) -->
    <div v-if="showListSkeleton" class="space-y-3" data-testid="history-skeleton">
      <div v-for="i in 5" :key="i" class="h-20 rounded-xl bg-slate-100 animate-pulse dark:bg-slate-800" />
    </div>

    <!-- Error -->
    <div v-else-if="error" class="rounded-xl p-4 md:p-6 liquid-glass-rose liquid-glass-hover text-center">
      <AppIcon name="AlertTriangle" size="lg" variant="pink" />
      <p class="text-sm text-rose-600 mt-2">{{ error }}</p>
      <NeonButton variant="ghost" size="sm" class="mt-3" @click="onRefreshClick">
        {{ t('common.retry') }}
      </NeonButton>
    </div>

    <!-- Empty State -->
    <div v-else-if="isEmpty" class="rounded-xl md:rounded-2xl p-6 md:p-10 liquid-glass text-center" data-testid="history-empty">
      <div class="w-12 h-12 md:w-16 md:h-16 rounded-xl md:rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-3 md:mb-4 dark:bg-slate-800">
        <AppIcon name="Inbox" size="lg" variant="cyan" class="md:hidden" />
        <AppIcon name="Inbox" size="xl" variant="cyan" class="hidden md:block" />
      </div>
      <h3 class="text-base md:text-lg font-semibold text-slate-700 mb-1">{{ t('history.empty') }}</h3>
      <p class="text-xs md:text-sm text-slate-400 mb-4 md:mb-5">
        {{ t('history.emptyDesc', { name: viewAccountName }) }}
      </p>

      <div
        v-if="siblingHints.length"
        class="mx-auto mb-5 max-w-md rounded-xl border border-violet-100 bg-violet-50/70 p-3 text-left dark:border-violet-500/25 dark:bg-violet-950/30"
        data-testid="history-empty-siblings"
      >
        <p class="mb-2 text-xs font-semibold text-violet-700 dark:text-violet-200">
          {{ t('history.emptyOtherAccounts') }}
        </p>
        <div class="flex flex-col gap-2">
          <NeonButton
            v-for="hint in siblingHints"
            :key="hint.id"
            variant="cyan"
            size="sm"
            class="min-h-11 w-full justify-between"
            :loading="isPromotingWorkspace"
            @click="selectHistoryAccount(hint.id)"
            @mouseenter="schedulePrefetch(hint.id)"
          >
            <span class="truncate">{{ hint.name }}</span>
            <span class="ml-2 shrink-0 text-[10px] opacity-80">
              {{ t('history.siblingCount', { count: hint.total }) }}
            </span>
          </NeonButton>
        </div>
      </div>

      <div
        v-if="reviewSiblingHints.length"
        class="mx-auto mb-5 max-w-md rounded-xl border border-amber-100 bg-amber-50/70 p-3 text-left dark:border-amber-500/25 dark:bg-amber-950/30"
        data-testid="history-empty-review-siblings"
      >
        <p class="mb-2 text-xs font-semibold text-amber-800 dark:text-amber-200">
          {{ t('history.emptyReviewOtherAccounts') }}
        </p>
        <div class="flex flex-col gap-2">
          <NeonButton
            v-for="hint in reviewSiblingHints"
            :key="`review-${hint.id}`"
            variant="peach"
            size="sm"
            class="min-h-11 w-full justify-between"
            @click="openReviewForAccount(hint.id)"
          >
            <span class="truncate">{{ hint.name }}</span>
            <span class="ml-2 shrink-0 text-[10px] opacity-80">
              {{ t('history.reviewSiblingCount', { count: hint.total }) }}
            </span>
          </NeonButton>
        </div>
      </div>

      <div class="flex justify-center gap-3">
        <NeonButton
          variant="pink"
          size="sm"
          @mouseenter="prefetchStartWorkspace({ deep: false, data: true })"
          @focus="prefetchStartWorkspace({ deep: false, data: true })"
          @click="navigateToStart(router)"
        >
          {{ t('history.startNew') }}
        </NeonButton>
        <NeonButton
          variant="ghost"
          size="sm"
          @mouseenter="prefetchRouteChunk('dashboard')"
          @focus="prefetchRouteChunk('dashboard')"
          @click="prefetchRouteChunk('dashboard'); router.push('/dashboard')"
        >
          {{ t('history.backHome') }}
        </NeonButton>
      </div>
    </div>

    <!-- Filter matched nothing (list still has rows) -->
    <div
      v-else-if="workflows.length > 0 && displayedWorkflows.length === 0"
      class="rounded-xl p-6 liquid-glass text-center"
      data-testid="history-filter-empty"
    >
      <p class="text-sm text-slate-500">{{ t('history.filterEmpty') }}</p>
      <NeonButton variant="ghost" size="sm" class="mt-3" @click="setStatusFilter('all')">
        {{ t('history.filterAll') }}
      </NeonButton>
    </div>

    <!-- Workflow List -->
    <div
      v-else
      class="space-y-2 md:space-y-3 transition-opacity duration-200"
      :class="isRevalidating ? 'opacity-80' : 'opacity-100'"
      data-testid="history-list"
    >
      <article
        v-for="wf in displayedWorkflows"
        :key="wf.thread_id"
        class="rounded-xl p-3 md:p-4 liquid-glass liquid-glass-hover hover:border-slate-300 transition-all duration-200"
        :aria-labelledby="`history-workflow-${wf.thread_id}`"
      >
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 sm:gap-2">
          <div class="flex items-center gap-2 md:gap-3 flex-1 min-w-0">
            <span :class="[statusColor(wf.status), 'w-2.5 h-2.5 md:w-3 md:h-3 rounded-full flex-shrink-0']" />

            <div class="flex-1 min-w-0 overflow-hidden">
              <div class="flex items-center gap-1.5 md:gap-2 flex-wrap min-w-0">
                <span :id="`history-workflow-${wf.thread_id}`" class="text-xs md:text-sm font-medium text-slate-700 truncate">{{ wf.label || wf.thread_id.slice(-8) }}</span>
                <span class="text-[10px] md:text-xs font-mono text-slate-400 hidden sm:inline truncate">{{ wf.thread_id }}</span>
                <span v-if="wf.dry_run" class="text-[10px] md:text-xs px-1 md:px-1.5 py-0.5 rounded bg-teal-50 text-teal-600 border border-teal-100 dark:bg-teal-950/45 dark:text-teal-300 dark:border-teal-500/30">
                  {{ t('history.dryRun') }}
                </span>
                <span v-else class="text-[10px] md:text-xs px-1 md:px-1.5 py-0.5 rounded bg-rose-50 text-rose-600 border border-rose-100 dark:bg-rose-950/45 dark:text-rose-300 dark:border-rose-500/30">
                  {{ t('history.live') }}
                </span>
                <span v-if="wf.workflow_mode" class="text-[10px] md:text-xs px-1 md:px-1.5 py-0.5 rounded border"
                  :class="modeColor(wf.workflow_mode)">
                  {{ modeLabel(wf.workflow_mode) }}
                </span>
                <span
                  class="text-[10px] md:text-xs px-1 md:px-1.5 py-0.5 rounded border"
                  :class="wf.showcase_visibility === 'public'
                    ? 'bg-teal-50 text-teal-600 border-teal-100 dark:bg-teal-950/45 dark:text-teal-300 dark:border-teal-500/30'
                    : wf.showcase_visibility === 'unlisted'
                      ? 'bg-amber-50 text-amber-600 border-amber-100 dark:bg-amber-950/45 dark:text-amber-300 dark:border-amber-500/30'
                      : 'bg-slate-50 text-slate-400 border-slate-200 dark:bg-slate-800/60 dark:text-slate-400 dark:border-slate-700'"
                >
                  {{ showcaseVisibilityLabel(wf) }}
                </span>
              </div>
              <div class="flex items-center gap-2 md:gap-3 mt-0.5 md:mt-1 text-[10px] md:text-xs text-slate-400">
                <span>{{ phaseLabel(wf.phase) }}</span>
                <span v-if="statusLabel(wf.status) !== phaseLabel(wf.phase)">{{ statusLabel(wf.status) }}</span>
                <span>{{ formatDate(wf.created_at) }}</span>
              </div>
            </div>
          </div>

          <div class="flex items-center gap-2 md:gap-3 flex-shrink-0 flex-wrap">
            <div class="w-16 md:w-20 hidden sm:block">
              <div class="h-1 md:h-1.5 rounded-full bg-slate-100 overflow-hidden dark:bg-slate-800">
                <div
                  class="h-full rounded-full bg-gradient-to-r from-rose-400 to-teal-400 transition-all"
                  :style="{ width: `${wf.progress_percent}%` }"
                />
              </div>
              <span class="text-[10px] md:text-xs text-slate-400 mt-0.5 block text-right">{{ wf.progress_percent }}%</span>
            </div>

            <div class="flex items-center gap-1.5 md:gap-2">
              <NeonButton
                v-if="wf.status === 'running'"
                variant="cyan"
                size="sm"
                class="min-h-11"
                @click.stop="resumeWorkflow(wf.thread_id)"
              >
                {{ t('history.resume') }}
              </NeonButton>
              <NeonButton
                v-else
                variant="ghost"
                size="sm"
                class="min-h-11"
                @click.stop="viewWorkflow(wf.thread_id)"
              >
                {{ t('history.view') }}
              </NeonButton>
              <NeonButton
                v-if="wf.status !== 'running'"
                variant="cyan"
                size="sm"
                class="min-h-11"
                @click.stop="replayWorkflow(wf.thread_id)"
              >
                {{ t('history.replay') }}
              </NeonButton>
              <NeonButton
                v-if="isShowcaseLinkable(wf)"
                variant="cyan"
                size="sm"
                class="min-h-11"
                @click.stop="openPublicShowcase(wf)"
              >
                <AppIcon name="ExternalLink" size="sm" variant="white" />
                <span class="hidden md:inline">{{ t('history.showcaseOpenPublic') }}</span>
              </NeonButton>
              <NeonButton
                variant="ghost"
                size="sm"
                class="min-h-11"
                @click.stop="openShowcaseSettings(wf)"
              >
                <AppIcon name="Eye" size="sm" variant="cyan" />
                <span class="hidden md:inline">{{ t('history.showcaseManage') }}</span>
              </NeonButton>
              <button
                v-if="wf.status !== 'running'"
                @click.stop="requestDelete(wf.thread_id)"
                class="min-h-11 min-w-11 rounded-lg text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-colors"
                :aria-label="t('history.delete')"
              >
                <AppIcon name="Trash2" size="sm" variant="pink" />
              </button>
            </div>
          </div>
        </div>

        <div v-if="wf.error" class="mt-1.5 md:mt-2 p-1.5 md:p-2 rounded liquid-glass-rose text-[10px] md:text-xs text-rose-600">
          {{ wf.error }}
        </div>
      </article>
    </div>

    <ConfirmModal
      :is-open="showDeleteModal"
      :title="t('history.deleteTitle')"
      :message="deleteMessage"
      :confirm-action="t('history.deleteConfirm')"
      variant="danger"
      @confirm="confirmDelete"
      @cancel="showDeleteModal = false; deleteTarget = null"
    />

    <div
      v-if="showcaseTarget"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm"
      role="presentation"
      @click.self="closeShowcaseSettings"
    >
      <section
        class="w-full max-w-lg rounded-2xl border border-slate-200/80 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900 md:p-6"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`showcase-settings-${showcaseTarget.thread_id}`"
      >
        <div class="flex items-start justify-between gap-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.16em] text-teal-600 dark:text-teal-300">{{ t('history.showcaseManage') }}</p>
            <h2 :id="`showcase-settings-${showcaseTarget.thread_id}`" class="mt-1 text-lg font-semibold text-slate-800 dark:text-slate-100">{{ t('history.showcaseTitle') }}</h2>
            <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ showcaseTarget.label || showcaseTarget.thread_id }}</p>
          </div>
          <button
            type="button"
            class="min-h-11 min-w-11 rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            :aria-label="t('common.close')"
            :disabled="isUpdatingShowcase"
            @click="closeShowcaseSettings"
          >
            <AppIcon name="X" size="sm" aria-hidden="true" />
          </button>
        </div>

        <div class="mt-5 space-y-4">
          <label class="block">
            <span class="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-300">{{ t('history.showcaseVisibility') }}</span>
            <select
              v-model="showcaseVisibility"
              class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
              :disabled="isUpdatingShowcase"
            >
              <option value="public">{{ t('history.showcaseVisibilityPublic') }}</option>
              <option value="unlisted">{{ t('history.showcaseVisibilityUnlisted') }}</option>
              <option value="private">{{ t('history.showcaseVisibilityPrivate') }}</option>
            </select>
          </label>

          <template v-if="showcaseVisibility !== 'private'">
            <label class="block">
              <span class="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-300">{{ t('history.showcaseTitleLabel') }}</span>
              <input
                v-model="showcaseTitle"
                type="text"
                maxlength="120"
                class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
                :placeholder="t('history.showcaseTitlePlaceholder')"
                :disabled="isUpdatingShowcase"
              />
            </label>
            <label class="block">
              <span class="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-300">{{ t('history.showcaseSummaryLabel') }}</span>
              <textarea
                v-model="showcaseSummary"
                rows="3"
                maxlength="360"
                class="w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
                :placeholder="t('history.showcaseSummaryPlaceholder')"
                :disabled="isUpdatingShowcase"
              />
            </label>
            <label v-if="showcaseVisibility === 'public'" class="flex min-h-11 items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              <input v-model="showcaseFeatured" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500" :disabled="isUpdatingShowcase" />
              <span>{{ t('history.showcaseFeatured') }}</span>
            </label>
            <label v-if="showcaseVisibility === 'public' && showcaseFeatured" class="block">
              <span class="mb-1.5 block text-xs font-semibold text-slate-600 dark:text-slate-300">{{ t('history.showcaseFeaturedRank') }}</span>
              <input v-model.number="showcaseFeaturedRank" type="number" min="0" max="1000" class="min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200" :disabled="isUpdatingShowcase" />
            </label>
          </template>
        </div>

        <div class="mt-6 flex justify-end gap-2">
          <button type="button" class="min-h-11 rounded-xl px-4 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800" :disabled="isUpdatingShowcase" @click="closeShowcaseSettings">{{ t('history.showcaseCancel') }}</button>
          <button type="button" class="min-h-11 rounded-xl bg-teal-600 px-4 text-sm font-semibold text-white shadow-sm hover:bg-teal-700 disabled:cursor-wait disabled:opacity-60" :disabled="isUpdatingShowcase" @click="saveShowcaseSettings">{{ isUpdatingShowcase ? t('common.loadingState') : t('history.showcaseSave') }}</button>
        </div>
      </section>
    </div>
  </div>
</template>
