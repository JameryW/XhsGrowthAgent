import axios, { AxiosInstance, AxiosError, AxiosResponse } from 'axios'

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
  (error: AxiosError<ApiResponse>) => {
    // Handle HTTP errors (404, 500, etc.)
    if (error.response?.data) {
      const apiResponse = error.response.data
      if (apiResponse.error) {
        return Promise.reject(new ApiError(
          apiResponse.error.message,
          apiResponse.error.code,
          apiResponse.error.details,
          apiResponse.request_id ?? undefined
        ))
      }
    }

    // Handle network/timeout errors
    const message = error.code === 'ECONNABORTED'
      ? 'Request timeout'
      : error.message || 'Network error'

    return Promise.reject(new ApiError(message, 'NETWORK_ERROR'))
  }
)

export default client