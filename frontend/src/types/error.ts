export type ErrorType = 'api' | 'timeout' | 'unknown' | 'retry_success'

export interface ErrorState {
  type: ErrorType
  message: string
  retryCount: number
  isRecovering: boolean
  recoverAction?: () => void
  timestamp: Date
}

export interface RetryConfig {
  maxRetries: number
  baseDelay: number
  maxDelay: number
}