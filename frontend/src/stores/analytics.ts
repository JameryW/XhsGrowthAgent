import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as analyticsApi from '@/api/analytics'
import type { GrowthReport, PerformanceData, CostData, PostPerformance } from '@/types/analytics'
import { useRealtimeStore } from './realtime'
import { useToastStore } from './toast'
import { EventType } from '@/realtime/events'
import i18n from '@/locales'

const { t } = i18n.global

export const useAnalyticsStore = defineStore('analytics', () => {
  // State
  const accountId = ref('default')
  const period = ref<'daily' | 'weekly' | 'monthly'>('weekly')
  const growthReport = ref<GrowthReport | null>(null)
  const performanceData = ref<PerformanceData | null>(null)
  const costData = ref<CostData | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

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
    isLoading.value = true
    error.value = null
    try {
      const [report, perf, costs] = await Promise.all([
        analyticsApi.getGrowthReport(accountId.value, period.value),
        analyticsApi.getPerformance(accountId.value, 20),
        analyticsApi.getCosts(),
      ])
      growthReport.value = report
      performanceData.value = perf
      costData.value = costs
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
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
      performanceData.value = await analyticsApi.getPerformance(accountId.value, 20)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function fetchCosts() {
    isLoading.value = true
    try {
      costData.value = await analyticsApi.getCosts()
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

  function setAccountId(id: string) {
    accountId.value = id
    fetchAllData()
  }

  return {
    accountId,
    period,
    growthReport,
    performanceData,
    costData,
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
    setAccountId,
  }
})