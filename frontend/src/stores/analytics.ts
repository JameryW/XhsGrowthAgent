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
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  let requestGeneration = 0

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
    return posts.value.reduce((sum, post) =>
      sum + post.engagement_rate, 0
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
  async function fetchAllData() {
    const generation = ++requestGeneration
    const requestedAccountId = accountId.value
    if (!requestedAccountId) {
      growthReport.value = null
      performanceData.value = null
      costData.value = null
      periodSummary.value = null
      error.value = null
      isLoading.value = false
      return
    }
    isLoading.value = true
    error.value = null
    try {
      const { report, performance, costs, period_summary } = await analyticsApi.getDashboard(
        requestedAccountId, period.value, 20
      )
      if (generation !== requestGeneration || accountId.value !== requestedAccountId) return
      growthReport.value = report
      performanceData.value = performance
      costData.value = costs
      periodSummary.value = period_summary ?? null
    } catch (e: any) {
      if (generation === requestGeneration) error.value = e.message
    } finally {
      if (generation === requestGeneration) isLoading.value = false
    }
  }

  async function fetchReport() {
    isLoading.value = true
    try {
      growthReport.value = await analyticsApi.getGrowthReport(accountId.value, period.value)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function fetchPerformance() {
    isLoading.value = true
    try {
      performanceData.value = await analyticsApi.getPerformance(accountId.value, period.value, 20)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
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
