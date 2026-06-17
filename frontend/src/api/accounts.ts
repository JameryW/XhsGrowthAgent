import client from './client'

// ── Types ──

export interface Account {
  id: string
  name: string
  is_active: boolean
  created_at: string
  updated_at?: string
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
