/**
 * Multi-account product contract — locks the rules that caused
 * "just published but not in history" confusion.
 */
import { describe, it, expect } from 'vitest'
import {
  pickPreferredViewAccount,
  isOwnedAccount,
} from '@/composables/useHistoryAccountScope'
import {
  sumOtherAccountTotals,
  sumAllAccountTotals,
  readQueryString,
} from '@/utils/accountViewSession'
import { accountIdFromThreadId } from '@/utils/threadAccount'

const accounts = [
  { id: 'acct-a', name: 'Workspace', is_active: true, created_at: '' },
  { id: 'acct-b', name: 'Other', is_active: false, created_at: '' },
] as any

describe('multi-account contract', () => {
  it('prefers URL account over session over workspace', () => {
    // session would be acct-b if we only had storage; URL wins.
    const route = { query: { account: 'acct-a' } } as any
    expect(pickPreferredViewAccount(route, accounts, 'acct-b')).toBe('acct-a')
  })

  it('rejects unowned account ids', () => {
    expect(isOwnedAccount(accounts, 'acct-z')).toBe(false)
    expect(isOwnedAccount(accounts, 'acct-b')).toBe(true)
  })

  it('nav badge counts all accounts; sibling probe excludes workspace', () => {
    const totals = { 'acct-a': 0, 'acct-b': 2, 'acct-c': 1 }
    expect(sumAllAccountTotals(totals)).toBe(3)
    expect(sumOtherAccountTotals(totals, 'acct-a')).toBe(3)
    expect(sumOtherAccountTotals(totals, 'acct-b')).toBe(1)
  })

  it('dashboard can recover account scope from thread id', () => {
    const accountId = 'c056e160-6c6e-424b-96df-67733a5d9c56'
    expect(accountIdFromThreadId(`xhs_${accountId}_4673f6f9`)).toBe(accountId)
  })

  it('prefers status.account_id over thread parse when both exist', () => {
    // Frontend resolution order (Dashboard): state.account_id → thread parse.
    const fromState = 'acct-from-status'
    const fromThread = accountIdFromThreadId('xhs_acct-from-thread_abcd1234')
    const resolved = fromState || fromThread
    expect(resolved).toBe('acct-from-status')
    expect(fromThread).toBe('acct-from-thread')
  })

  it('reads account query from route-like objects', () => {
    expect(readQueryString({ account: 'acct-b' }, 'account')).toBe('acct-b')
    expect(readQueryString({ account: ['acct-b', 'x'] }, 'account')).toBe('acct-b')
    expect(readQueryString({}, 'account')).toBeNull()
  })

  it('handoff query omits workspace account for clean URLs', async () => {
    const { accountQuery, withAccountQuery } = await import('@/utils/accountViewSession')
    expect(accountQuery('acct-b', { omitIfEquals: 'acct-a' })).toEqual({ account: 'acct-b' })
    expect(accountQuery('acct-a', { omitIfEquals: 'acct-a' })).toEqual({})
    expect(
      withAccountQuery({ tab: 'workflow' }, 'acct-b', { omitIfEquals: 'acct-a' }),
    ).toEqual({ tab: 'workflow', account: 'acct-b' })
  })
})
