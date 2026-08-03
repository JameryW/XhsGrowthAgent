<script setup lang="ts">
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import ErrorState from '@/components/ErrorState.vue'
import PageHeader from '@/components/PageHeader.vue'
import AccountScopeBar from '@/components/AccountScopeBar.vue'
import AccountViewNotice from '@/components/AccountViewNotice.vue'
import NeonButton from '@/components/NeonButton.vue'
import TooltipHelper from '@/components/TooltipHelper.vue'
import EvaluationRadar from '@/components/charts/EvaluationRadar.vue'
import EvaluationOverview from '@/components/evaluation/EvaluationOverview.vue'
import CreatorQualityPanel from '@/components/settings/CreatorQualityPanel.vue'
import CreatorNoteQualityPanel from '@/components/settings/CreatorNoteQualityPanel.vue'
import { getEvaluationList, getEvaluationResult } from '@/api/evaluation'
import * as analyticsApi from '@/api/analytics'
import type { CreatorNoteStats, CreatorNotesPayload } from '@/api/analytics'
import { useAccountsStore } from '@/stores/accounts'
import { useToastStore } from '@/stores/toast'
import { useLocalAccountBrowse } from '@/composables/useLocalAccountBrowse'
import { useFocusTrap } from '@/composables/useFocusTrap'
import {
  EVALUATION_VIEW_ACCOUNT_KEY,
  accountQuery,
  readQueryString,
  readSessionString,
  withAccountQuery,
  writeSessionString,
} from '@/utils/accountViewSession'
import { EvaluationSkeleton } from '@/components/skeletons'
import { trackInteraction } from '@/utils/interactionTelemetry'
import type {
  EvaluationListItem,
  EvaluationListResponse,
  EvaluationResultResponse,
} from '@/types/evaluation'
import {
  SCORE_THRESHOLDS,
  scoreTier as scoreTierOf,
  RADAR_EXCLUDED_DIMENSIONS,
  DIMENSION_LABEL_KEYS,
} from '@/constants/evaluation'
import { hasSnapshotMismatch } from '@/constants/qualityConsistency'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()

// ── 视图模式：列表 vs 详情（由路由 param 决定）──
const detailThreadId = computed(() => (route.params.threadId as string | undefined) ?? null)
const isDetailView = computed(() => !!detailThreadId.value)

// ── 账号选择（供总览/诊断/单篇流共用）──
// Local view may differ from workspace active — same contract as History /
// Analytics / Review. Intentional browse is preserved across workspace flips.
const accountsStore = useAccountsStore()
const toastStore = useToastStore()
const selectedAccountId = ref('')
const hasUserSelectedAccount = ref(false)

function persistEvaluationAccount(accountId: string | null) {
  writeSessionString(EVALUATION_VIEW_ACCOUNT_KEY, accountId)
}
const isPromotingWorkspace = ref(false)
const selectedAccount = computed(() =>
  accountsStore.accounts.find((account) => account.id === selectedAccountId.value),
)
const hasAccounts = computed(() => accountsStore.accounts.length > 0)

const {
  hasMultipleAccounts,
  isViewingNonWorkspace,
  viewAccountName: viewAccountNameRaw,
  workspaceAccountName: workspaceAccountNameRaw,
  accountChips: evaluationAccountChips,
  selectAccount,
  backToWorkspace,
  promoteToWorkspace,
} = useLocalAccountBrowse({
  accountsStore,
  selectedAccountId,
  locale,
  onSelected: (id, meta) => {
    hasUserSelectedAccount.value = !meta.isWorkspace
    persistEvaluationAccount(meta.isWorkspace ? null : id)
    syncEvaluationAccountQuery(id)
  },
})

const viewAccountName = computed(() => viewAccountNameRaw.value || t('nav.accountSelect'))
const workspaceAccountName = computed(
  () => workspaceAccountNameRaw.value || t('nav.accountSelect'),
)

function selectDefaultAccount() {
  const selectedStillExists = accountsStore.accounts.some(
    (account) => account.id === selectedAccountId.value,
  )
  if (hasUserSelectedAccount.value && selectedStillExists) return

  // URL → session sticky browse → workspace
  const fromQuery = readQueryString(route.query as Record<string, unknown>, 'account')
  if (fromQuery && accountsStore.accounts.some(a => a.id === fromQuery)) {
    selectedAccountId.value = fromQuery
    hasUserSelectedAccount.value = fromQuery !== accountsStore.activeAccountId
    return
  }
  const stored = readSessionString(EVALUATION_VIEW_ACCOUNT_KEY)
  if (stored && accountsStore.accounts.some(a => a.id === stored)) {
    selectedAccountId.value = stored
    hasUserSelectedAccount.value = stored !== accountsStore.activeAccountId
    // Restore sticky browse into the URL so refresh/share keeps scope.
    syncEvaluationAccountQuery(stored)
    return
  }

  const activeAccountExists = accountsStore.accounts.some(
    (account) => account.id === accountsStore.activeAccountId,
  )
  selectedAccountId.value = activeAccountExists
    ? accountsStore.activeAccountId!
    : accountsStore.accounts[0]?.id || ''
  hasUserSelectedAccount.value = false
}

async function refreshAccounts() {
  await accountsStore.fetchAccounts()
  selectDefaultAccount()
}

function syncEvaluationAccountQuery(accountId: string | null) {
  const current = readQueryString(route.query as Record<string, unknown>, 'account')
  const effective =
    accountId && accountId === accountsStore.activeAccountId ? null : accountId
  if ((effective || null) === (current || null)) return
  const nextQuery: Record<string, string | string[]> = {
    ...(route.query as Record<string, string | string[]>),
  }
  if (effective) nextQuery.account = effective
  else delete nextQuery.account
  void router.replace({ query: nextQuery })
}

function onAccountSelected(accountId: string) {
  selectAccount(accountId)
}

async function promoteEvaluationAccountToWorkspace() {
  if (isPromotingWorkspace.value) return
  isPromotingWorkspace.value = true
  try {
    const result = await promoteToWorkspace()
    if (result.ok) {
      hasUserSelectedAccount.value = false
      persistEvaluationAccount(null)
      syncEvaluationAccountQuery(null)
      toastStore.success(
        t('history.workspaceSwitched'),
        t('history.workspaceSwitchedDetail', { name: result.name }),
      )
    } else if (result.error && result.error !== 'noop') {
      toastStore.error(t('history.switchAccountFailed'), result.error)
    }
  } finally {
    isPromotingWorkspace.value = false
  }
}

function backToWorkspaceEvaluation() {
  hasUserSelectedAccount.value = false
  persistEvaluationAccount(null)
  backToWorkspace()
  syncEvaluationAccountQuery(null)
}

function openSettings() {
  void router.push('/settings')
}

watch(
  () => [accountsStore.activeAccountId, accountsStore.accounts] as const,
  (current, previous) => {
    const activeId = current[0]
    const prevActiveId = previous?.[0]
    if (activeId && prevActiveId && activeId !== prevActiveId) {
      // Follow workspace only when we were on the previous workspace account
      // (or never manually browsed). Keep intentional non-workspace browse.
      if (!hasUserSelectedAccount.value || selectedAccountId.value === prevActiveId) {
        hasUserSelectedAccount.value = false
      }
    }
    selectDefaultAccount()
  },
  { immediate: true },
)

