/** Auth store - authentication state management */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authApi from '@/api/auth'
import type { AuthUser } from '@/types/auth'
import { AUTH_TOKEN_KEY, AUTH_USER_KEY } from '@/types/auth'
import { clearAccountViewSession } from '@/utils/accountViewSession'
import { useToastStore } from './toast'
import i18n from '@/locales'

const { t } = i18n.global

/** Remembers the last logged-in console user across logout, so the next
 *  login can tell a user switch apart from a same-user re-login. */
const LAST_USER_KEY = 'auth_last_user_id'

/** localStorage namespaces written by account-scoped stores (workflow tabs).
 *  On a console-user switch the previous user's threads/tabs must not be
 *  restored — they would 404 (ownership is hidden cross-user) and leak
 *  another user's context into the new session. */
const ACCOUNT_SCOPED_LS_KEYS = ['activeThreadId', 'openTabIds', 'tabLabels'] as const

function clearAccountScopedLocalStorage(): void {
  for (const key of ACCOUNT_SCOPED_LS_KEYS) localStorage.removeItem(key)
  // History/Review multi-account view prefs (session) — avoid cross-user leak.
  clearAccountViewSession()
}

export const useAuthStore = defineStore('auth', () => {
  const toastStore = useToastStore()

  // State - restore from localStorage
  const token = ref<string | null>(localStorage.getItem(AUTH_TOKEN_KEY))
  const user = ref<AuthUser | null>(null)
  /** Set by login() when the console user changed: the caller must perform a
   *  full navigation (not router.push) so every Pinia store re-initializes
   *  without the previous user's in-memory state. */
  const requiresFullReset = ref(false)

  // Initialize user from localStorage
  const storedUser = localStorage.getItem(AUTH_USER_KEY)
  if (storedUser) {
    try {
      user.value = JSON.parse(storedUser)
    } catch {
      localStorage.removeItem(AUTH_USER_KEY)
    }
  }

  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const isInitialized = ref(false)

  // Computed
  const isAuthenticated = computed(() => !!token.value && !!user.value)

  // Actions
  async function login(username: string, password: string) {
    isLoading.value = true
    error.value = null
    try {
      const result = await authApi.login({ username, password })
      // A different console user must not inherit the previous user's
      // account-scoped state (tabs, cached analytics, account selections).
      const previousUserId = localStorage.getItem(LAST_USER_KEY)
      if (previousUserId && previousUserId !== result.user.id) {
        clearAccountScopedLocalStorage()
        requiresFullReset.value = true
      }
      localStorage.setItem(LAST_USER_KEY, result.user.id)
      token.value = result.token
      user.value = result.user
      localStorage.setItem(AUTH_TOKEN_KEY, result.token)
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(result.user))
      // The token was just minted by a successful login round-trip — mark auth
      // initialized so the router guard does not re-validate it on the very
      // next navigation. That re-validation could fail on a transient network
      // blip and bounce the user straight back to /login after a successful
      // login (the guard's initialize() clears auth on validate errors).
      isInitialized.value = true
      toastStore.success(t('common.success'), `${result.user.username}`)
      return result
    } catch (e: any) {
      error.value = e.message || t('login.error.loginFailed')
      toastStore.error(t('login.error.loginFailed'), e.message)
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function logout() {
    isLoading.value = true
    try {
      await authApi.logout()
    } catch {
      // Ignore logout API errors
    } finally {
      clearAuth()
      isLoading.value = false
      toastStore.info(t('nav.logout'), t('login.logoutSuccess'))
    }
  }

  function clearAuth() {
    token.value = null
    user.value = null
    localStorage.removeItem(AUTH_TOKEN_KEY)
    localStorage.removeItem(AUTH_USER_KEY)
    // Drop multi-account view prefs so the next session cannot inherit them
    // from the same browser tab (sessionStorage survives soft logouts).
    clearAccountViewSession()
  }

  async function initialize() {
    if (!token.value) {
      isInitialized.value = true
      return
    }

    isLoading.value = true
    try {
      const result = await authApi.validateToken()
      if (!result.valid) {
        // Token invalid - clear state
        clearAuth()
      }
    } catch (e: any) {
      // Only a definitive server answer (401/invalid) means the token is dead.
      // Transport failures (backend restarting, network blip) must NOT log the
      // user out — keep the token; the API client's 401 interceptor handles a
      // truly expired session on the next real request.
      if (e?.code !== 'NETWORK_ERROR') {
        clearAuth()
      }
    } finally {
      isLoading.value = false
      isInitialized.value = true
    }
  }

  return {
    token,
    user,
    isLoading,
    error,
    isInitialized,
    isAuthenticated,
    requiresFullReset,
    login,
    logout,
    clearAuth,
    initialize,
  }
})
