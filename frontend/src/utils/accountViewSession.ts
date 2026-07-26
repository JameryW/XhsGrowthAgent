/**
 * Session keys and helpers for multi-account local view
 * (History / Review / Evaluation + deep-link handoff).
 * Kept in one module so auth logout/user-switch can clear them without drift.
 */

export const HISTORY_VIEW_ACCOUNT_KEY = 'xhs.history.viewAccountId'
export const HISTORY_ACCOUNT_TOTALS_KEY = 'xhs.history.accountTotals'
export const REVIEW_VIEW_ACCOUNT_KEY = 'xhs.review.viewAccountId'
export const REVIEW_AWAITING_TOTALS_KEY = 'xhs.review.awaitingTotals'
export const EVALUATION_VIEW_ACCOUNT_KEY = 'xhs.evaluation.viewAccountId'

export const ACCOUNT_VIEW_SESSION_KEYS = [
  HISTORY_VIEW_ACCOUNT_KEY,
  HISTORY_ACCOUNT_TOTALS_KEY,
  REVIEW_VIEW_ACCOUNT_KEY,
  REVIEW_AWAITING_TOTALS_KEY,
  EVALUATION_VIEW_ACCOUNT_KEY,
] as const

export function readSessionString(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeSessionString(key: string, value: string | null): void {
  try {
    if (value) sessionStorage.setItem(key, value)
    else sessionStorage.removeItem(key)
  } catch {
    // private mode / quota
  }
}

export function readSessionTotals(key: string): Record<string, number> {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const out: Record<string, number> = {}
    for (const [id, n] of Object.entries(parsed || {})) {
      if (typeof n === 'number' && Number.isFinite(n) && n >= 0) out[id] = Math.floor(n)
    }
    return out
  } catch {
    return {}
  }
}

export function writeSessionTotals(key: string, totals: Record<string, number>): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(totals))
  } catch {
    // private mode / quota
  }
}

export function clearAccountViewSession(): void {
  for (const key of ACCOUNT_VIEW_SESSION_KEYS) {
    try {
      sessionStorage.removeItem(key)
    } catch {
      // private mode
    }
  }
}

/** Sum counts for every owned account except the workspace active one. */
export function sumOtherAccountTotals(
  totals: Record<string, number>,
  activeAccountId: string | null | undefined,
): number {
  let sum = 0
  for (const [id, n] of Object.entries(totals)) {
    if (activeAccountId && id === activeAccountId) continue
    if (typeof n === 'number' && n > 0) sum += n
  }
  return sum
}

/** Total awaiting reviews across all accounts (for nav badge). */
export function sumAllAccountTotals(totals: Record<string, number>): number {
  let sum = 0
  for (const n of Object.values(totals)) {
    if (typeof n === 'number' && n > 0) sum += n
  }
  return sum
}

/** Read a single string query param (first value if array). */
export function readQueryString(
  query: Record<string, unknown> | { [key: string]: unknown },
  key: string,
): string | null {
  const raw = query[key]
  if (typeof raw === 'string' && raw.trim()) return raw.trim()
  if (Array.isArray(raw) && typeof raw[0] === 'string' && raw[0].trim()) return raw[0].trim()
  return null
}

/**
 * Build a router query fragment that preserves account scope across surfaces.
 * Omits the key when account is empty or equals the workspace (optional clean URL).
 */
export function accountQuery(
  accountId: string | null | undefined,
  options?: { omitIfEquals?: string | null },
): { account: string } | Record<string, never> {
  const id = typeof accountId === 'string' ? accountId.trim() : ''
  if (!id) return {}
  if (options?.omitIfEquals && id === options.omitIfEquals) return {}
  return { account: id }
}

/**
 * Merge account into an existing query object without dropping other params.
 * When account should be omitted, removes any stale `account` key.
 */
export function withAccountQuery(
  query: Record<string, unknown> | undefined,
  accountId: string | null | undefined,
  options?: { omitIfEquals?: string | null },
): Record<string, string | string[]> {
  const next: Record<string, string | string[]> = {}
  for (const [k, v] of Object.entries(query || {})) {
    if (k === 'account') continue
    if (typeof v === 'string' || Array.isArray(v)) next[k] = v as string | string[]
  }
  const frag = accountQuery(accountId, options)
  if ('account' in frag) next.account = frag.account
  return next
}