// Honor ?account= deep links on the evaluation hub.
watch(
  () => readQueryString(route.query as Record<string, unknown>, 'account'),
  (next) => {
    if (!next || next === selectedAccountId.value) return
    if (accountsStore.accounts.length && !accountsStore.accounts.some(a => a.id === next)) return
    selectedAccountId.value = next
    hasUserSelectedAccount.value = next !== accountsStore.activeAccountId
  },
  { immediate: true },
)

// ── 历史笔记（单篇流的第二数据源；账号切换时重载）──
const notesItems = ref<CreatorNoteStats[]>([])
const notesTotal = ref(0)
const notesCursor = ref<string | null>(null)
const notesDataAsOf = ref<string | null>(null)
const notesSnapshotId = ref<string | null>(null)
const notesSnapshotMismatch = ref(false)
const notesLoading = ref(false)
const notesError = ref<string | null>(null)
let notesRequest = 0

async function readNotesPage(accountId: string, cursor: string | null = null): Promise<CreatorNotesPayload> {
  // Older test fixtures/backends only expose the bounded overview. Keep the
  // adapter local so every new UI reader still shares the canonical payload
  // shape when the endpoint is available.
  let reader: typeof analyticsApi.getCreatorNotes | undefined
  try { reader = analyticsApi.getCreatorNotes } catch { reader = undefined }
  if (typeof reader === 'function') {
    try {
      return await reader(accountId, {
        cursor,
        limit: 50,
        sort: 'published_at_desc',
      }, { suppressToast: true })
    } catch {
      // Older deployments (and tests with an unavailable canonical reader)
      // may only expose the bounded overview endpoint. Keep the page usable
      // while retaining the canonical shape for the upgraded endpoint.
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
    engagement_rate_unit: legacy.engagement_rate_unit,
    query: { sort: 'published_at_desc', published_from: null, published_to: null },
  }
}

async function loadNotes(accountId: string, reset = true) {
  const request = ++notesRequest
  if (reset) {
    notesItems.value = []
    notesTotal.value = 0
    notesCursor.value = null
    notesDataAsOf.value = null
    notesSnapshotId.value = null
    notesSnapshotMismatch.value = false
  }
  notesError.value = null
  if (!accountId) {
    notesLoading.value = false
    return
  }
  notesLoading.value = true
  try {
    const stats = await readNotesPage(accountId, reset ? null : notesCursor.value)
    if (request !== notesRequest) return
    const incoming = (stats.items || []).filter((note) => Boolean(note.note_id))
    if (!reset && hasSnapshotMismatch(notesSnapshotId.value, stats.snapshot_id)) {
      notesSnapshotMismatch.value = true
      trackInteraction('quality_note_set_mismatch', { source: 'quality', count: 1 })
      trackInteraction('quality_snapshot_lag', { source: 'quality', count: 1 })
      return
    }
    notesItems.value = reset ? incoming : [...notesItems.value, ...incoming]
    notesTotal.value = Number.isFinite(stats.total) ? stats.total : notesItems.value.length
    notesCursor.value = stats.next_cursor ?? null
    notesDataAsOf.value = stats.data_as_of ?? null
    notesSnapshotId.value = stats.snapshot_id ?? notesSnapshotId.value
  } catch (e) {
    if (request === notesRequest) notesError.value = (e as Error).message || t('evaluation.stream.notesUnavailable')
  } finally {
    if (request === notesRequest) notesLoading.value = false
  }
}

const notesHasMore = computed(() => Boolean(notesCursor.value) && notesItems.value.length < notesTotal.value)

function loadMoreNotes() {
  if (!notesLoading.value && notesHasMore.value) void loadNotes(selectedAccountId.value, false)
}

// ════════════════════════════════════════════════════════════
// 列表页状态
// ════════════════════════════════════════════════════════════
const listItems = ref<EvaluationListItem[]>([])
const listTotal = ref(0)
const listLimit = 20
const listOffset = ref(0)
const listSnapshotId = ref<string | null>(null)
const listSnapshotMismatch = ref(false)
const listDataAsOf = ref<string | null>(null)
const listLoading = ref(false)
const listError = ref<string | null>(null)
const searchQuery = ref('')
let listRequest = 0

// Historical-note drawer state is declared before the account watcher below;
// the watcher runs immediately during setup and must be able to clear stale
// cross-account subjects safely.
const drawerNoteId = ref('')
const drawerNoteTitle = ref('')

async function loadList(reset = false, accountId = selectedAccountId.value) {
  const request = ++listRequest
  if (!accountId) {
    listItems.value = []
    listTotal.value = 0
    listOffset.value = 0
    listLoading.value = false
    listError.value = null
    return
  }
  listLoading.value = true
  listError.value = null
  if (reset) {
    listOffset.value = 0
    listItems.value = []
    listSnapshotId.value = null
    listSnapshotMismatch.value = false
    listDataAsOf.value = null
  }
  try {
    const res: EvaluationListResponse = await getEvaluationList(
      accountId,
      listLimit,
      listOffset.value,
      { suppressToast: true },
    )
    if (request !== listRequest || accountId !== selectedAccountId.value) return
    const foreignRows = res.workflows.filter((item) => item.account_id !== accountId).length
    if (foreignRows > 0) {
      trackInteraction('quality_cross_account_row', { source: 'quality', count: foreignRows })
    }
    if (res.total > res.workflows.length) {
      trackInteraction('quality_list_truncated', { source: 'quality', count: res.total })
    }
    if (!reset && hasSnapshotMismatch(listSnapshotId.value, res.snapshot_id)) {
      listSnapshotMismatch.value = true
      trackInteraction('quality_note_set_mismatch', { source: 'quality', count: 1 })
      trackInteraction('quality_snapshot_lag', { source: 'quality', count: 1 })
      return
    }
    if (reset) {
      listItems.value = res.workflows
    } else {
      listItems.value = [...listItems.value, ...res.workflows]
    }
    listTotal.value = res.total
    listSnapshotId.value = res.snapshot_id ?? listSnapshotId.value
    listDataAsOf.value = res.data_as_of ?? null
  } catch (e) {
    if (request !== listRequest || accountId !== selectedAccountId.value) return
    listError.value = (e as Error).message || t('evaluation.list.loadError')
  } finally {
    if (request === listRequest) listLoading.value = false
  }
}

// listItems already contains every page loaded so far; adding the current
// offset double-counts after the first load and can hide remaining pages.
const hasMore = computed(() => listItems.value.length < listTotal.value)

function loadMore() {
  if (listLoading.value || !selectedAccountId.value) return
  listOffset.value = listItems.value.length
  void loadList(false, selectedAccountId.value)
}

watch(selectedAccountId, (accountId) => {
  // A drawer belongs to the previous account's subject. Close it before the
  // new account's paged reader resolves so no old note briefly renders under
  // a different account scope.
  drawerNoteId.value = ''
  drawerNoteTitle.value = ''
  if (!isDetailView.value) {
    // Account changes invalidate every paged collection immediately. The
    // request generation guards prevent late rows from the old account from
    // flashing into the new scope.
    void loadNotes(accountId, true)
    void loadList(true, accountId)
  }
}, { immediate: true })

// 前端过滤：标题 + thread_id + account_id + decision (EV-09)
const decisionFilter = ref<string>('all')
const filteredItems = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return listItems.value.filter((w) => {
    if (selectedAccountId.value && w.account_id !== selectedAccountId.value) return false
    if (decisionFilter.value !== 'all' && w.decision !== decisionFilter.value) return false
    if (!q) return true
    const title = (w.selected_title || '').toLowerCase()
    const tid = (w.thread_id || '').toLowerCase()
    const acc = (w.account_id || '').toLowerCase()
    return title.includes(q) || tid.includes(q) || acc.includes(q)
  })
})

