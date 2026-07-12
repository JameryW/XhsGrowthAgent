import client from './client'

// ── Types ──

export interface Account {
  id: string
  name: string
  is_active: boolean
  created_at: string
  updated_at?: string
  chrome_profile_path?: string
  cdp_port?: number
  /** Bound content niche (赛道), e.g. 美妆 / 母婴 */
  niche?: string
  /** manual | inferred | account_bound | "" */
  niche_source?: string
}

export type NicheSource = 'manual' | 'inferred' | 'account_bound' | 'cold_start' | string

export interface NicheResolution {
  niche: string
  source: NicheSource
  confidence: number
  evidence: string[]
  candidates: Array<{ niche: string; hits: number }>
  cold_start: boolean
  account_id?: string
}

/** Known product niches (aligned with backend niche_resolver.KNOWN_NICHES). */
export const KNOWN_NICHES = [
  '母婴',
  '美妆',
  '穿搭',
  '美食',
  '家居',
  '健身',
  '旅行',
  '数码',
  '宠物',
  '知识',
] as const

// ── Account CRUD ──

export async function listAccounts(): Promise<Account[]> {
  return client.get('/accounts') as unknown as Account[]
}

export async function getActiveAccount(): Promise<Account | null> {
  return client.get('/accounts/active') as unknown as Account | null
}

export async function createAccount(name: string, isActive = false): Promise<Account> {
  return client.post('/accounts', { name, is_active: isActive }) as unknown as Account
}

export async function updateAccount(
  accountId: string,
  data: {
    name?: string
    is_active?: boolean
    chrome_profile_path?: string
    cdp_port?: number
    niche?: string
    niche_source?: string
  }
): Promise<Account> {
  return client.put(`/accounts/${accountId}`, data) as unknown as Account
}

/** Infer niche from imported note history, or apply manual override. */
export async function resolveAccountNiche(
  accountId: string,
  body: { manual_niche?: string; persist?: boolean } = {}
): Promise<NicheResolution & { account_id: string }> {
  return client.post(`/accounts/${accountId}/niche/resolve`, {
    manual_niche: body.manual_niche ?? '',
    persist: body.persist ?? true,
  }) as unknown as NicheResolution & { account_id: string }
}

export async function deleteAccount(accountId: string): Promise<void> {
  await client.delete(`/accounts/${accountId}`)
}

// ── Durable profile login status ──

export type AccountLoginStatusValue = 'logged_in' | 'logged_out' | 'unavailable' | 'unknown'

export interface AccountLoginStatus {
  account_id: string
  status: AccountLoginStatusValue
  is_logged_in: boolean
  reason?: string
  signals?: string[]
  message?: string
}

export async function getAccountLoginStatus(accountId: string): Promise<AccountLoginStatus> {
  return client.get(`/accounts/${accountId}/login/status`) as unknown as AccountLoginStatus
}

// ── Scan-login (QR code) ──

export type QrLoginStatus = 'waiting' | 'scanned' | 'confirmed' | 'expired'

export interface QrLoginStart {
  status?: QrLoginStatus
  qr_id: string
  url: string
  account_id: string
}

export interface QrLoginStatusResponse {
  status: QrLoginStatus
  qr_id: string
  url?: string
  account_id: string
  verification_required?: boolean
}

export interface QrVerificationCodeResult extends QrLoginStatusResponse {
  submitted: boolean
  reason?: string
  clicked?: boolean
  target_count?: number
  frame_url?: string
}

export async function startQrLogin(accountId: string): Promise<QrLoginStart> {
  return client.post(
    `/accounts/${accountId}/login/qr`,
    undefined,
    { timeout: 12000 }
  ) as unknown as QrLoginStart
}

export async function getQrLoginStatus(accountId: string): Promise<QrLoginStatusResponse> {
  return client.get(`/accounts/${accountId}/login/qr/status`) as unknown as QrLoginStatusResponse
}

export async function submitQrVerificationCode(accountId: string, code: string): Promise<QrVerificationCodeResult> {
  return client.post(`/accounts/${accountId}/login/qr/verification-code`, { code }) as unknown as QrVerificationCodeResult
}

export async function stopQrLogin(accountId: string): Promise<{ stopped: boolean; account_id: string }> {
  return client.post(`/accounts/${accountId}/login/qr/stop`) as unknown as { stopped: boolean; account_id: string }
}
