import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  getActiveAccount: vi.fn(),
  createAccount: vi.fn(),
  updateAccount: vi.fn(),
  deleteAccount: vi.fn(),
}))

vi.mock('@/api/accounts', () => ({
  listAccounts: mocks.listAccounts,
  getActiveAccount: mocks.getActiveAccount,
  createAccount: mocks.createAccount,
  updateAccount: mocks.updateAccount,
  deleteAccount: mocks.deleteAccount,
}))

import { ApiError } from '@/api/client'
import { useAccountsStore } from '@/stores/accounts'

describe('accounts store — anonymous visitors must not see session errors', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('never surfaces "token expired or invalid" for a visitor without a session', async () => {
    const dead = () => Promise.reject(new ApiError('Authorization token required', 'ERROR_AUTH_TOKEN_MISSING'))
    mocks.listAccounts.mockImplementation(dead)
    mocks.getActiveAccount.mockImplementation(dead)
    const store = useAccountsStore()

    await store.fetchAccounts({ force: true })

    expect(store.error).toBeNull()
    expect(store.accounts).toEqual([])
  })

  it('swallows a dead-session failure instead of surfacing "token expired or invalid"', async () => {
    localStorage.setItem('auth_token', 'stale-token')
    const dead = () => Promise.reject(new ApiError('Token expired or invalid', 'ERROR_AUTH_TOKEN_INVALID'))
    mocks.listAccounts.mockImplementation(dead)
    mocks.getActiveAccount.mockImplementation(dead)
    const store = useAccountsStore()

    await store.fetchAccounts({ force: true })

    expect(store.error).toBeNull()
    expect(store.accounts).toEqual([])
  })

  it('still records genuine failures', async () => {
    localStorage.setItem('auth_token', 'live-token')
    mocks.listAccounts.mockRejectedValue(new ApiError('boom', 'ERROR_INTERNAL'))
    mocks.getActiveAccount.mockResolvedValue(null)
    const store = useAccountsStore()

    await store.fetchAccounts({ force: true })

    expect(store.error).toBe('boom')
  })
})
