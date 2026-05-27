// frontend/src/composables/useRetry.ts
import type { RetryConfig } from '@/types/error'

/**
 * Default retry configuration
 */
export const DEFAULT_CONFIG: RetryConfig = {
  maxRetries: 3,
  baseDelay: 1000,  // 1 second
  maxDelay: 4000    // 4 seconds
}

/**
 * Calculate exponential backoff delay
 * Formula: baseDelay * 2^retryCount, capped at maxDelay
 *
 * @param retryCount - Current retry count (0-indexed)
 * @param baseDelay - Base delay in milliseconds
 * @param maxDelay - Maximum delay cap in milliseconds
 * @returns Delay in milliseconds
 */
export function calculateDelay(
  retryCount: number,
  baseDelay: number = DEFAULT_CONFIG.baseDelay,
  maxDelay: number = DEFAULT_CONFIG.maxDelay
): number {
  const delay = baseDelay * Math.pow(2, retryCount)
  return Math.min(delay, maxDelay)
}

/**
 * Retry a function with exponential backoff
 *
 * @param fn - Function to retry (async or sync)
 * @param config - Retry configuration
 * @returns Promise with the result of the function
 * @throws Last error if all retries exhausted
 */
export async function retryWithBackoff<T>(
  fn: () => T | Promise<T>,
  config: RetryConfig = DEFAULT_CONFIG
): Promise<T> {
  const { maxRetries, baseDelay, maxDelay } = config

  let lastError: Error | undefined

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn()
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))

      // Don't wait after the last attempt
      if (attempt < maxRetries) {
        const delay = calculateDelay(attempt, baseDelay, maxDelay)
        await sleep(delay)
      }
    }
  }

  // All retries exhausted
  throw lastError
}

/**
 * Sleep utility for delay
 * @param ms - Milliseconds to sleep
 */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * Composable for retry functionality
 */
export function useRetry() {
  return {
    retryWithBackoff,
    calculateDelay,
    DEFAULT_CONFIG
  }
}