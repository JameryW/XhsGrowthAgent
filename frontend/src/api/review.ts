import client from './client'
import type { PendingReview, ReviewDecisionRequest, ReviewSubmitResponse } from '@/types/review'

// 获取待审核内容
export async function getPendingReview(threadId: string): Promise<PendingReview> {
  return client.get(`/review/pending/${threadId}`)
}

// 提交审核决定
export async function submitReview(
  threadId: string,
  request: ReviewDecisionRequest
): Promise<ReviewSubmitResponse> {
  return client.post(`/review/submit/${threadId}`, request)
}