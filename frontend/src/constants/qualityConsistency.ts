/** Shared frontend switches and snapshot helpers for the V2 rollout. */

/** Explicit UI sentinel; it is never sent as a real account id to APIs. */
export const ALL_ACCOUNTS_ID = '__all_accounts__'

/** V2 is enabled by default and can be disabled for an additive rollback. */
export const QUALITY_CONSISTENCY_V2_ENABLED =
  String(import.meta.env.VITE_QUALITY_CONSISTENCY_V2 ?? '1').toLowerCase()
  !== '0'
  && String(import.meta.env.VITE_QUALITY_CONSISTENCY_V2 ?? '1').toLowerCase()
  !== 'false'

export function isAllAccountsScope(accountId: string | null | undefined): boolean {
  return accountId === ALL_ACCOUNTS_ID
}

export function hasSnapshotMismatch(
  first: string | null | undefined,
  second: string | null | undefined,
): boolean {
  return Boolean(first && second && first !== second)
}
