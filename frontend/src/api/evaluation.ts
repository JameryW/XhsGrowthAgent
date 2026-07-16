import client from './client'
import type {
  EvaluationListResponse,
  EvaluationResultResponse,
  EvaluationTrendResponse,
} from '@/types/evaluation'

type RequestOptions = { suppressToast?: boolean }

// 列出有评估结果的工作流 — 含标题 + 评估摘要（专用端点，不污染通用 /workflow/list）
export async function getEvaluationList(
  accountId?: string,
  limit = 20,
  offset = 0,
  options?: RequestOptions,
): Promise<EvaluationListResponse> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  if (accountId) params.set('account_id', accountId)
  return client.get(`/evaluation/list?${params.toString()}`, options) as unknown as EvaluationListResponse
}

// 获取指定工作流的创作质量评估结果（RQGM agent-as-a-judge）
export async function getEvaluationResult(threadId: string, options?: RequestOptions): Promise<EvaluationResultResponse> {
  return client.get(`/evaluation/result/${threadId}`, options) as unknown as EvaluationResultResponse
}

// 对已导入历史笔记手动触发 RQGM 评估（thread-less，不写 checkpoint）
export async function evaluateNote(
  accountId: string,
  noteId: string,
): Promise<{ account_id: string; note_id: string; evaluation_result: EvaluationResultResponse['evaluation_result'] }> {
  return client.post('/evaluation/note', { account_id: accountId, note_id: noteId }) as unknown as Promise<{ account_id: string; note_id: string; evaluation_result: EvaluationResultResponse['evaluation_result'] }>
}

// 获取评估历史趋势（overall_score 时序 + 各维度均值）
export async function getEvaluationTrend(
  accountId?: string,
  limit = 100,
  options?: RequestOptions,
): Promise<EvaluationTrendResponse> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (accountId) params.set('account_id', accountId)
  return client.get(`/evaluation/trend?${params.toString()}`, options) as unknown as EvaluationTrendResponse
}
