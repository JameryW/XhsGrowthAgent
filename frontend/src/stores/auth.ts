/** Auth store - authentication state management */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authApi from '@/api/auth'
import type { AuthUser } from '@/types/auth'
import { AUTH_TOKEN_KEY, AUTH_USER_KEY } from '@/types/auth'
import { useToastStore } from './toast'

export const useAuthStore = defineStore('auth', () => {
  const toastStore = useToastStore()

  // State - restore from localStorage
  const token = ref<string | null>(localStorage.getItem(AUTH_TOKEN_KEY))
  const user = ref<AuthUser | null>(null)

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
      token.value = result.token
      user.value = result.user
      localStorage.setItem(AUTH_TOKEN_KEY, result.token)
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(result.user))
      toastStore.success('登录成功', `欢迎回来，${result.user.username}`)
      return result
    } catch (e: any) {
      error.value = e.message || '登录失败'
      toastStore.error('登录失败', e.message || '请检查用户名和密码')
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
      toastStore.info('已退出', '请重新登录以继续使用')
    }
  }

  function clearAuth() {
    token.value = null
    user.value = null
    localStorage.removeItem(AUTH_TOKEN_KEY)
    localStorage.removeItem(AUTH_USER_KEY)
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
    } catch {
      // Validation failed - clear state
      clearAuth()
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
    login,
    logout,
    clearAuth,
    initialize,
  }
})