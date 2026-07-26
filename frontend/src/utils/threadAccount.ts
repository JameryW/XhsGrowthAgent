/**
 * Resolve the owning XHS account id from a workflow thread id.
 *
 * Thread ids are minted as ``xhs_{account_id}_{8hex}`` (see backend
 * ``POST /workflow/start``). Account ids may contain hyphens (UUIDs).
 */
export function accountIdFromThreadId(threadId: string | null | undefined): string | null {
  if (!threadId) return null
  const raw = threadId.trim()
  if (!raw.startsWith('xhs_')) return null
  const body = raw.slice(4)
  const sep = body.lastIndexOf('_')
  if (sep <= 0) return null
  const suffix = body.slice(sep + 1)
  // 8 lowercase/upper hex chars from uuid.uuid4().hex[:8]
  if (!/^[0-9a-f]{8}$/i.test(suffix)) return null
  const accountId = body.slice(0, sep).trim()
  return accountId || null
}
