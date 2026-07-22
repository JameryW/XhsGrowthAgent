import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockGet = vi.fn()

vi.mock('@/api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}))

import { getCreatorNotes } from '@/api/analytics'

describe('analytics creator notes compatibility reader', () => {
  beforeEach(() => {
    mockGet.mockReset()
  })

  it('keeps snapshot and explicit unit metadata when canonical endpoint falls back', async () => {
    mockGet
      .mockRejectedValueOnce({ code: 'HTTP_404', message: 'canonical endpoint unavailable' })
      .mockResolvedValueOnce({
        account_id: 'acc-1',
        account: null,
        notes: [{ note_id: 'n-1', engagement_rate: 0.01 }],
        total: 1,
        limit: 50,
        data_as_of: '2026-07-22T10:00:00Z',
        snapshot_id: 'snapshot:legacy',
        engagement_rate_unit: 'fraction',
      })

    const payload = await getCreatorNotes('acc-1', { limit: 50 })

    expect(payload.snapshot_id).toBe('snapshot:legacy')
    expect(payload.data_as_of).toBe('2026-07-22T10:00:00Z')
    expect(payload.engagement_rate_unit).toBe('fraction')
    expect(mockGet).toHaveBeenCalledTimes(2)
  })

  it('does not guess a unit for an older response that omits it', async () => {
    mockGet
      .mockRejectedValueOnce({ code: 'HTTP_404', message: 'canonical endpoint unavailable' })
      .mockResolvedValueOnce({
        account_id: 'acc-1',
        account: null,
        notes: [{ note_id: 'n-1', engagement_rate: 5 }],
        total: 1,
        limit: 50,
        snapshot_id: 'snapshot:old',
      })

    const payload = await getCreatorNotes('acc-1', { limit: 50 })

    expect(payload.snapshot_id).toBe('snapshot:old')
    expect(payload.engagement_rate_unit).toBeUndefined()
  })
})
