import { describe, expect, it } from 'vitest'
import {
  buildFreeDraftHistoryLocation,
  buildFreeDraftHistoryMirrorLocation,
  buildFreeDraftTuiSourceQuery,
  parseFreeDraftHistoryContext,
  parseFreeDraftTuiSourceContext,
  type FreeDraftReviewContext,
} from '@/utils/freeDraftReviewContext'

const context: FreeDraftReviewContext = {
  accountId: 'acct-a',
  status: 'needs_attention',
  search: '京都亲子',
  draftId: 'draft-9',
}

describe('freeDraftReviewContext', () => {
  it('round-trips a legal review context through TUI and fixed History queries', () => {
    const source = buildFreeDraftTuiSourceQuery(context)
    expect(parseFreeDraftTuiSourceContext(source)).toEqual(context)

    const location = buildFreeDraftHistoryLocation(context, 'acct-a')
    expect(location?.name).toBe('history')
    expect(location?.query).toMatchObject({ tab: 'free-drafts', account: 'acct-a' })
    expect(parseFreeDraftHistoryContext(location!.query)).toEqual(context)
  })

  it('safely degrades unknown, array, blank and overlong query values', () => {
    const source = buildFreeDraftTuiSourceQuery(context)
    const accountKey = Object.keys(source).find(key => source[key] === 'acct-a')!
    const statusKey = Object.keys(source).find(key => source[key] === 'needs_attention')!
    const searchKey = Object.keys(source).find(key => source[key] === '京都亲子')!
    const draftKey = Object.keys(source).find(key => source[key] === 'draft-9')!

    expect(parseFreeDraftTuiSourceContext({ ...source, [statusKey]: 'invented' })?.status).toBe('all')
    expect(parseFreeDraftTuiSourceContext({ ...source, [statusKey]: ['published'] })).toBeNull()
    expect(parseFreeDraftTuiSourceContext({ ...source, [searchKey]: ['unsafe'] })).toBeNull()
    expect(parseFreeDraftTuiSourceContext({ ...source, [draftKey]: ['draft-9'] })).toBeNull()
    expect(parseFreeDraftTuiSourceContext({ ...source, [draftKey]: '   ' })?.draftId).toBeNull()
    expect(parseFreeDraftTuiSourceContext({ ...source, [searchKey]: 'x'.repeat(500) })?.search).toHaveLength(160)
    expect(parseFreeDraftTuiSourceContext({ ...source, [accountKey]: ['acct-a'] })).toBeNull()
    expect(parseFreeDraftTuiSourceContext({ ...source, [accountKey]: '   ' })).toBeNull()
  })

  it('keeps the History target fixed and lets the resolved owned account override source data', () => {
    const location = buildFreeDraftHistoryLocation(context, 'acct-owned')

    expect(location).toEqual({
      name: 'history',
      query: {
        account: 'acct-owned',
        tab: 'free-drafts',
        ...buildFreeDraftTuiSourceQuery({ ...context, accountId: 'acct-owned' }),
      },
    })
    expect(JSON.stringify(location)).not.toContain('return_to')
    expect(JSON.stringify(location)).not.toContain('evil.example')
    expect(parseFreeDraftHistoryContext(location!.query)?.accountId).toBe('acct-owned')
  })

  it('caps free text but rejects overlong account and draft identities', () => {
    const source = buildFreeDraftTuiSourceQuery({
      ...context,
      accountId: '  acct-a  ',
      search: `  ${'s'.repeat(400)}  `,
      draftId: `  ${'d'.repeat(400)}  `,
    })
    const parsed = parseFreeDraftTuiSourceContext(source)

    expect(parsed?.accountId).toBe('acct-a')
    expect(parsed?.search).toHaveLength(160)
    expect(parsed?.draftId).toBeNull()
    expect(parsed?.search.startsWith(' ')).toBe(false)
    const validSource = buildFreeDraftTuiSourceQuery(context)
    const accountKey = Object.keys(validSource).find(key => validSource[key] === context.accountId)!
    const draftKey = Object.keys(validSource).find(key => validSource[key] === context.draftId)!
    expect(parseFreeDraftTuiSourceContext({ ...validSource, [accountKey]: 'a'.repeat(400) })).toBeNull()
    expect(parseFreeDraftTuiSourceContext({ ...validSource, [draftKey]: 'd'.repeat(400) })?.draftId).toBeNull()
    expect(buildFreeDraftTuiSourceQuery({ ...context, accountId: 'a'.repeat(400) })).toEqual({})
    expect(buildFreeDraftHistoryLocation(context, 'a'.repeat(400))).toBeNull()
  })

  it('mirrors review fields without dropping parent-owned History query state', () => {
    const location = buildFreeDraftHistoryMirrorLocation(context, 'acct-owned', {
      tab: 'workflows',
      account: 'stale-account',
      status: 'completed',
      tags: ['one', 'two'],
      return_to: 'https://evil.example',
      returnUrl: 'https://evil.example/return',
      redirectTo: '/admin',
      callback_url: 'https://evil.example/callback',
      route_name: 'settings',
      ...buildFreeDraftTuiSourceQuery({ ...context, accountId: 'stale-account' }),
    })

    expect(location).toMatchObject({
      name: 'history',
      query: {
        tab: 'free-drafts',
        account: 'acct-owned',
        status: 'completed',
        tags: ['one', 'two'],
      },
    })
    expect(location?.query).not.toHaveProperty('return_to')
    expect(location?.query).not.toHaveProperty('returnUrl')
    expect(location?.query).not.toHaveProperty('redirectTo')
    expect(location?.query).not.toHaveProperty('callback_url')
    expect(location?.query).not.toHaveProperty('route_name')
    expect(parseFreeDraftHistoryContext(location!.query)).toEqual({
      ...context,
      accountId: 'acct-owned',
    })
  })

  it('isolates namespaced source fields from operational TUI fields', () => {
    const query = {
      mode: 'free',
      account_id: 'acct-runtime',
      draft_id: 'runtime-draft',
      action: 'publish',
      ...buildFreeDraftTuiSourceQuery(context),
    }

    expect(query).toMatchObject({
      mode: 'free',
      account_id: 'acct-runtime',
      draft_id: 'runtime-draft',
      action: 'publish',
    })
    expect(parseFreeDraftTuiSourceContext(query)).toEqual(context)
  })

  it('rejects History arrays and mismatched route/source accounts', () => {
    const location = buildFreeDraftHistoryLocation(context, 'acct-a')!
    expect(parseFreeDraftHistoryContext({ ...location.query, tab: ['free-drafts'] })).toBeNull()
    expect(parseFreeDraftHistoryContext({ ...location.query, account: ['acct-a'] })).toBeNull()
    expect(parseFreeDraftHistoryContext({ ...location.query, account: 'acct-b' })).toBeNull()
  })
})
