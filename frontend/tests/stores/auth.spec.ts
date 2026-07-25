import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  logout: vi.fn(),
  validateToken: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  login: mocks.login,
  logout: mocks.logout,
  validateToken: mocks.validateToken,
}))

vi.mock('@/stores/toast', () => ({
  useToastStore: () => ({ success: vi.fn(), info: vi.fn(), error: vi.fn(), warning: vi.fn() }),
}))

vi.mock('@/locales', () => ({
  default: { global: { t: (key: string) => key } },
}))

import { useAuthStore } from '@/stores/auth'

function authResult(id: string) {
  return { token: `token-${id}`, user: { id, username: id } }
}

describe('auth store console-user switching', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    mocks.login.mockReset()
  })

  it('clears account-scoped state and requests a full reset on user switch', async () => {
    localStorage.setItem('auth_last_user_id', 'user-a')
    localStorage.setItem('openTabIds', '["t-1"]')
    localStorage.setItem('activeThreadId', 't-1')
    localStorage.setItem('tabLabels', '{"t-1":"x"}')
    mocks.login.mockResolvedValueOnce(authResult('user-b'))
    const auth = useAuthStore()

    await auth.login('user-b', 'pw')

    expect(localStorage.getItem('openTabIds')).toBeNull()
    expect(localStorage.getItem('activeThreadId')).toBeNull()
    expect(localStorage.getItem('tabLabels')).toBeNull()
    expect(auth.requiresFullReset).toBe(true)
    expect(localStorage.getItem('auth_last_user_id')).toBe('user-b')
  })

  it('keeps account-scoped state when the same user logs in again', async () => {
    localStorage.setItem('auth_last_user_id', 'user-a')
    localStorage.setItem('openTabIds', '["t-1"]')
    mocks.login.mockResolvedValueOnce(authResult('user-a'))
    const auth = useAuthStore()

    await auth.login('user-a', 'pw')

    expect(localStorage.getItem('openTabIds')).toBe('["t-1"]')
    expect(auth.requiresFullReset).toBe(false)
  })

  it('does not reset on the first-ever login (no previous user)', async () => {
    localStorage.setItem('openTabIds', '["t-1"]')
    mocks.login.mockResolvedValueOnce(authResult('user-a'))
    const auth = useAuthStore()

    await auth.login('user-a', 'pw')

    expect(localStorage.getItem('openTabIds')).toBe('["t-1"]')
    expect(auth.requiresFullReset).toBe(false)
  })
})
