import client from './client'
import type { PendingReview, ReviewDecisionRequest, ReviewSubmitResponse } from '@/types/review'
import { useRetry } from '@/composables/useRetry'

// 获取待审核内容
export async function getPendingReview(threadId: string): Promise<PendingReview> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    try {
      const result = await client.get(`/review/pending/${threadId}`) as PendingReview
      return result
    } catch (error) {
      throw error
    }
  })
}

// 提交审核决定
export async function submitReview(
  threadId: string,
  request: ReviewDecisionRequest
): Promise<ReviewSubmitResponse> {
  const { retryWithBackoff } = useRetry()
  return retryWithBackoff(async () => {
    try {
      const result = await client.post(`/review/submit/${threadId}`, request) as ReviewSubmitResponse
      return result
    } catch (error) {
      throw error
    }
  })
}