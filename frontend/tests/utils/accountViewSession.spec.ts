import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import {
  accountQuery,
  clearAccountViewSession,
  EVALUATION_VIEW_ACCOUNT_KEY,
  HISTORY_VIEW_ACCOUNT_KEY,
  readSessionTotals,
  REVIEW_AWAITING_TOTALS_KEY,
  sumAllAccountTotals,
  sumOtherAccountTotals,
  withAccountQuery,
  writeSessionTotals,
} from '@/utils/accountViewSession'

describe('accountViewSession', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })
  afterEach(() => {
    sessionStorage.clear()
  })

  it('reads and writes totals records', () => {
    writeSessionTotals(REVIEW_AWAITING_TOTALS_KEY, { a: 1, b: 2 })
    expect(readSessionTotals(REVIEW_AWAITING_TOTALS_KEY)).toEqual({ a: 1, b: 2 })
  })

  it('sums totals with and without the active account', () => {
    const totals = { a: 1, b: 3, c: 0 }
    expect(sumAllAccountTotals(totals)).toBe(4)
    expect(sumOtherAccountTotals(totals, 'a')).toBe(3)
    expect(sumOtherAccountTotals(totals, null)).toBe(4)
  })

  it('clears all multi-account session keys including evaluation', () => {
    sessionStorage.setItem(HISTORY_VIEW_ACCOUNT_KEY, 'x')
    sessionStorage.setItem(EVALUATION_VIEW_ACCOUNT_KEY, 'y')
    writeSessionTotals(REVIEW_AWAITING_TOTALS_KEY, { a: 1 })
    clearAccountViewSession()
    expect(sessionStorage.getItem(HISTORY_VIEW_ACCOUNT_KEY)).toBeNull()
    expect(sessionStorage.getItem(EVALUATION_VIEW_ACCOUNT_KEY)).toBeNull()
    expect(readSessionTotals(REVIEW_AWAITING_TOTALS_KEY)).toEqual({})
  })

  it('builds account query fragments for deep-link handoff', () => {
    expect(accountQuery('acct-b')).toEqual({ account: 'acct-b' })
    expect(accountQuery('acct-a', { omitIfEquals: 'acct-a' })).toEqual({})
    expect(accountQuery(null)).toEqual({})
    expect(accountQuery('  ')).toEqual({})
  })

  it('merges account into existing query without dropping siblings', () => {
    expect(withAccountQuery({ tab: 'workflow', account: 'old' }, 'acct-b')).toEqual({
      tab: 'workflow',
      account: 'acct-b',
    })
    expect(
      withAccountQuery({ tab: 'notes', account: 'old' }, 'acct-a', {
        omitIfEquals: 'acct-a',
      }),
    ).toEqual({ tab: 'notes' })
  })
})
