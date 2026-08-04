// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { accountIdFromThreadId } from '@/utils/threadAccount'

describe('accountIdFromThreadId', () => {
  it('parses uuid account ids from start-minted thread ids', () => {
    const accountId = '9eaec02e-e1a4-429b-bed2-ce33ce7fc9dd'
    const threadId = `xhs_${accountId}_7176d7ff`
    expect(accountIdFromThreadId(threadId)).toBe(accountId)
  })

  it('returns null for malformed threads', () => {
    expect(accountIdFromThreadId(null)).toBeNull()
    expect(accountIdFromThreadId('')).toBeNull()
    expect(accountIdFromThreadId('not-a-thread')).toBeNull()
    expect(accountIdFromThreadId('xhs_only')).toBeNull()
    expect(accountIdFromThreadId('xhs_acct_nothex!!')).toBeNull()
  })
})
