import client from './client'

// ── Types ──

export interface ConsoleUser {
  id: string
  username: string
  created_at: string
  last_login_at: string | null
}

// ── CRUD ──

export async function listConsoleUsers(): Promise<ConsoleUser[]> {
  return client.get('/console-users') as unknown as ConsoleUser[]
}

export async function createConsoleUser(username: string, password: string): Promise<ConsoleUser> {
  return client.post('/console-users', { username, password }) as unknown as ConsoleUser
}

export async function changeConsoleUserPassword(userId: string, password: string): Promise<void> {
  await client.put(`/console-users/${userId}/password`, { password })
}

export async function deleteConsoleUser(userId: string): Promise<void> {
  await client.delete(`/console-users/${userId}`)
}
