/**
 * Safe, URL-sized context for moving between the Free Draft review queue and
 * the Free Creation TUI. This module deliberately owns every query key and
 * the fixed History destination so callers cannot introduce an open redirect
 * or collide with the TUI's operational deep-link fields.
 */

export const FREE_DRAFT_REVIEW_FILTERS = [
  'all',
  'needs_attention',
  'unpublished',
  'published',
  'publish_failed',
  'evaluated',
  'unevaluated',
] as const

export type FreeDraftReviewFilter = typeof FREE_DRAFT_REVIEW_FILTERS[number]

export type FreeDraftReviewContext = {
  accountId: string
  status: FreeDraftReviewFilter
  search: string
  draftId: string | null
}

export type FreeDraftHistoryLocation = {
  name: 'history'
  query: Record<string, string | string[]>
}

type QueryLike = Readonly<Record<string, unknown>>

const QUERY_KEYS = {
  account: 'fd_review_account',
  status: 'fd_review_status',
  search: 'fd_review_search',
  draft: 'fd_review_draft',
} as const

const FILTER_SET = new Set<string>(FREE_DRAFT_REVIEW_FILTERS)
const MAX_SEARCH_LENGTH = 160
const MAX_ID_LENGTH = 256

function singleString(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function normalizeId(value: unknown): string | null {
  const raw = singleString(value)
  if (raw == null) return null
  const normalized = raw.trim()
  if (!normalized || normalized.length > MAX_ID_LENGTH) return null
  return normalized
}

function normalizeStatus(value: unknown): FreeDraftReviewFilter {
  const raw = singleString(value)?.trim() || ''
  return FILTER_SET.has(raw) ? raw as FreeDraftReviewFilter : 'all'
}

function normalizeSearch(value: unknown): string {
  const raw = singleString(value)
  return raw == null ? '' : raw.trim().slice(0, MAX_SEARCH_LENGTH)
}

function normalizeContext(value: FreeDraftReviewContext): FreeDraftReviewContext | null {
  const accountId = normalizeId(value.accountId)
  if (!accountId) return null
  return {
    accountId,
    status: normalizeStatus(value.status),
    search: normalizeSearch(value.search),
    draftId: normalizeId(value.draftId),
  }
}

function parseNamespacedContext(query: QueryLike): FreeDraftReviewContext | null {
  // Vue Router represents repeated query keys as arrays. Review context is a
  // single-value protocol, so any supplied non-string value invalidates the
  // source rather than guessing which element the caller intended.
  if (Object.values(QUERY_KEYS).some((key) => (
    query[key] != null && typeof query[key] !== 'string'
  ))) return null
  const accountId = normalizeId(query[QUERY_KEYS.account])
  if (!accountId) return null
  return {
    accountId,
    status: normalizeStatus(query[QUERY_KEYS.status]),
    search: normalizeSearch(query[QUERY_KEYS.search]),
    draftId: normalizeId(query[QUERY_KEYS.draft]),
  }
}

/** Parse context on History only when it belongs to the fixed Free Draft tab. */
export function parseFreeDraftHistoryContext(query: QueryLike): FreeDraftReviewContext | null {
  if (singleString(query.tab)?.trim() !== 'free-drafts') return null
  const routeAccount = normalizeId(query.account)
  const context = parseNamespacedContext(query)
  if (!routeAccount || !context || routeAccount !== context.accountId) return null
  return context
}

/** Parse the namespaced source carried by a Free Creation TUI deep link. */
export function parseFreeDraftTuiSourceContext(query: QueryLike): FreeDraftReviewContext | null {
  return parseNamespacedContext(query)
}

/**
 * Return only namespaced source fields. In particular, this function can
 * never overwrite mode/account_id/draft_id/action when its result is merged
 * into an operational TUI query.
 */
export function buildFreeDraftTuiSourceQuery(
  context: FreeDraftReviewContext,
): Record<string, string> {
  const normalized = normalizeContext(context)
  if (!normalized) return {}
  return {
    [QUERY_KEYS.account]: normalized.accountId,
    [QUERY_KEYS.status]: normalized.status,
    ...(normalized.search ? { [QUERY_KEYS.search]: normalized.search } : {}),
    ...(normalized.draftId ? { [QUERY_KEYS.draft]: normalized.draftId } : {}),
  }
}

/**
 * Build the only supported return destination. The resolved owned account is
 * authoritative and replaces the raw source account. No caller-provided route
 * or unrelated query is accepted or forwarded.
 */
export function buildFreeDraftHistoryLocation(
  context: FreeDraftReviewContext,
  resolvedOwnedAccountId: string,
): FreeDraftHistoryLocation | null {
  const accountId = normalizeId(resolvedOwnedAccountId)
  if (!accountId) return null
  const normalized = normalizeContext({ ...context, accountId })
  if (!normalized) return null

  return {
    name: 'history',
    query: {
      tab: 'free-drafts',
      account: accountId,
      ...buildFreeDraftTuiSourceQuery(normalized),
    },
  }
}

const UNSAFE_RETURN_KEYS = new Set([
  'callback',
  'callbackurl',
  'continue',
  'continueurl',
  'destination',
  'href',
  'next',
  'nexturl',
  'path',
  'redirect',
  'redirectto',
  'redirecturl',
  'return',
  'returnto',
  'returnurl',
  'route',
  'routename',
  'target',
  'targeturl',
  'url',
])

function isUnsafeReturnKey(key: string): boolean {
  // Treat common separator/case variants as the same protocol field. This
  // prevents a parent query such as return_url or redirectTo from surviving
  // a review-owned mirror merely because it used a different spelling.
  return UNSAFE_RETURN_KEYS.has(key.replace(/[-_.]/g, '').toLowerCase())
}

/**
 * Mirror review-owned fields while already on History. Unlike the fixed TUI
 * return builder, this preserves parent-owned History query state. Controlled
 * review keys stay private to this module, and redirect-like inputs are never
 * carried forward.
 */
export function buildFreeDraftHistoryMirrorLocation(
  context: FreeDraftReviewContext,
  resolvedOwnedAccountId: string,
  currentHistoryQuery: QueryLike,
): FreeDraftHistoryLocation | null {
  const fixed = buildFreeDraftHistoryLocation(context, resolvedOwnedAccountId)
  if (!fixed) return null

  const query: Record<string, string | string[]> = {}
  const controlledKeys = new Set<string>(['tab', 'account', ...Object.values(QUERY_KEYS)])
  for (const [key, value] of Object.entries(currentHistoryQuery)) {
    if (controlledKeys.has(key) || isUnsafeReturnKey(key)) continue
    if (typeof value === 'string') query[key] = value
    else if (Array.isArray(value) && value.every(item => typeof item === 'string')) {
      query[key] = [...value]
    }
  }
  Object.assign(query, fixed.query)
  return { name: 'history', query }
}
