/** Auth type definitions */

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  token: string
  expires_at: string
  user: AuthUser
}

export interface AuthUser {
  id: string
  username: string
}

export interface ValidateResponse {
  valid: boolean
  user: AuthUser | null
  expires_at: string | null
}

/** Storage keys */
export const AUTH_TOKEN_KEY = 'auth_token'
export const AUTH_USER_KEY = 'auth_user'