// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockClient = vi.hoisted(() => ({
  get: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('@/api/client', () => ({ default: mockClient }))

import { deleteFreeDraft, getFreeDraft, listFreeDrafts } from '@/api/free'

describe('free draft API adapters', () => {
  beforeEach(() => {
    mockClient.get.mockReset()
    mockClient.delete.mockReset()
  })

  it('keeps list requests account-scoped and typed', async () => {
    const response = {
      account_id: 'acct-a',
      drafts: [],
      count: 0,
      truncated: false,
    }
    mockClient.get.mockResolvedValue(response)

    await expect(listFreeDrafts('acct-a', { status: 'unevaluated' }, { suppressToast: true })).resolves.toEqual(response)
    expect(mockClient.get).toHaveBeenCalledWith('/free/drafts/acct-a', {
      params: { status: 'unevaluated' },
      suppressToast: true,
    })
  })

  it('passes the account scope to detail and delete endpoints', async () => {
    mockClient.get.mockResolvedValue({ draft_id: 'draft-1', draft: { title: 'Draft' } })
    mockClient.delete.mockResolvedValue({ draft_id: 'draft-1', deleted: true })

    await getFreeDraft('acct-a', 'draft/1', { suppressToast: true })
    await deleteFreeDraft('acct-a', 'draft/1', { suppressToast: true })

    expect(mockClient.get).toHaveBeenCalledWith('/free/draft/draft%2F1', {
      params: { account_id: 'acct-a' },
      suppressToast: true,
    })
    expect(mockClient.delete).toHaveBeenCalledWith('/free/draft/draft%2F1', {
      params: { account_id: 'acct-a' },
      suppressToast: true,
    })
  })

  it('surfaces the persisted engagement snapshot on draft summaries', async () => {
    // last_analytics is server-set (task 08-24-free-post-feedback-loop); the
    // adapter must pass it through untouched for History panel rendering.
    const snapshot = {
      post_id: 'note_9',
      views: 900,
      likes: 30,
      collects: 10,
      comments: 5,
      shares: 2,
      engagement_rate: 5.22,
      fetched_at: '2026-08-24T08:00:00+00:00',
    }
    const response = {
      account_id: 'acct-a',
      drafts: [
        {
          draft_id: 'draft-1',
          title: '夏日穿搭',
          hashtags: [],
          published: true,
          last_analytics: snapshot,
        },
        {
          draft_id: 'draft-2',
          title: 'legacy',
          hashtags: [],
          published: false,
          last_analytics: null,
        },
      ],
      count: 2,
      truncated: false,
    }
    mockClient.get.mockResolvedValue(response)

    const result = await listFreeDrafts('acct-a')
    expect(result.drafts[0].last_analytics).toEqual(snapshot)
    expect(result.drafts[1].last_analytics).toBeNull()
  })
})
