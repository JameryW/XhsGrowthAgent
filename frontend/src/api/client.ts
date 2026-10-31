import axios, { AxiosInstance, AxiosError, AxiosResponse } from 'axios'
import { AUTH_TOKEN_KEY, AUTH_USER_KEY } from '@/types/auth'

declare module 'axios' {
  interface AxiosRequestConfig {
    /** Let a page-level error/empty state own the recovery message. */
    suppressToast?: boolean
  }
}

// ApiResponse envelope type from backend
export interface ApiResponse<T = unknown> {
  success: boolean
  data: T | null
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  } | null
  timestamp: string
  request_id: string | null
}

// Custom error class for API errors
export class ApiError extends Error {
  code: string
  details?: Record<string, unknown>
  requestId?: string

  constructor(message: string, code: string, details?: Record<string, unknown>, requestId?: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

// Create axios instance
const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor
client.interceptors.request.use(
  (config) => {
    // Add auth token if available
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor - unwrap ApiResponse format
client.interceptors.response.use(
  (response: AxiosResponse<ApiResponse>) => {
    const apiResponse = response.data

    // Check success flag
    if (!apiResponse.success) {
      // Throw structured error from ApiResponse.error
      const error = apiResponse.error
      if (error) {
        throw new ApiError(
          error.message,
          error.code,
          error.details,
          apiResponse.request_id ?? undefined
        )
      }
      // Fallback for malformed response
      throw new ApiError(
        'Unknown error occurred',
        'UNKNOWN_ERROR',
        undefined,
        apiResponse.request_id ?? undefined
      )
    }

    // Return only the data payload for successful responses
    return apiResponse.data as AxiosResponse
  },
  async (error: AxiosError<ApiResponse>) => {
    // Handle HTTP errors (404, 500, etc.)
    let apiError: ApiError

    if (error.response?.data) {
      const apiResponse = error.response.data
      if (apiResponse.error) {
        apiError = new ApiError(
          apiResponse.error.message,
          apiResponse.error.code,
          apiResponse.error.details,
          apiResponse.request_id ?? undefined
        )
      } else {
        apiError = new ApiError(
          'Unknown error occurred',
          'UNKNOWN_ERROR',
          undefined,
          apiResponse.request_id ?? undefined
        )
      }
    } else {
      // Handle network/timeout errors
      const message = error.code === 'ECONNABORTED'
        ? 'Request timeout'
        : error.message || 'Network error'
      apiError = new ApiError(message, 'NETWORK_ERROR')
    }

    // A dead console session is not an error the user can act on: drop the
    // stale token and stay quiet instead of toasting "Token expired or
    // invalid" on every page open (that toast used to be the entire UX of an
    // expired session, even on the public landing page, which fires an authed
    // /api/accounts call for the account widget). No forced navigation here:
    // the router guard already redirects protected routes after
    // authStore.initialize() clears the token, and public pages must keep
    // rendering for anonymous visitors. Real login failures still toast.
    const sessionGoneCodes = new Set([
      'ERROR_AUTH_TOKEN_INVALID',
      'ERROR_AUTH_TOKEN_MISSING',
      'ERROR_AUTH_TOKEN_EXPIRED',
    ])
    if (sessionGoneCodes.has(apiError.code)) {
      localStorage.removeItem(AUTH_TOKEN_KEY)
      localStorage.removeItem(AUTH_USER_KEY)
      return Promise.reject(apiError)
    }

    // Show toast notification for API errors (skip expected business-logic codes)
    const silentCodes = new Set([
      'ERROR_REVIEW_NOT_PENDING',
      'ERROR_WORKFLOW_NOT_FOUND',
    ])
    if (!silentCodes.has(apiError.code) && !error.config?.suppressToast) {
      try {
        const { useToastStore } = await import('@/stores/toast')
        const toastStore = useToastStore()
        toastStore.error(apiError.message)
      } catch {
        // Toast store not available, continue without toast
      }
    }

    return Promise.reject(apiError)
  }
)

export default client
