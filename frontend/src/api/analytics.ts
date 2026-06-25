import client from './client'
import type { GrowthReport, PerformanceData, CostData } from '@/types/analytics'

// 获取增长报告
export async function getGrowthReport(
  accountId: string,
  period: string = 'weekly'
): Promise<GrowthReport> {
  return client.get(`/analytics/report/${accountId}`, { params: { period } })
}

// 获取帖子表现
export async function getPerformance(
  accountId: string,
  period: string = 'weekly',
  limit: number = 20
): Promise<PerformanceData> {
  return client.get(`/analytics/performance/${accountId}`, { params: { period, limit } })
}

// 获取成本统计
export async function getCosts(period: string = 'weekly'): Promise<CostData> {
  return client.get('/analytics/costs', { params: { period } })
}

// Single-request dashboard bundle (avoids 3× cold-start cost)
export async function getDashboard(
  accountId: string,
  period: string = 'weekly',
  limit: number = 20
): Promise<{ report: GrowthReport; performance: PerformanceData; costs: CostData }> {
  return client.get(`/analytics/dashboard/${accountId}`, { params: { period, limit } })
}