import client from './client'
import type { EvaluationResultResponse, EvaluationTrendResponse } from '@/types/evaluation'

// 获取指定工作流的创作质量评估结果（RQGM agent-as-a-judge）
export async function getEvaluationResult(threadId: string): Promise<EvaluationResultResponse> {
  return client.get(`/evaluation/result/${threadId}`) as unknown as EvaluationResultResponse
}

// 获取评估历史趋势（overall_score 时序 + 各维度均值）
export async function getEvaluationTrend(
  accountId?: string,
  limit = 100,
): Promise<EvaluationTrendResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (accountId) params.set('account_id', accountId)
  return client.get(`/evaluation/trend?${params.toString()}`) as unknown as EvaluationTrendResponse
}
