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
})
