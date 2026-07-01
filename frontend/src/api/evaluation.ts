import client from './client'
import type { EvaluationResultResponse } from '@/types/evaluation'

// 获取指定工作流的创作质量评估结果（RQGM agent-as-a-judge）
export async function getEvaluationResult(threadId: string): Promise<EvaluationResultResponse> {
  return client.get(`/evaluation/result/${threadId}`) as unknown as EvaluationResultResponse
}
