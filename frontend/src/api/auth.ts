/** Auth API functions */

import client from './client'
import type { LoginRequest, LoginResponse, ValidateResponse } from '@/types/auth'

/** Login with username and password */
export async function login(request: LoginRequest): Promise<LoginResponse> {
  return client.post('/auth/login', request) as unknown as LoginResponse
}

/** Logout and invalidate token */
export async function logout(): Promise<void> {
  await client.post('/auth/logout')
}

/** Validate current token */
export async function validateToken(): Promise<ValidateResponse> {
  return client.get('/auth/validate') as unknown as ValidateResponse
}

/** Get current user info */
export async function getMe(): Promise<{ user: { id: string; username: string } }> {
  return client.get('/auth/me') as unknown as { user: { id: string; username: string } }
}