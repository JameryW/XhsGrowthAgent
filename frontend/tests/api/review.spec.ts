// frontend/tests/api/review.spec.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock the client so we can assert call shape without a real server.
const mockPost = vi.fn()
vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: (...args: unknown[]) => mockPost(...args),
  },
}))

// Mock useRetry to bypass backoff delays in tests.
vi.mock('@/composables/useRetry', () => ({
  useRetry: () => ({
    retryWithBackoff: async <T>(fn: () => Promise<T>) => fn(),
  }),
}))

import { updateCopy } from '@/api/review'
import type { CopyUpdateResponse } from '@/types/review'

describe('updateCopy', () => {
  beforeEach(() => {
    mockPost.mockReset()
  })

  it('posts to /review/update-copy/{threadId} with the provided body', async () => {
    const expected: CopyUpdateResponse = {
      thread_id: 'thread-abc',
      status: 'updated',
      evaluation_result: {
        overall_score: 82.5,
        dimensions: [],
        decision: 'approved',
        revision_hints: [],
        bias_warning: '',
        summary: 'Good copy',
      },
    }
    mockPost.mockResolvedValue(expected)

    const result = await updateCopy('thread-abc', {
      title: 'New Title',
      body_text: 'New body',
      hashtags: ['#tag1', '#tag2'],
    })

    expect(mockPost).toHaveBeenCalledWith('/review/update-copy/thread-abc', {
      title: 'New Title',
      body_text: 'New body',
      hashtags: ['#tag1', '#tag2'],
    })
    expect(result).toEqual(expected)
    expect(result.status).toBe('updated')
  })

  it('returns degraded evaluation_result (empty) with warning on evaluator failure', async () => {
    const degraded: CopyUpdateResponse = {
      thread_id: 'thread-xyz',
      status: 'updated',
      evaluation_result: {},
      warning: 'evaluator 降级放行：timeout',
    }
    mockPost.mockResolvedValue(degraded)

    const result = await updateCopy('thread-xyz', { title: 'Partial' })

    expect(mockPost).toHaveBeenCalledWith('/review/update-copy/thread-xyz', {
      title: 'Partial',
    })
    expect(result.warning).toBe('evaluator 降级放行：timeout')
    expect(Object.keys(result.evaluation_result)).toHaveLength(0)
  })

  it('passes undefined for omitted fields', async () => {
    mockPost.mockResolvedValue({
      thread_id: 't1',
      status: 'updated',
      evaluation_result: {},
    })

    await updateCopy('t1', {})

    // All fields undefined → sent as-is (backend treats null/undefined as "skip")
    expect(mockPost).toHaveBeenCalledWith('/review/update-copy/t1', {})
  })
})
