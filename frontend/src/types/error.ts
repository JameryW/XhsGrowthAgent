export type ErrorType = 'api' | 'timeout' | 'unknown' | 'retry_success'

export interface ErrorState {
  type: ErrorType
  message: string
  retryCount: number
  isRecovering: boolean
  recoverAction?: string // Action identifier instead of function for serialization
  timestamp: string // ISO format string for serialization
}

export interface RetryConfig {
  maxRetries: number
  baseDelay: number
  maxDelay: number
}