function openDetail(threadId: string) {
  trackInteraction('evaluation_drilldown', { method: 'click' })
  router.push({
    name: 'evaluation-detail',
    params: { threadId },
    query: withAccountQuery(
      { tab: 'workflow' },
      selectedAccountId.value,
      { omitIfEquals: accountsStore.activeAccountId },
    ),
  })
}

function setDecisionFilter(opt: string) {
  decisionFilter.value = opt
  trackInteraction('evaluation_filter_change', { decision: opt })
}

function evaluationActionCta(target: 'review' | 'dashboard') {
  trackInteraction('evaluation_decision_cta', { decision: ev.value?.decision ?? '', method: target })
  if (!detailThreadId.value) return
  const q = accountQuery(selectedAccountId.value, {
    omitIfEquals: accountsStore.activeAccountId,
  })
  if (target === 'review') {
    router.push({ name: 'review', params: { threadId: detailThreadId.value }, query: q })
  } else {
    router.push({ name: 'dashboard', params: { threadId: detailThreadId.value }, query: q })
  }
}

function backToList() {
  router.push({
    name: 'evaluation',
    query: withAccountQuery(
      { tab: sourceTab.value },
      selectedAccountId.value,
      { omitIfEquals: accountsStore.activeAccountId },
    ),
  })
}

// EV-01: copy the evaluated thread id for support/handoff.
async function copyThreadId() {
  if (!detailThreadId.value) return
  try {
    await navigator.clipboard.writeText(detailThreadId.value)
  } catch {
    // clipboard may be unavailable; silent — the id is still visible.
  }
}

// 列表页首次挂载加载
onMounted(async () => {
  if (isDetailView.value) return
  await refreshAccounts()
  if (selectedAccountId.value && !listItems.value.length && !listLoading.value) {
    await loadList(true, selectedAccountId.value)
  }
})

// 路由切换到列表页时按需加载（从详情返回且列表为空）
watch(isDetailView, (detail) => {
  if (!detail && listItems.value.length === 0 && !listLoading.value) {
    void loadList(true)
  }
})

// ── 来源分离：已发布历史笔记与工作流内容评审 ──
type SourceTab = 'historical' | 'workflow'
const sourceTab = ref<SourceTab>(route.query.tab === 'workflow' ? 'workflow' : 'historical')
const historicalAvailable = computed(() => Boolean(selectedAccountId.value))

watch(selectedAccountId, (accountId) => {
  if (!accountId && sourceTab.value !== 'workflow') {
    sourceTab.value = 'workflow'
    void router.replace({ query: { ...route.query, tab: 'workflow' } })
  }
})

const workflowRows = computed(() => filteredItems.value
  .slice()
  .sort((a, b) => (new Date(b.updated_at).getTime() || 0) - (new Date(a.updated_at).getTime() || 0)))

const historicalRows = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return notesItems.value
    .filter((note) => !selectedAccountId.value || note.account_id === selectedAccountId.value)
    .filter((note) => !q || (note.title || '').toLowerCase().includes(q) || note.note_id.toLowerCase().includes(q))
    .slice()
    .sort((a, b) => {
      const at = new Date(a.published_at || a.synced_at || '').getTime() || 0
      const bt = new Date(b.published_at || b.synced_at || '').getTime() || 0
      return bt - at || b.note_id.localeCompare(a.note_id)
    })
})

const visibleRowsCount = computed(() => sourceTab.value === 'workflow' ? workflowRows.value.length : historicalRows.value.length)
const visibleRowsTotal = computed(() => sourceTab.value === 'workflow' ? listTotal.value : notesTotal.value)
// 空态分流：有行但被当前搜索/筛选滤光 ≠ 账号下本来没有行（文档要求分开表达）。
const underlyingRowsCount = computed(() => (sourceTab.value === 'workflow' ? listItems.value : notesItems.value).length)

function clearFilters() {
  searchQuery.value = ''
  decisionFilter.value = 'all'
}

function goStartCreating() {
  void router.push('/start')
}

function setSourceTab(tab: SourceTab) {
  sourceTab.value = tab
  if (tab === 'workflow') decisionFilter.value = 'all'
  void router.replace({ query: { ...route.query, tab } })
}

// ── 历史笔记下钻抽屉 ──
function openNoteDrawer(note: CreatorNoteStats) {
  drawerNoteId.value = note.note_id
  drawerNoteTitle.value = note.title
  trackInteraction('evaluation_note_drilldown', { method: 'click' })
}

function closeNoteDrawer() {
  drawerNoteId.value = ''
}

// Trap focus inside the note drawer while it is open and restore it on close
// (same useFocusTrap pattern as the Analytics drill-down drawer).
const noteDrawerFocusTrap = useFocusTrap()
const noteDrawerRef = ref<HTMLElement | null>(null)
watch(drawerNoteId, async (noteId) => {
  if (noteId) {
    await nextTick()
    noteDrawerFocusTrap.activate(noteDrawerRef.value)
  } else {
    noteDrawerFocusTrap.deactivate()
  }
})

