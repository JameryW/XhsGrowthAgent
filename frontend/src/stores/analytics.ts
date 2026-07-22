import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as analyticsApi from '@/api/analytics'
import type {
  GrowthReport,
  PerformanceData,
  CostData,
  PostPerformance,
  AnalyticsPeriodSummary,
} from '@/types/analytics'
import { useRealtimeStore } from './realtime'
import { useToastStore } from './toast'
import { useAccountsStore } from './accounts'
import { EventType } from '@/realtime/events'
import i18n from '@/locales'

const { t } = i18n.global

export const useAnalyticsStore = defineStore('analytics', () => {
  // State
  const period = ref<'daily' | 'weekly' | 'monthly'>('weekly')
  const growthReport = ref<GrowthReport | null>(null)
  const performanceData = ref<PerformanceData | null>(null)
  const costData = ref<CostData | null>(null)
  const periodSummary = ref<AnalyticsPeriodSummary | null>(null)
  const dataAsOf = ref<string | null>(null)
  const snapshotId = ref<string | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  let requestGeneration = 0
  let scopedRequestGeneration = 0

  // Derive the scope from the selected account, or the first loaded account
  // when no explicit active account exists. Never query a synthetic `default`
  // account: an empty account scope is a real no-data state.
  const accountsStore = useAccountsStore()
  const accountId = computed(() => accountsStore.activeAccountId ?? accountsStore.accounts[0]?.id ?? '')

  // Computed
  const posts = computed<PostPerformance[]>(() =>
    performanceData.value?.posts || []
  )

  const totalEngagement = computed(() => {
    if (!posts.value.length) return 0
    return posts.value.reduce((sum, post) =>
      sum + post.likes + post.comments + post.collects, 0
    )
  })

  const avgEngagementRate = computed(() => {
    if (!posts.value.length) return 0
    const unit = performanceData.value?.engagement_rate_unit
    return posts.value.reduce((sum, post) =>
      sum + engagementRatePercent(post.engagement_rate, unit), 0
    ) / posts.value.length
  })

  // WebSocket event handlers
  const realtimeStore = useRealtimeStore()
  const toastStore = useToastStore()

  realtimeStore.wsService.onEvent(EventType.ANALYTICS_REPORT_UPDATED, (msg) => {
    const p = msg.payload as { report?: GrowthReport }
    if (p.report) {
      growthReport.value = p.report
      toastStore.info(t('common.success'), t('analytics.title'))
    }
  })

  realtimeStore.wsService.onEvent(EventType.ANALYTICS_COST_ALERT, (msg) => {
    const p = msg.payload as { message?: string; level?: string }
    const message = p.message || t('analytics.aiCost')
    if (p.level === 'critical') {
      toastStore.error(t('common.error'), message)
    } else {
      toastStore.warning(t('common.error'), message)
    }
  })

  realtimeStore.wsService.onEvent(EventType.ANALYTICS_PERFORMANCE_NEW, (msg) => {
    const p = msg.payload as { post?: PostPerformance }
    if (p.post && performanceData.value) {
      performanceData.value = {
        ...performanceData.value,
        posts: [...performanceData.value.posts, p.post],
      }
      toastStore.info(t('common.success'), `${p.post.title?.slice(0, 20)}...`)
    }
  })

  // Actions
  function clearAccountScopedData() {
    growthReport.value = null
    performanceData.value = null
    periodSummary.value = null
    dataAsOf.value = null
    snapshotId.value = null
  }

  async function fetchAllData() {
    const generation = ++requestGeneration
    const scopedGeneration = ++scopedRequestGeneration
    const requestedAccountId = accountId.value
    const requestedPeriod = period.value
    if (!requestedAccountId) {
      clearAccountScopedData()
      costData.value = null
      error.value = null
      isLoading.value = false
      return
    }
    isLoading.value = true
    error.value = null
    // A new account/period request must not be compared with the previous
    // snapshot while its response is in flight.
    dataAsOf.value = null
    snapshotId.value = null
    try {
      const dashboard = await analyticsApi.getDashboard(
        requestedAccountId, requestedPeriod, 20
      )
      const { report, performance, costs, period_summary } = dashboard
      if (
        generation !== requestGeneration
        || scopedGeneration !== scopedRequestGeneration
        || accountId.value !== requestedAccountId
        || period.value !== requestedPeriod
      ) return
      growthReport.value = report
      performanceData.value = performance
      costData.value = costs
      periodSummary.value = period_summary ?? null
      dataAsOf.value = dashboard.data_as_of
        ?? responseDataAsOf(report, performanceData.value, period_summary)
      snapshotId.value = dashboard.snapshot_id
        ?? responseSnapshotId(report, performanceData.value, period_summary)
    } catch (e: any) {
      if (
        generation === requestGeneration
        && scopedGeneration === scopedRequestGeneration
        && accountId.value === requestedAccountId
        && period.value === requestedPeriod
      ) {
        error.value = e.message
      }
    } finally {
      if (
        generation === requestGeneration
        && scopedGeneration === scopedRequestGeneration
        && accountId.value === requestedAccountId
        && period.value === requestedPeriod
      ) {
        isLoading.value = false
      }
    }
  }

  async function fetchReport() {
    const generation = ++scopedRequestGeneration
    const dashboardGeneration = requestGeneration
    const requestedAccountId = accountId.value
    const requestedPeriod = period.value
    if (!requestedAccountId) {
      clearAccountScopedData()
      error.value = null
      isLoading.value = false
      return
    }
    // A standalone report must not remain paired with posts/summary from a
    // previous account or snapshot while it is loading.
    clearAccountScopedData()
    error.value = null
    isLoading.value = true
    try {
      const report = await analyticsApi.getGrowthReport(requestedAccountId, requestedPeriod)
      if (
        generation !== scopedRequestGeneration
        || dashboardGeneration !== requestGeneration
        || accountId.value !== requestedAccountId
        || period.value !== requestedPeriod
      ) return
      growthReport.value = report
      dataAsOf.value = report.data_as_of ?? null
      snapshotId.value = report.snapshot_id ?? null
    } catch (e: any) {
      if (
        generation === scopedRequestGeneration
        && dashboardGeneration === requestGeneration
        && accountId.value === requestedAccountId
        && period.value === requestedPeriod
      ) error.value = e.message
    } finally {
      if (
        generation === scopedRequestGeneration
        && dashboardGeneration === requestGeneration
        && accountId.value === requestedAccountId
        && period.value === requestedPeriod
      ) isLoading.value = false
    }
  }

  async function fetchPerformance() {
    const generation = ++scopedRequestGeneration
    const dashboardGeneration = requestGeneration
    const requestedAccountId = accountId.value
    const requestedPeriod = period.value
    if (!requestedAccountId) {
      clearAccountScopedData()
      error.value = null
      isLoading.value = false
      return
    }
    // Keep report/posts/period metadata from being displayed as a mixed
    // snapshot when callers use this legacy single-endpoint action.
    clearAccountScopedData()
    error.value = null
    isLoading.value = true
    try {
      const performance = await analyticsApi.getPerformance(
        requestedAccountId,
        requestedPeriod,
        20,
      )
      if (
        generation !== scopedRequestGeneration
        || dashboardGeneration !== requestGeneration
        || accountId.value !== requestedAccountId
        || period.value !== requestedPeriod
      ) return
      performanceData.value = performance
      dataAsOf.value = performance.data_as_of ?? null
      snapshotId.value = performance.snapshot_id ?? null
    } catch (e: any) {
      if (
        generation === scopedRequestGeneration
        && dashboardGeneration === requestGeneration
        && accountId.value === requestedAccountId
        && period.value === requestedPeriod
      ) error.value = e.message
    } finally {
      if (
        generation === scopedRequestGeneration
        && dashboardGeneration === requestGeneration
        && accountId.value === requestedAccountId
        && period.value === requestedPeriod
      ) isLoading.value = false
    }
  }

  async function fetchCosts() {
    isLoading.value = true
    try {
      costData.value = await analyticsApi.getCosts(period.value)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  function setPeriod(p: 'daily' | 'weekly' | 'monthly') {
    period.value = p
    fetchAllData()
  }

  return {
    accountId,
    period,
    growthReport,
    performanceData,
    costData,
    periodSummary,
    dataAsOf,
    snapshotId,
    isLoading,
    error,
    posts,
    totalEngagement,
    avgEngagementRate,
    fetchAllData,
    fetchReport,
    fetchPerformance,
    fetchCosts,
    setPeriod,
  }
})

function responseDataAsOf(
  report: GrowthReport | null | undefined,
  performance: PerformanceData | null | undefined,
  summary: AnalyticsPeriodSummary | undefined,
): string | null {
  return report?.data_as_of ?? performance?.data_as_of ?? summary?.data_as_of ?? null
}

function responseSnapshotId(
  report: GrowthReport | null | undefined,
  performance: PerformanceData | null | undefined,
  summary: AnalyticsPeriodSummary | undefined,
): string | null {
  return report?.snapshot_id ?? performance?.snapshot_id ?? summary?.snapshot_id ?? null
}

function engagementRatePercent(value: number, unit?: string): number {
  if (unit === 'fraction') return value * 100
  if (unit === 'percent') return value
  // Compatibility for a legacy response that predates the explicit unit.
  return value <= 1 ? value * 100 : value
}
