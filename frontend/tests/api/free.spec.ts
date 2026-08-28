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

  it('surfaces the server-computed engagement trend on draft summaries', async () => {
    // engagement_trend is server-computed (task 08-26-free-snapshot-trend);
    // the adapter must pass it through untouched for History panel rendering.
    const trend = { views: 350, delta_views: 200, captured_at: '2026-08-25T09:30:00Z' }
    const response = {
      account_id: 'acct-a',
      drafts: [
        { draft_id: 'draft-1', title: '夏日穿搭', hashtags: [], published: true, engagement_trend: trend },
        { draft_id: 'draft-2', title: 'legacy', hashtags: [], published: true, engagement_trend: null },
      ],
      count: 2,
      truncated: false,
    }
    mockClient.get.mockResolvedValue(response)

    const result = await listFreeDrafts('acct-a')
    expect(result.drafts[0].engagement_trend).toEqual(trend)
    expect(result.drafts[1].engagement_trend).toBeNull()
  })

  it('surfaces creative-memory anchors on draft summaries', async () => {
    // style/play/material anchors are server-set on records (task
    // 08-26-free-anchor-display); the adapter passes them through untouched.
    const response = {
      account_id: 'acct-a',
      drafts: [
        {
          draft_id: 'draft-1',
          title: '夏日穿搭',
          hashtags: [],
          style_id: 'style_heal',
          play_id: 'p_9',
          material_ids: ['m1', 'm2'],
        },
        { draft_id: 'draft-2', title: 'legacy', hashtags: [], style_id: '', play_id: '', material_ids: [] },
      ],
      count: 2,
      truncated: false,
    }
    mockClient.get.mockResolvedValue(response)

    const result = await listFreeDrafts('acct-a')
    expect(result.drafts[0].style_id).toBe('style_heal')
    expect(result.drafts[0].play_id).toBe('p_9')
    expect(result.drafts[0].material_ids).toEqual(['m1', 'm2'])
    expect(result.drafts[1].style_id).toBe('')
    expect(result.drafts[1].material_ids).toEqual([])
  })

  it('surfaces safe publish-attempt metadata on draft summaries', async () => {
    const publishSummary = {
      status: 'failed',
      error_type: 'account_inactive',
      at: '2026-08-25T09:30:00Z',
    }
    const response = {
      account_id: 'acct-a',
      drafts: [
        { draft_id: 'draft-1', title: '发布失败', hashtags: [], published: false, last_publish: publishSummary },
        { draft_id: 'draft-2', title: 'legacy', hashtags: [], published: false, last_publish: null },
      ],
      count: 2,
      truncated: false,
    }
    mockClient.get.mockResolvedValue(response)

    const result = await listFreeDrafts('acct-a')
    expect(result.drafts[0].last_publish).toEqual(publishSummary)
    expect(result.drafts[1].last_publish).toBeNull()
  })
})
