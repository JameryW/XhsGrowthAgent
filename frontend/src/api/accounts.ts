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
}

export interface Credential {
  key_name: string
  masked_value: string
  is_set: boolean
}

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

export async function updateAccount(accountId: string, data: { name?: string; is_active?: boolean }): Promise<Account> {
  return client.put(`/accounts/${accountId}`, data) as unknown as Account
}

export async function deleteAccount(accountId: string): Promise<void> {
  await client.delete(`/accounts/${accountId}`)
}

// ── Credentials ──

export async function listCredentials(accountId: string): Promise<Credential[]> {
  return client.get(`/accounts/${accountId}/credentials`) as unknown as Credential[]
}

export async function setCredentials(accountId: string, credentials: Record<string, string>): Promise<{ updated_keys: string[] }> {
  return client.put(`/accounts/${accountId}/credentials`, { credentials }) as unknown as { updated_keys: string[] }
}

export async function deleteCredential(accountId: string, keyName: string): Promise<void> {
  await client.delete(`/accounts/${accountId}/credentials/${keyName}`)
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
}

export interface QrVerificationCodeResult extends QrLoginStatusResponse {
  submitted: boolean
  reason?: string
  clicked?: boolean
  target_count?: number
  frame_url?: string
}

export async function startQrLogin(accountId: string): Promise<QrLoginStart> {
  return client.post(`/accounts/${accountId}/login/qr`) as unknown as QrLoginStart
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