function formatCompact(value: number | undefined): string {
  if (value == null) return '0'
  return new Intl.NumberFormat(locale.value || undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

// 列表项的 decision 徽章 class
function decisionBadgeClass(decision: string): string {
  if (decision === 'approved') return 'decision-approved'
  if (decision === 'needs_revision') return 'decision-revision'
  return 'decision-rejected'
}

const DECISION_KEYS: Record<string, string> = {
  approved: 'evaluation.decision.approved',
  needs_revision: 'evaluation.decision.needs_revision',
  rejected: 'evaluation.decision.rejected',
}

function decisionLabel(decision: string): string {
  return t(DECISION_KEYS[decision] ?? 'evaluation.decision.unknown')
}

// EV-04: thresholds live in constants/evaluation.ts; map the tier to the
// CSS class used by list rows and the detail badge.
function scoreTierClass(
  score: number | null | undefined,
  thresholds = SCORE_THRESHOLDS,
): string {
  switch (scoreTierOf(score, thresholds)) {
    case 'pass': return 'score-pass'
    case 'warn': return 'score-warn'
    case 'fail': return 'score-fail'
    default: return 'score-none'
  }
}

function formatDateTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString(locale.value || undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function phaseLabel(phase: string): string {
  const key = `dashboard.timeline.${phase}`
  // 兜底：未知 phase 原样返回
  return t(key) === key ? phase : t(key)
}

// ════════════════════════════════════════════════════════════
// 详情页状态（复用原有评估结果展示逻辑）
// ════════════════════════════════════════════════════════════
const result = ref<EvaluationResultResponse | null>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)

const ev = computed(() => result.value?.evaluation_result)
const hasResult = computed(() => !!result.value && result.value.has_evaluation && !!ev.value)
const scoreThresholds = computed(() => result.value?.thresholds ?? SCORE_THRESHOLDS)
const detailStatus = computed(() => {
  const status = result.value?.status || ev.value?.status
  if (result.value?.degraded || ev.value?.degraded) return 'degraded'
  return status || 'ready'
})
const detailUnavailable = computed(() => ['unavailable', 'degraded', 'failed', 'running'].includes(detailStatus.value))

async function loadDetail(threadId: string) {
  detailLoading.value = true
  detailError.value = null
  result.value = null
  try {
    result.value = await getEvaluationResult(threadId, { suppressToast: true })
  } catch (e) {
    detailError.value = (e as Error).message || t('evaluation.error.fetch')
  } finally {
    detailLoading.value = false
  }
}

function retryDetail() {
  if (detailThreadId.value) void loadDetail(detailThreadId.value)
}

// 进入详情页 / thread_id 变化时加载
watch(
  detailThreadId,
  (tid) => {
    if (tid) loadDetail(tid)
  },
  { immediate: true },
)

const scoreClass = computed(() => scoreTierClass(ev.value?.overall_score, scoreThresholds.value))
// EV-07: dimension count is data-driven, not hardcoded "9-Dimension".
const radarDimensionCount = computed(() =>
  (ev.value?.dimensions || []).filter((d) => !RADAR_EXCLUDED_DIMENSIONS.includes(d.dimension)).length,
)
// EV-06: bias severity lives on the bias_check dimension, not the top-level
// result. Escalate the alert visually when severity is high.
const biasSeverity = computed(() => {
  const dim = (ev.value?.dimensions || []).find((d) => d.dimension === 'bias_check')
  return dim?.bias_severity ?? null
})
const biasCardClass = computed(() => {
  const sev = biasSeverity.value
  if (sev == null || !Number.isFinite(sev)) return ''
  // bias_severity is a 0–100 score (higher means worse), matching the
  // evaluator prompt/state contract.
  if (sev >= 70) return 'bias-card--high'
  if (sev >= 40) return 'bias-card--med'
  return ''
})

const detailDecisionClass = computed(() => {
  const d = ev.value?.decision
  if (!d || detailUnavailable.value) return 'decision-unknown'
  if (d === 'approved') return 'decision-approved'
  if (d === 'needs_revision') return 'decision-revision'
  return 'decision-rejected'
})

const DETAIL_DECISION_KEYS: Record<string, string> = {
  approved: 'evaluation.decision.approved',
  needs_revision: 'evaluation.decision.needs_revision',
  rejected: 'evaluation.decision.rejected',
}

function dimLabel(dim: string): string {
  return t(DIMENSION_LABEL_KEYS[dim] ?? 'evaluation.dim.unknown', { dim })
}

function dimDescription(dim: string): string {
  const key = `evaluation.dimHelp.${dim}`
  return t(key) === key ? t('evaluation.dimHelp.unknown') : t(key)
}
</script>

<template>
  <div class="app-page-content evaluation-view">
    <!-- ════════ 列表视图 ════════ -->
    <template v-if="!isDetailView">
      <PageHeader
        :title="t('evaluation.title')"
        :description="t('creatorQuality.page.hubSubtitle')"
        icon="ClipboardCheck"
        tone="purple"
        title-id="evaluation-title"
      />

      <AccountScopeBar
        v-if="hasMultipleAccounts"
        class="eval-section"
        :chips="evaluationAccountChips"
        :label="t('history.accountFilter')"
        tone="violet"
        id-prefix="evaluation-account-chip"
        :disabled="isPromotingWorkspace"
        :workspace-badge-label="t('history.workspaceBadge')"
        :title-for-workspace="t('history.chipTitleWorkspace')"
        :title-for-browse="t('evaluation.chipTitleBrowse')"
        :announce-template="t('history.announceViewing')"
        @select="onAccountSelected"
      />

      <AccountViewNotice
        v-if="isViewingNonWorkspace"
        class="eval-section"
        variant="viewOnly"
        :message="t('evaluation.viewOnlyBanner', {
          view: viewAccountName,
          workspace: workspaceAccountName,
        })"
      >
        <template #actions>
          <NeonButton variant="ghost" size="sm" class="min-h-11" @click="backToWorkspaceEvaluation">
            {{ t('evaluation.backToWorkspace', { name: workspaceAccountName }) }}
          </NeonButton>
          <NeonButton
            variant="cyan"
            size="sm"
            class="min-h-11"
            :loading="isPromotingWorkspace"
            @click="promoteEvaluationAccountToWorkspace"
          >
            {{ t('history.useAsWorkspace', { name: viewAccountName }) }}
          </NeonButton>
        </template>
      </AccountViewNotice>

      <!-- 融合总览：历史账户分 × 单篇评估趋势 -->
      <EvaluationOverview
        class="eval-section"
        :account-id="selectedAccountId"
        :accounts="accountsStore.accounts"
        :active-account-id="accountsStore.activeAccountId"
        :accounts-loading="accountsStore.isLoading"
        :hide-account-selector="hasMultipleAccounts"
        :evaluated-total="listTotal"
        @update:account-id="onAccountSelected"
        @refresh-accounts="refreshAccounts"
      />

      <!-- 无账号：引导前往设置页导入数据 -->
      <section v-if="!hasAccounts" class="dark-explicit eval-section rounded-2xl border border-dashed border-slate-300 bg-white/70 px-5 py-10 text-center dark:border-slate-600 dark:bg-slate-900/60">
        <div class="dark-explicit mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 dark:bg-slate-800">
          <AppIcon name="Database" size="lg" variant="cyan" />
        </div>
        <h3 class="dark-explicit mt-4 text-base font-semibold text-slate-700 dark:text-slate-200">{{ t('creatorQuality.page.noAccountTitle') }}</h3>
        <p class="dark-explicit mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">{{ t('creatorQuality.page.noAccountDescription') }}</p>
        <button type="button" class="mt-5 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 to-amber-500 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:shadow-md" @click="openSettings">
          <AppIcon name="Settings" size="sm" variant="white" />
          {{ t('creatorQuality.page.manageAccounts') }}
        </button>
      </section>

      <!-- 诊断区块：历史创作质量（账户级报告） -->
      <section v-if="selectedAccount" class="eval-section" :aria-label="t('creatorQuality.title')">
        <div class="section-head">
          <p class="section-eyebrow">{{ t('evaluation.section.diagnosis') }}</p>
          <h2 class="section-title">{{ t('creatorQuality.title') }}</h2>
        </div>
        <CreatorQualityPanel :account-id="selectedAccount.id" :account-name="selectedAccount.name" compact class="shadow-sm" />
      </section>

      <!-- 单篇区块：来源分离，避免将发布后表现与内容评审混成一个分数 -->
      <section class="eval-section" :aria-label="t('evaluation.section.content')">
        <div class="section-head">
          <p class="section-eyebrow">{{ t('evaluation.section.content') }}</p>
          <h2 class="section-title">{{ t('evaluation.stream.title') }}</h2>
          <p class="section-description">{{ t('evaluation.stream.separationHint') }}</p>
        </div>

        <div class="source-tabs" role="tablist" :aria-label="t('evaluation.stream.tabsLabel')">
          <button v-if="historicalAvailable" type="button" role="tab" class="source-tab min-h-11" :class="{ 'source-tab--active': sourceTab === 'historical' }" :aria-selected="sourceTab === 'historical'" @click="setSourceTab('historical')">
            {{ t('evaluation.stream.historicalTab') }}
            <span class="source-tab-count">{{ notesItems.length }} / {{ notesTotal }}</span>
          </button>
          <button type="button" role="tab" class="source-tab min-h-11" :class="{ 'source-tab--active': sourceTab === 'workflow' }" :aria-selected="sourceTab === 'workflow'" @click="setSourceTab('workflow')">
            {{ t('evaluation.stream.workflowTab') }}
            <span class="source-tab-count">{{ listItems.length }} / {{ listTotal }}</span>
          </button>
        </div>


        <div v-if="notesSnapshotMismatch || listSnapshotMismatch" class="dark-explicit mt-3 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50/80 px-3 py-2 text-xs leading-5 text-amber-700 dark:border-amber-400/30 dark:bg-amber-950/30 dark:text-amber-200" role="alert">
          <AppIcon name="AlertTriangle" size="sm" variant="peach" />
          <span class="flex-1">{{ t('evaluation.snapshotMismatch') }}</span>
          <button type="button" class="dark-explicit min-h-9 rounded-md border border-amber-300 px-2 font-semibold hover:bg-amber-100 dark:border-amber-400/40 dark:hover:bg-amber-900/40" @click="sourceTab === 'historical' ? loadNotes(selectedAccountId, true) : loadList(true, selectedAccountId)">{{ t('evaluation.error.retry') }}</button>
        </div>

        <section v-if="sourceTab === 'workflow'" class="filter-chips" role="group" :aria-label="t('evaluation.list.filterLabel')">
          <button v-for="opt in ['all', 'approved', 'needs_revision', 'rejected']" :key="opt" type="button" class="filter-chip min-h-11" :class="{ 'filter-chip--active': decisionFilter === opt }" :aria-pressed="decisionFilter === opt" @click="setDecisionFilter(opt)">
            {{ opt === 'all' ? t('evaluation.list.filterAll') : decisionLabel(opt) }}
          </button>
        </section>

        <section class="search-bar">
          <input v-model="searchQuery" class="thread-input" :aria-label="t('evaluation.list.searchPlaceholder')" :placeholder="t('evaluation.list.searchPlaceholder')" />
          <!-- Loaded/total counts live on the source tabs; this count appears
               only while filtering, as feedback on the active query. -->
          <span v-if="searchQuery.trim()" class="result-count">{{ t('evaluation.list.loadedCount', { loaded: visibleRowsCount, total: visibleRowsTotal }) }}</span>
        </section>

        <ErrorState v-if="sourceTab === 'workflow' && listError" variant="api" :message="listError" :retry-label="t('evaluation.error.retry')" hide-dismiss @retry="loadList(true, selectedAccountId)" />
        <ErrorState v-if="sourceTab === 'historical' && notesError" variant="api" :message="notesError" :retry-label="t('evaluation.error.retry')" hide-dismiss @retry="loadNotes(selectedAccountId, true)" />

        <EvaluationSkeleton v-if="(sourceTab === 'workflow' ? listLoading && !listItems.length : notesLoading && !notesItems.length)" variant="list" />

        <!-- 筛选无结果：有数据但被当前搜索/筛选滤光，给出清除筛选动作 -->
        <div v-else-if="visibleRowsCount === 0 && underlyingRowsCount > 0 && !(sourceTab === 'workflow' ? listError : notesError)" class="empty-state">
          <AppIcon name="SearchX" size="xl" variant="muted" />
          <div class="empty-title">{{ t('evaluation.list.noMatch') }}</div>
          <button type="button" class="load-more-btn min-h-11" @click="clearFilters">
            {{ t('showcase.resetFilters') }}
          </button>
        </div>

        <!-- 真空列表：按来源给出下一步动作 -->
        <div v-else-if="visibleRowsCount === 0 && !(sourceTab === 'workflow' ? listError : notesError)" class="empty-state">
          <AppIcon name="HelpCircle" size="xl" variant="muted" />
          <div class="empty-title">{{ sourceTab === 'workflow' ? t('evaluation.list.empty') : t('evaluation.stream.historicalEmpty') }}</div>
          <button v-if="sourceTab === 'workflow'" type="button" class="min-h-11 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 to-amber-500 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:shadow-md" @click="goStartCreating">
            <AppIcon name="Plus" size="sm" variant="white" />
            {{ t('nav.startWorkflow') }}
          </button>
          <button v-else type="button" class="min-h-11 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-rose-500 to-amber-500 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:shadow-md" @click="openSettings">
            <AppIcon name="Settings" size="sm" variant="white" />
            {{ t('creatorQuality.page.manageAccounts') }}
          </button>
        </div>

        <div v-else class="eval-list">
          <div v-if="sourceTab === 'historical' && notesLoading" class="notes-hint" aria-busy="true">{{ t('creatorNoteQuality.loading') }}</div>
          <div v-if="sourceTab === 'workflow' && listLoading" class="notes-hint" aria-busy="true">{{ t('evaluation.list.loading') }}</div>
          <template v-if="sourceTab === 'workflow'">
            <button v-for="item in workflowRows" :key="item.thread_id" type="button" class="eval-item" :aria-label="`${item.selected_title || t('evaluation.empty.title')} · ${decisionLabel(item.decision || 'unknown')}`" @click="openDetail(item.thread_id)">
              <div class="item-main">
                <div class="item-title">{{ item.selected_title || t('evaluation.empty.title') }}</div>
                <div class="item-meta"><span class="source-badge source-workflow">{{ t('evaluation.stream.sourceWorkflow') }}</span><span class="meta-tag">{{ phaseLabel(item.phase) }}</span><span class="meta-sep">·</span><span class="meta-time">{{ formatDateTime(item.updated_at) }}</span></div>
              </div>
              <div class="item-right"><span class="score-kind">{{ t('evaluation.rqgmScoreLabel') }}</span><span class="item-score" :class="scoreTierClass(item.overall_score, { pass: item.pass_threshold ?? SCORE_THRESHOLDS.pass, warn: item.warn_threshold ?? SCORE_THRESHOLDS.warn })">{{ item.overall_score == null || item.degraded || item.status_detail === 'degraded' || item.status_detail === 'failed' ? '—' : item.overall_score.toFixed(1) }}</span><span class="decision-badge" :class="decisionBadgeClass(item.decision || 'unknown')">{{ item.degraded ? t('evaluation.status.degraded') : decisionLabel(item.decision || 'unknown') }}</span></div>
            </button>
          </template>
          <template v-else>
            <button v-for="note in historicalRows" :key="note.note_id" type="button" class="eval-item" :aria-label="`${note.title || t('creatorNoteQuality.untitled')} · ${t('evaluation.stream.sourceImported')}`" @click="openNoteDrawer(note)">
              <div class="item-main"><div class="item-title">{{ note.title || t('creatorNoteQuality.untitled') }}</div><div class="item-meta"><span class="source-badge source-imported">{{ t('evaluation.stream.sourceImported') }}</span><span class="meta-time">{{ formatDateTime(note.published_at) }}</span></div></div>
              <div class="item-right item-right-note"><span class="score-kind">{{ t('evaluation.performanceScoreLabel') }}</span><span class="note-metric">{{ t('creatorNoteQuality.metrics.views') }} {{ formatCompact(note.views) }}</span><span class="note-metric">{{ t('creatorNoteQuality.metrics.likes') }} {{ formatCompact(note.likes) }}</span></div>
            </button>
          </template>
        </div>

        <div v-if="sourceTab === 'workflow' && hasMore" class="load-more"><button class="load-more-btn min-h-11" type="button" :disabled="listLoading" @click="loadMore"><AppIcon v-if="listLoading" name="Loader2" variant="muted" class="spin" /><span>{{ t('evaluation.list.loadMore') }}</span></button></div>
        <div v-if="sourceTab === 'historical' && notesHasMore" class="load-more"><button class="load-more-btn min-h-11" type="button" :disabled="notesLoading" @click="loadMoreNotes"><AppIcon v-if="notesLoading" name="Loader2" variant="muted" class="spin" /><span>{{ t('evaluation.list.loadMore') }}</span></button></div>
        <div v-if="(sourceTab === 'workflow' ? listItems.length : notesItems.length) > 0 && (sourceTab === 'workflow' ? listDataAsOf : notesDataAsOf)" class="data-as-of" role="status">
          <!-- Counts are on the source tabs; this line carries only the
               snapshot timestamp. -->
          <span>{{ t('evaluation.dataAsOf') }} {{ formatDateTime((sourceTab === 'workflow' ? listDataAsOf : notesDataAsOf)!) }}</span>
        </div>
      </section>
    </template>

    <!-- ════════ 详情视图 ════════ -->
    <template v-else>
      <PageHeader
        :title="t('evaluation.list.detailTitle')"
        :eyebrow="t('nav.evaluation')"
        icon="ClipboardCheck"
        tone="purple"
        title-id="evaluation-detail-title"
      >
        <!-- EV-01: deep-link context — show which thread was judged so a user
             arriving at /evaluation/:threadId can confirm and copy the id.
             The decision badge lives in the overview card below; repeating it
             here showed the same badge twice. -->
        <template v-if="detailThreadId" #meta>
          <span class="font-mono">{{ detailThreadId.slice(-8) }}</span>
          <button type="button" class="dark-explicit copy-thread min-h-9 px-2 text-xs rounded-md border border-slate-200 hover:bg-slate-50 dark:border-slate-600 dark:hover:bg-slate-800" @click="copyThreadId">
            <AppIcon name="Copy" size="sm" variant="muted" />
            {{ t('evaluation.action.copyId') }}
          </button>
        </template>
        <template #actions>
          <button type="button" class="back-btn min-h-11" @click="backToList">
            <AppIcon name="ArrowLeft" variant="muted" />
            <span>{{ t('evaluation.list.back') }}</span>
          </button>
        </template>
      </PageHeader>

      <!-- 加载中 -->
      <EvaluationSkeleton v-if="detailLoading" variant="detail" />

      <!-- 错误 (INF-01: shared presentational ErrorState) -->
      <ErrorState v-else-if="detailError" variant="api" :message="detailError" :retry-label="t('evaluation.error.retry')" hide-dismiss @retry="retryDetail" />

      <!-- 空状态：无评估结果 -->
      <div v-else-if="hasResult === false && result" class="empty-state">
        <AppIcon name="HelpCircle" size="xl" variant="muted" />
        <div class="empty-title">{{ t('evaluation.empty.title') }}</div>
        <div class="empty-desc">{{ t('evaluation.empty.desc') }}</div>
      </div>

      <!-- 结果展示（复用原有结构） -->
      <div v-if="hasResult && ev" class="result-grid">
        <!-- 总分 + 决策 -->
        <section class="overview-card">
          <div class="score-block">
            <span class="score-label">{{ t('evaluation.rqgmScoreLabel') }}</span>
            <span class="score-value" :class="detailUnavailable ? 'score-none' : scoreClass">{{ detailUnavailable || ev.overall_score == null ? '—' : ev.overall_score.toFixed(1) }}</span>
          </div>
          <div class="decision-badge" :class="detailDecisionClass">
            {{ detailUnavailable ? t('evaluation.status.notReady') : t(DETAIL_DECISION_KEYS[ev.decision || 'unknown'] ?? 'evaluation.decision.unknown') }}
          </div>
          <p class="text-xs text-slate-400">{{ t('evaluation.weightedScoreHint') }}</p>
          <p v-if="detailUnavailable" class="status-notice" role="status">{{ t('evaluation.status.degradedHint') }} <button type="button" class="retry-btn min-h-9" @click="retryDetail">{{ t('evaluation.error.retry') }}</button></p>
          <p v-if="result?.data_as_of || result?.evaluated_at" class="text-xs text-slate-400">{{ t('evaluation.dataAsOf') }} {{ formatDateTime(result?.data_as_of || result?.evaluated_at || '') }}</p>
          <p v-if="result?.evaluation_id || result?.evaluator_fingerprint || result?.snapshot_id" class="text-xs text-slate-400">
            <span v-if="result?.evaluation_id">{{ t('evaluation.evaluationId') }}: {{ result.evaluation_id }}</span>
            <span v-if="result?.evaluator_fingerprint"> · {{ t('evaluation.evaluatorFingerprint') }} {{ result.evaluator_fingerprint }}</span>
            <span v-if="result?.snapshot_id"> · {{ t('evaluation.snapshotId') }} {{ result.snapshot_id }}</span>
          </p>
          <p v-if="ev.summary" class="summary">{{ ev.summary }}</p>
        </section>

        <!-- 雷达图 -->
        <section class="radar-card">
          <h3 class="card-title">{{ t('evaluation.radarTitleDynamic', { count: radarDimensionCount }) }}</h3>
          <EvaluationRadar :dimensions="ev.dimensions || []" />
        </section>

        <!-- 偏倚告警 -->
        <section v-if="ev.bias_warning" class="bias-card" :class="biasCardClass">
          <div class="bias-header">
            <AppIcon name="AlertTriangle" variant="peach" />
            <span>{{ t('evaluation.bias.title') }}</span>
            <span v-if="biasSeverity != null" class="bias-severity">{{ t('evaluation.bias.severity') }}: {{ biasSeverity.toFixed(1) }}</span>
          </div>
          <p class="bias-text">{{ ev.bias_warning }}</p>
        </section>

        <!-- 维度详情 -->
        <section class="dims-card">
          <h3 class="card-title">{{ t('evaluation.dimensionsTitle') }}</h3>
          <div v-for="d in ev.dimensions || []" :key="d.dimension" class="dim-row">
            <div class="dim-head">
              <span class="dim-name">
                {{ dimLabel(d.dimension) }}
                <TooltipHelper :content="dimDescription(d.dimension)" position="top">
                  <span class="dim-help" tabindex="0" role="button" :aria-label="dimDescription(d.dimension)">?</span>
                </TooltipHelper>
                <span v-if="d.is_blocking" class="blocking-tag">{{ t('evaluation.blocking') }}</span>
              </span>
              <span class="dim-score" :class="d.available === false || d.score == null ? 'score-none' : scoreTierClass(d.score, scoreThresholds)">
                {{ d.available === false || d.score == null ? '—' : d.score.toFixed(1) }}
              </span>
            </div>
            <p v-if="d.rationale" class="dim-rationale">{{ d.rationale }}</p>
            <ul v-if="d.issues?.length" class="dim-issues">
              <li v-for="(issue, i) in d.issues" :key="i">{{ issue }}</li>
            </ul>
          </div>
        </section>

        <!-- 修订建议 -->
        <section v-if="ev.revision_hints?.length" class="hints-card">
          <h3 class="card-title">{{ t('evaluation.hintsTitle') }}</h3>
          <ul class="hints-list">
            <li v-for="(h, i) in ev.revision_hints" :key="i">{{ h }}</li>
          </ul>
        </section>

        <!-- EV-03: action outlet — route to revise/approve by decision -->
        <section v-if="detailThreadId" class="action-card">
          <button
            v-if="ev.decision === 'needs_revision' || ev.decision === 'rejected'"
            type="button"
            class="action-cta"
            @click="evaluationActionCta('review')"
          >
            <AppIcon name="Pencil" size="sm" />
            {{ t('evaluation.action.revise') }}
          </button>
          <button
            v-else-if="ev.decision === 'approved'"
            type="button"
            class="action-cta"
            @click="evaluationActionCta('dashboard')"
          >
            <AppIcon name="Workflow" size="sm" />
            {{ t('evaluation.action.viewWorkflow') }}
          </button>
        </section>
      </div>
    </template>

    <!-- 历史笔记下钻抽屉：单篇质量 + RQGM 评估（复用 AN-08 抽屉模式） -->
    <Teleport to="body">
      <div
        v-if="drawerNoteId && selectedAccountId"
        ref="noteDrawerRef"
        class="fixed inset-0 z-modal flex justify-end"
        role="dialog"
        aria-modal="true"
        :aria-label="t('creatorNoteQuality.title')"
        @keydown.esc="closeNoteDrawer"
      >
        <div class="absolute inset-0 bg-black/40" @click="closeNoteDrawer" />
        <div class="dark-explicit relative h-full w-full max-w-md space-y-4 overflow-y-auto bg-white p-4 shadow-xl md:max-w-3xl md:p-6 dark:bg-slate-900">
          <div class="flex items-start justify-between gap-3">
            <h2 class="dark-explicit truncate text-base font-semibold text-slate-800 md:text-lg dark:text-slate-100">{{ drawerNoteTitle || t('creatorNoteQuality.untitled') }}</h2>
            <button type="button" class="dark-explicit min-h-11 min-w-[44px] shrink-0 rounded-lg p-2 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" :aria-label="t('common.close')" @click="closeNoteDrawer">
              <AppIcon name="X" size="sm" variant="muted" />
            </button>
          </div>
          <CreatorNoteQualityPanel :account-id="selectedAccountId" :note-id="drawerNoteId" compact />
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* ── 故事线区块：总览 → 诊断 → 单篇 ── */
.eval-section { margin-top: 1rem; }
@media (min-width: 768px) {
  .eval-section { margin-top: 1.25rem; }
}
.section-head { margin-bottom: 0.75rem; }
.section-head-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.75rem;
}
.section-eyebrow {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #7c3aed;
}
html.dark .section-eyebrow { color: #c4b5fd; }
.section-title {
  margin-top: 0.25rem;
  font-size: 1.125rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #1e293b;
}
.section-description { margin-top: 0.35rem; font-size: 0.75rem; line-height: 1.5; color: #64748b; }
html.dark .section-description { color: #94a3b8; }
html.dark .section-title { color: #f1f5f9; }

/* ── 单篇时间流：来源徽章与笔记指标 ── */
.source-badge {
  flex-shrink: 0;
  border-radius: 999px;
  padding: 0.125rem 0.5rem;
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.source-workflow { background: #ccfbf1; color: #0f766e; }
html.dark .source-workflow { background: rgba(20,184,166,0.16); color: #5eead4; }
.source-imported { background: #ede9fe; color: #6d28d9; }
html.dark .source-imported { background: rgba(139,92,246,0.18); color: #c4b5fd; }
.source-tabs { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.9rem; border-bottom: 1px solid #e2e8f0; }
.source-tab { display: inline-flex; align-items: center; gap: 0.45rem; border: 0; border-bottom: 2px solid transparent; background: transparent; padding: 0.5rem 0.75rem; color: #64748b; font-size: 0.8rem; font-weight: 700; cursor: pointer; }
.source-tab--active { border-color: #7c3aed; color: #6d28d9; }
.source-tab-count { color: #94a3b8; font-size: 0.68rem; font-weight: 600; }
html.dark .source-tabs { border-color: #334155; }
html.dark .source-tab { color: #94a3b8; }
html.dark .source-tab--active { color: #c4b5fd; border-color: #a78bfa; }
.item-right-note { flex-direction: row; align-items: center; gap: 0.5rem; }
.note-metric { font-size: 0.75rem; color: #64748b; white-space: nowrap; font-variant-numeric: tabular-nums; }
html.dark .note-metric { color: #94a3b8; }
.score-kind { font-size: 0.62rem; color: #94a3b8; white-space: nowrap; }
.data-as-of { display: flex; flex-wrap: wrap; justify-content: center; margin-top: 0.7rem; color: #94a3b8; font-size: 0.7rem; }
.notes-hint {
  padding: 0.5rem 0.875rem;
  font-size: 0.75rem;
  color: #94a3b8;
}

/* ── 详情页返回操作 ── */
.back-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem;
  padding: 0.4rem 0.8rem; border: 1px solid #e2e8f0; border-radius: 0.5rem;
  background: #fff; color: #334155; font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.back-btn:hover { background: #f8fafc; }

/* ── 列表页搜索栏 ── */
.search-bar { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
.filter-chips { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
.filter-chip { padding: 0.25rem 0.875rem; border-radius: 9999px; border: 1px solid #e2e8f0; background: #fff; color: #475569; font-size: 0.75rem; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.filter-chip:hover { background: #f8fafc; }
.filter-chip--active { background: #0d9488; border-color: #0d9488; color: #fff; }
html.dark .filter-chip { background: #1e293b; border-color: #334155; color: #cbd5e1; }
html.dark .filter-chip--active { background: #0d9488; border-color: #0d9488; color: #fff; }
.thread-input {
  flex: 1; min-width: 240px; padding: 0.625rem 0.875rem;
  border: 1px solid #e2e8f0; border-radius: 0.5rem; font-size: 0.875rem;
  background: #fff;
}
.thread-input:focus { outline: none; border-color: #F43F5E; box-shadow: 0 0 0 3px rgba(244,63,94,0.12); }
.result-count { font-size: 0.75rem; color: #94a3b8; white-space: nowrap; }

/* ── 列表项 ── */
.eval-list { display: flex; flex-direction: column; gap: 0.5rem; }
.eval-item {
  display: flex; justify-content: space-between; align-items: center; gap: 0.75rem;
  background: #fff; border: 1px solid #e2e8f0; border-radius: 0.625rem;
  width: 100%; text-align: left; color: inherit; font: inherit;
  padding: 0.75rem 1rem; cursor: pointer; transition: border-color 0.15s, box-shadow 0.15s;
}
.eval-item:hover { border-color: #fda4af; box-shadow: 0 1px 4px rgba(244,63,94,0.08); }
.item-main { flex: 1; min-width: 0; }
.item-title {
  font-size: 0.9rem; font-weight: 600; color: #1e293b; margin-bottom: 0.25rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.item-meta { font-size: 0.75rem; color: #64748b; display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap; }
.meta-tag { color: #475569; }
.meta-sep { color: #cbd5e1; }
.meta-account { font-family: monospace; }
.meta-time { color: #94a3b8; }
.item-right { display: flex; flex-direction: column; align-items: flex-end; gap: 0.35rem; flex-shrink: 0; }
.item-score { font-size: 1.25rem; font-weight: 800; line-height: 1; }

.load-more { display: flex; justify-content: center; margin-top: 1rem; }
.load-more-btn {
  display: inline-flex; align-items: center; gap: 0.5rem;
  padding: 0.5rem 1.25rem; border: 1px solid #e2e8f0; border-radius: 0.5rem;
  background: #fff; color: #334155; font-size: 0.8125rem; font-weight: 600;
  cursor: pointer; transition: background 0.15s;
}
.load-more-btn:hover:not(:disabled) { background: #f8fafc; }
.load-more-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.no-more { text-align: center; font-size: 0.75rem; color: #94a3b8; margin-top: 0.75rem; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.empty-state {
  display: flex; flex-direction: column; align-items: center; gap: 0.75rem;
  padding: 3rem 1rem; text-align: center; color: #94a3b8;
}
.empty-title { font-size: 1rem; font-weight: 600; color: #475569; }
.empty-desc { font-size: 0.8125rem; max-width: 420px; }

/* ── 详情结果（复用原样式）── */
.result-grid { display: grid; gap: 1rem; grid-template-columns: 1fr; }
@media (min-width: 768px) { .result-grid { grid-template-columns: 1fr 1fr; } }
.overview-card, .radar-card, .bias-card, .dims-card, .hints-card, .action-card {
  background: #fff; border: 1px solid #e2e8f0; border-radius: 0.75rem; padding: 1.25rem;
}
.overview-card { display: flex; flex-direction: column; gap: 0.75rem; align-items: flex-start; }
.score-block { display: flex; align-items: baseline; gap: 0.5rem; }
.score-label { font-size: 0.8125rem; color: #64748b; }
.score-value { font-size: 2.5rem; font-weight: 800; line-height: 1; }
.score-pass { color: #16a34a; }
.score-warn { color: #d97706; }
.score-fail { color: #dc2626; }
.score-none { color: #94a3b8; }
.decision-badge { padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
.decision-approved { background: #dcfce7; color: #15803d; }
.decision-revision { background: #fef3c7; color: #b45309; }
.decision-rejected { background: #fee2e2; color: #b91c1c; }
.decision-unknown { background: #f1f5f9; color: #64748b; }
.summary { font-size: 0.8125rem; color: #475569; margin: 0; }
.status-notice { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; font-size: 0.75rem; color: #b45309; }

.card-title { font-size: 0.9rem; font-weight: 600; color: #1e293b; margin: 0 0 0.75rem; }
.bias-card { border-color: #fde68a; background: #fffbeb; }
.bias-card--med { border-color: #fdba74; background: #fff7ed; }
.bias-card--high { border-color: #f87171; background: #fef2f2; box-shadow: 0 0 0 1px #f87171 inset; }
.bias-header { display: flex; align-items: center; gap: 0.5rem; color: #b45309; font-weight: 600; font-size: 0.875rem; margin-bottom: 0.5rem; }
.bias-card--high .bias-header { color: #b91c1c; }
.bias-severity { margin-left: auto; font-size: 0.75rem; font-weight: 700; padding: 0.125rem 0.5rem; border-radius: 0.375rem; background: rgba(0,0,0,0.06); }
.bias-card--high .bias-severity { background: #dc2626; color: #fff; }
.bias-text { font-size: 0.8125rem; color: #92400e; margin: 0; }
.bias-card--high .bias-text { color: #991b1b; }

.dim-row { padding: 0.625rem 0; border-bottom: 1px solid #f1f5f9; }
.dim-row:last-child { border-bottom: none; }
.dim-head { display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }
.dim-help { display: inline-flex; align-items: center; justify-content: center; width: 2.75rem; height: 2.75rem; margin: -0.75rem -0.75rem -0.75rem 0.1rem; border-radius: 999px; color: #0d9488; font-size: 0.7rem; font-weight: 700; cursor: help; }
.dim-help:focus-visible { outline: 2px solid #0d9488; outline-offset: 2px; }
.dim-name { font-size: 0.8125rem; font-weight: 600; color: #334155; display: inline-flex; align-items: center; gap: 0.5rem; }
.blocking-tag { font-size: 0.625rem; padding: 0.1rem 0.4rem; background: #fee2e2; color: #b91c1c; border-radius: 4px; font-weight: 700; }
.dim-score { font-size: 0.9rem; font-weight: 700; }
.dim-rationale { font-size: 0.75rem; color: #64748b; margin: 0.25rem 0 0; }
.dim-issues { margin: 0.375rem 0 0; padding-left: 1.1rem; }
.dim-issues li { font-size: 0.75rem; color: #475569; margin-bottom: 0.2rem; }

.hints-list { margin: 0; padding-left: 1.1rem; }
.hints-list li { font-size: 0.8125rem; color: #334155; margin-bottom: 0.4rem; line-height: 1.5; }
.action-card { display: flex; gap: 0.75rem; }
.action-cta { display: inline-flex; align-items: center; gap: 0.5rem; min-height: 44px; padding: 0.5rem 1.25rem; border-radius: 0.625rem; background: #0d9488; color: #fff; font-weight: 600; font-size: 0.875rem; border: 0; cursor: pointer; transition: background 0.15s; }
.action-cta:hover { background: #0f766e; }

.radar-card { grid-column: 1 / -1; }
@media (min-width: 768px) { .radar-card { grid-column: auto; } }
</style>
